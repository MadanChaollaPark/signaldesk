import contextlib
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


SCHEMA = '''
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, csrf TEXT NOT NULL, authenticated INTEGER NOT NULL DEFAULT 0, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS oauth_states(state TEXT PRIMARY KEY, session_id TEXT NOT NULL, verifier TEXT NOT NULL, scopes TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS oauth_account(id INTEGER PRIMARY KEY CHECK(id=1), email TEXT NOT NULL, encrypted TEXT NOT NULL, scopes TEXT NOT NULL, connected_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS registers(id TEXT PRIMARY KEY, name TEXT NOT NULL, acronym TEXT, slug TEXT, domain TEXT, source_url TEXT, source_date TEXT, updated TEXT, in_register INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS reg_domain ON registers(domain);
CREATE TABLE IF NOT EXISTS organizations(id TEXT PRIMARY KEY, name TEXT NOT NULL, domain TEXT, register_id TEXT REFERENCES registers(id), resolution TEXT NOT NULL, candidates TEXT NOT NULL DEFAULT '[]', resolution_note TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, org_id TEXT NOT NULL REFERENCES organizations(id), title TEXT NOT NULL, description TEXT NOT NULL, summary TEXT NOT NULL, location TEXT, topic TEXT, status TEXT, source_url TEXT, checked_at TEXT, published_at TEXT, deadline TEXT, provenance TEXT NOT NULL, imported_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, title TEXT NOT NULL, date TEXT, source_url TEXT, checked_at TEXT, description TEXT, provenance TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS participation(id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES events(id), organization TEXT NOT NULL, person TEXT NOT NULL DEFAULT '', role TEXT NOT NULL, source_url TEXT, evidence_status TEXT NOT NULL DEFAULT 'possible');
CREATE TABLE IF NOT EXISTS clients(id INTEGER PRIMARY KEY AUTOINCREMENT, company TEXT NOT NULL, name TEXT NOT NULL, email TEXT NOT NULL, role TEXT NOT NULL DEFAULT '', domain TEXT NOT NULL DEFAULT '', relationship TEXT NOT NULL, context TEXT NOT NULL, allowed_claim TEXT NOT NULL DEFAULT '', permission INTEGER NOT NULL DEFAULT 0, verified INTEGER NOT NULL DEFAULT 0, demo INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS evidence(id INTEGER PRIMARY KEY AUTOINCREMENT, org_id TEXT NOT NULL REFERENCES organizations(id), client_id INTEGER REFERENCES clients(id), kind TEXT NOT NULL, status TEXT NOT NULL, claim TEXT NOT NULL, source_url TEXT NOT NULL, source_date TEXT NOT NULL, participants TEXT NOT NULL DEFAULT '', roles TEXT NOT NULL DEFAULT '', supersedes INTEGER REFERENCES evidence(id), created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS opportunities(id TEXT PRIMARY KEY REFERENCES organizations(id), status TEXT NOT NULL DEFAULT 'review', updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS drafts(id INTEGER PRIMARY KEY AUTOINCREMENT, opportunity_id TEXT NOT NULL REFERENCES opportunities(id), route TEXT NOT NULL CHECK(route IN ('intro','direct')), client_id INTEGER REFERENCES clients(id), recipient TEXT NOT NULL DEFAULT '', recipient_name TEXT NOT NULL DEFAULT '', recipient_verified INTEGER NOT NULL DEFAULT 0, sender TEXT NOT NULL DEFAULT '', subject TEXT NOT NULL, body TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, evidence_hash TEXT NOT NULL, model TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'review', created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(opportunity_id,route));
CREATE TABLE IF NOT EXISTS approvals(id TEXT PRIMARY KEY, draft_id INTEGER NOT NULL REFERENCES drafts(id), binding TEXT NOT NULL, version INTEGER NOT NULL, created_at TEXT NOT NULL, invalidated_at TEXT);
CREATE TABLE IF NOT EXISTS sends(id TEXT PRIMARY KEY, draft_id INTEGER NOT NULL REFERENCES drafts(id), opportunity_id TEXT NOT NULL, route TEXT NOT NULL, client_id INTEGER, recipient TEXT NOT NULL, sender TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL, evidence TEXT NOT NULL, binding TEXT NOT NULL, approval_id TEXT NOT NULL REFERENCES approvals(id), message_id TEXT NOT NULL UNIQUE, state TEXT NOT NULL, provider_id TEXT, thread_id TEXT, error TEXT, outcome TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(draft_id));
CREATE TABLE IF NOT EXISTS suppressions(email TEXT PRIMARY KEY, reason TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS activity(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, object_id TEXT NOT NULL DEFAULT '', detail TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS imports(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, report TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS import_previews(id TEXT PRIMARY KEY, session_id TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS gmail_results(id TEXT PRIMARY KEY, session_id TEXT NOT NULL, payload TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS replies(id TEXT PRIMARY KEY, send_id TEXT NOT NULL REFERENCES sends(id), payload TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS integration_runs(id INTEGER PRIMARY KEY AUTOINCREMENT, service TEXT NOT NULL, status TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS login_attempts(ip TEXT PRIMARY KEY, count INTEGER NOT NULL, window REAL NOT NULL);
'''


class Database:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as c:
            c.executescript(SCHEMA)
            c.execute('PRAGMA journal_mode=WAL')
        Path(path).chmod(0o600)

    @contextlib.contextmanager
    def connect(self, write=False):
        c = sqlite3.connect(self.path, timeout=20, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        c.execute('PRAGMA busy_timeout=20000')
        try:
            c.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    def all(self, sql, args=()):
        with self.connect() as c:
            return [dict(r) for r in c.execute(sql, args)]

    def one(self, sql, args=()):
        rows = self.all(sql, args)
        return rows[0] if rows else None

    def setting(self, key, default=None):
        r = self.one('SELECT value FROM settings WHERE key=?', (key,))
        return json.loads(r['value']) if r else default


def set_setting(c, key, value):
    c.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, canonical(value)))


def audit(c, kind, object_id, detail):
    c.execute('INSERT INTO activity(kind,object_id,detail,created_at) VALUES(?,?,?,?)', (kind, str(object_id), canonical(detail), now()))


def invalidate(c, reason):
    c.execute('UPDATE approvals SET invalidated_at=? WHERE invalidated_at IS NULL', (now(),))
    c.execute("UPDATE drafts SET state='review' WHERE state='approved'")
    audit(c, 'evidence_changed', '', {'reason': reason})
