"""End-to-end browser workflow in an isolated local app with a fake mail adapter."""
import json
import sys
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from playwright.sync_api import sync_playwright,expect
from werkzeug.serving import make_server,WSGIRequestHandler
from werkzeug.security import generate_password_hash
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from signaldesk.app import create_app
from conftest import seeded,FakeMail
BASE=Path('/srv/data/signal-intro-20261027');checks=[];errors=[]
class Quiet(WSGIRequestHandler):
    def log_request(self,*args):pass
with TemporaryDirectory(dir=BASE/'runtime/tmp',prefix='browser-fixture-') as temporary:
    app=create_app({'TESTING':True,'DATABASE':temporary+'/state.sqlite','RUNTIME':temporary+'/runtime','BASE_URL':'http://127.0.0.1','PASSWORD_HASH':generate_password_hash('test-password')})
    db=app.extensions['db'];seeded.__wrapped__(db)
    # Fixture data stays isolated. No real mailbox adapter can send in this process.
    fake=FakeMail();gmail=app.extensions['gmail']
    with db.connect(write=True) as cx:cx.execute('INSERT INTO oauth_account VALUES(1,?,?,?,?)',('sender@example.com','ISOLATED_FAKE_TOKEN_NEVER_USED',json.dumps(fake.account()['scopes']),'2026-10-27T00:00:00+00:00'))
    gmail.account=fake.account;gmail.can_send=fake.can_send;gmail.send=fake.send
    server=make_server('127.0.0.1',0,app,threaded=True,request_handler=Quiet);base=f'http://127.0.0.1:{server.server_port}';app.config['BASE_URL']=base
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='/srv/data/go-review-20261027/runtime/browsers/chromium-1248/chrome-linux64/chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
            page=browser.new_page(viewport={'width':1440,'height':1040});page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(base);page.get_by_label('Workspace password').fill('test-password');page.get_by_role('button',name='Open workspace').click();page.get_by_role('heading',name='Find the right moment.').wait_for()
            page.goto(base+'/#profile');page.get_by_role('heading',name='Your offering, your rules').wait_for();page.locator('[name=offering]').fill('TEST FIXTURE: policy research support');page.get_by_role('button',name='Save profile',exact=False).click();expect(page.locator('#toast')).to_contain_text('Profile saved');checks.append('Offering onboarding saved via browser')
            page.goto(base+'/#clients');page.get_by_role('heading',name='Clients & network',exact=True).wait_for();page.get_by_role('button',name='Edit',exact=True).click();page.locator('#client-form [name=context]').fill('TEST FIXTURE: verified project relationship, not a real client.');page.get_by_role('button',name='Save contact').click();expect(page.locator('#toast')).to_contain_text('Contact saved');checks.append('Client context edited and persisted via browser')
            page.get_by_role('button',name='Import CSV',exact=True).click();page.locator('#csv-text').fill('company,name,email,relationship,context,demo\nDEMO Imported Studio,DEMO Pat,pat@example.com,DEMO partner,DEMO fixture only,true\n');page.get_by_role('button',name='Validate & preview').click();page.get_by_role('button',name='Import 1 reviewed rows').click();expect(page.get_by_role('heading',name='DEMO Imported Studio')).to_be_visible();checks.append('CSV preview and explicit commit via browser; demo labelled')
            page.screenshot(path=str(BASE/'outputs/10-fixture-clients.png'),full_page=True)
            page.goto(base+'/#opportunity/target');page.get_by_role('heading',name='Review your outreach').wait_for();page.locator('#draft-client').select_option('1');page.get_by_role('button',name='Prepare intro request').click();page.locator('textarea[name=body]').wait_for()
            # Template is entirely source backed with complete fixture offering and personal relationship.
            expect(page.locator('#approve-button')).to_be_enabled();page.locator('textarea[name=body]').fill(page.locator('textarea[name=body]').input_value()+'\n\nTEST FIXTURE: this reaches a local fake provider only.');expect(page.locator('#approve-button')).to_be_disabled();page.get_by_role('button',name='Save draft',exact=True).click();expect(page.locator('#approve-button')).to_be_enabled()
            page.locator('#approve-button').click();page.get_by_role('heading',name='Approve this exact message').wait_for();page.screenshot(path=str(BASE/'outputs/11-fixture-approval-modal.png'),full_page=True)
            page.locator('#send-form input[name=attested]').check();page.locator('#send-form button[type=submit]').click();expect(page.locator('#toast')).to_contain_text('Gmail accepted');assert len(fake.calls)==1;checks.append('Exact message confirmation and per-message approval dispatch one fake send')
            page.get_by_role('button',name='Direct outreach',exact=False).click();expect(page.locator('.route-tabs button.active')).to_contain_text('Direct outreach');page.locator('#draft-client').select_option('1');page.get_by_role('button',name='Prepare direct draft').click();page.locator('textarea[name=body]').wait_for();page.locator('[name=recipient_name]').fill('Sam Prospect');page.locator('[name=recipient]').fill('sam@target.example');page.locator('[name=recipient_verified]').check();page.locator('textarea[name=body]').fill('Hi Sam,\nTEST FIXTURE: We worked with Example Client on research. We noticed your Policy Director opening. Is a short discussion useful?\nJordan');page.get_by_role('button',name='Save draft',exact=True).click();expect(page.locator('.blockers')).to_contain_text('intro route is active');expect(page.locator('#approve-button')).to_be_disabled();checks.append('Pending intro blocks direct route in browser and backend')
            page.get_by_role('button',name='Suppress contact',exact=True).click();page.locator('#suppress-form button').click();expect(page.locator('.blockers')).to_contain_text('suppressed');checks.append('Suppression persists and blocks the prospect')
            page.goto(base+'/#activity');page.get_by_role('heading',name='Activity & outcomes').wait_for();expect(page.get_by_text('provider accepted',exact=True)).to_be_visible();page.get_by_text('Exact reserved message & evidence').click();expect(page.get_by_text('TEST FIXTURE: this reaches a local fake provider only.',exact=False)).to_be_visible();checks.append('Activity retains exact content, evidence and provider acceptance without delivery claims')
            page.screenshot(path=str(BASE/'outputs/12-fixture-activity.png'),full_page=True)
            assert not errors,errors
            browser.close()
        result={'mode':'ISOLATED TEST FIXTURE — local fake mail only','checks':checks,'fake_sends':len(fake.calls),'real_sends':0,'page_errors':errors}
        (BASE/'outputs/browser-workflow-results.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
    finally:
        server.shutdown();thread.join(timeout=5)
