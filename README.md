# SignalDesk

A single-user workspace that turns hiring signals and recorded client relationships into reviewable introduction requests and direct outreach drafts. **SignalDesk is a working name.**

**Workflow:** hiring signal → organisation match → relationship evidence → editable draft → explicit approval → provider outcome.

## Current status

This is the actual first-version application source, exported from the Azure build—not a reconstructed implementation. It uses Flask, SQLite, a responsive JavaScript UI, and a vendored Meterless H-MEM reference.

| Component | Status |
|---|---|
| Dashboard, offering profile, client CSV preview/import, event evidence | Implemented; tested in the private deployment |
| Editable introduction/direct drafts and approval binding | Implemented; application and browser checks recorded |
| Duplicate prevention, suppression, cooldown and uncertain send outcomes | Implemented; simulated-provider checks |
| H-MEM relationship corrections and recall | Local upstream reference integrated |
| Gmail OAuth, search, sending and reconciliation | Implemented; fake-provider tested, **not live Google verified** |
| Zetaris evidence join | Adapter implemented; **no live query verified** |
| Nightshift/Nemotron | Adapter implemented; **no live model response verified** |
| Default drafting | Deterministic templates until a model is configured |

The deployed build imported an existing EUJobs snapshot containing 20,573 register identities, 711 job records and 49 events. This does **not** mean every register entity was freshly investigated. Those records, private clients, mailbox content, credentials and operational screenshots are **not included** here. Event overlap alone is not evidence that two people know each other. No real email or sales result is claimed.

## Run a private empty workspace

Requires Python 3.12 and, for H-MEM, Node.js 24. Use macOS or Linux; the current memory adapter uses POSIX file locking.

```sh
git clone https://github.com/MadanChaollaPark/signaldesk.git
cd signaldesk
python3.12 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python - <<'PYTHON'
from pathlib import Path
import shutil
from signaldesk.app import create_app
root = Path.cwd()
app = create_app({
    "DATABASE": str(root / "data/signaldesk.sqlite"),
    "RUNTIME": str(root / "runtime"),
    "HMEM_DIR": str(root / "data/hmem"),
    "NODE": shutil.which("node") or "/missing/node",
})
app.run(host="127.0.0.1", port=3290, debug=False)
PYTHON
```

Open <http://127.0.0.1:3290>. Read the generated `runtime/admin-password` locally to sign in; never commit or share it. The development server is for local evaluation, not public production hosting.

A clean checkout starts empty. Configure the offering and import your own clients/events through the UI using the templates in `static/`. The source-refresh adapter currently expects the private EUJobs database schema at its configured paths; those datasets are not distributed. To connect another installation, pass `EUJOBS_DB` and `EUJOBS_RESOURCES` to `create_app` with authorised source paths. Do not describe a fresh checkout as a populated demo.

The production `wsgi.py`, `deploy/` files and operational scripts retain the original Azure directory layout. Adapt them to your installation; do not install them verbatim on an unrelated host. `.env.example` documents configuration; it is not loaded automatically. Set environment variables in the service or shell.

## Test the portable application behaviour

```sh
.venv/bin/pytest -q --deselect tests/test_event_conflicts.py::test_csv_conflicts_are_visible_in_desktop_and_mobile_review
```

These tests use synthetic records and fake providers, not live email delivery. The real-source test skips when the private EUJobs data is absent. The deselected desktop/mobile test and standalone browser scripts require the original deployment's Chromium path and output directories; adapt those before running them elsewhere. This exclusion does not count as a local browser pass.

## Integrations and operating boundaries

- [Gmail, Zetaris, Nightshift/Nemotron and H-MEM setup](docs/INTEGRATIONS.md)
- [Evidence, approvals and send-state design](docs/SECURITY-AND-WORKFLOW.md)
- [Original Azure operations runbook](docs/OPERATIONS.md)
- [Publication provenance and limitations](docs/PUBLICATION.md)

Each email requires approval of its exact content and recipient. Editing invalidates approval. An uncertain provider result is retained for reconciliation rather than retried blindly. Client relationships and permission to mention customer work must be supplied and verified by the user.

For private server access, use your own SSH alias:

```sh
ssh -N -L 3290:127.0.0.1:3290 YOUR_SERVER_ALIAS
```

## Upstream attribution

`vendor/hmem/` contains the Meterless H-MEM reference. Its Apache-2.0 licence and pinned upstream commit are retained in `vendor/hmem/LICENSE` and `vendor/hmem/UPSTREAM.json`. A project-wide licence for the remaining application code has not been selected.
