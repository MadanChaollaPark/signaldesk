#!/usr/bin/env python3
"""Create an access-controlled local bundle. Never uploads to any external service."""
import csv
import json
import os
import sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
os.umask(0o077)
target=ROOT/'data/zetaris-export';target.mkdir(parents=True,exist_ok=True,mode=0o700)
source=sqlite3.connect('file:'+str(ROOT/'data/signaldesk.sqlite')+'?mode=ro',uri=True)
source.execute('PRAGMA query_only=ON');source.execute('BEGIN')
counts={}
for table in ('registers','organizations','jobs','events','participation','clients'):
    cursor=source.execute('SELECT * FROM '+table)
    rows=cursor.fetchall();counts[table]=len(rows)
    path=target/(table+'.csv')
    with path.open('w',newline='') as f:
        w=csv.writer(f);w.writerow([c[0] for c in cursor.description]);w.writerows(rows)
    path.chmod(0o600)
source.close()
(target/'manifest.json').write_text(json.dumps({'private':True,'uploaded':False,'tables':counts},indent=2))
print(json.dumps({'local_bundle':str(target),'tables':counts,'uploaded':False},indent=2))
