# SignalDesk security and workflow

This is a single-user internal Azure pilot. It has no automatic sender or follow-up worker. Discovery refreshes only the local evidence snapshot.

## Authentication and private data

All application pages, APIs, OAuth callbacks and mailbox results require a server-side session. The anonymous endpoints are `/login`, `/healthz` (generic status only), and static assets (code/styles and explicitly labelled sample CSVs). Sessions expire after 12 hours and rotate at login. The session cookie is HttpOnly and SameSite=Lax; HTTPS deployments also set Secure. Login attempts are limited to 10 per 15-minute window per remote address. Mutations require the session-bound CSRF token and a matching Origin when supplied. Host validation protects against unexpected Host headers. Referrer-Policy is `same-origin`, which retains a valid Origin on browser login forms without leaking private paths to external sites.

The dashboard binds to 127.0.0.1:3290. SSH forwarding is the current access method. No public host or anonymous private API was created. A future HTTPS reverse proxy must preserve the configured Host; update `SIGNALDESK_BASE_URL` and Google’s exact redirect together. Do not trust arbitrary forwarded headers.

`data/` and `runtime/` are private server directories. The database, app encryption key, password and service environment use mode 0600. Google access and refresh tokens are encrypted with Fernet using `runtime/token.key`. That key must be backed up separately from any database export and protected like a credential. OAuth client JSON never enters Git. Gunicorn access logging is disabled to avoid logging authorization codes in callback query strings. Provider error bodies and credentials are not logged.

## Source boundaries

EUJobs opens via SQLite URI `mode=ro` plus `PRAGMA query_only=ON` in a consistent read transaction. An explicit allowlist selects organizations and non-sample listing fields. The 197 MB register JSON is streamed with ijson, keeping only allowlisted identity fields. Its hash is computed incrementally from the same open file, and in-place modification is checked before import. EUJobs contacts, accounts, payments, users and outbox contents are never imported. EUJobs service and importer are untouched.

Source URLs accept HTTP(S) only, disallow embedded credentials and are escaped in HTML. They are links for the reviewer; the server does not fetch user-entered evidence URLs, so there is no arbitrary evidence-fetch endpoint. Sponsor endpoints are configured by the server administrator, not supplied by API users, and require HTTPS unless loopback. Imported descriptions and mailbox excerpts are data, never tool instructions. The optional model cannot approve or send.

Entity resolution unions all exact register slug/name/acronym/domain matches. A conflicting union remains ambiguous. There are no fuzzy automatic mergers. Reviewed manual identity links retain a reason. Organisation overlap at an event remains a possible connection. Named relationship evidence requires explicit user verification; no client relationship is inferred from mailbox correspondence.

## Approval and dispatch state machine

1. Generate or edit an alternative route. Saving increments its version, stores a hash of the supporting evidence/profile and invalidates previous approvals. The intro and direct routes have separate drafts.
2. The user reviews a confirmation dialog containing the exact saved recipient, sender, subject and body and attests to the evidence and customer-claim permissions.
3. The backend binds approval to the draft ID, opportunity, route, selected client, recipient/name/verification, sender, subject, body, version and evidence hash.
4. Dispatch takes `BEGIN IMMEDIATE`, rechecks the approval, evidence, profile, source freshness, account permission, suppression, client/contact cooldown, held/rejected status and competing route. An intro needs a verified non-demo client and current named personal relationship evidence. A selected direct customer example needs permission and an allowed claim.
5. The backend inserts a unique reservation (`UNIQUE(draft_id)`) and a unique RFC Message-ID **before** contacting Gmail. Concurrent double clicks return the same reservation; a competing route is blocked. Exact content and the full evidence snapshot are immutable in the send journal.
6. A single provider call occurs outside the transaction, without HTTP retry. Explicit 400/401/403/404/413/429 rejections become `failed`. Timeout, malformed success or other ambiguous response becomes `outcome_unknown`. A success containing a provider message ID becomes `provider_accepted`, never `delivered`.
7. On service restart, interrupted `submitting` reservations become `outcome_unknown`. A stuck submission can also be reconciled after 90 seconds. Reconciliation searches Gmail Sent by the unique Message-ID and checks sender, recipient and subject. No matching message is **not** proof of failure and never authorizes a retry.
8. There is intentionally no retry button in this pilot, including for failed reservations. A reserved route stays immutable. Intro pending blocks direct outreach. A user-recorded decline/closure can release the other route, but it still needs a new review and must pass cooldowns.

Drafts, including ones whose source jobs later close, remain available in Activity. Reply checks are user-triggered, limited to the recorded thread, and require the expected sender and In-Reply-To. Replies and manual outcomes are distinct. No delivery tracking, bounce ingestion or automatic follow-up is claimed.

## Gmail scope and OAuth details

Read-only connection requests `gmail.readonly`; enabling sending requests `gmail.readonly` plus `gmail.send`. Metadata-only scope cannot support the desired mailbox query/excerpt workflow. No modify, delete, compose or full-mail scope is requested. This internal pilot still needs the relevant Google consent configuration; read-only Gmail is a restricted scope and external production use may require Google's verification process.

State is random, session-bound, one-use and expires in 10 minutes. PKCE uses an S256 challenge and a server-stored verifier. Redirect URI is fixed from the configured origin, checked against the installed web-client JSON and checked on callback. Offline/read access is verified before storing the account. Searches accept a name or an email, restrict to the last two years and return at most ten messages; arbitrary Gmail query operators are not accepted. Search results are session-bound and expire after 30 minutes. Only a selected excerpt is imported, initially as possible evidence. Disconnect removes local tokens/results/states and requests Google revocation; revocation failure is explicitly reported with account-permissions instructions.

## Known pilot limits

One user and mailbox; explicit user verification rather than an independent relationship-verification service; literal configurable signal scoring; partial event coverage; source descriptions may be brief summaries linking to full responsibilities; no automatic retry or delivery receipts. H-MEM uses the upstream deterministic reference with hash embeddings, not a production semantic-memory service. Google, Zetaris and Nightshift live credentials were absent during this build. Mock contracts and fixture screenshots do not establish live external integrations.
