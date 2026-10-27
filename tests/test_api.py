import json
import pytest
from conftest import ready,FakeMail
from signaldesk.workflow import draft_binding


def test_authentication_and_csrf_are_server_enforced(client,auth,seeded,app):
    anonymous=app.test_client()
    for url in ['/api/signals','/api/clients','/api/events','/api/activity','/api/bootstrap','/api/opportunities/target','/oauth/google/callback']:
        assert anonymous.get(url).status_code==401
    assert anonymous.get('/healthz').json['status']=='ok'
    assert client.post('/api/profile',json={}).status_code==403
    assert client.post('/api/profile',headers={**auth,'Origin':'https://attacker.example'},json={}).status_code==403
    r=client.get('/');assert "frame-ancestors 'none'" in r.headers['Content-Security-Policy']
    assert 'no-store' in r.headers['Cache-Control']


def test_draft_save_and_send_endpoints_require_exact_review(client,auth,seeded,db,app,monkeypatch):
    d=ready(db);m=FakeMail();g=app.extensions['gmail']
    for name in ('account','can_send','send'):monkeypatch.setattr(g,name,getattr(m,name))
    assert client.post(f'/api/drafts/{d["id"]}/send',headers=auth,json={'approval_id':'missing'}).status_code==409
    r=client.get('/api/opportunities/target');saved=r.json['drafts'][0]
    a=client.post(f'/api/drafts/{d["id"]}/approve',headers=auth,json={'version':saved['version'],'binding':saved['binding'],'attested':True})
    assert a.status_code==200,a.json
    sent=client.post(f'/api/drafts/{d["id"]}/send',headers=auth,json=a.json)
    assert sent.json['send']['state']=='provider_accepted'
    again=client.post(f'/api/drafts/{d["id"]}/send',headers=auth,json=a.json)
    assert again.json['send']['id']==sent.json['send']['id'] and len(m.calls)==1


def test_client_edit_and_csv_preview_commit(client,auth,db):
    row={'company':'Client','name':'Alex','email':'a@example.com','relationship':'past client','context':'Known work','permission':False,'verified':True}
    r=client.post('/api/clients',headers=auth,json=row);assert r.status_code==201
    cid=r.json['id'];row['context']='Corrected context'
    assert client.put(f'/api/clients/{cid}',headers=auth,json=row).status_code==200
    assert db.one('SELECT context FROM clients')['context']=='Corrected context'
    p=client.post('/api/import/preview',headers=auth,json={'kind':'clients','csv':'company,name,relationship,context\nOther,Sam,partner,Worked together\n'}).json
    assert db.one('SELECT count(*) n FROM clients')['n']==1
    assert client.post('/api/import/commit',headers=auth,json={'preview_id':p['preview_id']}).json['imported']==1
    assert client.post('/api/import/commit',headers=auth,json={'preview_id':p['preview_id']}).status_code==400


def test_disabled_gmail_is_honest(client,auth):
    g=client.get('/api/bootstrap').json['gmail'];assert not g['connected'] and not g['can_send'] and g['state']=='setup_needed'
    assert client.post('/api/gmail/connect',headers=auth,json={}).status_code==400


def test_evidence_corrections_retain_history_and_change_recommendation(client,auth,seeded,db):
    d=ready(db,'intro')
    r=client.post('/api/opportunities/target/evidence',headers=auth,json={'client_id':1,'kind':'relationship','status':'conflicting','claim':'Correction: Alex no longer knows Sam at Target Org. Prior relationship was mistaken.','source_url':'https://example.com/correction','source_date':'2026-10-20','participants':'Alex; Sam','roles':'No verified current relationship','supersedes':1})
    assert r.status_code==200,r.json
    assert db.one('SELECT count(*) n FROM evidence')['n']==2
    detail=client.get('/api/opportunities/target').json
    assert len(detail['evidence'])==1 and detail['evidence'][0]['supersedes']==1
    assert 'Correction:' in detail['memory']['context']
    assert 'Alex confirmed knowing' not in detail['memory']['context']
    assert any('conflict' in b for b in detail['drafts'][0]['blockers'])


def test_unsafe_source_url_and_unverified_claim_are_rejected(client,auth,seeded):
    base={'kind':'relationship','status':'verified','claim':'They know each other','source_date':'2026-10-20','participants':'Alex; Sam','attested':True}
    assert client.post('/api/opportunities/target/evidence',headers=auth,json={**base,'source_url':'javascript:alert(1)'}).status_code==400
    assert client.post('/api/opportunities/target/evidence',headers=auth,json={**base,'attested':False}).status_code==400


def test_sessions_rotate_and_logout_revokes_server_access(app,client,auth):
    cookie=client.get_cookie('signaldesk_session')
    assert cookie.http_only and cookie.same_site=='Lax'
    assert client.post('/api/logout',headers=auth,json={}).status_code==200
    assert client.get('/api/bootstrap').status_code==401
    client.set_cookie('signaldesk_session',cookie.value)
    assert client.get('/api/bootstrap').status_code==401


def test_old_drafts_remain_accessible_after_job_closes(client,auth,seeded,db):
    d=ready(db)
    with db.connect(write=True) as c:c.execute("UPDATE jobs SET status='closed'")
    assert not client.get('/api/signals').json['opportunities']
    archive=client.get('/api/activity').json['drafts']
    assert archive[0]['id']==d['id']
    assert client.get('/api/opportunities/target').status_code==200
