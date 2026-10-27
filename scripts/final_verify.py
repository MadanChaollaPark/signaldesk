"""Read final deployed state and write durable verification; never send mail."""
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
from datetime import datetime,timezone
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[2];APP=ROOT/'app';OUT=ROOT/'outputs'
def command(*args):return subprocess.check_output(args,text=True,cwd=APP).strip()
checks=[]
def record(name,passed,detail,evidence=None):
    checks.append({'name':name,'passed':bool(passed),'detail':detail,'evidence':evidence})
service=command('systemctl','--user','show','signal-intro-web.service','-p','ActiveState','-p','SubState','-p','UnitFileState','-p','NRestarts','-p','MemoryCurrent')
record('persistent_web_service','ActiveState=active' in service and 'UnitFileState=enabled' in service,service)
timer=command('systemctl','--user','show','signal-intro-refresh.timer','-p','ActiveState','-p','UnitFileState','-p','NextElapseUSecRealtime')
record('persistent_source_refresh','ActiveState=active' in timer and 'UnitFileState=enabled' in timer,timer)
refresh=command('systemctl','--user','show','signal-intro-refresh.service','-p','Result','-p','ExecMainStatus')
record('refresh_unit_exercised','Result=success' in refresh and 'ExecMainStatus=0' in refresh,refresh,'runtime/refresh.log')
ports=command('ss','-ltn');lines=[l for l in ports.splitlines() if ':3290' in l]
record('loopback_only',len(lines)==1 and '127.0.0.1:3290' in lines[0],lines)
r=requests.get('http://127.0.0.1:3290/healthz',timeout=10);record('live_health',r.status_code==200 and r.json().get('status')=='ok',{'status':r.status_code,'body':r.json()})
unauth={p:requests.get('http://127.0.0.1:3290'+p,timeout=10,allow_redirects=False).status_code for p in ['/','/api/bootstrap','/api/signals','/api/events','/api/activity','/api/opportunities/anything','/oauth/google/callback']}
record('private_routes_require_auth',all(code==(302 if path=='/' else 401) for path,code in unauth.items()),unauth)
s=requests.Session();login=s.get('http://127.0.0.1:3290/login',timeout=10)
csrf=re.search('name="csrf" value="([^"]+)',login.text)[1]
r=s.post('http://127.0.0.1:3290/login',data={'csrf':csrf,'password':(ROOT/'runtime/admin-password').read_text().strip()},headers={'Origin':'http://127.0.0.1:3290'},allow_redirects=False,timeout=10)
record('live_login',r.status_code==302,'Authenticated using protected server credential; no value recorded.')
b=s.get('http://127.0.0.1:3290/api/bootstrap',timeout=10).json();csrf=b['csrf']
queue=s.get('http://127.0.0.1:3290/api/signals',timeout=10).json()['opportunities']
record('actual_source_signals',len(queue)>0 and any(o['register_id'] for o in queue),{'opportunities':len(queue),'register_linked_opportunities':sum(bool(o['register_id']) for o in queue),'fresh_opportunities':sum(o['freshness']=='fresh' for o in queue),'source':b['source']},'outputs/source-import.json')
record('honest_gmail_status',not b['gmail']['connected'] and not b['gmail']['can_send'] and b['gmail']['state']=='setup_needed',b['gmail'])
r=s.post('http://127.0.0.1:3290/api/profile',json={},timeout=10);record('csrf_enforced',r.status_code==403,{'status':r.status_code})
r=s.post('http://127.0.0.1:3290/api/integrations/hmem/probe',json={},headers={'X-CSRF-Token':csrf},timeout=20);record('hmem_in_deployed_sandbox',r.status_code==200 and r.json().get('fixture') is True,r.json(),'outputs/hmem-upstream-tests.txt')
source_sample=[{'organization':o['name'],'register_id':o['register_id'],'resolution':o['resolution'],'domain':o['domain'],'job':{k:o['jobs'][0][k] for k in ('id','title','source_url','checked_at','description','provenance')}} for o in queue[:3]]
(OUT/'source-sample.json').write_text(json.dumps(source_sample,indent=2))
db=sqlite3.connect('file:'+str(ROOT/'data/signaldesk.sqlite')+'?mode=ro',uri=True)
counts={t:db.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('registers','organizations','jobs','events','clients','drafts','sends','oauth_account')};integrity=db.execute('PRAGMA integrity_check').fetchone()[0];db.close()
record('isolated_db_integrity',integrity=='ok',{'integrity':integrity,'counts':counts})
record('no_real_outreach',counts['sends']==0 and counts['oauth_account']==0,'Live app has zero send reservations and zero connected Gmail accounts.')
record('no_fabricated_clients',counts['clients']==0,'Live client table remains empty. Only isolated browser fixtures used synthetic clients.')
permissions={str(p.relative_to(ROOT)):oct(p.stat().st_mode&0o777) for p in [ROOT/'data',ROOT/'data/signaldesk.sqlite',ROOT/'runtime/token.key',ROOT/'runtime/admin-password',ROOT/'runtime/web.env']}
record('private_permissions',all(v in ('0o600','0o700') for v in permissions.values()),permissions)
for name in ['browser-results.json','browser-workflow-results.json']:
    x=json.loads((OUT/name).read_text());record(name,not x['page_errors'] and x.get('real_sends',x.get('external_sends',0))==0,x,'outputs/'+name)
regression=json.loads((OUT/'event-conflict-regression.json').read_text());regression_tests=(OUT/'event-conflict-tests.txt').read_text()
record('event_conflict_review_regression',regression['status']=='passed' and not regression['page_errors'] and regression['real_sends']==0 and '4 passed' in regression_tests,{'browser':regression,'tests':regression_tests.strip()},'outputs/event-conflict-tests.xml')
tests=(OUT/'tests-final.txt').read_text();record('application_tests','38 passed' in tests and 'failed' not in tests.lower(),tests.strip(),'outputs/pytest-results.xml')
hmem=(OUT/'hmem-upstream-tests.txt').read_text();record('hmem_upstream_tests','10 passed' in hmem,hmem.strip(),'outputs/hmem-upstream-tests.txt')
pictures=sorted(p.name for p in OUT.glob('*.png') if p.name[:2].isdigit())
record('durable_screenshots',len(pictures)>=12,pictures)
eu=requests.get('http://127.0.0.1:3210/',timeout=20);eu_service=command('systemctl','is-active','eujobs.service')
record('eujobs_healthy',eu.status_code==200 and eu_service=='active',{'http_status':eu.status_code,'system_service':eu_service,'pid':command('systemctl','show','eujobs.service','-p','MainPID','--value')})
logs=(ROOT/'runtime/web-error.log').read_text();record('web_log_no_application_errors','Traceback' not in logs and '[ERROR]' not in logs,{'lines':len(logs.splitlines()),'tracebacks':logs.count('Traceback')},'runtime/web-error.log')
revision=command('git','rev-parse','HEAD');git_status=command('git','status','--porcelain');branch=command('git','branch','--show-current')
record('source_committed',not git_status and branch.startswith('codex/'),{'commit':revision,'branch':branch,'status':git_status})
runner=json.loads((ROOT/'control/runner-status.json').read_text());record('requested_execution_settings',runner['model']=='gpt-6-astra' and runner['reasoningEffort']=='high' and runner['serviceTier']=='default' and not runner['fastMode'] and not runner['ultrafastMode'],{k:runner[k] for k in ('model','reasoningEffort','serviceTier','fastMode','ultrafastMode')})
result={'status':'ready_for_review' if all(x['passed'] for x in checks) else 'in_progress','checked_at':datetime.now(timezone.utc).isoformat(),'commit':revision,'checks':checks,'pendingSetup':['Enter the actual offering, ideal buyer, sender name and verified client/reference permissions.','Install a Google Web OAuth client JSON at runtime/google-oauth.json (0600), set GOOGLE_CLIENT_FILE, authorize the exact redirect and connect the intended account; gmail.send is a separate grant.','Provide an existing Zetaris origin, numeric org ID and query credentials; register the six SignalDesk datasets and run the evidence join.','Provide a persistent Azure-accessible Nightshift runtime/token and Nemotron-capable routing; verify an actual returned Nemotron model ID.','Optional public HTTPS hostname/reverse proxy only after explicit authorized host setup; current SSH access is fully usable.'],'external_real_sends':0,'live_google_verified':False,'live_zetaris_verified':False,'live_nightshift_nemotron_verified':False,'hmem_reference_verified':True}
(OUT/'verification.json').write_text(json.dumps(result,indent=2))
print(json.dumps({'status':result['status'],'checks_passed':sum(c['passed'] for c in checks),'checks_total':len(checks),'failed':[c['name'] for c in checks if not c['passed']]},indent=2))
if not all(c['passed'] for c in checks):sys.exit(1)
