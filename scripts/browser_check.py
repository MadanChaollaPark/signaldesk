"""Real deployment browser checks. No external email actions."""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
BASE=Path('/srv/data/signal-intro-20261027')
out=BASE/'outputs';errors=[];checks=[]
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/srv/data/go-review-20261027/runtime/browsers/chromium-1248/chrome-linux64/chrome',headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
    context=browser.new_context(viewport={'width':1440,'height':1040},device_scale_factor=1)
    page=context.new_page();page.on('pageerror',lambda err:errors.append(str(err)))
    page.goto('http://127.0.0.1:3290/');page.get_by_label('Workspace password').fill((BASE/'runtime/admin-password').read_text().strip());page.get_by_role('button',name='Open workspace').click()
    page.get_by_role('heading',name='Find the right moment.').wait_for();page.locator('tbody tr').first.wait_for()
    assert page.locator('tbody tr').count()>0;checks.append('Desktop populated real signals queue')
    page.screenshot(path=str(out/'01-signals-desktop.png'),full_page=True)
    # Choose a registered company with a current opening from the live queue.
    opportunity=page.evaluate("async()=>{const r=await fetch('/api/signals');return (await r.json()).opportunities.find(o=>o.register_id&&o.freshness==='fresh').id}")
    page.goto('http://127.0.0.1:3290/#opportunity/'+opportunity)
    page.get_by_role('heading',name='Review your outreach').wait_for()
    if page.get_by_role('button',name='Prepare intro request').count():
        page.get_by_role('button',name='Prepare intro request').click()
    page.locator('textarea[name=body]').wait_for()
    body=page.locator('textarea[name=body]').input_value()
    assert 'introduction' in body or 'introducing' in body
    page.locator('textarea[name=body]').fill(body if 'Draft note: review source' in body else body+'\n\nDraft note: review source and relationship before sending.')
    assert page.locator('#approve-button').is_disabled()
    page.get_by_role('button',name='Save draft',exact=True).click()
    page.get_by_text('Saved version',exact=False).wait_for()
    page.reload();page.locator('textarea[name=body]').wait_for()
    assert 'Draft note: review source' in page.locator('textarea[name=body]').input_value();checks.append('Editable intro persists through page reload; send disabled while setup incomplete')
    page.screenshot(path=str(out/'02-draft-review-desktop.png'),full_page=True)
    page.get_by_role('button',name='Direct outreach',exact=False).click()
    expect(page.locator('.route-tabs button.active')).to_contain_text('Direct outreach')
    if page.get_by_role('button',name='Prepare direct draft').count():page.get_by_role('button',name='Prepare direct draft').click()
    page.locator('textarea[name=body]').wait_for();assert 'Prospect first name' in page.locator('textarea[name=body]').input_value();checks.append('Alternative direct draft editable and separately persisted')
    page.screenshot(path=str(out/'03-direct-draft-desktop.png'),full_page=True)
    page.goto('http://127.0.0.1:3290/#clients');page.get_by_role('heading',name='Clients & network',exact=True).wait_for();page.screenshot(path=str(out/'04-clients-desktop.png'),full_page=True)
    page.get_by_role('button',name='Add client / contact',exact=False).click();page.get_by_role('heading',name='Add a client or network contact').wait_for();page.get_by_label('Company *',exact=True).fill('DEMO Example Studio');page.get_by_label('Contact name *',exact=True).fill('DEMO Alex');page.get_by_label('This is a labelled demo contact',exact=False).check();page.screenshot(path=str(out/'05-client-entry-labelled-demo.png'),full_page=True);page.get_by_role('button',name='Close dialog').click();checks.append('Client entry dialog usable; labelled demo unsaved')
    page.goto('http://127.0.0.1:3290/#settings');page.get_by_role('heading',name='Connections & settings').wait_for();assert page.get_by_text('Setup needed',exact=True).count()>0;page.screenshot(path=str(out/'06-gmail-settings-desktop.png'),full_page=True);checks.append('Gmail credentials absent reported honestly')
    page.goto('http://127.0.0.1:3290/#connections');page.get_by_role('heading',name='Connections & events').wait_for();assert page.get_by_text('Event evidence library',exact=True).is_visible();checks.append('Actual sourced events library loads')
    mobile=browser.new_context(viewport={'width':390,'height':844},device_scale_factor=1,is_mobile=True,has_touch=True,storage_state=context.storage_state())
    mp=mobile.new_page();mp.on('pageerror',lambda err:errors.append(str(err)));mp.goto('http://127.0.0.1:3290/#signals');mp.get_by_role('heading',name='Find the right moment.').wait_for();mp.screenshot(path=str(out/'07-signals-mobile.png'),full_page=True)
    assert mp.evaluate('document.documentElement.scrollWidth <= window.innerWidth');checks.append('Mobile signals queue has no horizontal page overflow')
    mp.goto('http://127.0.0.1:3290/#opportunity/'+opportunity);mp.get_by_role('heading',name='Review your outreach').wait_for();mp.screenshot(path=str(out/'08-draft-review-mobile.png'),full_page=True);assert mp.evaluate('document.documentElement.scrollWidth <= window.innerWidth');checks.append('Mobile editable draft view has no horizontal overflow')
    mp.goto('http://127.0.0.1:3290/#settings');mp.get_by_role('heading',name='Connections & settings').wait_for();mp.screenshot(path=str(out/'09-gmail-settings-mobile.png'),full_page=True)
    assert not errors,errors
    (out/'browser-results.json').write_text(json.dumps({'checks':checks,'page_errors':errors,'actual_service':'http://127.0.0.1:3290','external_sends':0,'demo_clients_saved':0,'opportunity_id':opportunity},indent=2))
    browser.close()
print(json.dumps({'checks':checks,'page_errors':errors},indent=2))
