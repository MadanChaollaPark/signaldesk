#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from signaldesk.app import create_app
from signaldesk.sources import import_eujobs
from signaldesk.db import now
p=argparse.ArgumentParser();p.add_argument('command',choices=['init','refresh','recover','hmem-probe']);args=p.parse_args()
app=create_app();db=app.extensions['db']
if args.command in ('init','refresh'):
    print(json.dumps(import_eujobs(db,app.config['EUJOBS_DB'],app.config['EUJOBS_RESOURCES']),indent=2))
elif args.command=='recover':
    with db.connect(write=True) as c:
        c.execute("UPDATE sends SET state='outcome_unknown',error='Service restarted during submission. Reconcile with Gmail; do not resend.',updated_at=? WHERE state='submitting'",(now(),))
        c.execute("UPDATE drafts SET state='outcome_unknown' WHERE id IN (SELECT draft_id FROM sends WHERE state='outcome_unknown')")
    print('Interrupted submissions marked for reconciliation.')
else:
    print(json.dumps(app.extensions['sponsors'].probe('hmem'),indent=2))
