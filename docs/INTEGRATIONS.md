# Configure optional integrations on Azure

No sponsor runtime/account or Google OAuth client was found in the project environment. All secrets belong in the mode-0600 `/srv/data/signal-intro-20261027/runtime/web.env` or the specified protected JSON file. Restart **only** `signal-intro-web.service` after editing configuration. No integration uses the laptop as a hidden runtime dependency.

## Google Gmail

1. In a Google Cloud project, enable Gmail API and configure OAuth consent. For personal testing, add the intended Google account as a test user if applicable.
2. Create an OAuth **Web application** client. Authorize the exact redirect `http://127.0.0.1:3290/oauth/google/callback`. Use the dashboard at `http://127.0.0.1:3290`, not an alternate hostname. A public deployment must use its own authorized HTTPS redirect.
3. Download the client JSON and install it on this Azure server as `runtime/google-oauth.json`, owned by azureuser, mode 0600. It must have a `web` object with `client_id`, `client_secret`, and a matching `redirect_uris` list.
4. Add `GOOGLE_CLIENT_FILE=/srv/data/signal-intro-20261027/runtime/google-oauth.json` to `runtime/web.env` and run `systemctl --user restart signal-intro-web.service`.
5. Keep the SSH tunnel open while connecting. Settings → Connect Gmail starts read-only consent. Enable sending separately. Only the connected address can be the sender; aliases are not supported in this version.
6. Use the dashboard to search a company/person/address, inspect excerpts, and import individual messages as possible evidence. Verify the relationship separately. No ChatGPT connector token is reused.

The local fake-provider suite exercises code exchange, PKCE, state, scopes, refresh, search, selected evidence, revocation, MIME sending, ambiguous outcomes and reconciliation. No real Google account or real send was tested.

Official references consulted:
- [Google web-server OAuth](https://developers.google.com/identity/protocols/oauth2/web-server)
- [Gmail scopes](https://developers.google.com/workspace/gmail/api/auth/scopes)
- [Gmail message listing/query](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list)
- [Gmail sending](https://developers.google.com/workspace/gmail/api/guides/sending)

## Zetaris

Supply an existing instance and query-capable account; no platform, account, cloud resource or subscription was created.

```text
ZETARIS_BASE_URL=https://your-existing-zetaris-origin
ZETARIS_ORG_ID=your-numeric-organization-id
ZETARIS_API_KEY=your-private-key
# Or use ZETARIS_USERNAME and ZETARIS_PASSWORD instead of API_KEY.
# ZETARIS_ENGINE_ID is optional if the deployment requires it.
```

The adapter follows the official helper: authenticated POST `/api/proxy/sql-editor/sqls/run-query` with `{sql, limit}` and `X-Org-ID`. It can log in through `/api/auth/login` when username/password are configured. Configure a read-only `signaldesk` schema exposing `registers`, `organizations`, `jobs`, `events`, `participation` and `clients` with the columns in the application schema. `scripts/export_zetaris.py` makes a private local CSV bundle for a controlled import; it never uploads. Protect this bundle because it may contain actual client data. It excludes sessions, OAuth, messages, approvals and logs. Use your existing Zetaris deployment's supported file/data connector to register these tables; connection/registration is a setup task, not a claimed completed integration.

Settings → Verify adapter executes a real bounded SELECT joining all six datasets. SQL and actual response are recorded in the isolated application DB. `query_returned` means a response was obtained; empty rows do not prove a cross-source match. No live Zetaris query was run in this build. HTTP contract behavior is tested against a fake response.

[Official getting-started repository](https://github.com/zetaris/getting-started), [connection guide](https://github.com/zetaris/getting-started/blob/main/docs/connections/README.md), [HTTP helper](https://github.com/zetaris/getting-started/blob/main/scripts/zetaris_api.py).

## Meterless Nightshift and NVIDIA Nemotron

Supply a persistent Azure-accessible Nightshift runtime with an authorized token and a fleet that can actually route to Nemotron. This build does not install a GPU model or depend on a laptop hotspot.

```text
NIGHTSHIFT_BASE_URL=http://127.0.0.1:8088/v1
NIGHTSHIFT_TOKEN=your-private-runtime-token
NIGHTSHIFT_ROUTE=meterless/local
```

A remote base must use HTTPS. The documented provider contract requires `Authorization: Bearer` and `meterless-app: signaldesk`. The adapter calls `/models`, then `/chat/completions`. The requested `meterless/*` ID is a routing disposition, not a model name. It records the actual returned `model`, response ID, input hash and proposed text. Nemotron is marked verified only if the returned model names Nemotron and is not a `meterless/*` routing ID. If the provider returns only a routing ID, the response remains model-unverified.

Opportunity → Review with configured model explicitly sends a bounded evidence bundle to the configured runtime for research and proposed alternatives. Its output cannot dispatch or approve mail. Generated suggestions can be copied into the editable draft, then reviewed under the normal rules. Local templates remain the default usable path. No live Nightshift call or verified Nemotron response occurred in this build.

[Meterless engines](https://meterless.ai/engines.html), [Nightshift hotspot contract](https://github.com/Meterless/Meterless/blob/main/docs/products/nightshift/hotspot.md), [NVIDIA Nemotron](https://www.nvidia.com/en-us/ai-data-science/foundation-models/nemotron/).

## Meterless H-MEM

This integration **did run locally**. The Apache-2.0 upstream TypeScript reference source is vendored under `vendor/hmem`; `UPSTREAM.json` records the exact commit. A small Node 24 bridge stores sourced user-verified facts and corrections in `data/hmem`, with a per-target file lock, provenance and trust ledger. Superseded evidence is removed from active recall using authoritative SQLite IDs. Correction evidence changes the next intro eligibility calculation independently of memory retrieval.

It is the deterministic reference, not an installed production library or semantic-embedding service. No dreaming, background synthesis or autonomous inference is enabled. The adapter probe uses a clearly labelled isolated fixture. The upstream 10-test suite and an application correction/recall test passed; evidence files are in `outputs/`.

[Upstream H-MEM specification/reference](https://github.com/Meterless/Meterless/blob/main/engines/hmem/README.md).
