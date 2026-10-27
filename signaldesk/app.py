import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse
from flask import Flask, request, jsonify, render_template, redirect, g, make_response
from werkzeug.security import generate_password_hash, check_password_hash
from cryptography.fernet import Fernet
from .db import Database, now, canonical, digest, audit, set_setting, invalidate
from .sources import ValidationError, clean, email, truth, date, safe_url, validate_client, csv_preview, save_client, save_events, import_eujobs
from .workflow import DEFAULT_PROFILE, Conflict, queue, snapshot, connections, save_draft, draft_binding, blockers, approve, dispatch, parsed
from .gmail import Gmail

ROOT=Path(__file__).resolve().parents[2]


def protected_file(path, make):
    path=Path(path)
    if not path.exists():
        path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f:f.write(make())
    path.chmod(0o600)
    return path.read_text().strip()


def create_app(test_config=None):
    os.umask(0o077)
    app=Flask(__name__,template_folder='../templates',static_folder='../static')
    app.config.update(BASE_URL=os.environ.get('SIGNALDESK_BASE_URL','http://127.0.0.1:3290'),DATABASE=os.environ.get('SIGNALDESK_DB',str(ROOT/'data/signaldesk.sqlite')),RUNTIME=str(ROOT/'runtime'),GOOGLE_CLIENT_FILE=os.environ.get('GOOGLE_CLIENT_FILE',''),EUJOBS_DB='/srv/data/eujobs/db/eujobs.sqlite',EUJOBS_RESOURCES='/srv/data/eujobs/db/resources.json',MAX_CONTENT_LENGTH=600000)
    if test_config: app.config.update(test_config)
    base=urlparse(app.config['BASE_URL'])
    if base.scheme not in ('http','https') or not base.hostname or base.path not in ('','/') or base.username or base.query or base.fragment:
        raise RuntimeError('BASE_URL must be an HTTP(S) origin.')
    if base.scheme=='http' and base.hostname not in ('127.0.0.1','localhost') and not app.config.get('TESTING'):
        raise RuntimeError('Non-loopback deployment requires HTTPS.')
    app.config['TRUSTED_HOSTS']=list({base.netloc,'127.0.0.1:3290','localhost:3290'}) if not app.config.get('TESTING') else ['localhost','127.0.0.1']
    runtime=Path(app.config['RUNTIME']);runtime.mkdir(parents=True,exist_ok=True,mode=0o700)
    password_hash=app.config.get('PASSWORD_HASH')
    if not password_hash:
        password=protected_file(runtime/'admin-password',lambda:secrets.token_urlsafe(24))
        password_hash=protected_file(runtime/'password-hash',lambda:generate_password_hash(password))
    key=protected_file(runtime/'token.key',lambda:Fernet.generate_key().decode())
    db=Database(app.config['DATABASE']);app.extensions['db']=db
    gmail=Gmail(db,app.config,key.encode());app.extensions['gmail']=gmail
    from .sponsors import Sponsors
    sponsors=Sponsors(db,app.config);app.extensions['sponsors']=sponsors

    def session_new(auth=False):
        sid=secrets.token_urlsafe(40);csrf=secrets.token_urlsafe(32)
        with db.connect(write=True) as c:
            c.execute('DELETE FROM sessions WHERE expires<?',(time.time(),))
            c.execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashlib.sha256(sid.encode()).hexdigest(),csrf,int(auth),time.time()+43200))
        g.new_sid=sid
        return {'id':hashlib.sha256(sid.encode()).hexdigest(),'csrf':csrf,'authenticated':int(auth)}

    @app.before_request
    def secure_request():
        if request.path=='/healthz' or request.path.startswith('/static/'):
            return
        sid=request.cookies.get('signaldesk_session','')
        g.session=db.one('SELECT * FROM sessions WHERE id=? AND expires>?',(hashlib.sha256(sid.encode()).hexdigest(),time.time())) if sid else None
        if not g.session:
            if request.path!='/login':
                return (jsonify(error='Authentication required.'),401) if request.path.startswith('/api/') or request.path.startswith('/oauth/') else redirect('/login')
            g.session=session_new()
        if not g.session['authenticated'] and request.path!='/login':
            return (jsonify(error='Authentication required.'),401) if request.path.startswith('/api/') or request.path.startswith('/oauth/') else redirect('/login')
        if request.method not in ('GET','HEAD','OPTIONS'):
            token=request.headers.get('X-CSRF-Token') or request.form.get('csrf','')
            origin=request.headers.get('Origin')
            if not token or not hmac.compare_digest(token,g.session['csrf']) or (origin and origin.rstrip('/')!=app.config['BASE_URL'].rstrip('/')):
                return jsonify(error='Request verification failed. Reload the page.'),403

    @app.after_request
    def security_headers(response):
        response.headers.update({'X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Referrer-Policy':'same-origin','Cache-Control':'no-store','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",'Permissions-Policy':'camera=(), microphone=(), geolocation=()'})
        if hasattr(g,'new_sid'):
            response.set_cookie('signaldesk_session',g.new_sid,httponly=True,secure=base.scheme=='https',samesite='Lax',max_age=43200)
        return response

    @app.errorhandler(ValidationError)
    def validation(e):return jsonify(error=str(e)),409 if isinstance(e,Conflict) else 400

    @app.errorhandler(413)
    def too_large(e):return jsonify(error='Upload is too large. Use CSV files under 400 KB.'),413

    @app.errorhandler(500)
    def internal(e):return jsonify(error='The operation could not be completed. No automatic send retry will occur.'),500

    def payload():
        d=request.get_json(silent=True)
        if not isinstance(d,dict): raise ValidationError('Expected a JSON object.')
        return d

    @app.get('/healthz')
    def health():
        db.one('SELECT 1 AS ok')
        return jsonify(status='ok',service='signaldesk')

    @app.route('/login',methods=['GET','POST'])
    def login():
        error=None
        if request.method=='POST':
            ip=request.remote_addr or 'unknown'
            with db.connect(write=True) as c:
                old=c.execute('SELECT * FROM login_attempts WHERE ip=?',(ip,)).fetchone()
                count=old['count'] if old and old['window']>time.time()-900 else 0
                if count>=10: return render_template('login.html',csrf=g.session['csrf'],error='Too many attempts. Try again in 15 minutes.'),429
                c.execute('INSERT OR REPLACE INTO login_attempts VALUES(?,?,?)',(ip,count+1,old['window'] if count else time.time()))
            if check_password_hash(password_hash,request.form.get('password','')):
                with db.connect(write=True) as c:
                    c.execute('DELETE FROM sessions WHERE id=?',(g.session['id'],));c.execute('DELETE FROM login_attempts WHERE ip=?',(ip,))
                session_new(True);return redirect('/')
            error='That password did not match.'
        return render_template('login.html',csrf=g.session['csrf'],error=error)

    @app.post('/api/logout')
    def logout():
        with db.connect(write=True) as c:c.execute('DELETE FROM sessions WHERE id=?',(g.session['id'],))
        response=jsonify(ok=True);response.delete_cookie('signaldesk_session');return response

    @app.get('/')
    def index():return render_template('index.html',csrf=g.session['csrf'])

    @app.get('/api/bootstrap')
    def bootstrap():
        latest=db.one("SELECT * FROM imports WHERE kind='eujobs' ORDER BY id DESC LIMIT 1")
        return jsonify(profile={**DEFAULT_PROFILE,**db.setting('profile',{})},clients=db.all('SELECT * FROM clients ORDER BY company,name'),gmail=gmail.status(),integrations=sponsors.status(),source=json.loads(latest['report']) if latest else None,csrf=g.session['csrf'])

    @app.get('/api/signals')
    def signals():return jsonify(opportunities=queue(db))

    @app.get('/api/opportunities/<oid>')
    def opportunity(oid):
        with db.connect() as c:
            s=snapshot(c,oid)
            drafts=[dict(r) for r in c.execute('SELECT * FROM drafts WHERE opportunity_id=?',(oid,))]
            for d in drafts:
                d['binding']=draft_binding(d);d['blockers']=blockers(c,d,s,gmail.account(),gmail.can_send())
            state=c.execute('SELECT status FROM opportunities WHERE id=?',(oid,)).fetchone()
        relevant_events=[e for e in s['events'] if e['organization'].casefold()==s['organization']['name'].casefold()]
        return jsonify(organization=s['organization'],jobs=s['jobs'],evidence=s['evidence'],connections=connections(s),events=relevant_events,drafts=drafts,status=state['status'],evidence_hash=digest(s),memory=sponsors.recall(oid))

    @app.post('/api/profile')
    def update_profile():
        d=payload();p={k:clean(d.get(k,''),3000 if k in ('offering','buyer') else 1000) for k in ('offering','buyer','keywords','exclusions','sender_name')}
        for k in ('cooldown_days','freshness_days'):
            try:p[k]=int(d.get(k,14))
            except (ValueError,TypeError):raise ValidationError('Limits must be whole numbers.')
            if not 1<=p[k]<=90:raise ValidationError('Limits must be between 1 and 90 days.')
        with db.connect(write=True) as c:set_setting(c,'profile',p);invalidate(c,'Campaign profile changed')
        return jsonify(profile=p)

    @app.post('/api/sources/refresh')
    def refresh():return jsonify(report=import_eujobs(db,app.config['EUJOBS_DB'],app.config['EUJOBS_RESOURCES']))

    @app.get('/api/registers')
    def registers():
        term=clean(request.args.get('q',''),150,True)
        return jsonify(records=db.all('SELECT id,name,domain,source_url,in_register FROM registers WHERE id=? OR name LIKE ? ORDER BY name LIMIT 25',(term,'%'+term.replace('%','').replace('_','')+'%')))

    @app.post('/api/opportunities/<oid>/resolve')
    def resolution(oid):
        d=payload();rid=clean(d.get('register_id',''),100,True);note=clean(d.get('note',''),1500,True)
        with db.connect(write=True) as c:
            r=c.execute('SELECT * FROM registers WHERE id=?',(rid,)).fetchone()
            if not r or not r['in_register']:raise ValidationError('Choose a current register record.')
            if not c.execute('SELECT id FROM organizations WHERE id=?',(oid,)).fetchone():raise ValidationError('Organization not found.')
            c.execute("UPDATE organizations SET register_id=?,domain=?,resolution='manual',resolution_note=? WHERE id=?",(rid,r['domain'],note,oid));invalidate(c,'User reviewed entity identity')
        return jsonify(ok=True)

    @app.post('/api/clients')
    def add_client():
        row=validate_client(payload())
        with db.connect(write=True) as c:cid=save_client(c,row);audit(c,'client_added',cid,{'demo':row['demo']})
        return jsonify(id=cid),201

    @app.put('/api/clients/<int:cid>')
    def edit_client(cid):
        row=validate_client(payload())
        with db.connect(write=True) as c:save_client(c,row,cid);audit(c,'client_updated',cid,{})
        return jsonify(ok=True)

    @app.post('/api/import/preview')
    def preview():
        d=payload();r=csv_preview(clean(d.get('csv',''),400000,True),d.get('kind'))
        preview_id=secrets.token_urlsafe(24)
        with db.connect(write=True) as c:
            c.execute('DELETE FROM import_previews WHERE expires<?',(time.time(),))
            c.execute('INSERT INTO import_previews VALUES(?,?,?,?,?)',(preview_id,g.session['id'],r['kind'],canonical(r),time.time()+1800))
        return jsonify(**r,preview_id=preview_id)

    @app.post('/api/import/commit')
    def commit_import():
        pid=clean(payload().get('preview_id',''),100,True)
        with db.connect(write=True) as c:
            r=c.execute('SELECT * FROM import_previews WHERE id=? AND session_id=? AND expires>?',(pid,g.session['id'],time.time())).fetchone()
            if not r:raise ValidationError('Preview expired. Preview the CSV again.')
            p=json.loads(r['payload'])
            if p['errors']:raise ValidationError('Fix every validation error before importing.')
            if r['kind']=='clients':
                for row in p['rows']:save_client(c,row)
            else:save_events(c,p['rows'])
            c.execute('DELETE FROM import_previews WHERE id=?',(pid,))
            c.execute('INSERT INTO imports(kind,report,created_at) VALUES(?,?,?)',(r['kind'],canonical({'rows':p['count']}),now()))
            audit(c,'csv_imported','',{'kind':r['kind'],'rows':p['count']})
        return jsonify(imported=p['count'])

    @app.get('/api/events')
    def events():
        return jsonify(events=db.all('SELECT * FROM events ORDER BY date DESC'),participation=db.all('SELECT * FROM participation ORDER BY event_id,role'))

    def add_evidence(oid,d,kind=None):
        cid=d.get('client_id') or None
        if cid is not None and (not isinstance(cid,int) or not db.one('SELECT id FROM clients WHERE id=?',(cid,))):raise ValidationError('Select an existing client.')
        status=d.get('status','possible');ekind=kind or d.get('kind','relationship')
        if status not in ('verified','possible','conflicting','rejected') or ekind not in ('relationship','employment','event','gmail'):
            raise ValidationError('Invalid evidence type or status.')
        claim=clean(d.get('claim',''),3000,True);url=safe_url(d.get('source_url',''));when=date(d.get('source_date',''),True)
        if parsed(when)>datetime.now(timezone.utc):raise ValidationError('Relationship evidence cannot have a future verification date.')
        people=clean(d.get('participants',''),1000);roles=clean(d.get('roles',''),1000)
        if status=='verified' and (not truth(d.get('attested')) or not people):raise ValidationError('Name the participants and explicitly verify the source before marking evidence verified.')
        supersedes=d.get('supersedes') or None
        with db.connect(write=True) as c:
            if not c.execute('SELECT id FROM organizations WHERE id=?',(oid,)).fetchone():raise ValidationError('Organization not found.')
            if supersedes and not c.execute('SELECT id FROM evidence WHERE id=? AND org_id=?',(supersedes,oid)).fetchone():raise ValidationError('Correction must reference evidence for the same target.')
            if supersedes and c.execute('SELECT id FROM evidence WHERE supersedes=?',(supersedes,)).fetchone():raise Conflict('This evidence was already corrected. Refresh and correct the latest record.')
            eid=c.execute('INSERT INTO evidence(org_id,client_id,kind,status,claim,source_url,source_date,participants,roles,supersedes,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(oid,cid,ekind,status,claim,url,when,people,roles,supersedes,now())).lastrowid
            invalidate(c,'Relationship evidence or correction added')
            audit(c,'evidence_added',eid,{'status':status,'supersedes':supersedes})
        memory=sponsors.remember(oid,eid)
        return {'id':eid,'memory':memory}

    @app.post('/api/opportunities/<oid>/evidence')
    def evidence(oid):return jsonify(add_evidence(oid,payload()))

    @app.post('/api/opportunities/<oid>/drafts/<route>')
    def draft(oid,route):
        d=payload();cid=d.get('client_id') or None
        if cid is not None and not isinstance(cid,int):raise ValidationError('Client ID must be a number.')
        result=save_draft(db,oid,route,d,regenerate=d.get('regenerate') is True,client_id=cid)
        return jsonify(draft=result)

    @app.post('/api/drafts/<int:did>/approve')
    def approval(did):
        d=payload();aid=approve(db,did,d.get('version'),d.get('binding'),gmail.account(),gmail.can_send(),d.get('attested') is True)
        return jsonify(approval_id=aid)

    @app.post('/api/drafts/<int:did>/send')
    def send(did):return jsonify(send=dispatch(db,did,clean(payload().get('approval_id',''),100,True),gmail))

    @app.post('/api/opportunities/<oid>/status')
    def set_status(oid):
        status=payload().get('status')
        if status not in ('review','hold','rejected'):raise ValidationError('Invalid opportunity state.')
        with db.connect(write=True) as c:
            if not c.execute('SELECT id FROM opportunities WHERE id=?',(oid,)).fetchone():raise ValidationError('Opportunity not found.')
            c.execute('UPDATE opportunities SET status=?,updated_at=? WHERE id=?',(status,now(),oid));c.execute('UPDATE approvals SET invalidated_at=? WHERE draft_id IN (SELECT id FROM drafts WHERE opportunity_id=?) AND invalidated_at IS NULL',(now(),oid));audit(c,'opportunity_status',oid,{'status':status})
        return jsonify(ok=True)

    @app.post('/api/suppressions')
    def suppress():
        d=payload();address=email(d.get('email',''),True);reason=clean(d.get('reason','Manual suppression'),1000,True)
        with db.connect(write=True) as c:
            c.execute('INSERT OR REPLACE INTO suppressions VALUES(?,?,?)',(address,reason,now()));invalidate(c,'Recipient suppressed');audit(c,'suppressed',address,{'reason':reason})
        return jsonify(ok=True)

    @app.get('/api/activity')
    def activity():
        return jsonify(drafts=db.all('SELECT d.*,o.name company FROM drafts d JOIN organizations o ON o.id=d.opportunity_id ORDER BY d.updated_at DESC'),sends=db.all('SELECT * FROM sends ORDER BY created_at DESC'),activity=db.all('SELECT * FROM activity ORDER BY id DESC LIMIT 150'),replies=db.all('SELECT * FROM replies ORDER BY created_at DESC'),suppressions=db.all('SELECT * FROM suppressions ORDER BY created_at DESC'))

    @app.post('/api/sends/<sid>/reconcile')
    def reconcile(sid):
        s=db.one('SELECT * FROM sends WHERE id=?',(sid,))
        if not s:raise ValidationError('Send not found.')
        if s['state'] not in ('outcome_unknown','submitting'):raise ValidationError('This send does not require reconciliation.')
        if s['state']=='submitting' and time.time()-parsed(s['created_at']).timestamp()<90:raise Conflict('Submission is still in progress. Wait before reconciling.')
        result=gmail.reconcile(s)
        with db.connect(write=True) as c:
            c.execute('UPDATE sends SET state=?,provider_id=?,thread_id=?,error=?,updated_at=? WHERE id=?',(result['state'],result.get('id'),result.get('threadId'),result.get('error'),now(),sid));c.execute('UPDATE drafts SET state=? WHERE id=?',(result['state'],s['draft_id']));audit(c,'reconciled',sid,result)
        return jsonify(result=result)

    @app.post('/api/sends/<sid>/replies')
    def sync_replies(sid):
        s=db.one('SELECT * FROM sends WHERE id=?',(sid,))
        if not s:raise ValidationError('Send not found.')
        replies=gmail.replies(s)
        with db.connect(write=True) as c:
            for r in replies:c.execute('INSERT OR IGNORE INTO replies VALUES(?,?,?,?)',(r['id'],sid,canonical(r),now()))
            audit(c,'replies_checked',sid,{'found':len(replies)})
        return jsonify(replies=replies)

    @app.post('/api/sends/<sid>/outcome')
    def set_outcome(sid):
        outcome=payload().get('outcome')
        if outcome not in ('declined','closed','replied','intro_made'):raise ValidationError('Choose a supported outcome.')
        with db.connect(write=True) as c:
            s=c.execute('SELECT * FROM sends WHERE id=?',(sid,)).fetchone()
            if not s or s['state']!='provider_accepted':raise Conflict('Resolve provider state before recording a route outcome.')
            c.execute('UPDATE sends SET outcome=?,updated_at=? WHERE id=?',(outcome,now(),sid));audit(c,'outcome_recorded',sid,{'outcome':outcome,'source':'user'})
        return jsonify(ok=True)

    @app.post('/api/gmail/connect')
    def connect_gmail():return jsonify(url=gmail.start(g.session['id'],payload().get('with_send') is True))

    @app.get('/oauth/google/callback')
    def callback():
        if request.base_url!=gmail.redirect_uri:raise ValidationError('OAuth callback URL does not match the configured redirect.')
        gmail.callback(g.session['id'],request.args.get('state',''),request.args.get('code',''),request.args.get('error'))
        return redirect('/#settings')

    @app.post('/api/gmail/search')
    def search_gmail():
        d=payload();result=gmail.search(d.get('term',''),d.get('kind','company'))
        with db.connect(write=True) as c:
            c.execute('DELETE FROM gmail_results WHERE expires<?',(time.time(),))
            for m in result['messages']:
                token=secrets.token_urlsafe(24)
                c.execute('INSERT INTO gmail_results VALUES(?,?,?,?)',(token,g.session['id'],canonical(m),time.time()+1800));m['selection_id']=token
        return jsonify(result)

    @app.post('/api/gmail/import')
    def import_gmail():
        d=payload();r=db.one('SELECT * FROM gmail_results WHERE id=? AND session_id=? AND expires>?',(d.get('selection_id'),g.session['id'],time.time()))
        if not r:raise ValidationError('Search result expired. Search again and select the message.')
        m=json.loads(r['payload']);oid=clean(d.get('org_id',''),100,True)
        try:
            message_date=parsedate_to_datetime(m['date']).isoformat()
        except (ValueError,TypeError):
            message_date=now()
        data={'client_id':d.get('client_id'),'status':'possible','claim':m['subject']+' — '+m['snippet'],'source_url':m['url'],'source_date':message_date,'participants':m['from']+'; '+m['to'],'roles':'Mailbox correspondents; relationship not yet verified.'}
        return jsonify(add_evidence(oid,data,'gmail'))

    @app.post('/api/gmail/disconnect')
    def disconnect_gmail():return jsonify(gmail.disconnect())

    @app.post('/api/integrations/<service>/probe')
    def probe(service):return jsonify(sponsors.probe(service))

    @app.post('/api/opportunities/<oid>/research')
    def research(oid):
        with db.connect() as c:s=snapshot(c,oid)
        return jsonify(sponsors.research(s))

    return app
