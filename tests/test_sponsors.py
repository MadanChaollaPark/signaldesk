import pytest
from signaldesk.sponsors import Sponsors,JOIN_SQL

class Response:
    def __init__(self,data):self.data=data
    def raise_for_status(self):pass
    def json(self):return self.data

class FakeHTTP:
    def __init__(self,model):self.model=model;self.requests=[]
    def get(self,url,**kwargs):self.requests.append(('GET',url,kwargs));return Response({'data':[{'id':'meterless/local'}]})
    def post(self,url,**kwargs):
        self.requests.append(('POST',url,kwargs))
        if url.endswith('run-query'):return Response({'rows':[{'register_id':'fixture-123','organization':'Fixture Target'}]})
        return Response({'model':self.model,'id':'fixture-response','choices':[{'message':{'content':'Fixture only: verify the source and recipient.'}}]})


def test_zetaris_real_contract_without_live_claims(app,db):
    s=Sponsors(db,{**app.config,'ZETARIS_BASE_URL':'https://zetaris.example','ZETARIS_ORG_ID':'12','ZETARIS_API_KEY':'fixture-secret'})
    s.http=FakeHTTP('');r=s.zetaris();assert r['result']['rows']
    _,url,args=s.http.requests[-1]
    assert url.endswith('/api/proxy/sql-editor/sqls/run-query') and args['headers']['X-Org-ID']=='12'
    assert args['json']['sql']==JOIN_SQL and 'JOIN signaldesk.clients' in JOIN_SQL
    assert 'fixture-secret' not in db.one('SELECT detail FROM integration_runs')['detail']


@pytest.mark.parametrize('model,verified',[('meterless/local',False),('nvidia/Nemotron-3-Nano-30B-A3B',True),('other-model',False)])
def test_nightshift_never_equates_routing_mode_to_nemotron(app,db,model,verified):
    s=Sponsors(db,{**app.config,'NIGHTSHIFT_BASE_URL':'http://127.0.0.1:8088/v1','NIGHTSHIFT_TOKEN':'fixture-token'})
    s.http=FakeHTTP(model);r=s.nightshift({'source':'fixture'})
    assert r['nemotron_verified']==verified and r['returned_model']==model
    assert s.http.requests[-1][2]['headers']['meterless-app']=='signaldesk'
    assert 'fixture-token' not in db.one('SELECT detail FROM integration_runs')['detail']
