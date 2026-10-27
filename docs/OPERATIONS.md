# Operations

Run as azureuser. Lingering is already enabled, so the web service and refresh timer do not depend on an SSH login or laptop connection.

```sh
systemctl --user status signal-intro-web.service
systemctl --user status signal-intro-refresh.timer
journalctl --user -u signal-intro-web.service --since today --no-pager
```

Only this app's units are in scope for changes. `eujobs.service` is a separate system service, not a user unit. Its loopback port is 3210.

## Local backup

Use SQLite's backup API against the **project** database for a consistent private backup. No EUJobs backup is required or authorized for this app because only allowlisted data is imported read-only.

```sh
umask 077
mkdir -p /srv/data/signal-intro-20261027/data/backups
/srv/data/signal-intro-20261027/runtime/venv/bin/python - <<'PY'
import sqlite3
from datetime import datetime,timezone
from pathlib import Path
root=Path('/srv/data/signal-intro-20261027')
path=root/'data/backups'/('signaldesk-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.sqlite')
source=sqlite3.connect('file:'+str(root/'data/signaldesk.sqlite')+'?mode=ro',uri=True)
target=sqlite3.connect(path)
source.backup(target)
target.close();source.close();path.chmod(0o600)
print(path)
PY
```

Protect `runtime/token.key`, the OAuth JSON, private environment file and H-MEM directory in any backup policy. A DB backup without the key cannot decrypt OAuth tokens. A key and DB together expose mailbox credentials, so keep them access-controlled. No automatic off-server backup destination was provisioned.

## Recovery

A service start marks interrupted send reservations `outcome_unknown`; it never replays them. Use Activity → Reconcile in Gmail with the original sender connected. If no unique matching Sent message is found, keep the unknown outcome. Do not manually delete reservations to force a resend.

The refresh timer copies only current allowed source records into the isolated DB. Missing/closed jobs become inactive; old drafts remain visible in Activity. Material source/profile changes require another review before dispatch. Refresh failures leave the existing snapshot intact and are visible in `runtime/refresh.log`; freshness gates eventually block sends from stale sources.

To rotate the workspace password, stop only this web service, write a new protected `runtime/admin-password`, replace `runtime/password-hash` with a Werkzeug-generated hash, remove rows from this app's `sessions` and `oauth_states` tables, and start the service. Do not regenerate `runtime/token.key` unless intentionally invalidating all stored OAuth tokens.

## Verification evidence

The durable `outputs/` directory holds real-service screenshots 01–09, separately labelled fake-provider workflow screenshots 10–12, application test results, H-MEM upstream tests, import provenance and final service/security checks. Files may contain client/mailbox information after real usage; they are private and excluded from Git. These private evidence files are excluded from the public source repository.
