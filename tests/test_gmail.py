"""Local HTTP fake provider only. No requests to Google or real mail delivery."""
import base64
import hashlib
import json
import threading
import time
from email import message_from_bytes
from pathlib import Path
from urllib.parse import parse_qs,urlparse
import pytest
from flask import Flask,request,jsonify
from werkzeug.serving import make_server,WSGIRequestHandler
from werkzeug.security import generate_password_hash
from signaldesk.app import create_app
from signaldesk.gmail import READ,SEND
from conftest import login

class Quiet(WSGIRequestHandler):
    def log_request(self,*args):pass

@pytest.fixture
def provider(tmp_path):
    fake=Flask('fake_google');state={'sent':[],'search':[],'scopes':READ+' '+SEND,'mode':'accepted','revoked':False,'refreshes':0,'challenge':None}
    @fake.post('/token')
    def token():
        assert request.form['client_id']=='fixture-id'
        assert request.form['client_secret']=='fixture-secret'
        if request.form['grant_type']=='authorization_code':
            verifier=request.form['code_verifier'];challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
            assert challenge==state['challenge']
            assert request.form['redirect_uri']=='http://localhost/oauth/google/callback'
        else:
            assert request.form['refresh_token']=='fixture-refresh';state['refreshes']+=1
        return jsonify(access_token='fixture-access',refresh_token='fixture-refresh',scope=state['scopes'],expires_in=3600,token_type='Bearer')
    @fake.get('/gmail/profile')
    def profile():
        assert request.headers['Authorization']=='Bearer fixture-access'
        return jsonify(emailAddress='sender@example.com')
    @fake.get('/gmail/messages')
    def search():
        state['search'].append(dict(request.args))
        if state.get('empty'):return jsonify(messages=[])
        return jsonify(messages=[{'id':'message1','threadId':'thread1'}])
    @fake.get('/gmail/messages/message1')
    def message():
        sent=state['sent'][-1] if state['sent'] else None
        headers={'From':sent['From'] if sent else 'alex@example.com','To':sent['To'] if sent else 'sender@example.com','Subject':sent['Subject'] if sent else 'Fixture work together','Date':'Tue, 27 Oct 2026 07:00:00 +0000','Message-ID':sent['Message-ID'] if sent else '<fixture@example.com>'}
        return jsonify(id='message1',threadId='thread1',snippet='Fixture excerpt: we worked together on a research project.',payload={'headers':[{'name':k,'value':v} for k,v in headers.items()]})
    @fake.post('/gmail/messages/send')
    def send():
        raw=base64.urlsafe_b64decode(request.json['raw']);state['sent'].append(message_from_bytes(raw))
        if state['mode']=='unknown':return jsonify(error='fake failure after acceptance'),503
        if state['mode']=='failed':return jsonify(error='invalid fixture request'),400
        return jsonify(id='message1',threadId='thread1')
    @fake.get('/gmail/threads/thread1')
    def thread():
        sent=state['sent'][-1]
        return jsonify(messages=[{'id':'reply1','threadId':'thread1','snippet':'Fixture response','payload':{'headers':[{'name':'From','value':sent['To']},{'name':'To','value':sent['From']},{'name':'In-Reply-To','value':sent['Message-ID']},{'name':'Subject','value':'Re: '+sent['Subject']}]}}])
    @fake.post('/revoke')
    def revoke():
        assert request.form['token']=='fixture-refresh';state['revoked']=True
        return '',200
    server=make_server('127.0.0.1',0,fake,request_handler=Quiet);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    root=f'http://127.0.0.1:{server.server_port}'
    creds=tmp_path/'google.json';creds.write_text(json.dumps({'web':{'client_id':'fixture-id','client_secret':'fixture-secret','redirect_uris':['http://localhost/oauth/google/callback']}}));creds.chmod(0o600)
    app=create_app({'TESTING':True,'DATABASE':str(tmp_path/'app.sqlite'),'RUNTIME':str(tmp_path/'runtime'),'BASE_URL':'http://localhost','PASSWORD_HASH':generate_password_hash('test-password'),'GOOGLE_CLIENT_FILE':str(creds),'FAKE_AUTH_URL':root+'/auth','FAKE_TOKEN_URL':root+'/token','FAKE_REVOKE_URL':root+'/revoke','FAKE_API':root+'/gmail'})
    client=app.test_client();headers={'X-CSRF-Token':login(client)}
    yield app,client,headers,state
    server.shutdown();thread.join(timeout=3)


def connect(provider,with_send=True):
    app,c,h,s=provider
    start=c.post('/api/gmail/connect',headers=h,json={'with_send':with_send});assert start.status_code==200
    params=parse_qs(urlparse(start.json['url']).query);s['challenge']=params['code_challenge'][0]
    assert params['code_challenge_method']==['S256']
    assert params['redirect_uri']==['http://localhost/oauth/google/callback']
    if not with_send:s['scopes']=READ
    callback=c.get('/oauth/google/callback',query_string={'state':params['state'][0],'code':'fixture-code'})
    assert callback.status_code==302,callback.json
    return params


def test_oauth_state_pkce_encryption_scopes_refresh_disconnect(provider):
    app,c,h,s=provider;params=connect(provider,False);g=app.extensions['gmail'];db=app.extensions['db']
    assert g.account()['email']=='sender@example.com' and not g.can_send()
    row=db.one('SELECT encrypted FROM oauth_account');assert 'fixture-refresh' not in row['encrypted'] and 'fixture-access' not in row['encrypted']
    assert c.get('/oauth/google/callback',query_string={'state':params['state'][0],'code':'fixture-code'}).status_code==400
    assert c.get('/oauth/google/callback',query_string={'state':'attacker','code':'fixture-code'}).status_code==400
    token=json.loads(g.cipher.decrypt(row['encrypted'].encode()));token['expires_at']=0
    with db.connect(write=True) as cx:cx.execute('UPDATE oauth_account SET encrypted=?',(g.cipher.encrypt(json.dumps(token).encode()).decode(),))
    assert g.access_token()=='fixture-access' and s['refreshes']==1
    result=c.post('/api/gmail/disconnect',headers=h,json={});assert result.json['revoked'] and s['revoked'] and not g.account()
    assert not db.all('SELECT * FROM oauth_states')


def test_scoped_search_and_selected_import_no_bulk_index(provider):
    app,c,h,s=provider;connect(provider)
    r=c.post('/api/gmail/search',headers=h,json={'term':'Example Client','kind':'company'})
    assert r.status_code==200 and len(r.json['messages'])==1
    assert s['search'][-1]['maxResults']=='10' and 'newer_than:2y' in s['search'][-1]['q']
    assert c.post('/api/gmail/search',headers=h,json={'term':'in:anywhere OR *','kind':'company'}).status_code==400
    db=app.extensions['db']
    assert not db.all('SELECT * FROM evidence')
    with db.connect(write=True) as cx:
        cx.execute("INSERT INTO organizations VALUES('target','Target','',NULL,'unmatched','[]','')")
    selection=r.json['messages'][0]['selection_id']
    imported=c.post('/api/gmail/import',headers=h,json={'selection_id':selection,'org_id':'target'})
    assert imported.status_code==200,imported.json
    e=db.one('SELECT * FROM evidence');assert e['status']=='possible' and e['kind']=='gmail' and 'Fixture excerpt' in e['claim']
    assert not db.all('SELECT * FROM clients')
    assert c.post('/api/gmail/import',headers=h,json={'selection_id':'forged','org_id':'target'}).status_code==400


def test_provider_acceptance_mime_timeout_reconciliation_and_replies(provider):
    app,c,h,s=provider;connect(provider);g=app.extensions['gmail']
    d={'sender':'sender@example.com','recipient':'sam@example.com','subject':'Fixture test message','body':'Only a local fake receives this message.'}
    r=g.send(d,'<signaldesk.test@example.com>');assert r['state']=='provider_accepted'
    assert s['sent'][0]['To']=='sam@example.com' and s['sent'][0]['Message-ID']=='<signaldesk.test@example.com>'
    sent={**d,'message_id':'<signaldesk.test@example.com>','thread_id':'thread1'}
    assert g.replies(sent)[0]['snippet']=='Fixture response'
    s['mode']='unknown';r=g.send(d,'<signaldesk.unknown@example.com>');assert r['state']=='outcome_unknown'
    sent['message_id']='<signaldesk.unknown@example.com>'
    assert g.reconcile(sent)['state']=='provider_accepted'
    s['empty']=True;assert g.reconcile(sent)['state']=='outcome_unknown'
    s['mode']='failed';assert g.send(d,'<signaldesk.failed@example.com>')['state']=='failed'


def test_oauth_wrong_session_denial_and_missing_scope(provider):
    app,c,h,s=provider
    r=c.post('/api/gmail/connect',headers=h,json={});params=parse_qs(urlparse(r.json['url']).query);s['challenge']=params['code_challenge'][0]
    second=app.test_client();login(second)
    assert second.get('/oauth/google/callback',query_string={'state':params['state'][0],'code':'fixture-code'}).status_code==400
    assert c.get('/oauth/google/callback',query_string={'state':params['state'][0],'error':'access_denied'}).status_code==400
    assert not app.extensions['gmail'].account()
    r=c.post('/api/gmail/connect',headers=h,json={});params=parse_qs(urlparse(r.json['url']).query);s['challenge']=params['code_challenge'][0];s['scopes']=SEND
    assert c.get('/oauth/google/callback',query_string={'state':params['state'][0],'code':'fixture-code'}).status_code==400
    assert not app.extensions['gmail'].account()


def test_sender_change_prevents_submission(provider):
    app,c,h,s=provider;connect(provider);g=app.extensions['gmail']
    result=g.send({'sender':'different@example.com','recipient':'sam@example.com','subject':'Do not submit','body':'Fixture'},'<wrong-sender@example.com>')
    assert result['state']=='failed' and not s['sent']


def test_revocation_failure_clears_local_tokens_and_reports_uncertainty(provider,monkeypatch):
    import requests
    app,c,h,s=provider;connect(provider);g=app.extensions['gmail']
    def timeout(*args,**kwargs):raise requests.Timeout('fixture')
    monkeypatch.setattr(g.http,'post',timeout)
    result=c.post('/api/gmail/disconnect',headers=h,json={})
    assert result.json['disconnected'] and not result.json['revoked']
    assert 'not confirmed' in result.json['message'] and g.account() is None
