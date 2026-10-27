import json
import sys
from datetime import datetime,timezone,timedelta
from pathlib import Path
import pytest
from werkzeug.security import generate_password_hash
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from signaldesk.app import create_app
from signaldesk.db import now,canonical,set_setting
from signaldesk.sources import save_client
from signaldesk.workflow import save_draft,DEFAULT_PROFILE

@pytest.fixture
def app(tmp_path):
    return create_app({'TESTING':True,'DATABASE':str(tmp_path/'db.sqlite'),'RUNTIME':str(tmp_path/'runtime'),'BASE_URL':'http://localhost','PASSWORD_HASH':generate_password_hash('test-password'),'HMEM_DIR':str(tmp_path/'hmem')})

@pytest.fixture
def db(app):return app.extensions['db']

@pytest.fixture
def client(app):return app.test_client()

def login(client):
    import re
    r=client.get('/login');token=re.search(r'name="csrf" value="([^"]+)',r.text)[1]
    r=client.post('/login',data={'csrf':token,'password':'test-password'})
    assert r.status_code==302
    return client.get('/api/bootstrap').json['csrf']

@pytest.fixture
def auth(client):return {'X-CSRF-Token':login(client)}

@pytest.fixture
def seeded(db):
    with db.connect(write=True) as c:
        c.execute('INSERT INTO registers VALUES(?,?,?,?,?,?,?,?,?)',('123-456-78','Target Org','TO','target-org','target.example','https://example.com/register','2026-10-14','2026-10-14',1))
        c.execute('INSERT INTO organizations VALUES(?,?,?,?,?,?,?)',('target','Target Org','target.example','123-456-78','exact name','[]',''))
        c.execute('INSERT INTO opportunities VALUES(?,?,?)',('target','review',now()))
        c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',('job','target','Policy Director','Responsibilities include government relations and policy strategy.','Lead policy team','Brussels','Policy','published','https://example.com/job',now(),now(),(datetime.now(timezone.utc)+timedelta(days=20)).isoformat(),canonical({'system':'test fixture'}),now()))
        cid=save_client(c,dict(company='Example Client',name='Alex Client',email='alex@example.com',role='Director',domain='example.com',relationship='past client',context='Verified test fixture project in 2025',allowed_claim='We worked with Example Client on research.',permission=1,verified=1,demo=0))
        c.execute('INSERT INTO evidence(org_id,client_id,kind,status,claim,source_url,source_date,participants,roles,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',('target',cid,'relationship','verified','Alex confirmed knowing Sam at Target Org','https://example.com/evidence','2026-10-20','Alex Client; Sam Prospect','Former colleagues',now()))
        set_setting(c,'profile',{**DEFAULT_PROFILE,'offering':'policy research support','buyer':'Policy directors','sender_name':'Jordan','keywords':'policy'})
    return {'oid':'target','cid':cid}


def ready(db,route='direct',cid=1,oid='target'):
    d=save_draft(db,oid,route,regenerate=True,client_id=cid)
    body='Hi Sam,\nI saw your Policy Director opening. We worked with Example Client on research. Is policy research support useful?\nJordan'
    return save_draft(db,oid,route,{'version':d['version'],'subject':'Your policy opening','body':body,'recipient':'alex@example.com' if route=='intro' else 'sam@target.example','recipient_name':'Alex Client' if route=='intro' else 'Sam Prospect','recipient_verified':True,'sender':'sender@example.com'},client_id=cid)

class FakeMail:
    def __init__(self,state='provider_accepted'):
        self.calls=[];self.state=state
    def account(self):return {'email':'sender@example.com','scopes':['https://www.googleapis.com/auth/gmail.readonly','https://www.googleapis.com/auth/gmail.send']}
    def can_send(self):return True
    def send(self,d,message_id):
        self.calls.append((dict(d),message_id))
        if self.state=='raise':raise TimeoutError('simulated')
        return {'state':self.state,'id':'fake-accepted' if self.state=='provider_accepted' else None,'threadId':'fake-thread'}
