import json
import re
import uuid
from datetime import datetime, timezone, timedelta
from .db import now, canonical, digest, audit
from .sources import ValidationError, clean, email, truth, norm

DEFAULT_PROFILE = {'offering':'','buyer':'','keywords':'','exclusions':'','sender_name':'','cooldown_days':14,'freshness_days':14}


class Conflict(ValidationError):
    pass


def parsed(value):
    try:
        d=datetime.fromisoformat((value or '').replace('Z','+00:00'))
        return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d
    except ValueError:
        return None


def job_state(j, freshness=14):
    today=datetime.now(timezone.utc)
    deadline=parsed(j.get('deadline'))
    checked=parsed(j.get('checked_at'))
    if j['status']!='published' or (deadline and deadline<today):
        return 'inactive'
    if not checked or checked > today+timedelta(days=1) or checked < today-timedelta(days=freshness):
        return 'stale'
    return 'fresh'


def profile(c):
    r=c.execute("SELECT value FROM settings WHERE key='profile'").fetchone()
    return {**DEFAULT_PROFILE,**(json.loads(r['value']) if r else {})}


def snapshot(c, oid):
    org=c.execute('SELECT o.*, r.source_url register_url,r.source_date register_date,r.in_register FROM organizations o LEFT JOIN registers r ON r.id=o.register_id WHERE o.id=?',(oid,)).fetchone()
    if not org:
        raise ValidationError('Opportunity not found.')
    jobs=[dict(r) for r in c.execute('SELECT * FROM jobs WHERE org_id=? ORDER BY id',(oid,))]
    ev=[dict(r) for r in c.execute('''SELECT * FROM evidence WHERE org_id=? AND id NOT IN (SELECT supersedes FROM evidence WHERE supersedes IS NOT NULL) ORDER BY id''',(oid,))]
    clients=[dict(r) for r in c.execute('SELECT * FROM clients ORDER BY id')]
    events=[dict(r) for r in c.execute('''SELECT e.*,p.organization,p.person,p.role,p.evidence_status FROM events e JOIN participation p ON p.event_id=e.id ORDER BY e.id,p.id''')]
    return {'organization':dict(org),'jobs':jobs,'evidence':ev,'clients':clients,'events':events,'profile':profile(c)}


def match_basis(jobs, p):
    words=[w.strip().casefold() for w in p['keywords'].split(',') if w.strip()]
    excluded=[w.strip().casefold() for w in p['exclusions'].split(',') if w.strip()]
    text=' '.join(j['title']+' '+j['summary']+' '+j['description'] for j in jobs).casefold()
    matches=[w for w in words if w in text]
    exclusions=[w for w in excluded if w in text]
    return {'matched':matches,'excluded':exclusions,'configured':bool(words),'fit':'excluded' if exclusions else 'matched' if matches else 'unscored' if not words else 'no keyword match','explanation':'Literal matches in source job title, summary or description. Hiring is a possible need, not confirmed buying intent.'}


def queue(db):
    with db.connect() as c:
        p=profile(c)
        orgs=[dict(r) for r in c.execute('''SELECT o.*,op.status, r.source_date register_date FROM opportunities op JOIN organizations o ON o.id=op.id LEFT JOIN registers r ON r.id=o.register_id''')]
        jobs=[dict(r) for r in c.execute('SELECT * FROM jobs')]
        drafts=[dict(r) for r in c.execute('SELECT opportunity_id,route,state FROM drafts')]
        ev=[dict(r) for r in c.execute("SELECT org_id,status FROM evidence WHERE id NOT IN (SELECT supersedes FROM evidence WHERE supersedes IS NOT NULL)")]
        sends=[dict(r) for r in c.execute('SELECT opportunity_id,state FROM sends')]
    out=[]
    for o in orgs:
        js=[j for j in jobs if j['org_id']==o['id'] and job_state(j,p['freshness_days'])!='inactive']
        if not js:
            continue
        js.sort(key=lambda j:(job_state(j,p['freshness_days'])=='fresh',j.get('checked_at') or ''),reverse=True)
        b=match_basis(js,p)
        o.update(jobs=js,job_count=len(js),basis=b,freshness=job_state(js[0],p['freshness_days']),drafts=[d for d in drafts if d['opportunity_id']==o['id']],connections=sum(e['org_id']==o['id'] and e['status']=='verified' for e in ev),send_states=[s['state'] for s in sends if s['opportunity_id']==o['id']])
        out.append(o)
    out.sort(key=lambda o:(o['basis']['fit']=='matched',o['freshness']=='fresh',bool(o['register_id']),o['jobs'][0]['checked_at'] or ''),reverse=True)
    return out


def connections(s):
    results=[]
    names={norm(s['organization']['name'])}
    relevant=[e for e in s['events'] if norm(e['organization']) in names]
    for client in s['clients']:
        for e in relevant:
            others=[p for p in s['events'] if p['id']==e['id'] and norm(p['organization'])==norm(client['company'])]
            for other in others:
                results.append({'client_id':client['id'],'client':client['name'],'company':client['company'],'event':e['title'],'date':e['date'],'source_url':e['source_url'],'target_person':e['person'],'target_role':e['role'],'target_status':e['evidence_status'],'client_person':other['person'],'client_role':other['role'],'client_status':other['evidence_status'],'status':'conflicting' if 'conflicting' in (other['evidence_status'],e['evidence_status']) else 'possible','explanation':'Shared event participation is a possible connection. It does not establish that these people know one another.'})
    return results


def draft_binding(d):
    return digest({k:d[k] for k in ('id','opportunity_id','route','client_id','recipient','recipient_name','recipient_verified','sender','subject','body','version','evidence_hash')})


def template(s, route, client_id=None):
    p=s['profile'];org=s['organization'];js=[j for j in s['jobs'] if job_state(j,p['freshness_days'])!='inactive']
    js.sort(key=lambda j:j.get('checked_at') or '',reverse=True)
    if not js:
        raise Conflict('No active hiring source remains. Hold this opportunity.')
    j=js[0];client=next((c for c in s['clients'] if c['id']==client_id),None)
    offer=p['offering'] or '[Add your offering in Profile]'
    signature=p['sender_name'] or '[Your name]'
    role=j['title']
    if route=='intro':
        greeting=client['name'].split()[0] if client else '[Client first name]'
        evidence=next((e for e in reversed(s['evidence']) if e['client_id']==client_id and e['status']=='verified' and e['kind']=='relationship'),None)
        connection=f"My notes indicate: {evidence['claim']}" if evidence else '[Verify a personal connection before sending]'
        subject=f'An introduction to {org["name"]}?'
        body=f'Hi {greeting},\n\nI noticed {org["name"]} is advertising for {role}.\n\n{connection}\n\nOur offering is {offer}. If you feel it is relevant, would you be comfortable introducing me to the right person there? No problem at all if not.\n\nThe opening: {j["source_url"]}\n\nThanks,\n{signature}'
    else:
        subject=f'{org["name"]} — your {role} opening'
        ref=f"For context, {client['allowed_claim']}" if client and client['permission'] and client['verified'] and not client['demo'] and client['allowed_claim'] else '[Select a permitted customer example, or remove this line]'
        body=f'Hi [Prospect first name],\n\nI saw your opening for {role}. That may mean this is a useful time to discuss {offer}.\n\n{ref}\n\nWould a brief conversation be useful? If this is not your area, please let me know.\n\nThe opening: {j["source_url"]}\n\nBest,\n{signature}'
    return {'subject':subject[:300],'body':body,'recipient':client['email'] if route=='intro' and client else '', 'recipient_name':client['name'] if route=='intro' and client else '', 'recipient_verified':int(bool(route=='intro' and client and client['verified'])),'model':'deterministic evidence template v1'}


def save_draft(db, oid, route, data=None, regenerate=False, client_id=None, generator=None):
    if route not in ('intro','direct'):
        raise ValidationError('Choose intro or direct.')
    with db.connect(write=True) as c:
        old=c.execute('SELECT * FROM drafts WHERE opportunity_id=? AND route=?',(oid,route)).fetchone()
        if old and c.execute('SELECT id FROM sends WHERE draft_id=?',(old['id'],)).fetchone():
            raise Conflict('This route has a send reservation; its exact message is immutable. Review Activity.')
        s=snapshot(c,oid)
        if client_id is not None and not any(r['id']==client_id for r in s['clients']):
            raise ValidationError('Selected client does not exist.')
        if regenerate:
            fields=template(s,route,client_id)
            if old:
                fields['sender']=old['sender']
            else:
                account=c.execute('SELECT email FROM oauth_account WHERE id=1').fetchone();fields['sender']=account['email'] if account else ''
        else:
            if old and data.get('version')!=old['version']:
                raise Conflict('This draft changed in another tab. Reload it before saving.')
            fields={k:clean(data.get(k,''),300 if k=='subject' else 15000,True) for k in ('subject','body')}
            fields.update(recipient=email(data.get('recipient','')),sender=email(data.get('sender','')),recipient_name=clean(data.get('recipient_name',''),150),recipient_verified=truth(data.get('recipient_verified')),model=old['model'] if old else 'human authored')
        if old:
            c.execute('UPDATE drafts SET client_id=?,recipient=?,recipient_name=?,recipient_verified=?,sender=?,subject=?,body=?,version=version+1,evidence_hash=?,model=?,state=?,updated_at=? WHERE id=?',(client_id,fields['recipient'],fields['recipient_name'],fields['recipient_verified'],fields['sender'],fields['subject'],fields['body'],digest(s),fields['model'],'review',now(),old['id']))
            did=old['id'];c.execute('UPDATE approvals SET invalidated_at=? WHERE draft_id=? AND invalidated_at IS NULL',(now(),did))
        else:
            did=c.execute('INSERT INTO drafts(opportunity_id,route,client_id,recipient,recipient_name,recipient_verified,sender,subject,body,evidence_hash,model,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(oid,route,client_id,fields['recipient'],fields['recipient_name'],fields['recipient_verified'],fields['sender'],fields['subject'],fields['body'],digest(s),fields['model'],now(),now())).lastrowid
        audit(c,'draft_regenerated' if regenerate else 'draft_saved',did,{'route':route,'version':old['version']+1 if old else 1})
        return dict(c.execute('SELECT * FROM drafts WHERE id=?',(did,)).fetchone())


def blockers(c, d, s, account, send_enabled=True):
    reasons=[];p=s['profile']
    if not p['offering'] or not p['buyer'] or not p['sender_name']:
        reasons.append('Complete your offering, ideal buyer and sender name in Profile.')
    if digest(s)!=d['evidence_hash']:
        reasons.append('Evidence changed. Review the current evidence and save this draft again.')
    if not d['recipient'] or not d['recipient_name'] or not d['recipient_verified']:
        reasons.append('Enter and verify the named business recipient.')
    if not account or not send_enabled:
        reasons.append('Gmail sending is not connected or send permission is absent.')
    if account and d['sender'].lower()!=account['email'].lower():
        reasons.append('Sender must match the connected Gmail account.')
    if not d['sender']:
        reasons.append('Choose a connected sender.')
    if any(x in d['subject']+d['body'] for x in ('[',']')):
        reasons.append('Replace or remove all bracketed drafting placeholders.')
    if '\n' in d['subject'] or '\r' in d['subject']:
        reasons.append('Subject cannot contain line breaks.')
    if not any(job_state(j,p['freshness_days'])=='fresh' for j in s['jobs']):
        reasons.append('No fresh, active hiring source. Refresh EUJobs or hold this opportunity.')
    if match_basis([j for j in s['jobs'] if job_state(j,p['freshness_days'])!='inactive'],p)['excluded']:
        reasons.append('This opportunity matches a campaign exclusion.')
    if s['organization']['resolution']=='ambiguous':
        reasons.append('Resolve conflicting register identities before outreach.')
    state=c.execute('SELECT status FROM opportunities WHERE id=?',(d['opportunity_id'],)).fetchone()
    if state['status'] in ('hold','rejected'):
        reasons.append('This opportunity is held or rejected. Return it to review first.')
    if d['state'] in ('hold','rejected'):
        reasons.append('This draft is held or rejected. Save a reviewed version first.')
    if c.execute('SELECT email FROM suppressions WHERE email=?',(d['recipient'].lower(),)).fetchone():
        reasons.append('This recipient is suppressed.')
    client=next((x for x in s['clients'] if x['id']==d['client_id']),None)
    if client:
        if not client['verified'] or client['demo']:
            reasons.append('The selected client must be a verified, non-demo relationship.')
        if d['route']=='direct' and (not client['permission'] or not client['allowed_claim']):
            reasons.append('This client has no permitted customer reference claim.')
    if d['route']=='intro':
        if not client or client['email']!=d['recipient']:
            reasons.append('An intro request must go to the selected past client or network contact.')
        relevant=[e for e in s['evidence'] if e['client_id']==d['client_id']]
        if any(e['status']=='conflicting' for e in relevant):
            reasons.append('Relationship evidence contains an unresolved conflict.')
        if not any(e['status']=='verified' and e['kind']=='relationship' and e['participants'] for e in relevant):
            reasons.append('Verify a personal connection with named participants; event overlap alone is insufficient.')
    previous=c.execute('SELECT id FROM sends WHERE draft_id=?',(d['id'],)).fetchone()
    if previous:
        reasons.append('This route already has a send reservation. Reconcile it in Activity; do not resend.')
    active=c.execute("SELECT route,state FROM sends WHERE opportunity_id=? AND state IN ('submitting','provider_accepted','outcome_unknown') AND outcome NOT IN ('declined','closed')",(d['opportunity_id'],)).fetchone()
    if active:
        reasons.append(f"The {active['route']} route is active ({active['state']}); another route is blocked.")
    since=(datetime.now(timezone.utc)-timedelta(days=p['cooldown_days'])).isoformat()
    recent=c.execute("SELECT id FROM sends WHERE created_at>? AND state IN ('submitting','provider_accepted','outcome_unknown') AND (recipient=? OR (? IS NOT NULL AND client_id=?))",(since,d['recipient'],d['client_id'],d['client_id'])).fetchone()
    if recent:
        reasons.append(f"Contact/client cooldown is active ({p['cooldown_days']} days).")
    return list(dict.fromkeys(reasons))


def approve(db, draft_id, version, binding, account, send_enabled, attested):
    with db.connect(write=True) as c:
        row=c.execute('SELECT * FROM drafts WHERE id=?',(draft_id,)).fetchone()
        if not row: raise ValidationError('Draft not found.')
        d=dict(row);s=snapshot(c,d['opportunity_id'])
        if not attested:
            raise Conflict('Review and confirm the exact content, recipient, permitted claims and evidence first.')
        if d['version']!=version or draft_binding(d)!=binding:
            raise Conflict('The message changed. Reload and review the exact saved version.')
        reasons=blockers(c,d,s,account,send_enabled)
        if reasons: raise Conflict(' '.join(reasons))
        aid=str(uuid.uuid4())
        c.execute('UPDATE approvals SET invalidated_at=? WHERE draft_id=? AND invalidated_at IS NULL',(now(),draft_id))
        c.execute('INSERT INTO approvals VALUES(?,?,?,?,?,NULL)',(aid,draft_id,binding,version,now()))
        c.execute("UPDATE drafts SET state='approved' WHERE id=?",(draft_id,))
        audit(c,'approved',draft_id,{'binding':binding,'version':version})
        return aid


def dispatch(db, draft_id, approval_id, adapter):
    # One durable reservation before any provider I/O. No automatic retries.
    with db.connect(write=True) as c:
        row=c.execute('SELECT * FROM drafts WHERE id=?',(draft_id,)).fetchone()
        if not row: raise ValidationError('Draft not found.')
        d=dict(row)
        existing=c.execute('SELECT * FROM sends WHERE draft_id=?',(draft_id,)).fetchone()
        if existing:
            return dict(existing)
        a=c.execute('SELECT * FROM approvals WHERE id=? AND draft_id=?',(approval_id,draft_id)).fetchone()
        if not a or a['invalidated_at'] or a['binding']!=draft_binding(d) or d['state']!='approved':
            raise Conflict('A valid approval of this exact saved message is required.')
        s=snapshot(c,d['opportunity_id'])
        account=adapter.account()
        reasons=blockers(c,d,s,account,adapter.can_send())
        if reasons: raise Conflict(' '.join(reasons))
        sid=str(uuid.uuid4());message_id=f'<signaldesk.{sid}@{d["sender"].split("@")[1]}>'
        c.execute('INSERT INTO sends(id,draft_id,opportunity_id,route,client_id,recipient,sender,subject,body,evidence,binding,approval_id,message_id,state,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(sid,draft_id,d['opportunity_id'],d['route'],d['client_id'],d['recipient'],d['sender'],d['subject'],d['body'],canonical(s),draft_binding(d),approval_id,message_id,'submitting',now(),now()))
        audit(c,'send_reserved',sid,{'draft_id':draft_id,'route':d['route']})
    try:
        result=adapter.send(d,message_id)
        state=result.get('state','outcome_unknown')
        if state not in ('provider_accepted','failed','outcome_unknown'):
            state='outcome_unknown'
    except Exception:
        result={'error':'Provider result unavailable. Reconcile before any further action.'};state='outcome_unknown'
    with db.connect(write=True) as c:
        c.execute('UPDATE sends SET state=?,provider_id=?,thread_id=?,error=?,updated_at=? WHERE id=?',(state,result.get('id'),result.get('threadId'),result.get('error'),now(),sid))
        c.execute('UPDATE drafts SET state=? WHERE id=?',(state,draft_id))
        audit(c,'send_result',sid,{'state':state,'provider_id':result.get('id'),'delivery':'Acceptance is not proof of delivery.'})
        return dict(c.execute('SELECT * FROM sends WHERE id=?',(sid,)).fetchone())
