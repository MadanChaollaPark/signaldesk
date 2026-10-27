import concurrent.futures
import json
import pytest
from conftest import ready, FakeMail
from signaldesk.db import set_setting,now,invalidate
from signaldesk.workflow import approve,dispatch,draft_binding,save_draft,Conflict,queue,snapshot,blockers


def approved(db,d,mail=None):
    m=mail or FakeMail()
    return approve(db,d['id'],d['version'],draft_binding(d),m.account(),m.can_send(),True)


def test_editable_draft_persists_and_invalidates_approval(db,seeded):
    d=ready(db);a=approved(db,d)
    changed=save_draft(db,'target','direct',dict(d,body='A completely edited, persisted message.'),client_id=seeded['cid'])
    assert changed['body']=='A completely edited, persisted message.'
    assert changed['version']==d['version']+1
    assert db.one('SELECT invalidated_at FROM approvals WHERE id=?',(a,))['invalidated_at']
    with pytest.raises(Conflict):dispatch(db,d['id'],a,FakeMail())
    with pytest.raises(Conflict):save_draft(db,'target','direct',d,client_id=1)


def test_no_approval_no_send(db,seeded):
    d=ready(db);m=FakeMail()
    with pytest.raises(Conflict):dispatch(db,d['id'],'invalid',m)
    assert not m.calls
    with pytest.raises(Conflict):approve(db,d['id'],d['version'],draft_binding(d),m.account(),True,False)
    with pytest.raises(Conflict):approve(db,d['id'],d['version'],'wrong',m.account(),True,True)


def test_material_evidence_change_blocks_even_without_invalidation(db,seeded):
    d=ready(db);a=approved(db,d)
    with db.connect(write=True) as c:c.execute("UPDATE evidence SET claim='Conflicting newer fact' WHERE id=1")
    m=FakeMail()
    with pytest.raises(Conflict,match='Evidence changed'):dispatch(db,d['id'],a,m)
    assert not m.calls


def test_suppression_rechecked_at_send(db,seeded):
    d=ready(db);a=approved(db,d)
    with db.connect(write=True) as c:c.execute('INSERT INTO suppressions VALUES(?,?,?)',(d['recipient'],'No outreach',now()))
    with pytest.raises(Conflict,match='suppressed'):dispatch(db,d['id'],a,FakeMail())


def test_intro_pending_excludes_direct_route(db,seeded):
    m=FakeMail();intro=ready(db,'intro');direct=ready(db,'direct');ai=approved(db,intro);ad=approved(db,direct)
    sent=dispatch(db,intro['id'],ai,m)
    assert sent['state']=='provider_accepted'
    with pytest.raises(Conflict,match='route is active'):dispatch(db,direct['id'],ad,m)
    assert len(m.calls)==1


def test_concurrent_double_clicks_reserve_once(db,seeded):
    d=ready(db);a=approved(db,d);m=FakeMail()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        results=list(ex.map(lambda _:dispatch(db,d['id'],a,m),range(16)))
    assert len(m.calls)==1
    assert len({s['id'] for s in results})==1
    assert db.one('SELECT count(*) n FROM sends')['n']==1
    s=db.one('SELECT * FROM sends');assert s['body']==d['body'] and s['binding']==draft_binding(d)
    assert json.loads(s['evidence'])['organization']['name']=='Target Org'


@pytest.mark.parametrize('result',['failed','outcome_unknown','raise'])
def test_failed_and_unknown_are_not_retried(db,seeded,result):
    d=ready(db);m=FakeMail(result);a=approved(db,d,m)
    s=dispatch(db,d['id'],a,m);again=dispatch(db,d['id'],a,m)
    assert s['state']==('outcome_unknown' if result=='raise' else result)
    assert again['id']==s['id'] and len(m.calls)==1
    with pytest.raises(Conflict):save_draft(db,'target','direct',dict(d,body='Retry?'),client_id=1)


def test_client_cooldown_across_opportunities(db,seeded):
    m=FakeMail();d=ready(db,'intro');dispatch(db,d['id'],approved(db,d),m)
    with db.connect(write=True) as c:
        c.execute("INSERT INTO organizations VALUES('other','Other','other.example',NULL,'unmatched','[]','')")
        c.execute("INSERT INTO opportunities VALUES('other','review',?)",(now(),))
        c.execute("INSERT INTO jobs SELECT 'other-job','other',title,description,summary,location,topic,status,source_url,checked_at,published_at,deadline,provenance,imported_at FROM jobs WHERE id='job'")
    other=ready(db,'direct',oid='other')
    with pytest.raises(Conflict,match='cooldown'):approved(db,other)


@pytest.mark.parametrize('field,value,reason',[('checked_at','2020-01-01','fresh'),('deadline','2020-01-01','fresh'),('status','closed','fresh')])
def test_stale_and_inactive_sources_block(db,seeded,field,value,reason):
    d=ready(db)
    with db.connect(write=True) as c:c.execute(f'UPDATE jobs SET {field}=?',(value,))
    # Save changed evidence explicitly; freshness must still block approval.
    d=save_draft(db,'target','direct',dict(d),client_id=1)
    with pytest.raises(Conflict,match=reason):approved(db,d)


def test_intro_requires_named_personal_evidence_not_coattendance(db,seeded):
    with db.connect(write=True) as c:c.execute("UPDATE evidence SET kind='event',status='possible'")
    d=ready(db,'intro')
    with pytest.raises(Conflict,match='personal connection'):approved(db,d)


def test_demo_unpermitted_and_wrong_sender_block(db,seeded):
    with db.connect(write=True) as c:c.execute('UPDATE clients SET demo=1,permission=0')
    d=ready(db)
    with pytest.raises(Conflict,match='non-demo'):approved(db,d)
    with db.connect(write=True) as c:c.execute('UPDATE clients SET demo=0')
    d=save_draft(db,'target','direct',d,client_id=1)
    with pytest.raises(Conflict,match='permitted'):approved(db,d)
    with db.connect(write=True) as c:c.execute('UPDATE clients SET permission=1')
    d=save_draft(db,'target','direct',dict(d,sender='impostor@example.com'),client_id=1)
    with pytest.raises(Conflict,match='Sender must match'):approved(db,d)


def test_route_race_only_one_provider_call(db,seeded):
    intro=ready(db,'intro');direct=ready(db,'direct');m=FakeMail();ai=approved(db,intro);ad=approved(db,direct)
    def run(d,a):
        try:return dispatch(db,d['id'],a,m)['state']
        except Conflict:return 'blocked'
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        results=list(ex.map(lambda args:run(*args),[(intro,ai),(direct,ad)]))
    assert results.count('blocked')==1 and len(m.calls)==1
