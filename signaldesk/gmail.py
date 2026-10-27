"""Bounded Gmail OAuth/search/send adapter. Tokens never leave the server."""
import base64
import hashlib
import json
import secrets
import time
from email.message import EmailMessage
from email.utils import parseaddr
from urllib.parse import urlencode
import requests
from cryptography.fernet import Fernet
from .db import now, canonical, invalidate
from .sources import ValidationError, clean, email

READ = 'https://www.googleapis.com/auth/gmail.readonly'
SEND = 'https://www.googleapis.com/auth/gmail.send'


class Gmail:
    def __init__(self, db, config, key):
        self.db=db;self.config=config;self.cipher=Fernet(key)
        self.http=requests.Session()
        self.http.mount('https://',requests.adapters.HTTPAdapter(max_retries=0))
        self.credentials=None
        path=config.get('GOOGLE_CLIENT_FILE')
        if path:
            try:
                with open(path) as f: raw=json.load(f)
                self.credentials=raw['web']
                for k in ('client_id','client_secret','redirect_uris'):
                    if not self.credentials.get(k): raise ValueError()
                if self.redirect_uri not in self.credentials['redirect_uris']:
                    raise ValueError()
            except (OSError,KeyError,ValueError):
                self.credentials=None
        self.auth_url='https://accounts.google.com/o/oauth2/v2/auth'
        self.token_url='https://oauth2.googleapis.com/token'
        self.revoke_url='https://oauth2.googleapis.com/revoke'
        self.api='https://gmail.googleapis.com/gmail/v1/users/me'
        if config.get('TESTING'):
            for k in ('auth_url','token_url','revoke_url','api'):
                if config.get('FAKE_'+k.upper()): setattr(self,k,config['FAKE_'+k.upper()])

    @property
    def redirect_uri(self):
        return self.config['BASE_URL'].rstrip('/')+'/oauth/google/callback'

    def configured(self):
        return self.credentials is not None

    def account(self):
        r=self.db.one('SELECT email,scopes,connected_at FROM oauth_account WHERE id=1')
        if r: r['scopes']=json.loads(r['scopes'])
        return r

    def can_send(self):
        a=self.account()
        return bool(self.configured() and a and SEND in a['scopes'])

    def status(self):
        a=self.account()
        return {'configured':self.configured(),'connected':bool(a),'account':a,'can_send':self.can_send(),'redirect_uri':self.redirect_uri,'state':'connected' if a else 'ready_to_connect' if self.configured() else 'setup_needed','search_limit':10,'scope_note':'Read-only scope supports scoped search. Sending requires a separate send permission. No bulk mailbox indexing.'}

    def start(self, session_id, with_send=False):
        if not self.configured(): raise ValidationError('Google OAuth web-client credentials are not installed. See Settings.')
        state=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(64)
        challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        scopes=[READ]+([SEND] if with_send else [])
        with self.db.connect(write=True) as c:
            c.execute('DELETE FROM oauth_states WHERE expires<? OR session_id=?',(time.time(),session_id))
            c.execute('INSERT INTO oauth_states VALUES(?,?,?,?,?)',(state,session_id,verifier,canonical(scopes),time.time()+600))
        return self.auth_url+'?'+urlencode({'client_id':self.credentials['client_id'],'redirect_uri':self.redirect_uri,'response_type':'code','scope':' '.join(scopes),'state':state,'access_type':'offline','prompt':'consent','code_challenge':challenge,'code_challenge_method':'S256'})

    def callback(self, session_id, state, code, error=None):
        with self.db.connect(write=True) as c:
            r=c.execute('SELECT * FROM oauth_states WHERE state=? AND session_id=?',(state,session_id)).fetchone()
            if not r or r['expires']<time.time(): raise ValidationError('OAuth state is missing, expired or belongs to another session. Connect again.')
            c.execute('DELETE FROM oauth_states WHERE state=?',(state,))
        if error or not code: raise ValidationError('Google consent was not completed. Nothing was connected.')
        try:
            response=self.http.post(self.token_url,data={'client_id':self.credentials['client_id'],'client_secret':self.credentials['client_secret'],'code':code,'code_verifier':r['verifier'],'redirect_uri':self.redirect_uri,'grant_type':'authorization_code'},timeout=20)
            response.raise_for_status();token=response.json()
            granted=token.get('scope','').split()
            if READ not in granted: raise ValueError('Missing read scope')
            response=self.http.get(self.api+'/profile',headers={'Authorization':'Bearer '+token['access_token']},timeout=20)
            response.raise_for_status();account_email=email(response.json()['emailAddress'],True)
            if not token.get('refresh_token'): raise ValueError('Offline grant unavailable')
        except (requests.RequestException,ValueError,KeyError):
            raise ValidationError('Google authorization could not be verified, including offline/read access. Reconnect and grant the requested permissions.')
        token['expires_at']=time.time()+int(token.get('expires_in',3600))
        with self.db.connect(write=True) as c:
            c.execute('INSERT OR REPLACE INTO oauth_account VALUES(1,?,?,?,?)',(account_email,self.cipher.encrypt(canonical(token).encode()).decode(),canonical(granted),now()))
            invalidate(c,'Connected sender or Gmail permissions changed')
        return account_email

    def access_token(self, expected_email=None):
        row=self.db.one('SELECT encrypted,email FROM oauth_account WHERE id=1')
        if not row: raise ValidationError('Connect Gmail first.')
        if expected_email and row['email'].lower()!=expected_email.lower(): raise ValidationError('Connected sender changed. Review the message again.')
        token=json.loads(self.cipher.decrypt(row['encrypted'].encode()))
        if token['expires_at'] > time.time()+90: return token['access_token']
        if not self.configured(): raise ValidationError('Google OAuth credentials are unavailable.')
        try:
            r=self.http.post(self.token_url,data={'client_id':self.credentials['client_id'],'client_secret':self.credentials['client_secret'],'grant_type':'refresh_token','refresh_token':token['refresh_token']},timeout=20)
            r.raise_for_status();new=r.json();token.update(new);token['expires_at']=time.time()+int(new.get('expires_in',3600))
            token['access_token']
        except (requests.RequestException,ValueError,KeyError):
            raise ValidationError('Gmail access could not be refreshed. Reconnect the account.')
        with self.db.connect(write=True) as c:
            # Do not resurrect a disconnected account during a concurrent refresh.
            c.execute('UPDATE oauth_account SET encrypted=? WHERE id=1 AND encrypted=?',(self.cipher.encrypt(canonical(token).encode()).decode(),row['encrypted']))
        return token['access_token']

    def get(self, path, params=None):
        try:
            r=self.http.get(self.api+path,params=params,headers={'Authorization':'Bearer '+self.access_token()},timeout=20)
            r.raise_for_status();return r.json()
        except (requests.RequestException,ValueError):
            raise ValidationError('Gmail request failed. Check the connection and try again.')

    @staticmethod
    def excerpt(m):
        headers={h['name'].lower():h['value'] for h in m.get('payload',{}).get('headers',[])}
        return {'id':m['id'],'thread_id':m.get('threadId',''),'snippet':m.get('snippet','')[:1500],'subject':headers.get('subject',''),'from':headers.get('from',''),'to':headers.get('to',''),'date':headers.get('date',''),'internal_date':m.get('internalDate',''),'message_id':headers.get('message-id',''),'in_reply_to':headers.get('in-reply-to',''),'url':'https://mail.google.com/mail/u/0/#all/'+m['id']}

    def search(self, term, kind='company'):
        term=clean(term,150,True)
        if kind=='email':
            term=email(term,True);q=f'{{from:{term} to:{term}}}'
        elif kind=='company':
            if not all(c.isalnum() or c in " .&'-" for c in term):
                raise ValidationError('Use a company or person name without Gmail search operators.')
            q='"'+term+'"'
        else: raise ValidationError('Search by company/person name or email.')
        q+=' newer_than:2y -in:trash -in:spam'
        result=self.get('/messages',{'q':q,'maxResults':10})
        rows=[]
        for m in result.get('messages',[])[:10]:
            full=self.get('/messages/'+m['id'],{'format':'metadata','metadataHeaders':['From','To','Subject','Date','Message-ID','In-Reply-To']})
            rows.append(self.excerpt(full))
        return {'query':q,'messages':rows,'coverage':'At most 10 recent matching messages from the last two years. An email exchange does not by itself prove a client relationship.'}

    def disconnect(self):
        row=self.db.one('SELECT encrypted FROM oauth_account WHERE id=1')
        revoked=False
        if row:
            token=json.loads(self.cipher.decrypt(row['encrypted'].encode()))
            try:
                r=self.http.post(self.revoke_url,data={'token':token.get('refresh_token') or token['access_token']},timeout=20)
                revoked=r.status_code==200
            except requests.RequestException: pass
        with self.db.connect(write=True) as c:
            c.execute('DELETE FROM oauth_account');c.execute('DELETE FROM oauth_states');c.execute('DELETE FROM gmail_results')
            invalidate(c,'Gmail disconnected')
        return {'disconnected':True,'revoked':revoked,'message':'Account disconnected and Google grant revoked.' if revoked else 'Local tokens deleted. Google revocation was not confirmed; remove access in your Google Account permissions.'}

    def send(self, draft, message_id):
        if not self.can_send(): return {'state':'failed','error':'Gmail send permission is absent; nothing submitted.'}
        try: token=self.access_token(expected_email=draft['sender'])
        except ValidationError: return {'state':'failed','error':'Gmail authorization failed before submission.'}
        message=EmailMessage();message['From']=draft['sender'];message['To']=draft['recipient'];message['Subject']=draft['subject'];message['Message-ID']=message_id;message.set_content(draft['body'])
        raw=base64.urlsafe_b64encode(message.as_bytes()).decode()
        try:
            r=self.http.post(self.api+'/messages/send',headers={'Authorization':'Bearer '+token},json={'raw':raw},timeout=25)
            if r.status_code in (400,401,403,404,413,429):
                return {'state':'failed','error':f'Gmail rejected the request (HTTP {r.status_code}); no acceptance recorded.'}
            r.raise_for_status();result=r.json()
            if not result.get('id'): raise ValueError()
            return {'state':'provider_accepted','id':result['id'],'threadId':result.get('threadId')}
        except (requests.RequestException,ValueError):
            return {'state':'outcome_unknown','error':'Gmail acceptance is uncertain. Reconcile by the unique Message-ID; never blindly resend.'}

    def reconcile(self, sent):
        if sent['sender']!=(self.account() or {}).get('email'):
            raise ValidationError('Reconnect the original sending account to reconcile.')
        result=self.get('/messages',{'q':'in:sent rfc822msgid:'+sent['message_id'].strip('<>'),'maxResults':2})
        msgs=result.get('messages',[])
        if len(msgs)!=1:
            return {'state':'outcome_unknown','error':'No unique matching sent message found yet. This is not proof that sending failed.'}
        m=self.get('/messages/'+msgs[0]['id'],{'format':'metadata','metadataHeaders':['From','To','Subject','Message-ID']});e=self.excerpt(m)
        if (e['message_id']!=sent['message_id'] or parseaddr(e['from'])[1].lower()!=sent['sender'] or parseaddr(e['to'])[1].lower()!=sent['recipient'] or e['subject']!=sent['subject']):
            return {'state':'outcome_unknown','error':'Message metadata did not match the reserved send.'}
        return {'state':'provider_accepted','id':m['id'],'threadId':m.get('threadId'),'error':None}

    def replies(self, sent):
        if sent['sender']!=(self.account() or {}).get('email'):
            raise ValidationError('Reconnect the original sending account to check replies.')
        if not sent.get('thread_id'): raise ValidationError('Reconcile the send to obtain a thread first.')
        thread=self.get('/threads/'+sent['thread_id'],{'format':'metadata','metadataHeaders':['From','To','Subject','Date','Message-ID','In-Reply-To']})
        results=[]
        for m in thread.get('messages',[])[:30]:
            e=self.excerpt(m)
            if parseaddr(e['from'])[1].lower()==sent['recipient'] and e['in_reply_to']==sent['message_id']:
                results.append(e)
        return results
