"use strict";
const $ = (s) => document.querySelector(s),
  $$ = (s) => [...document.querySelectorAll(s)];
const esc = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const href = (v) => (/^https?:\/\//i.test(v || "") ? esc(v) : "#");
const short = (s, n = 100) =>
  s && s.length > n ? s.slice(0, n) + "…" : s || "";
const day = (s) =>
  s
    ? new Date(s).toLocaleDateString("en-GB", {
        day: "numeric",
        month: "short",
        year: "numeric",
      })
    : "Not recorded";
const relative = (s) => {
  if (!s) return "Not checked";
  const d = Math.max(0, Math.floor((Date.now() - new Date(s)) / 86400000));
  return d === 0
    ? "Checked today"
    : d === 1
      ? "Checked yesterday"
      : `Checked ${d} days ago`;
};
const initials = (s) =>
  s
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0])
    .join("")
    .toUpperCase();
const pill = (s, c = "") => `<span class="pill ${c}">${esc(s)}</span>`;
const link = (url, label = "View source ↗") =>
  url
    ? `<a class="source-link" href="${href(url)}" target="_blank" rel="noopener noreferrer">${esc(label)}</a>`
    : "";
function eventConnection(c) {
  const conflicting = c.status === "conflicting";
  return `<article class="warning" data-event-connection="${esc(c.status)}">
    <strong>${conflicting ? "Conflicting event evidence" : "Possible event connection"} · ${esc(c.client)}</strong>
    <p>${pill(conflicting ? "Conflicting participation — review required" : "Possible overlap — relationship unverified", conflicting ? "red" : "amber")}</p>
    <p>${esc(c.event)} · ${day(c.date)}</p>
    <p>Target: ${esc(c.target_person || "Unnamed")} (${esc(c.target_role)}). Participation assessment: ${esc(c.target_status)}.</p>
    <p>Client: ${esc(c.client_person || "Unnamed")} (${esc(c.client_role)}). Participation assessment: ${esc(c.client_status)}.</p>
    ${link(c.source_url)}
    <p>${conflicting ? "At least one participation record is conflicting. Resolve the conflicting evidence before relying on this event as a connection. Shared participation does not establish that these people know one another." : esc(c.explanation)}</p>
  </article>`;
}
const title = (eyebrow, h, p, actions = "") =>
  `<div class="page-heading"><div><p class="eyebrow">${eyebrow}</p><h1>${h}</h1><p>${p}</p></div>${actions ? `<div class="heading-actions">${actions}</div>` : ""}</div>`;
const field = (name, label, value = "", type = "text", help = "") =>
  `<label>${label}<input name="${name}" type="${type}" value="${esc(value)}" ${["email"].includes(type) ? 'autocomplete="off"' : ""}>${help ? `<span class="field-help">${help}</span>` : ""}</label>`;
const area = (name, label, value = "", help = "") =>
  `<label>${label}<textarea name="${name}">${esc(value)}</textarea>${help ? `<span class="field-help">${help}</span>` : ""}</label>`;
const check = (name, label, checked = false) =>
  `<label class="check"><input type="checkbox" name="${name}" ${checked ? "checked" : ""}><span>${label}</span></label>`;
const state = {
  bootstrap: null,
  signals: [],
  detail: null,
  route: "intro",
  filter: "all",
  search: "",
  register: "all",
  page: 0,
  dirty: false,
};
let csrf = $('meta[name="csrf-token"]').content;
async function api(path, method = "GET", data) {
  const r = await fetch("/api" + path, {
    method,
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
    body: data === undefined ? undefined : JSON.stringify(data),
  });
  if (r.status === 401) {
    location.href = "/login";
    throw Error("Please sign in again.");
  }
  const j = await r.json();
  if (!r.ok) throw Error(j.error || "Request failed.");
  return j;
}
function toast(message, error = false) {
  const el = $("#toast");
  el.textContent = message;
  el.className = "toast" + (error ? " error-toast" : "");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(
    () => el.classList.add("hidden"),
    error ? 11000 : 5000,
  );
}
function modal(content) {
  $("#modal-content").innerHTML = content;
  $("#modal").showModal();
}
const modalTitle = (t) =>
  `<div class="modal-title"><h2>${t}</h2><button class="close-button" data-action="close-modal" aria-label="Close dialog">×</button></div>`;
const formData = (form) => {
  const d = Object.fromEntries(new FormData(form));
  form
    .querySelectorAll('input[type="checkbox"]')
    .forEach((x) => (d[x.name] = x.checked));
  return d;
};
function clientOptions(id, blank = "Choose a client / contact") {
  return (
    `<option value="">${blank}</option>` +
    state.bootstrap.clients
      .map(
        (c) =>
          `<option value="${c.id}" ${c.id == id ? "selected" : ""}>${esc(c.company)} · ${esc(c.name)}${c.demo ? " (DEMO)" : ""}</option>`,
      )
      .join("")
  );
}
function signalOptions(id) {
  return (
    `<option value="">Choose a target organisation</option>` +
    state.signals
      .map(
        (o) =>
          `<option value="${o.id}" ${o.id === id ? "selected" : ""}>${esc(o.name)}</option>`,
      )
      .join("")
  );
}
async function boot() {
  state.bootstrap = await api("/bootstrap");
  csrf = state.bootstrap.csrf;
  state.signals = (await api("/signals")).opportunities;
  $("#nav-count").textContent = state.signals.length;
}
async function route() {
  $("#toast").classList.add("hidden");
  const hash = location.hash.slice(1) || "signals",
    page = hash.split("/")[0];
  state.dirty = false;
  $$("[data-nav]").forEach((a) =>
    a.classList.toggle(
      "active",
      a.dataset.nav === (page === "opportunity" ? "signals" : page),
    ),
  );
  $("#page-name").textContent =
    {
      signals: "Signals",
      clients: "Clients & network",
      connections: "Connections",
      profile: "Offering & profile",
      settings: "Connections & settings",
      activity: "Activity & outcomes",
      opportunity: "Opportunity review",
    }[page] || "Signals";
  if (page === "opportunity") await renderDetail(hash.slice(12));
  else if (page === "signals") renderSignals();
  else if (page === "clients") renderClients();
  else if (page === "profile") renderProfile();
  else if (page === "settings") renderSettings();
  else if (page === "connections") await renderConnections();
  else if (page === "activity") await renderActivity();
  else location.hash = "signals";
}
function renderSignals() {
  const all = state.signals,
    registered = all.filter((o) => o.register_id).length,
    fresh = all.filter((o) => o.freshness === "fresh").length,
    prepared = all.filter((o) => o.drafts.length).length;
  let filtered = all.filter(
    (o) =>
      (state.filter === "all" ||
        (state.filter === "review" && o.status === "review") ||
        (state.filter === "hold" && o.status === "hold") ||
        (state.filter === "drafts" && o.drafts.length) ||
        (state.filter === "rejected" && o.status === "rejected")) &&
      (!state.search ||
        `${o.name} ${o.jobs.map((j) => j.title).join(" ")}`
          .toLowerCase()
          .includes(state.search.toLowerCase())) &&
      (state.register === "all" ||
        (state.register === "registered" && o.register_id) ||
        (state.register === "review" && o.resolution === "ambiguous") ||
        (state.register === "matched" && o.basis.fit === "matched")),
  );
  const pages = Math.max(1, Math.ceil(filtered.length / 15));
  state.page = Math.min(state.page, pages - 1);
  const visible = filtered.slice(state.page * 15, state.page * 15 + 15);
  const source = state.bootstrap.source;
  $("#main").innerHTML =
    title(
      "YOUR NEXT CONVERSATION STARTS HERE",
      "Find the right moment.",
      "Real hiring signals. Relevant relationships. Outreach you can stand behind.",
      `<button data-action="refresh">↻ &nbsp; Refresh sources</button><a class="button" href="#profile">Configure offering ↗</a>`,
    ) +
    (!state.bootstrap.profile.offering
      ? `<div class="setup-banner"><span class="icon-square">◇</span><div><strong>Make these signals relevant to your business</strong><p>Add your offering and ideal buyer to explain which opportunities fit.</p></div><a href="#profile">Set up your profile →</a></div>`
      : "") +
    `<div class="stats"><div class="stat featured"><div class="stat-label">Active opportunities <span>◉</span></div><strong>${all.length}</strong><small>Grouped by organisation</small></div><div class="stat"><div class="stat-label">Register-linked <span>↗</span></div><strong>${registered}</strong><small>Exact or reviewed identities</small></div><div class="stat"><div class="stat-label">Fresh hiring signals <span>◷</span></div><strong>${fresh}</strong><small>Checked within ${state.bootstrap.profile.freshness_days} days</small></div><div class="stat"><div class="stat-label">Drafts to review <span>✎</span></div><strong>${prepared}</strong><small>Your approval comes first</small></div></div><div class="toolbar"><div class="tabs">${[
      ["all", "All signals", all.length],
      [
        "review",
        "Needs review",
        all.filter((o) => o.status === "review").length,
      ],
      ["drafts", "Drafted", prepared],
      ["hold", "On hold", all.filter((o) => o.status === "hold").length],
      ["rejected", "Rejected", ""],
    ]
      .map(
        ([id, n, count]) =>
          `<button data-action="filter" data-id="${id}" class="${state.filter === id ? "active" : ""}">${n} ${count !== "" ? `<span class="number">${count}</span>` : ""}</button>`,
      )
      .join(
        "",
      )}</div><div class="filters"><input id="signal-search" type="search" aria-label="Search signals" placeholder="Search company or role…" value="${esc(state.search)}"><select id="signal-register" aria-label="Filter register and fit">${[
      ["all", "All organisations"],
      ["registered", "Register-linked"],
      ["review", "Identity needs review"],
      ["matched", "Offering matches"],
    ]
      .map(
        ([v, n]) =>
          `<option value="${v}" ${state.register === v ? "selected" : ""}>${n}</option>`,
      )
      .join(
        "",
      )}</select></div></div><section class="queue-panel"><div class="table-scroll"><table><thead><tr><th>Organisation</th><th>Why now · Hiring signal</th><th>Connection</th><th>Source freshness</th><th></th></tr></thead><tbody>${visible.map((o) => `<tr><td class="company-td"><div class="company-cell"><div class="company-logo">${esc(initials(o.name))}</div><div><a class="company-name" href="#opportunity/${o.id}">${esc(o.name)}</a><span class="cell-sub">${o.register_id ? "✓ Transparency Register" : o.resolution === "ambiguous" ? "Identity needs review" : "Register link unconfirmed"}</span></div></div></td><td><div class="job-title">${esc(short(o.jobs[0].title, 80))}</div><span class="cell-sub">${o.job_count > 1 ? `+${o.job_count - 1} other openings · ` : ""}${esc(o.jobs[0].location || "Location unspecified")}</span>${o.basis.matched.length ? `<span class="cell-sub">Fit: ${esc(o.basis.matched.join(", "))}</span>` : ""}</td><td class="connection-td">${pill(o.connections ? `${o.connections} verified evidence` : "Add your network", o.connections ? "green" : "")}<span class="cell-sub">${o.connections ? "Review personal connection" : "No inferred clients"}</span></td><td class="freshness-td">${pill(o.freshness === "fresh" ? "● Fresh source" : "Review freshness", o.freshness === "fresh" ? "green" : "amber")}<span class="cell-sub">${relative(o.jobs[0].checked_at)}</span></td><td class="action-td right"><a class="button review-button" href="#opportunity/${o.id}">Review <span>→</span></a><span class="cell-sub">${esc(o.send_states[0] || (o.status !== "review" ? o.status : o.drafts.length ? "Draft prepared" : "Not contacted"))}</span></td></tr>`).join("")}</tbody></table>${!visible.length ? '<div class="empty"><h2>No signals in this view</h2><p>Try another filter or refresh the source data.</p></div>' : ""}</div><div class="table-foot"><span>${filtered.length ? `${state.page * 15 + 1}–${Math.min((state.page + 1) * 15, filtered.length)} of ${filtered.length} opportunities` : "0 opportunities"}</span><div class="pagination"><button data-action="page" data-dir="-1" ${state.page === 0 ? "disabled" : ""} aria-label="Previous page">←</button><span>${state.page + 1} / ${pages}</span><button data-action="page" data-dir="1" ${state.page === pages - 1 ? "disabled" : ""} aria-label="Next page">→</button></div></div></section><div class="source-note"><span>ⓘ</span><div>Actual EUJobs data · Last imported ${day(source?.imported_at)} · Register snapshot ${day(source?.register_metadata?.exportDate)}.<br>Hiring indicates possible need, not confirmed purchase intent. ${source?.jobs || 0} jobs imported read-only; expired and closed roles are excluded from this queue.</div></div>`;
}
async function renderDetail(oid) {
  state.detail = await api("/opportunities/" + oid);
  const d = state.detail,
    o = d.organization,
    active = state.signals.find((s) => s.id === oid),
    jobs = d.jobs
      .filter(
        (j) =>
          j.status === "published" &&
          (!j.deadline || new Date(j.deadline) > new Date()),
      )
      .sort((a, b) => (b.checked_at || "").localeCompare(a.checked_at || "")),
    draft = d.drafts.find((x) => x.route === state.route);
  state.dirty = false;
  $("#main").innerHTML =
    `<div class="detail-top"><a class="back-link" href="#signals">← &nbsp; Back to signals</a><span class="muted">/</span><span class="small muted">Opportunity review</span></div><div class="row-between detail-heading"><div><div class="actions">${pill(o.register_id ? "Register-linked" : "Identity unconfirmed", o.register_id ? "green" : "amber")}${pill(d.status === "review" ? "Needs review" : d.status)}</div><h1>${esc(o.name)}</h1><p>${jobs.length} active opening${jobs.length !== 1 ? "s" : ""} · ${esc(o.domain || "Domain unconfirmed")}</p></div><div class="actions"><button data-action="opportunity-status" data-status="hold">Hold</button><button class="subtle" data-action="opportunity-status" data-status="rejected">Reject</button>${d.status !== "review" ? '<button data-action="opportunity-status" data-status="review">Return to review</button>' : ""}</div></div><div class="detail-grid"><div><section class="panel"><div class="evidence-label"><b>1</b> THE SIGNAL</div><h2>Why this organisation, why now</h2><p class="muted">${state.bootstrap.profile.offering ? `Possible fit for ${esc(state.bootstrap.profile.offering)}.` : "Set your offering to assess fit. The hiring evidence below is real; buyer intent is unconfirmed."}</p>${active?.basis.matched.length ? `<div class="success">Literal source matches: ${esc(active.basis.matched.join(", "))}</div>` : ""}${active?.basis.excluded.length ? `<div class="warning">Campaign exclusions: ${esc(active.basis.excluded.join(", "))}</div>` : ""}${jobs
      .slice(0, 3)
      .map(
        (j) =>
          `<div class="job-evidence"><h3>${esc(j.title)}</h3><div class="actions">${pill(relative(j.checked_at), j.checked_at && Date.now() - new Date(j.checked_at) < state.bootstrap.profile.freshness_days * 86400000 ? "green" : "amber")}${pill(j.location || "Location unspecified")}</div><div class="source-excerpt">${esc(j.description || j.summary)}</div><div class="metadata"><div><span>FIRST PUBLISHED</span><strong>${day(j.published_at)}</strong></div><div><span>APPLICATION DEADLINE</span><strong>${j.deadline ? day(j.deadline) : "Not provided"}</strong></div></div>${link(j.source_url, "Original job & full responsibilities ↗")}<p class="small muted">EUJobs source ID: ${esc(j.id)}</p></div>`,
      )
      .join("")}${
      jobs.length > 3
        ? `<details><summary>${jobs.length - 3} more openings</summary>${jobs
            .slice(3)
            .map((j) => `<p>${link(j.source_url, j.title)}</p>`)
            .join("")}</details>`
        : ""
    }<div class="metadata"><div><span>REGISTER IDENTIFIER</span><strong>${esc(o.register_id || "Unconfirmed")}</strong></div><div><span>IDENTITY BASIS</span><strong>${esc(o.resolution)}</strong></div><div><span>REGISTER SNAPSHOT</span><strong>${day(o.register_date)}</strong></div><div><span>SOURCE PROVENANCE</span><strong>EUJobs / EU Transparency Register</strong></div></div>${link(o.register_url, "Open register record ↗")}<button class="subtle small" data-action="resolve">Review identity</button>${o.resolution_note ? `<p class="small muted">Review note: ${esc(o.resolution_note)}</p>` : ""}</section><section class="panel"><div class="panel-header"><div class="evidence-label"><b>2</b> THE CONNECTION</div><button class="subtle small" data-action="evidence">+ Add evidence</button></div><h2>What actually connects you</h2>${d.evidence.length ? d.evidence.map((e) => `<div class="event-card"><div class="row-between">${pill(e.status, e.status === "verified" ? "green" : e.status === "conflicting" ? "red" : "amber")}<button class="subtle small" data-action="evidence" data-id="${e.id}">Correct</button></div><p>${esc(e.claim)}</p><span class="small muted">${esc(e.participants)} · ${esc(e.roles)} · ${day(e.source_date)}</span><br>${link(e.source_url)}${e.supersedes ? `<p class="small muted">Corrects evidence #${e.supersedes}; original retained in history.</p>` : ""}</div>`).join("") : `<div class="empty compact"><div class="empty-symbol">♧</div><h3>No verified personal connection yet</h3><p>Add your past clients and verify a named relationship. A shared event is a lead to investigate, not proof that two people know each other.</p><a class="button" href="#clients">Add your network →</a></div>`}${d.connections.map(eventConnection).join("")}${d.events.length ? `<details><summary>${d.events.length} sourced event participation records</summary>${d.events.map((e) => `<div class="event-card"><h3>${esc(e.title)}</h3><p>${day(e.date)} · ${esc(e.role)}${e.person ? " · " + esc(e.person) : ""}</p><p class="participation-assessment">${pill("Participation assessment: " + e.evidence_status, e.evidence_status === "conflicting" ? "red" : "")} </p><p>${esc(short(e.description, 300))}</p>${link(e.source_url)}</div>`).join("")}</details>` : ""}${d.memory.memories?.length ? `<details><summary>H-MEM · verified corrections retained</summary><p class="small muted">Local deterministic reference implementation. Evidence remains authoritative.</p>${d.memory.memories.map((m) => `<p>${esc(m.memory.content)}</p>`).join("")}</details>` : ""}</section><section class="panel"><div class="evidence-label"><b>3</b> RESEARCH NOTES</div><h3>Why this person</h3><p class="muted">${state.bootstrap.profile.buyer ? `Your ideal buyer is ${esc(state.bootstrap.profile.buyer)}. Verify that the named recipient owns this responsibility.` : "The ideal buyer has not been configured. No recipient or decision-maker is inferred from a job listing."}</p><h3>What remains uncertain</h3><p class="muted">A vacancy does not confirm budget or buying intent. Source coverage may omit responsibilities. Customer relationships and reference permission must be explicit; an email exchange or shared event does not establish endorsement.</p><button data-action="research">Review with configured model</button><div id="research-result"></div></section></div><div><section class="panel composer"><div class="composer-head"><div class="row-between"><h2>Review your outreach</h2>${pill("Your decision", "green")}</div><p>Two alternatives for this opportunity. Only one route can be active.</p><div class="route-tabs"><button data-action="route-tab" data-route="intro" class="${state.route === "intro" ? "active" : ""}">↗ &nbsp; Ask for an introduction</button><button data-action="route-tab" data-route="direct" class="${state.route === "direct" ? "active" : ""}">✉ &nbsp; Direct outreach</button></div></div><div class="composer-body">${state.route === "intro" ? '<p class="small muted">To your past client or network contact. Ask whether they feel comfortable introducing you.</p>' : '<p class="small muted">To the prospect. Reference only a permitted customer example; never imply a recommendation.</p>'}<form id="draft-form"><label>${state.route === "intro" ? "Client / contact to ask" : "Permitted customer example (optional)"}<select name="client_id" id="draft-client">${clientOptions(draft?.client_id)}</select></label>${draft ? `<div class="form-grid compact">${field("recipient_name", "Recipient name", draft.recipient_name)}${field("recipient", "Recipient email", draft.recipient, "email")}</div>${check("recipient_verified", "I verified this person’s business address and relevance.", draft.recipient_verified)}${field("sender", "From · connected Gmail account", draft.sender, "email", state.bootstrap.gmail.connected ? `Connected as ${esc(state.bootstrap.gmail.account.email)}` : "Gmail is not connected. Sending is disabled.")}${field("subject", "Subject", draft.subject)}<label>Exact email body<textarea name="body" class="email-body">${esc(draft.body)}</textarea></label><div class="row-between"><span id="save-state" class="send-label">Saved version ${draft.version} · ${esc(draft.model)}</span><button type="button" class="subtle small" data-action="regenerate">↻ Regenerate</button></div>` : `<div class="empty compact"><div class="empty-symbol">✎</div><h3>Start with the evidence</h3><p>Prepare an editable ${state.route === "intro" ? "introduction request" : "direct email"} using the current sources and your profile. Missing facts stay clearly marked.</p><button class="primary" type="button" data-action="regenerate">Prepare ${state.route === "intro" ? "intro request" : "direct draft"} →</button></div>`}</form>${draft?.blockers.length ? `<div class="warning"><strong>Before this message can be sent</strong><ul class="blockers">${draft.blockers.map((b) => `<li>${esc(b)}</li>`).join("")}</ul></div>` : draft ? '<div class="success">Ready for your final review. Approval binds to this saved message and its supporting evidence.</div>' : ""}</div><div class="composer-footer"><div class="actions"><button data-action="save-draft" ${!draft ? "disabled" : ""}>Save draft</button><button class="primary" id="approve-button" data-action="review-send" ${!draft || draft.blockers.length ? "disabled" : ""}>Approve and send <span>→</span></button></div><p>No automatic sends or follow-ups. Gmail acceptance is not a delivery receipt.</p><div class="actions"><button class="subtle" data-action="suppress" ${!draft?.recipient ? "disabled" : ""}>Suppress contact</button><span class="small muted">${draft ? esc(draft.state) : "Not drafted"}</span></div></div></section><div class="info"><strong>Every change starts a new review.</strong><br>Editing the recipient, sender, text, route or evidence invalidates previous approval. Intro pending blocks direct outreach.</div></div></div>`;
}
function renderClients() {
  $("#main").innerHTML =
    title(
      "YOUR MOST VALUABLE CONTEXT",
      "Clients & network",
      "Tell SignalDesk who you know, how you worked together, and what you have permission to share.",
      `<button data-action="csv" data-kind="clients">Import CSV</button><button class="primary" data-action="client">+ Add client / contact</button>`,
    ) +
    `<div class="info">EUJobs contacts are not treated as your clients. Every relationship here comes from your entry, reviewed import or selected mailbox evidence.</div>` +
    (state.bootstrap.clients.length
      ? `<div class="client-list">${state.bootstrap.clients.map((c) => `<article class="client-card"><div class="row-between"><div class="company-cell"><div class="company-logo">${esc(initials(c.company))}</div><div><h3>${esc(c.company)}</h3><span class="cell-sub">${esc(c.name)} · ${esc(c.role || c.relationship)}</span></div></div><button class="subtle small" data-action="client" data-id="${c.id}">Edit</button></div><div class="actions">${pill(c.demo ? "DEMO — never send" : c.verified ? "User-verified relationship" : "Needs verification", c.verified && !c.demo ? "green" : "amber")}${pill(c.permission ? "Reference permitted" : "Private reference")}</div><p class="muted">${esc(c.context)}</p>${c.allowed_claim ? `<div class="claim-box"><strong>Allowed reference claim</strong><br>${esc(c.allowed_claim)}</div>` : ""}<span class="small muted">${esc(c.email || "No email recorded")} · Updated ${day(c.updated_at)}</span></article>`).join("")}</div>`
      : `<section class="panel"><div class="empty"><div class="empty-symbol">♧</div><h2>Your relationships belong here</h2><p>Add a past client or a trusted contact. Record the context, verify their role, and choose which customer claims may appear in outreach. We won’t invent a connection.</p><div class="actions"><button class="primary" data-action="client">+ Add your first contact</button><button data-action="csv" data-kind="clients">Preview a CSV import</button></div></div></section>`) +
    `<section class="panel"><h3>A simple import format</h3><p class="muted">Preview every row before saving. A sample is available for learning the format; it is labelled DEMO and cannot be used for sending.</p><a class="button" href="/static/clients-template.csv" download>Download labelled CSV example ↓</a></section>`;
}
function clientModal(cid) {
  const c = state.bootstrap.clients.find((x) => x.id == cid) || {};
  modal(
    modalTitle(
      cid ? "Edit client / contact" : "Add a client or network contact",
    ) +
      `<form id="client-form" data-id="${cid || ""}"><div class="form-grid">${field("company", "Company *", c.company)}${field("name", "Contact name *", c.name)}${field("email", "Business email", c.email, "email")}${field("role", "Role", c.role)}${field("domain", "Company domain", c.domain)}${field("relationship", "Relationship *", c.relationship, "text", "For example: past client, former colleague, partner.")}</div>${area("context", "Relationship context *", c.context, "How do you know this person? Record concrete work and dates.")}${check("verified", "I verified this client / network relationship.", c.verified)}${area("allowed_claim", "Exact customer claim you may share", c.allowed_claim, "Use only wording the client permits. Never imply an endorsement without evidence.")}${check("permission", "I have permission to share this customer name and the claim above.", c.permission)}${check("demo", "This is a labelled demo contact (sending will be blocked).", c.demo)}<div class="actions"><button class="primary" type="submit">Save contact</button><button type="button" data-action="close-modal">Cancel</button></div></form>`,
  );
}
function renderProfile() {
  const p = state.bootstrap.profile;
  $("#main").innerHTML =
    title(
      "MAKE THE MATCH MEANINGFUL",
      "Your offering, your rules",
      "Configure what you sell and who you want to help. Nothing is inferred about your business.",
    ) +
    `<div class="two-col"><section class="panel"><form id="profile-form">${area("offering", "What do you offer? *", p.offering, "Describe the service or product in one or two plain sentences.")}${area("buyer", "Who is the ideal buyer? *", p.buyer, "Team, responsibilities, company type, geography or needs.")}${field("keywords", "Relevant hiring terms", p.keywords, "text", "Comma-separated terms. Matches are literal and explained in the queue.")}${field("exclusions", "Exclude signals containing", p.exclusions, "text", "Comma-separated terms; matching opportunities cannot send.")}${field("sender_name", "Your name for the email signature *", p.sender_name)}<div class="form-grid">${field("cooldown_days", "Contact / client cooldown (days)", p.cooldown_days, "number")}${field("freshness_days", "Maximum source age (days)", p.freshness_days, "number")}</div><button type="submit" class="primary">Save profile →</button></form></section><div><section class="panel"><h2>Specificity makes better outreach</h2><p class="muted">The job is a signal to investigate. Your profile tells SignalDesk what kind of responsibilities could be relevant to your offering.</p><div class="divider"></div><h3>Customer examples stay permissioned</h3><p class="muted">Add exact allowed claims to each client record. A selected example can be used in a direct draft only when the relationship and permission are verified.</p><a class="button" href="#clients">Manage client references →</a></section><div class="info">Changing your profile invalidates existing approvals. Review and save affected drafts against the new profile before sending.</div></div></div>`;
}
async function renderConnections() {
  const r = await api("/events");
  $("#main").innerHTML =
    title(
      "EVIDENCE BEFORE ASSUMPTIONS",
      "Connections & events",
      "Explore actual event sources and bring in named participation when you have it.",
      `<button class="primary" data-action="csv" data-kind="events">+ Import event evidence</button>`,
    ) +
    `<div class="warning"><strong>Coverage: ${r.events.length} sourced events; no complete attendee roster.</strong><br>EUJobs supplies organisers and event excerpts. A shared organisation or event is a possible connection, never proof that two people know each other. Add personal evidence in the opportunity review.</div><div class="two-col"><section class="panel"><h2>Event evidence library</h2>${r.events
      .map(
        (e) =>
          `<article class="event-card"><h3>${esc(e.title)}</h3><span class="small muted">${day(e.date)} · Source checked ${day(e.checked_at)}</span><div class="event-roles">${r.participation
            .filter((p) => p.event_id === e.id)
            .map((p) =>
              pill(
                `${p.person || p.organization} · ${p.role} · Participation assessment: ${p.evidence_status}`,
                p.evidence_status === "conflicting" ? "red" : "",
              ),
            )
            .join(
              "",
            )}</div><details><summary>Read source excerpt</summary><p>${esc(e.description)}</p></details>${link(e.source_url)}</article>`,
      )
      .join(
        "",
      )}</section><div><section class="panel"><h2>Bring your own event evidence</h2><p class="muted">Import each participant as one row, with a shared event ID, date, source URL, organisation, name and role. Ambiguous participants remain possible until you verify them.</p><p class="muted">Roles: organiser, cohost, speaker, attendee or mentioned. Dates and conflicts remain visible.</p><a class="button" href="/static/events-template.csv" download>Download CSV example ↓</a></section><section class="panel"><h3>Correct the record</h3><p class="muted">Open an opportunity to add or correct a personal connection. Corrections retain the original evidence, invalidate approvals, and update local H-MEM reference memory.</p><a class="button" href="#signals">Review opportunities →</a></section></div></div>`;
}
function renderSettings() {
  const g = state.bootstrap.gmail,
    i = state.bootstrap.integrations;
  $("#main").innerHTML =
    title(
      "PRIVATE BY DESIGN",
      "Connections & settings",
      "Connect your mailbox on your terms. See what is available and what still needs setup.",
    ) +
    `<div class="two-col"><div><section class="panel"><div class="settings-title"><div class="gmail-logo">M</div><div><h2>Gmail</h2><p class="muted">Search selectively. Send deliberately.</p></div><span class="pill ${g.connected ? "green" : "amber"}">${g.connected ? "Connected" : g.configured ? "Ready to connect" : "Setup needed"}</span></div>${g.connected ? `<p>Connected as <strong>${esc(g.account.email)}</strong></p><p class="muted">${g.can_send ? "Search and explicit per-message sending are enabled." : "Read-only search is enabled. Sending needs separate permission."}</p><div class="actions">${!g.can_send ? '<button class="primary" data-action="gmail-connect" data-send="true">Enable Gmail sending</button>' : ""}<button data-action="gmail-disconnect" class="danger">Disconnect & revoke</button></div>` : `<p class="muted">${g.configured ? "Connect the Google account you want to search. You can enable sending separately." : "A Google OAuth web client has not been installed on this Azure server. No mailbox is connected and sending is disabled."}</p><button class="primary" data-action="gmail-connect" ${!g.configured ? "disabled" : ""}>Connect Gmail · read-only</button>`}<div class="divider"></div><h3>How your mailbox is used</h3><p class="muted">Search by company, person or address. At most 10 recent matches are shown. Only messages you select become evidence; there is no whole-mailbox import.</p><p class="small muted">Tokens are encrypted on the server. A ChatGPT connector does not grant this app Gmail access.</p></section><section class="panel"><h2>Search your mailbox</h2><form id="gmail-search-form"><label>Company, person or email<input name="term" placeholder="e.g. Example Company" required ${!g.connected ? "disabled" : ""}></label><label>Search type<select name="kind"><option value="company">Company / person name</option><option value="email">Email address</option></select></label><button class="primary" ${!g.connected ? "disabled" : ""}>Search recent messages</button></form><div id="gmail-results">${!g.connected ? '<p class="field-help">Available after you connect Gmail.</p>' : ""}</div></section></div><div><section class="panel"><h2>Google OAuth setup</h2><ol class="setup-steps"><li>Create a Google Cloud project, enable Gmail API and configure OAuth consent for your own account.</li><li>Create a <strong>Web application</strong> OAuth client. Add this exact redirect:<br><code class="code">${esc(g.redirect_uri)}</code></li><li>Install its downloaded JSON on Azure as <code class="code">runtime/google-oauth.json</code>, readable only by azureuser. Set <code class="code">GOOGLE_CLIENT_FILE</code> in the protected service environment file and restart this app.</li><li>Connect read-only first. Grant <code class="code">gmail.send</code> separately when you are ready. Read-only Gmail access is a restricted Google scope; follow Google’s consent and verification requirements for your deployment.</li></ol>${link("https://developers.google.com/identity/protocols/oauth2/web-server", "Official Google OAuth guide ↗")} ${link("https://developers.google.com/workspace/gmail/api/auth/scopes", "Gmail scopes ↗")}<p class="field-help">Keep the SSH tunnel open while completing localhost OAuth. The Azure app itself keeps running without your laptop.</p></section><section class="panel"><h2>Research integrations</h2>${[
      [
        "zetaris",
        "Zetaris",
        "Query register, jobs, events and clients together. Needs a configured instance, query permission and registered SignalDesk tables.",
      ],
      [
        "nightshift",
        "Nightshift → Nemotron",
        "Requires an Azure-accessible runtime and token. A routing-mode ID is not proof of Nemotron.",
      ],
      [
        "hmem",
        "Meterless H-MEM",
        "Local upstream reference implementation for verified facts and corrections. Deterministic hash embeddings; SQLite remains authoritative.",
      ],
    ]
      .map(
        ([key, name, desc]) =>
          `<div class="integration-row"><div class="row-between"><h3>${name}</h3>${pill(i[key].state.replaceAll("_", " "), i[key].state === "setup_needed" ? "amber" : i[key].state.includes("exercised") ? "green" : "")}</div><p>${desc}</p><button class="small" data-action="probe" data-service="${key}" ${!i[key].configured ? "disabled" : ""}>Verify adapter</button>${i[key].last ? `<details><summary>Last recorded evidence · ${day(i[key].last.created_at)}</summary><pre>${esc(JSON.stringify(i[key].last.detail, null, 2))}</pre></details>` : ""}</div>`,
      )
      .join(
        "",
      )}<div class="info">${esc(i.fallback)}</div></section></div></div>`;
}
async function renderActivity() {
  const a = await api("/activity");
  $("#main").innerHTML =
    title(
      "A RECORD YOU CAN TRUST",
      "Activity & outcomes",
      "Return to old decisions, exact sent messages and provider results. Acceptance is never labelled as delivery.",
    ) +
    `<div class="two-col"><div><section class="panel"><h2>Outreach history</h2>${
      a.sends.length
        ? a.sends
            .map(
              (s) =>
                `<article class="event-card"><div class="row-between"><h3>${esc(s.subject)}</h3>${pill(s.state.replaceAll("_", " "), s.state === "provider_accepted" ? "green" : s.state === "failed" ? "red" : "amber")}</div><p>${esc(s.route === "intro" ? "Introduction request" : "Direct outreach")} · ${day(s.created_at)}</p><p>From ${esc(s.sender)}<br>To ${esc(s.recipient)}</p><details><summary>Exact reserved message & evidence</summary><pre>${esc(s.body)}</pre><p>Message-ID: ${esc(s.message_id)}</p><pre>${esc(JSON.stringify(JSON.parse(s.evidence), null, 2))}</pre></details>${s.error ? `<div class="warning">${esc(s.error)}</div>` : ""}<p class="small muted">Outcome: ${esc(s.outcome || "Not yet recorded")}. Provider acceptance is not a delivery receipt.</p><div class="actions">${["submitting", "outcome_unknown"].includes(s.state) ? `<button data-action="reconcile" data-id="${s.id}">Reconcile in Gmail</button>` : ""}${s.state === "provider_accepted" ? `<button data-action="replies" data-id="${s.id}">Check replies</button><button data-action="outcome" data-id="${s.id}">Record outcome</button>` : ""}<a class="button" href="#opportunity/${s.opportunity_id}">Open opportunity</a></div>${a.replies
                  .filter((r) => r.send_id === s.id)
                  .map((r) => {
                    const m = JSON.parse(r.payload);
                    return `<div class="success"><strong>Reply from ${esc(m.from)}</strong><p>${esc(m.snippet)}</p>${link(m.url, "Open reply in Gmail ↗")}</div>`;
                  })
                  .join("")}</article>`,
            )
            .join("")
        : `<div class="empty compact"><div class="empty-symbol">◷</div><h3>No outreach has been sent</h3><p>Saved drafts stay in the opportunity queue. Once you explicitly approve and send, the exact message and provider result appear here.</p><a href="#signals" class="button">Back to signals →</a></div>`
    }</section><section class="panel"><h2>Saved drafts · including older signals</h2>${a.drafts.length ? a.drafts.map((d) => `<div class="event-card"><h3>${esc(d.company)} · ${esc(d.route)}</h3><p>${esc(d.subject)}</p><span class="small muted">Version ${d.version} · ${esc(d.state)} · ${day(d.updated_at)}</span><br><a class="button" href="#opportunity/${d.opportunity_id}">Open saved draft →</a></div>`).join("") : '<p class="muted">No saved drafts yet.</p>'}</section><section class="panel"><h2>Suppressed contacts</h2>${a.suppressions.length ? a.suppressions.map((s) => `<p><strong>${esc(s.email)}</strong><br><span class="muted">${esc(s.reason)} · ${day(s.created_at)}</span></p>`).join("") : '<p class="muted">No contacts suppressed. Suppression blocks both outreach routes.</p>'}</section></div><section class="panel"><h2>Workspace history</h2>${a.activity.length ? a.activity.map((e) => `<div class="timeline-item"><span class="time">${new Date(e.created_at).toLocaleString("en-GB")}</span><h3>${esc(e.kind.replaceAll("_", " "))}</h3><p class="muted">${esc(short(JSON.stringify(JSON.parse(e.detail)), 250))}</p></div>`).join("") : '<p class="muted">Your review decisions will appear here.</p>'}</section></div>`;
}
function csvModal(kind) {
  modal(
    modalTitle(
      kind === "clients"
        ? "Import clients · preview first"
        : "Import event participation",
    ) +
      `<p class="muted small">Upload or paste a CSV. All rows must pass validation before anything is saved. Existing contacts are never silently merged.</p><p><a href="/static/${kind}-template.csv" download>Download labelled example ↓</a></p><label>Choose CSV file<input id="csv-file" type="file" accept=".csv,text/csv"></label><form id="csv-form" data-kind="${kind}"><label>CSV contents<textarea id="csv-text" name="csv" rows="8" required placeholder="${kind === "clients" ? "company,name,email,relationship,context" : "event_id,title,date,organization,person,role,source_url"}"></textarea></label><button class="primary">Validate & preview</button></form><div id="csv-preview"></div>`,
  );
}
function evidenceModal(eid) {
  const e = state.detail.evidence.find((x) => x.id == eid) || {};
  modal(
    modalTitle(
      eid ? "Correct relationship evidence" : "Add relationship evidence",
    ) +
      `<form id="evidence-form" data-supersedes="${eid || ""}"><label>Relevant client / contact<select name="client_id">${clientOptions(e.client_id)}</select></label><div class="form-grid"><label>Evidence type<select name="kind">${["relationship", "employment", "event", "gmail"].map((k) => `<option ${e.kind === k ? "selected" : ""}>${k}</option>`).join("")}</select></label><label>Assessment<select name="status">${["possible", "verified", "conflicting", "rejected"].map((k) => `<option ${e.status === k ? "selected" : ""}>${k}</option>`).join("")}</select></label></div>${area("claim", "What does the evidence establish? *", e.claim, "For an introduction, record a specific personal connection; do not infer it from organisation co-attendance.")}${field("participants", "Named participants *", e.participants)}${field("roles", "Roles / employment context", e.roles)}<div class="form-grid">${field("source_date", "Evidence / verification date *", new Date().toISOString().slice(0, 10), "date")}${field("source_url", "Source URL (or describe direct verification in claim)", e.source_url, "url")}</div>${check("attested", "I have checked the source and named people. “Verified” reflects actual evidence, not an inference.")}${eid ? '<p class="small muted">The original record remains in history. All affected approvals are invalidated.</p>' : ""}<button class="primary">Save evidence</button></form>`,
  );
}
function resolveModal() {
  modal(
    modalTitle("Review register identity") +
      `<p class="muted small">Choose the actual legal entity. Similar names alone are not enough. This decision is recorded and remains separate from source matching.</p><form id="register-search-form"><label>Legal name or register ID<input name="q" value="${esc(state.detail.organization.name)}" required></label><button>Search register snapshot</button></form><div id="register-results"></div>`,
  );
}
function markDirty() {
  state.dirty = true;
  const save = $("#save-state");
  if (save)
    save.textContent =
      "Unsaved changes · approval invalidated until saved & reviewed";
  const b = $("#approve-button");
  if (b) b.disabled = true;
}
async function saveDraft() {
  const d = formData($("#draft-form")),
    old = state.detail.drafts.find((x) => x.route === state.route);
  d.version = old?.version;
  d.client_id = d.client_id ? Number(d.client_id) : null;
  await api(
    `/opportunities/${state.detail.organization.id}/drafts/${state.route}`,
    "POST",
    d,
  );
  await renderDetail(state.detail.organization.id);
  toast("Draft saved. Any previous approval has been invalidated.");
}
function reviewSend() {
  const d = state.detail.drafts.find((x) => x.route === state.route);
  if (state.dirty || !d || d.blockers.length) return;
  modal(
    modalTitle("Approve this exact message") +
      `<p class="small muted">${d.route === "intro" ? "Introduction request to your contact" : "Direct outreach to the prospect"} · Saved version ${d.version}</p><div class="info"><strong>From:</strong> ${esc(d.sender)}<br><strong>To:</strong> ${esc(d.recipient_name)} &lt;${esc(d.recipient)}&gt;<br><strong>Subject:</strong> ${esc(d.subject)}</div><pre>${esc(d.body)}</pre><form id="send-form">${check("attested", "I reviewed this exact message, verified the recipient and the evidence, and checked permission for every customer claim. I want to send this message now.")}<div class="actions"><button type="submit" class="primary">Approve and send this version →</button><button type="button" data-action="close-modal">Keep editing</button></div></form>`,
  );
}
async function action(btn) {
  const a = btn.dataset.action;
  if (a === "close-modal") return $("#modal").close();
  if (a === "logout") {
    await api("/logout", "POST", {});
    location.href = "/login";
    return;
  }
  if (a === "filter") {
    state.filter = btn.dataset.id;
    state.page = 0;
    return renderSignals();
  }
  if (a === "page") {
    state.page += Number(btn.dataset.dir);
    return renderSignals();
  }
  if (a === "refresh") {
    await api("/sources/refresh", "POST", {});
    await boot();
    renderSignals();
    toast(
      "EUJobs refreshed read-only. Changed evidence invalidates approvals.",
    );
    return;
  }
  if (a === "client") return clientModal(btn.dataset.id);
  if (a === "csv") return csvModal(btn.dataset.kind);
  if (a === "evidence") return evidenceModal(btn.dataset.id);
  if (a === "resolve") return resolveModal();
  if (a === "route-tab") {
    if (state.dirty) {
      toast("Save your edits before switching alternatives.", true);
      return;
    }
    state.route = btn.dataset.route;
    return renderDetail(state.detail.organization.id);
  }
  if (a === "regenerate") {
    const client_id = Number($("#draft-client").value) || null;
    if (state.dirty) {
      toast("Save your edits before regenerating.", true);
      return;
    }
    await api(
      `/opportunities/${state.detail.organization.id}/drafts/${state.route}`,
      "POST",
      { regenerate: true, client_id },
    );
    await renderDetail(state.detail.organization.id);
    return toast("Editable draft prepared from the current evidence.");
  }
  if (a === "save-draft") return saveDraft();
  if (a === "review-send") return reviewSend();
  if (a === "opportunity-status") {
    await api(`/opportunities/${state.detail.organization.id}/status`, "POST", {
      status: btn.dataset.status,
    });
    await boot();
    await renderDetail(state.detail.organization.id);
    return toast("Opportunity moved to " + btn.dataset.status + ".");
  }
  if (a === "suppress") {
    const d = state.detail.drafts.find((x) => x.route === state.route);
    modal(
      modalTitle("Suppress this contact") +
        `<p>Block both outreach routes to <strong>${esc(d.recipient)}</strong>.</p><form id="suppress-form">${field("reason", "Reason", "Do not contact")}<input type="hidden" name="email" value="${esc(d.recipient)}"><button class="danger">Suppress contact</button></form>`,
    );
    return;
  }
  if (a === "gmail-connect") {
    const r = await api("/gmail/connect", "POST", {
      with_send: btn.dataset.send === "true",
    });
    location.href = r.url;
    return;
  }
  if (a === "gmail-disconnect") {
    modal(
      modalTitle("Disconnect Gmail") +
        `<p class="muted">Delete local tokens and request revocation from Google. Previously selected evidence and outreach history stay in this private workspace.</p><button class="danger" data-action="confirm-disconnect">Disconnect & revoke now</button>`,
    );
    return;
  }
  if (a === "confirm-disconnect") {
    const r = await api("/gmail/disconnect", "POST", {});
    $("#modal").close();
    await boot();
    renderSettings();
    return toast(r.message, !r.revoked);
  }
  if (a === "commit-csv") {
    const r = await api("/import/commit", "POST", {
      preview_id: btn.dataset.id,
    });
    $("#modal").close();
    await boot();
    await route();
    return toast(`${r.imported} rows imported.`);
  }
  if (a === "probe") {
    const r = await api(
      `/integrations/${btn.dataset.service}/probe`,
      "POST",
      {},
    );
    await boot();
    renderSettings();
    return toast(
      r.fixture
        ? "H-MEM upstream reference ran successfully with an isolated labelled fixture."
        : "Adapter returned evidence. Inspect its recorded result.",
    );
  }
  if (a === "research") {
    const r = await api(
      `/opportunities/${state.detail.organization.id}/research`,
      "POST",
      {},
    );
    $("#research-result").innerHTML =
      `<div class="info"><strong>${esc(r.returned_model || r.model || r.service)}</strong><p>${esc(r.output)}</p>${r.pending ? `<p>${esc(r.pending)}</p>` : ""}</div>`;
    return;
  }
  if (a === "select-gmail") {
    modal(
      modalTitle("Import selected mailbox evidence") +
        `<p class="small muted">This excerpt will be saved as possible evidence. It does not automatically mark anyone as your client.</p><form id="gmail-import-form" data-id="${btn.dataset.id}"><label>Target organisation<select name="org_id" required>${signalOptions()}</select></label><label>Client / contact (optional)<select name="client_id">${clientOptions()}</select></label><button class="primary">Import this message only</button></form>`,
    );
    return;
  }
  if (a === "reconcile" || a === "replies") {
    const r = await api(`/sends/${btn.dataset.id}/${a}`, "POST", {});
    await renderActivity();
    return toast(
      a === "reconcile"
        ? r.result.state.replaceAll("_", " ")
        : `${r.replies.length} matching replies found.`,
    );
  }
  if (a === "outcome") {
    modal(
      modalTitle("Record a verified outcome") +
        `<form id="outcome-form" data-id="${btn.dataset.id}"><label>Outcome<select name="outcome"><option value="replied">Reply received</option><option value="intro_made">Introduction made</option><option value="declined">Introduction declined</option><option value="closed">Route closed by me</option></select></label><p class="muted small">This is your manual record. Closing a route does not approve or send its alternative; cooldowns still apply.</p><button class="primary">Save outcome</button></form>`,
    );
    return;
  }
  if (a === "choose-register") {
    const rid = btn.dataset.id;
    $("#register-results").innerHTML =
      `<form id="resolve-form" data-id="${esc(rid)}"><p>Selected register record: <strong>${esc(rid)}</strong></p>${area("note", "Why is this the correct entity? *", "", "Explain the exact legal identity or verified alias.")}<button class="primary">Confirm reviewed identity</button></form>`;
  }
}
async function submit(form) {
  const d = formData(form);
  switch (form.id) {
    case "client-form":
      await api(
        "/clients" + (form.dataset.id ? "/" + form.dataset.id : ""),
        form.dataset.id ? "PUT" : "POST",
        d,
      );
      $("#modal").close();
      await boot();
      renderClients();
      toast("Contact saved with explicit permissions.");
      break;
    case "profile-form":
      await api("/profile", "POST", d);
      await boot();
      renderProfile();
      toast("Profile saved. Review any affected drafts again.");
      break;
    case "csv-form": {
      const r = await api("/import/preview", "POST", {
        kind: form.dataset.kind,
        csv: d.csv,
      });
      $("#csv-preview").innerHTML =
        `<div class="divider"></div><h3>${r.count} valid rows · ${r.errors.length} errors</h3>${r.errors.map((e) => `<p class="error">Line ${e.line}: ${esc(e.error)}</p>`).join("")}<pre>${esc(JSON.stringify(r.rows.slice(0, 20), null, 2))}</pre>${r.count > 20 ? '<p class="small muted">First 20 rows shown; all rows validated.</p>' : ""}<button class="primary" data-action="commit-csv" data-id="${r.preview_id}" ${r.errors.length ? "disabled" : ""}>Import ${r.count} reviewed rows</button>`;
      break;
    }
    case "draft-form":
      await saveDraft();
      break;
    case "evidence-form":
      d.client_id = Number(d.client_id) || null;
      d.supersedes = Number(form.dataset.supersedes) || null;
      await api(
        `/opportunities/${state.detail.organization.id}/evidence`,
        "POST",
        d,
      );
      $("#modal").close();
      await renderDetail(state.detail.organization.id);
      toast("Evidence saved. Affected approvals are invalidated.");
      break;
    case "send-form": {
      if (!d.attested)
        throw Error("Please confirm that you reviewed this exact message.");
      const draft = state.detail.drafts.find((x) => x.route === state.route);
      const a = await api(`/drafts/${draft.id}/approve`, "POST", {
        version: draft.version,
        binding: draft.binding,
        attested: true,
      });
      const r = await api(`/drafts/${draft.id}/send`, "POST", {
        approval_id: a.approval_id,
      });
      $("#modal").close();
      await renderDetail(state.detail.organization.id);
      toast(
        r.send.state === "provider_accepted"
          ? "Gmail accepted the message. This is not a delivery receipt."
          : `Provider state: ${r.send.state}. Check Activity before further action.`,
        r.send.state !== "provider_accepted",
      );
      break;
    }
    case "suppress-form":
      await api("/suppressions", "POST", d);
      $("#modal").close();
      await renderDetail(state.detail.organization.id);
      toast("Contact suppressed across both routes.");
      break;
    case "gmail-search-form": {
      const r = await api("/gmail/search", "POST", d);
      $("#gmail-results").innerHTML =
        `<div class="info">${esc(r.coverage)}</div>${r.messages.length ? r.messages.map((m) => `<article class="event-card"><h3>${esc(m.subject)}</h3><p>${esc(m.from)} → ${esc(m.to)}</p><p>${esc(m.snippet)}</p><span class="small muted">${esc(m.date)}</span><div class="actions">${link(m.url, "Open in Gmail ↗")}<button data-action="select-gmail" data-id="${m.selection_id}">Select as evidence</button></div></article>`).join("") : '<p class="muted">No recent matches. Try a company name or known email address.</p>'}`;
      break;
    }
    case "gmail-import-form":
      d.client_id = Number(d.client_id) || null;
      d.selection_id = form.dataset.id;
      await api("/gmail/import", "POST", d);
      $("#modal").close();
      toast(
        "Selected excerpt saved as possible evidence. Verify it in the opportunity.",
      );
      break;
    case "register-search-form": {
      const r = await api("/registers?q=" + encodeURIComponent(d.q));
      $("#register-results").innerHTML =
        r.records
          .map(
            (x) =>
              `<div class="event-card"><h3>${esc(x.name)}</h3><p>${esc(x.id)} · ${esc(x.domain)} · ${x.in_register ? "Current" : "Removed"}</p>${link(x.source_url)}<button data-action="choose-register" data-id="${esc(x.id)}" ${!x.in_register ? "disabled" : ""}>Choose</button></div>`,
          )
          .join("") ||
        '<p class="muted">No exact search results. Try the legal name or register ID.</p>';
      break;
    }
    case "resolve-form":
      await api(
        `/opportunities/${state.detail.organization.id}/resolve`,
        "POST",
        { register_id: form.dataset.id, note: d.note },
      );
      $("#modal").close();
      await boot();
      await renderDetail(state.detail.organization.id);
      toast("Identity review saved.");
      break;
    case "outcome-form":
      await api(`/sends/${form.dataset.id}/outcome`, "POST", d);
      $("#modal").close();
      await renderActivity();
      toast("Outcome recorded. No alternative was sent.");
      break;
  }
}
document.addEventListener("click", async (e) => {
  const b = e.target.closest("[data-action]");
  if (!b || b.disabled) return;
  const was = b.disabled;
  b.disabled = true;
  try {
    await action(b);
  } catch (err) {
    toast(err.message, true);
  } finally {
    if (b.isConnected) b.disabled = was;
  }
});
document.addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target,
    buttons = [...form.querySelectorAll("button")];
  buttons.forEach((b) => (b.disabled = true));
  try {
    await submit(form);
  } catch (err) {
    toast(err.message, true);
  } finally {
    buttons.forEach((b) => {
      if (b.isConnected) b.disabled = false;
    });
  }
});
document.addEventListener("input", (e) => {
  if (e.target.closest("#draft-form") && e.target.name !== "client_id")
    markDirty();
  if (e.target.id === "signal-search") {
    state.search = e.target.value;
    state.page = 0;
    const pos = e.target.selectionStart;
    renderSignals();
    $("#signal-search").focus();
    $("#signal-search").setSelectionRange(pos, pos);
  }
});
document.addEventListener("change", async (e) => {
  if (e.target.id === "signal-register") {
    state.register = e.target.value;
    state.page = 0;
    renderSignals();
  }
  if (
    e.target.id === "draft-client" &&
    state.detail.drafts.some((d) => d.route === state.route)
  )
    markDirty();
  if (e.target.id === "csv-file") {
    const file = e.target.files[0];
    if (file) {
      if (file.size > 400000) return toast("Use a CSV under 400 KB.", true);
      $("#csv-text").value = await file.text();
    }
  }
});
window.addEventListener("hashchange", () =>
  route().catch((e) => toast(e.message, true)),
);
window.addEventListener("beforeunload", (e) => {
  if (state.dirty) {
    e.preventDefault();
    e.returnValue = "";
  }
});
(async () => {
  try {
    await boot();
    await route();
  } catch (e) {
    $("#main").innerHTML =
      '<div class="panel"><h2>Workspace unavailable</h2><p>Please reload the page.</p></div>';
    toast(e.message, true);
  }
})();
