"""Read only source ingestion. Never opens EUJobs with write access."""
import csv
import hashlib
import os
import ijson
import io
import json
import re
import sqlite3
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from .db import now, canonical, digest, invalidate


class ValidationError(ValueError):
    pass


def clean(value, maximum=2000, required=False):
    if not isinstance(value, str):
        raise ValidationError('Expected text.')
    value = value.strip()
    if len(value) > maximum or '\x00' in value or (required and not value):
        raise ValidationError(f'Text must be {"1" if required else "0"}–{maximum} characters.')
    return value


def email(value, required=False):
    value = clean(value, 254, required).lower()
    if value and not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?\.[a-z]{2,63}", value):
        raise ValidationError('Enter one valid email address, without a display name.')
    return value


def safe_url(value, required=False):
    value = clean(value or '', 2000, required)
    if not value:
        return ''
    p = urlparse(value)
    if p.scheme not in ('https', 'http') or not p.hostname or p.username or p.password or any(ord(c) < 32 for c in value):
        raise ValidationError('Source links must be HTTP or HTTPS URLs without credentials.')
    return value


def date(value, required=False):
    value = clean(value or '', 50, required)
    if value:
        try:
            datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            raise ValidationError('Use an ISO date, such as 2026-10-27.')
    return value


def truth(value):
    if value in (True, 1, '1', 'true', 'yes'):
        return 1
    if value in (False, 0, '0', 'false', 'no', '', None):
        return 0
    raise ValidationError('Boolean fields must be true/false or yes/no.')


def norm(value):
    return ' '.join(unicodedata.normalize('NFKC', value or '').casefold().split())


def domain(value):
    if not value:
        return ''
    p = urlparse(value if '://' in value else 'https://' + value)
    h = (p.hostname or '').lower().removeprefix('www.').rstrip('.')
    return h if re.fullmatch(r'[a-z0-9.-]+\.[a-z]{2,63}', h) else ''


def build_index(registers):
    indices = {key: defaultdict(set) for key in ('slug', 'name', 'domain')}
    for r in registers:
        if not r['in_register']:
            continue
        for key in indices:
            v = norm(r[key])
            if v:
                indices[key][v].add(r['id'])
        if r.get('acronym'):
            indices['name'][norm(r['acronym'])].add(r['id'])
    return indices


def resolve(name, domains, slugs, indices):
    """Only unique exact identifiers; conflicting keys always require review."""
    hits = set()
    methods = []
    for key, values in [('slug', slugs), ('name', [name]), ('domain', domains)]:
        for value in values:
            found = indices[key].get(norm(value), set())
            if found:
                hits |= found
                methods.append(key)
    if len(hits) == 1:
        return next(iter(hits)), 'exact ' + '/'.join(sorted(set(methods))), []
    return None, 'ambiguous' if hits else 'unmatched', sorted(hits)


def read_register_snapshot(resources):
    # The production resource file is ~197 MB. Never materialize its complete
    # array or raw bytes; retain only the small allowlisted identity fields.
    registers = []
    with Path(resources).open('rb') as stream:
        before = os.fstat(stream.fileno())
        for r in ijson.items(stream, 'lobbyingEntities.item'):
            if not r.get('identificationCode'):
                continue
            registers.append(dict(id=r['identificationCode'], name=r['name'], acronym=r.get('acronym', ''), slug=r.get('slug', ''), domain=domain(r.get('webSiteURL') or r.get('website')), source_url=safe_url(r.get('sourceUrl')), source_date=r.get('sourceDate', ''), updated=r.get('lastUpdateDate', ''), in_register=int(bool(r.get('inRegister')))))
        stream.seek(0)
        metadata = next(ijson.items(stream, 'lobbyingEntitiesSource'), {})
        stream.seek(0)
        checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
        after = os.fstat(stream.fileno())
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValidationError('Register source changed while reading; retry the refresh.')
    return registers, metadata, checksum


def import_eujobs(db, source_db, resources):
    registers, register_metadata, register_checksum = read_register_snapshot(resources)
    index = build_index(registers)
    src = sqlite3.connect('file:' + str(Path(source_db).resolve()) + '?mode=ro', uri=True)
    src.row_factory = sqlite3.Row
    src.execute('PRAGMA query_only=ON')
    src.execute('BEGIN')
    # Deliberate column/table allowlist. No contacts, users, payments or outbox.
    orgs = [dict(r) for r in src.execute('SELECT id,name FROM organizations')]
    listings = [dict(r) for r in src.execute('''SELECT id,kind,title,organization,organizationId,summary,description,location,topic,status,sourceUrl,sourceCheckedAt,publishedAt,deadline,startsAt,externalSource,sourceIdentity,entitySlug,employerSourceUrl,url FROM listings WHERE isSample=0''')]
    src.close()
    by_org = defaultdict(list)
    for j in listings:
        by_org[j['organizationId']].append(j)
    report = {'source': 'EUJobs read-only SELECT', 'register_metadata': register_metadata, 'register_sha256': register_checksum, 'registers': len(registers), 'organizations': len(orgs), 'jobs': 0, 'events': 0, 'linked': 0, 'ambiguous': 0, 'unmatched': 0, 'imported_at': now(), 'event_coverage': 'Organisers and source excerpts only; no attendee roster. Dates are source dates, not proof of attendance.'}
    with db.connect(write=True) as c:
        before = digest([tuple(r) for r in c.execute('SELECT * FROM jobs ORDER BY id')])
        c.executemany('INSERT OR REPLACE INTO registers VALUES(:id,:name,:acronym,:slug,:domain,:source_url,:source_date,:updated,:in_register)', registers)
        for org in orgs:
            js = by_org[org['id']]
            domains = [domain(j.get('employerSourceUrl') or j.get('sourceUrl') or j.get('url')) for j in js]
            rid, method, candidates = resolve(org['name'], domains, [j['entitySlug'] for j in js if j['entitySlug']], index)
            report['linked' if rid else method] += 1
            d = next((r['domain'] for r in registers if r['id'] == rid), '') if rid else ''
            c.execute('''INSERT INTO organizations VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name, domain=CASE WHEN organizations.resolution='manual' THEN organizations.domain ELSE excluded.domain END, register_id=CASE WHEN organizations.resolution='manual' THEN organizations.register_id ELSE excluded.register_id END, resolution=CASE WHEN organizations.resolution='manual' THEN 'manual' ELSE excluded.resolution END,candidates=excluded.candidates''', (org['id'], org['name'], d, rid, method, canonical(candidates), ''))
        # Disappeared records become inactive; source closure/expiry is never forgotten.
        c.execute("UPDATE jobs SET status='missing'")
        for j in listings:
            provenance = canonical({'system': 'EUJobs', 'table': 'listings', 'source_id': j['id'], 'external_source': j['externalSource'], 'source_identity': j['sourceIdentity']})
            if j['kind'] == 'job':
                c.execute('''INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET org_id=excluded.org_id,title=excluded.title,description=excluded.description,summary=excluded.summary,location=excluded.location,topic=excluded.topic,status=excluded.status,source_url=excluded.source_url,checked_at=excluded.checked_at,published_at=excluded.published_at,deadline=excluded.deadline,provenance=excluded.provenance''', (j['id'],j['organizationId'],j['title'],j['description'],j['summary'],j['location'],j['topic'],j['status'],safe_url(j['sourceUrl'] or j['url']),j['sourceCheckedAt'],j['publishedAt'],j['deadline'],provenance,now()))
                c.execute('INSERT OR IGNORE INTO opportunities VALUES(?,?,?)', (j['organizationId'],'review',now()))
                report['jobs'] += 1
            else:
                c.execute('INSERT OR REPLACE INTO events VALUES(?,?,?,?,?,?,?)', (j['id'],j['title'],j['startsAt'],safe_url(j['sourceUrl']),j['sourceCheckedAt'],j['description'],provenance))
                c.execute('INSERT OR REPLACE INTO participation VALUES(?,?,?,?,?,?,?)',(digest(['organizer',j['id']]),j['id'],j['organization'],'','organizer',safe_url(j['sourceUrl']),'verified'))
                report['events'] += 1
        after = digest([tuple(r) for r in c.execute('SELECT * FROM jobs ORDER BY id')])
        if before != after:
            invalidate(c, 'EUJobs source snapshot changed')
        c.execute('INSERT INTO imports(kind,report,created_at) VALUES(?,?,?)', ('eujobs',canonical(report),now()))
    return report


def validate_client(d):
    return dict(company=clean(d.get('company', ''),200,True), name=clean(d.get('name',''),150,True), email=email(d.get('email','')), role=clean(d.get('role',''),200), domain=domain(d.get('domain','')), relationship=clean(d.get('relationship',''),100,True), context=clean(d.get('context',''),3000,True), allowed_claim=clean(d.get('allowed_claim',''),1000), permission=truth(d.get('permission')), verified=truth(d.get('verified')), demo=truth(d.get('demo')))


def validate_event(d):
    role = clean(d.get('role',''),50,True)
    if role not in ('organizer','cohost','speaker','attendee','mentioned'):
        raise ValidationError('Event role must be organizer, cohost, speaker, attendee or mentioned.')
    status = d.get('evidence_status','possible')
    if status not in ('verified','possible','conflicting'):
        raise ValidationError('Evidence status must be verified, possible or conflicting.')
    return dict(event_id=clean(d.get('event_id',''),120,True),title=clean(d.get('title',''),300,True),date=date(d.get('date',''),True),organization=clean(d.get('organization',''),200,True),person=clean(d.get('person',''),150),role=role,source_url=safe_url(d.get('source_url',''),True),evidence_status=status)


def csv_preview(text, kind):
    if kind not in ('clients','events'):
        raise ValidationError('Unknown import type.')
    if len(text) > 400000:
        raise ValidationError('CSV is too large; use at most 500 rows.')
    reader = csv.DictReader(io.StringIO(text.lstrip('\ufeff')))
    required = {'clients':{'company','name','relationship','context'},'events':{'event_id','title','date','organization','role','source_url'}}[kind]
    if not required.issubset(set(reader.fieldnames or [])):
        raise ValidationError('Missing CSV headers: ' + ', '.join(sorted(required - set(reader.fieldnames or []))))
    rows, errors, seen = [], [], set()
    for i, d in enumerate(reader, 2):
        if i > 501:
            raise ValidationError('Use at most 500 rows per import.')
        try:
            if None in d or any(v is None for v in d.values()):
                raise ValidationError('Wrong number of columns.')
            row = (validate_client if kind == 'clients' else validate_event)(d)
            key = (row['company'],row['name'],row['email']) if kind=='clients' else (row['event_id'],row['organization'],row['person'],row['role'])
            if key in seen:
                raise ValidationError('Duplicate row in this file.')
            seen.add(key); rows.append(row)
        except ValidationError as e:
            errors.append({'line':i,'error':str(e)})
    if not rows and not errors:
        errors.append({'line':2,'error':'No data rows found.'})
    return {'kind':kind,'rows':rows,'errors':errors,'count':len(rows)}


def save_client(c, row, client_id=None):
    if client_id is not None:
        if not c.execute('SELECT id FROM clients WHERE id=?',(client_id,)).fetchone():
            raise ValidationError('Client not found.')
        c.execute('UPDATE clients SET '+','.join(k+'=?' for k in row)+',updated_at=? WHERE id=?', (*row.values(),now(),client_id))
    else:
        if c.execute('SELECT id FROM clients WHERE lower(company)=lower(?) AND lower(name)=lower(?) AND lower(email)=lower(?)',(row['company'],row['name'],row['email'])).fetchone():
            raise ValidationError('This client contact already exists; edit it instead.')
        client_id=c.execute('INSERT INTO clients('+','.join(row)+',updated_at) VALUES('+','.join('?' for _ in row)+',?)',(*row.values(),now())).lastrowid
    invalidate(c,'Client relationship or reference permission changed')
    return client_id


def save_events(c, rows):
    for r in rows:
        eid='csv:'+r['event_id']
        old=c.execute('SELECT title,date,source_url FROM events WHERE id=?',(eid,)).fetchone()
        if old and (old['title'],old['date'],old['source_url']) != (r['title'],r['date'],r['source_url']):
            raise ValidationError('The same event ID has conflicting title/date/source. Resolve the CSV before importing.')
        c.execute('INSERT OR IGNORE INTO events VALUES(?,?,?,?,?,?,?)',(eid,r['title'],r['date'],r['source_url'],now(),'User-imported participation; the user must verify the source.',canonical({'system':'user CSV'})))
        c.execute('INSERT OR REPLACE INTO participation VALUES(?,?,?,?,?,?,?)',(digest([eid,r['organization'],r['person'],r['role']]),eid,r['organization'],r['person'],r['role'],r['source_url'],r['evidence_status']))
    invalidate(c,'Event evidence changed')
