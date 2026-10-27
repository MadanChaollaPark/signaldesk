import json
import sqlite3
from pathlib import Path
import pytest
from signaldesk.sources import build_index,resolve,csv_preview,save_client,save_events,ValidationError,import_eujobs
from signaldesk.workflow import queue


def test_resolution_never_silently_merges_conflicts_or_fuzzy_names():
    rs=[{'id':'1','name':'Acme Europe','acronym':'AE','slug':'acme','domain':'acme.eu','in_register':1},{'id':'2','name':'Acme Partners','acronym':'AP','slug':'partners','domain':'acme.eu','in_register':1}]
    idx=build_index(rs)
    assert resolve('Acme Europe',[],[],idx)==('1','exact name',[])
    assert resolve('Acme Europe',['acme.eu'],[],idx)==(None,'ambiguous',['1','2'])
    assert resolve('Acme Europ',[],[],idx)[1]=='unmatched'


def test_csv_validation_preview_and_duplicate_safety(db):
    text='company,name,email,relationship,context,verified,permission,demo\nExample,Alex,alex@example.com,past client,Project in 2025,true,false,false\n'
    p=csv_preview(text,'clients');assert p['count']==1 and not p['errors']
    assert db.one('SELECT count(*) n FROM clients')['n']==0
    with db.connect(write=True) as c:save_client(c,p['rows'][0])
    with pytest.raises(ValidationError,match='already exists'):
        with db.connect(write=True) as c:save_client(c,p['rows'][0])
    assert csv_preview(text.replace('alex@example.com','not an email'),'clients')['errors']
    with pytest.raises(ValidationError):csv_preview('name,email\nAlex,alex@example.com','clients')


def test_conflicting_event_metadata_rolls_back(db):
    rows=csv_preview('event_id,title,date,organization,person,role,source_url\ne1,Forum,2026-10-10,Target,A,speaker,https://example.com/event\ne1,Other title,2026-10-10,Client,B,attendee,https://example.com/event\n','events')['rows']
    with pytest.raises(ValidationError,match='conflicting'):
        with db.connect(write=True) as c:save_events(c,rows)
    assert not db.all('SELECT * FROM events')


def test_actual_eujobs_is_readonly_and_source_backed(db,tmp_path):
    source='/srv/data/eujobs/db/eujobs.sqlite';resources='/srv/data/eujobs/db/resources.json'
    if not Path(source).exists():pytest.skip('Azure source unavailable')
    r=import_eujobs(db,source,resources)
    assert r['jobs']>100 and r['registers']>10000 and r['events']>=49 and r['linked']>0
    assert db.one('SELECT count(*) n FROM clients')['n']==0
    assert not db.one("SELECT name FROM sqlite_master WHERE name='contacts'")
    qs=queue(db);assert qs and any(o['register_id'] for o in qs)
    original=sqlite3.connect('file:'+source+'?mode=ro',uri=True)
    for j in db.all('SELECT * FROM jobs LIMIT 20'):
        row=original.execute('SELECT title,sourceUrl,description FROM listings WHERE id=?',(j['id'],)).fetchone()
        assert row==(j['title'],j['source_url'],j['description'])
    original.close()
    # Repeat import must not create duplicates or invalidate unchanged evidence.
    before=db.one('SELECT count(*) n FROM activity')['n'];import_eujobs(db,source,resources)
    assert db.one('SELECT count(*) n FROM jobs')['n']==r['jobs']
    assert db.one('SELECT count(*) n FROM activity')['n']==before
