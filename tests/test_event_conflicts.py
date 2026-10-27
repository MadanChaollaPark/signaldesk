"""Regression for review finding: preserve event conflicts from CSV to review UI."""
import json
import threading
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright, expect
from werkzeug.serving import WSGIRequestHandler, make_server
from signaldesk.sources import csv_preview, save_events
from signaldesk.workflow import connections, snapshot

ROOT = Path(__file__).resolve().parents[2]
BROWSER = '/srv/data/go-review-20261027/runtime/browsers/chromium-1248/chrome-linux64/chrome'


def event_csv(target_status, client_status, event_id='regression'):
    return ('event_id,title,date,organization,person,role,source_url,evidence_status\n'
            f'{event_id},TEST FIXTURE {event_id},2026-10-20,Target Org,Sam Prospect,speaker,https://example.com/{event_id},{target_status}\n'
            f'{event_id},TEST FIXTURE {event_id},2026-10-20,Example Client,Alex Client,attendee,https://example.com/{event_id},{client_status}\n')


@pytest.mark.parametrize('target_status,client_status,expected', [
    ('conflicting', 'verified', 'conflicting'),
    ('verified', 'conflicting', 'conflicting'),
    ('verified', 'verified', 'possible'),
])
def test_event_connection_preserves_each_participation_assessment(db, seeded, target_status, client_status, expected):
    preview = csv_preview(event_csv(target_status, client_status), 'events')
    assert not preview['errors']
    with db.connect(write=True) as c:
        save_events(c, preview['rows'])
        result = connections(snapshot(c, 'target'))[0]
    assert result['status'] == expected
    assert result['target_status'] == target_status
    assert result['client_status'] == client_status
    assert result['target_person'] == 'Sam Prospect'
    assert result['client_person'] == 'Alex Client'
    assert (result['target_role'], result['client_role']) == ('speaker', 'attendee')
    assert result['source_url'] == 'https://example.com/regression'
    assert result['date'] == '2026-10-20'


class Quiet(WSGIRequestHandler):
    def log_request(self, *args):
        pass


def test_csv_conflicts_are_visible_in_desktop_and_mobile_review(app, db, seeded):
    # This fixture app has no Google client or connected account. No sender is called.
    server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=Quiet)
    base = f'http://127.0.0.1:{server.server_port}'
    app.config['BASE_URL'] = base
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    errors = []
    evidence = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=BROWSER, args=['--no-sandbox', '--disable-dev-shm-usage'])
            page = browser.new_page(viewport={'width': 1440, 'height': 1040})
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(base)
            page.get_by_label('Workspace password').fill('test-password')
            page.get_by_role('button', name='Open workspace').click()
            page.get_by_role('heading', name='Find the right moment.').wait_for()
            page.goto(base+'/#connections')
            page.get_by_role('heading', name='Connections & events').wait_for()
            page.get_by_role('button', name='Import event evidence', exact=False).click()
            csv = event_csv('conflicting', 'verified', 'target-conflict')
            csv += event_csv('verified', 'conflicting', 'client-conflict').split('\n', 1)[1]
            csv += event_csv('verified', 'verified', 'ordinary-overlap').split('\n', 1)[1]
            page.locator('#csv-text').fill(csv)
            page.get_by_role('button', name='Validate & preview').click()
            page.get_by_role('button', name='Import 6 reviewed rows').click()
            expect(page.get_by_role('heading', name='TEST FIXTURE target-conflict')).to_be_visible()
            for viewport, name in [({'width':1440,'height':1040},'desktop'), ({'width':390,'height':844},'mobile')]:
                page.set_viewport_size(viewport)
                page.goto(base+'/#connections')
                library = page.locator('article.event-card').filter(has=page.get_by_role('heading', name='TEST FIXTURE target-conflict', exact=True))
                expect(library).to_contain_text('Sam Prospect · speaker · Participation assessment: conflicting')
                expect(library).to_contain_text('Alex Client · attendee · Participation assessment: verified')
                page.goto(base+'/#opportunity/target')
                page.get_by_role('heading', name='What actually connects you').wait_for()
                conflict_cards = page.locator('[data-event-connection="conflicting"]')
                expect(conflict_cards).to_have_count(2)
                for event_name, side in [('target-conflict','Target'), ('client-conflict','Client')]:
                    card = conflict_cards.filter(has_text='TEST FIXTURE '+event_name)
                    expect(card).to_contain_text('Conflicting event evidence · Alex Client')
                    expect(card).to_contain_text('Conflicting participation — review required')
                    expect(card).not_to_contain_text('Possible event connection')
                    expect(card).to_contain_text('Sam Prospect (speaker)')
                    expect(card).to_contain_text('Alex Client (attendee)')
                    expect(card).to_contain_text('20 Oct 2026')
                    expect(card.locator('a')).to_have_attribute('href', 'https://example.com/'+event_name)
                    expect(card.locator('p').filter(has_text=side+':')).to_contain_text('Participation assessment: conflicting')
                possible = page.locator('[data-event-connection="possible"]')
                expect(possible).to_have_count(1)
                expect(possible).to_contain_text('Possible event connection · Alex Client')
                expect(possible).to_contain_text('Possible overlap — relationship unverified')
                expect(possible).to_contain_text('does not establish that these people know one another')
                page.get_by_text('3 sourced event participation records', exact=True).click()
                assessments = page.locator('.participation-assessment')
                expect(assessments).to_have_count(3)
                expect(assessments.filter(has_text='conflicting')).to_be_visible()
                assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
                section = page.locator('section.panel').filter(has=page.get_by_role('heading', name='What actually connects you'))
                section.screenshot(path=str(ROOT/f'outputs/13-event-conflicts-{name}.png'))
                evidence.append({'viewport':name,'conflicts_visible':2,'ordinary_possible_visible':1,'participation_assessment_text_visible':True,'overflow':False})
            assert not errors
            browser.close()
        assert db.one('SELECT count(*) n FROM sends')['n'] == 0
        (ROOT/'outputs/event-conflict-regression.json').write_text(json.dumps({'status':'passed','mode':'ISOLATED TEST FIXTURE; CSV import through actual UI','checks':evidence,'page_errors':errors,'real_sends':0},indent=2))
    finally:
        server.shutdown()
        thread.join(timeout=5)
