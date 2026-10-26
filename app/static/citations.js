"use strict";

const identityKey = "virgozone.identity.v1";
const $ = (id) => document.getElementById(id);

const state = {
  items: [],
  facets: { persons: [], violations: [] },
  selectedId: null,
  detail: null,
  status: null,
  admin: false,
  publicWrite: false,
  violations: [],
  refreshTimer: null,
};

const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

function formatTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : dateFormat.format(date);
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function readIdentity() {
  try {
    const value = JSON.parse(localStorage.getItem(identityKey));
    if (value && typeof value.id === "string" && typeof value.displayName === "string") return value;
  } catch (error) {
    console.debug("Ignoring invalid local identity", error);
  }
  return null;
}

function makeBrowserId() {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}`;
}

function showIdentityDialog() {
  $("identity-input").value = readIdentity()?.displayName ?? "";
  if (!$("identity-dialog").open) $("identity-dialog").showModal();
}

function saveIdentity(event) {
  event.preventDefault();
  const displayName = $("identity-input").value.trim().replace(/\s+/g, " ");
  if (!displayName || displayName.length > 40) {
    $("identity-error").textContent = "Choose a name between 1 and 40 characters.";
    return;
  }
  const existing = readIdentity();
  localStorage.setItem(identityKey, JSON.stringify({ id: existing?.id ?? makeBrowserId(), displayName }));
  $("identity-error").textContent = "";
  $("identity-dialog").close();
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers ?? {}) },
    ...options,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  if (response.status === 204) return null;
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof payload.detail === "string" ? payload.detail : JSON.stringify(payload.detail ?? payload);
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return payload;
}

function runAction(action, params) {
  return api("/api/citations/actions", { method: "POST", body: { action, params } });
}

// ---------- filters ----------

function toIso(local) {
  if (!local) return "";
  const date = new Date(local);
  return Number.isNaN(date.getTime()) ? "" : date.toISOString();
}

function currentQuery() {
  const params = new URLSearchParams();
  const q = $("filter-q").value.trim();
  if (q) params.set("q", q);
  params.set("status", $("filter-status").value);
  if ($("filter-person").value) params.set("person", $("filter-person").value);
  if ($("filter-violation").value) params.set("violation", $("filter-violation").value);
  params.set("offense", $("filter-offense").value);
  if ($("filter-overdue").checked) params.set("overdue_only", "true");
  const after = toIso($("filter-after").value);
  const before = toIso($("filter-before").value);
  if (after) params.set("issued_after", after);
  if (before) params.set("issued_before", before);
  params.set("sort", $("filter-sort").value);
  params.set("order", $("filter-order").dataset.order);
  return params;
}

function syncUrl(params) {
  const url = new URL(location.href);
  url.search = params.toString();
  if (state.selectedId) url.searchParams.set("citation", state.selectedId);
  history.replaceState(null, "", url);
}

function restoreFromUrl() {
  const params = new URL(location.href).searchParams;
  const set = (id, key) => { if (params.has(key)) $(id).value = params.get(key); };
  set("filter-q", "q");
  set("filter-status", "status");
  set("filter-offense", "offense");
  set("filter-sort", "sort");
  $("filter-overdue").checked = params.get("overdue_only") === "true";
  if (params.has("order")) setOrder(params.get("order"));
  state.pendingPerson = params.get("person") ?? "";
  state.pendingViolation = params.get("violation") ?? "";
  state.selectedId = params.get("citation");
}

function setOrder(order) {
  const button = $("filter-order");
  button.dataset.order = order;
  const sort = $("filter-sort").value;
  const labels = {
    date: ["↑ oldest", "↓ newest"],
    person: ["↑ A→Z", "↓ Z→A"],
    type: ["↑ A→Z", "↓ Z→A"],
    status: ["↑ open first", "↓ void first"],
    due: ["↑ soonest", "↓ latest"],
    comments: ["↑ fewest", "↓ most"],
  };
  button.textContent = (labels[sort] ?? labels.date)[order === "asc" ? 0 : 1];
}

function fillSelect(select, values, keepValue, placeholder) {
  const current = keepValue ?? select.value;
  select.replaceChildren(new Option(placeholder, ""));
  for (const value of values) select.append(new Option(value, value));
  select.value = values.includes(current) ? current : "";
}

// ---------- list ----------

async function loadWall() {
  const params = currentQuery();
  syncUrl(params);
  try {
    const payload = await api(`/api/citations/wall?${params.toString()}`);
    state.items = payload.items;
    state.facets = payload.facets;
    fillSelect($("filter-person"), payload.facets.persons, state.pendingPerson, "Everyone");
    fillSelect($("filter-violation"), payload.facets.violations, state.pendingViolation, "Every type");
    state.pendingPerson = undefined;
    state.pendingViolation = undefined;
    $("list-count").textContent = `${payload.total} shown · ${payload.message}`;
    renderList();
  } catch (error) {
    $("list-count").textContent = "unavailable";
    $("citation-list").replaceChildren(el("div", "notice", `Citations are unavailable: ${error.message}`));
  }
}

function renderList() {
  const list = $("citation-list");
  if (!state.items.length) {
    list.replaceChildren(el("div", "empty-state", "No citations match these filters. Everyone is behaving. Suspicious."));
    return;
  }
  list.replaceChildren(...state.items.map(renderCard));
}

function renderCard(row) {
  const card = el("button", `citation-card status-${row.status}${row.overdue ? " is-overdue" : ""}${row.id === state.selectedId ? " is-selected" : ""}`);
  card.type = "button";
  card.dataset.id = row.id;
  card.append(el("p", "citation-offender", row.offender));
  const badges = el("div");
  badges.append(el("span", `badge status-${row.status}`, row.status));
  if (row.overdue) badges.append(" ", el("span", "badge is-overdue", "overdue"));
  if (row.first_offense) badges.append(" ", el("span", "badge is-first", "first offense"));
  card.append(badges);
  card.append(el("p", "citation-violation", row.violation));
  const meta = el("p", "citation-meta");
  meta.append(el("span", null, row.citation_number));
  meta.append(el("span", null, `issued ${formatTime(row.issued_at)}`));
  if (row.due_at) meta.append(el("span", null, `due ${formatTime(row.due_at)}`));
  meta.append(el("span", null, `${row.comment_count} comment${row.comment_count === 1 ? "" : "s"}`));
  card.append(meta);
  card.addEventListener("click", () => selectCitation(row.id));
  return card;
}

// ---------- detail ----------

async function selectCitation(id) {
  state.selectedId = id;
  renderList();
  syncUrl(currentQuery());
  $("detail-panel").classList.add("is-open");
  try {
    state.detail = await api(`/api/citations/${encodeURIComponent(id)}`);
    renderDetail();
  } catch (error) {
    $("detail-body").replaceChildren(el("div", "notice", error.message));
  }
}

function closeDetail() {
  state.selectedId = null;
  state.detail = null;
  $("detail-panel").classList.remove("is-open");
  $("detail-eyebrow").textContent = "select a citation";
  $("detail-body").replaceChildren();
  renderList();
  syncUrl(currentQuery());
}

function renderDetail() {
  const { record, receipt, remedies, history, comments } = state.detail;
  $("detail-eyebrow").textContent = `${record.citation_number} · ${record.status}${record.overdue ? " · overdue" : ""}`;
  const body = $("detail-body");
  body.replaceChildren();

  const receiptSection = el("section", "detail-section");
  receiptSection.append(el("h3", null, "Notice"), el("pre", "receipt", receipt));
  body.append(receiptSection);

  const remedySection = el("section", "detail-section");
  remedySection.append(el("h3", null, "Remedies"));
  const remedyList = el("ul", "remedy-list");
  if (!remedies.length) remedyList.append(el("li", null, "No remedies recorded."));
  for (const remedy of remedies) {
    const item = el("li", remedy.completed ? "is-complete" : "");
    item.textContent = `${remedy.description} (${remedy.required ? "required" : "optional"})`;
    if (!remedy.completed && record.status === "open" && (state.admin || state.publicWrite)) {
      const done = el("button", "secondary-button", "Mark done");
      done.type = "button";
      done.addEventListener("click", () => mutate("complete-remedy", {
        citation: record.id, expected_revision: record.revision, remedy_id: remedy.id, actor: actorName(),
      }));
      item.append(" ", done);
    }
    remedyList.append(item);
  }
  remedySection.append(remedyList);
  body.append(remedySection);

  if (state.admin) body.append(renderOrganizerTools(record));

  const commentsSection = el("section", "detail-section citation-comments");
  commentsSection.append(el("h3", null, "Peanut gallery"));
  const commentList = el("div", "comment-list");
  if (!comments.length) commentList.append(el("p", "comment-empty", "No commentary yet."));
  for (const comment of comments) commentList.append(renderComment(comment));
  commentsSection.append(commentList, renderComposer(record.id));
  body.append(commentsSection);

  const historySection = el("section", "detail-section");
  historySection.append(el("h3", null, "Activity"));
  const historyList = el("ul", "history-list");
  for (const event of [...history].reverse()) {
    const item = el("li");
    const payload = event.event_payload ?? {};
    const actor = event.actor || payload.actor || "system";
    const extra = payload.notes || payload.reason || payload.description || "";
    item.append(el("time", null, `${formatTime(event.created_at)} · ${actor}`));
    item.append(document.createTextNode(`${event.event_type ?? "event"}${extra ? ` — ${extra}` : ""}`));
    historyList.append(item);
  }
  historySection.append(historyList);
  body.append(historySection);
}

function renderComment(comment) {
  const node = el("div", "comment");
  node.dataset.id = comment.id;
  node.append(el("p", "comment-author", `${comment.author_name} · ${formatTime(comment.created_at)}`));
  node.append(el("p", "comment-text", comment.text));
  return node;
}

function renderComposer(citationId) {
  const wrapper = el("div");
  const form = el("form", "comment-composer");
  const input = el("input");
  input.maxLength = 2000;
  input.placeholder = "Add commentary…";
  input.required = true;
  const button = el("button", "send-button", "➤");
  button.type = "submit";
  const error = el("p", "comment-error");
  form.append(input, button);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const identity = readIdentity();
    if (!identity) {
      showIdentityDialog();
      return;
    }
    try {
      await api(`/api/citations/${encodeURIComponent(citationId)}/comments`, {
        method: "POST",
        body: { browser_id: identity.id, author: identity.displayName, text: input.value },
      });
      input.value = "";
      error.textContent = "";
    } catch (failure) {
      error.textContent = failure.message;
    }
  });
  wrapper.append(form, error);
  return wrapper;
}

function actorName() {
  return readIdentity()?.displayName ?? "";
}

function renderOrganizerTools(record) {
  const section = el("section", "detail-section");
  section.append(el("h3", null, "Organizer"));
  const form = el("form", "detail-form");
  const notes = el("textarea");
  notes.placeholder = "Notes / reason (required for reopen, void, and resolving with remedies still owed)";
  notes.maxLength = 1000;
  notes.rows = 2;
  const remedy = el("input");
  remedy.placeholder = "Add a remedy…";
  remedy.maxLength = 500;
  const error = el("p", "form-error");
  const actions = el("div", "detail-form-actions");
  const base = { citation: record.id, expected_revision: record.revision, actor: actorName() };
  const button = (label, handler) => {
    const node = el("button", "secondary-button", label);
    node.type = "button";
    node.addEventListener("click", async () => {
      error.textContent = "";
      try {
        await handler();
      } catch (failure) {
        error.textContent = failure.message;
      }
    });
    return node;
  };
  if (record.status === "open") {
    actions.append(button("Resolve", () => {
      const owed = state.detail.remedies.some((remedy) => remedy.required && !remedy.completed);
      const text = notes.value.trim() || undefined;
      return mutate("resolve", { ...base, notes: text, override_reason: owed ? text : undefined });
    }));
    actions.append(button("Void", () => mutate("void", { ...base, reason: notes.value.trim() })));
    actions.append(button("Add remedy", () => mutate("add-remedy", { ...base, description: remedy.value.trim(), required: true })));
  } else if (record.status !== "void") {
    actions.append(button("Reopen", () => mutate("reopen", { ...base, reason: notes.value.trim() })));
  }
  form.append(notes, remedy, actions, error);
  form.addEventListener("submit", (event) => event.preventDefault());
  section.append(form);
  return section;
}

async function mutate(action, params) {
  const cleaned = Object.fromEntries(Object.entries(params).filter(([, value]) => value !== undefined && value !== ""));
  await runAction(action, cleaned);
  await Promise.all([loadWall(), state.selectedId ? selectCitation(state.selectedId) : null, loadStatus()]);
}

// ---------- status / organizer ----------

async function loadStatus() {
  try {
    state.status = await api("/api/citations/status");
  } catch (error) {
    state.status = { available: false, error: error.message };
  }
  state.admin = Boolean(state.status.admin);
  state.publicWrite = Boolean(state.status.public_write);
  renderStatus();
  $("issue-card").hidden = !(state.status.available && (state.admin || state.publicWrite));
  $("sync-now-button").hidden = !state.admin;
  $("conflicts-button").hidden = !state.admin;
  $("organizer-logout").hidden = !state.admin;
  if (!$("issue-card").hidden && !state.violations.length) await loadIssueOptions();
}

function renderStatus() {
  const status = state.status;
  const grid = $("stat-grid");
  grid.replaceChildren();
  const dashboard = status.dashboard ?? {};
  for (const [key, label, cls] of [["open", "open", "is-open"], ["overdue", "overdue", "is-overdue"], ["resolved", "resolved", "is-resolved"], ["void", "void", "is-void"], ["due_soon", "due soon", ""], ["incomplete_required_remedies", "remedies owed", ""]]) {
    const stat = el("div", `stat ${cls}`);
    stat.append(el("dt", null, label), el("dd", null, String(dashboard[key] ?? "—")));
    grid.append(stat);
  }
  const card = $("sync-card");
  card.classList.remove("is-ok", "is-warn", "is-error");
  if (!status.available) {
    card.classList.add("is-error");
    $("sync-line").textContent = "citations offline";
    $("sync-detail").textContent = status.error ?? "";
    return;
  }
  const sync = status.synchronization ?? {};
  if (!sync.enabled) {
    card.classList.add("is-warn");
    $("sync-line").textContent = "local only";
    $("sync-detail").textContent = "Remote synchronization is disabled. Showing this workstation's records.";
  } else if (sync.last_error || sync.unresolved_conflicts) {
    card.classList.add("is-error");
    $("sync-line").textContent = sync.unresolved_conflicts ? `${sync.unresolved_conflicts} conflict(s)` : "sync error";
    $("sync-detail").textContent = sync.last_error ?? "Review conflicts; both versions are preserved.";
  } else if (!status.session_present) {
    card.classList.add("is-warn");
    $("sync-line").textContent = "not signed in";
    $("sync-detail").textContent = "Run `python -m app.citations_login` on the host to sign in to the shared workspace.";
  } else {
    card.classList.add(sync.pending_changes ? "is-warn" : "is-ok");
    $("sync-line").textContent = sync.pending_changes ? `${sync.pending_changes} pending` : "in sync";
    $("sync-detail").textContent = `last sync ${formatTime(sync.last_successful_sync)}\nremote cursor ${sync.remote_cursor ?? "—"} · every ${sync.sync_interval_seconds ?? "?"}s`;
  }
}

async function loadIssueOptions() {
  try {
    const [violations, persons] = await Promise.all([api("/api/citations/violations"), api("/api/citations/persons")]);
    state.violations = violations.items;
    $("violation-options").replaceChildren(...violations.items.map((row) => new Option(row.title)));
    $("person-options").replaceChildren(...persons.items.map((row) => new Option(row.display_name)));
  } catch (error) {
    $("issue-error").textContent = error.message;
  }
}

async function submitIssue(event) {
  event.preventDefault();
  $("issue-error").textContent = "";
  const minutes = Number($("issue-deadline").value);
  const params = {
    display_name: $("issue-name").value.trim(),
    violation: $("issue-violation").value,
    description: $("issue-description").value.trim() || undefined,
    remedy: $("issue-remedy").value.trim() || undefined,
    actor: $("issue-actor").value.trim() || actorName() || undefined,
    resolution_duration_seconds: minutes > 0 ? Math.round(minutes * 60) : undefined,
  };
  try {
    const result = await mutateReturning("issue-for-attendee", params);
    $("issue-form").reset();
    $("issue-deadline").value = "60";
    if (result?.record?.id) await selectCitation(result.record.id);
  } catch (error) {
    $("issue-error").textContent = error.message;
  }
}

async function mutateReturning(action, params) {
  const cleaned = Object.fromEntries(Object.entries(params).filter(([, value]) => value !== undefined && value !== ""));
  const result = await runAction(action, cleaned);
  await Promise.all([loadWall(), loadStatus(), loadIssueOptions()]);
  return result;
}

async function organizerLogin(event) {
  event.preventDefault();
  $("organizer-error").textContent = "";
  try {
    await api("/api/admin/login", { method: "POST", body: { password: $("organizer-password").value } });
    $("organizer-password").value = "";
    $("organizer-dialog").close();
    await loadStatus();
    if (state.selectedId) await selectCitation(state.selectedId);
  } catch (error) {
    $("organizer-error").textContent = error.message;
  }
}

async function organizerLogout() {
  await api("/api/admin/logout", { method: "POST" });
  $("organizer-dialog").close();
  await loadStatus();
  if (state.selectedId) await selectCitation(state.selectedId);
}

async function showConflicts() {
  const list = $("conflicts-list");
  list.replaceChildren(el("p", "comment-empty", "loading…"));
  $("conflicts-dialog").showModal();
  try {
    const payload = await api("/api/citations/conflicts");
    list.replaceChildren();
    if (!payload.items.length) list.append(el("p", "comment-empty", "No unresolved conflicts."));
    for (const conflict of payload.items) {
      const item = el("li");
      item.append(el("strong", null, conflict.label), document.createTextNode(` — ${conflict.detail} `));
      for (const choice of ["local", "remote"]) {
        const button = el("button", "secondary-button", `Keep ${choice}`);
        button.type = "button";
        button.addEventListener("click", async () => {
          await runAction("sync-resolve", { conflict_id: conflict.id, choice });
          await Promise.all([showConflicts(), loadStatus(), loadWall()]);
        });
        item.append(" ", button);
      }
      list.append(item);
    }
  } catch (error) {
    list.replaceChildren(el("div", "notice", error.message));
  }
}

// ---------- live updates ----------

function scheduleRefresh() {
  if (state.refreshTimer) return;
  state.refreshTimer = window.setTimeout(async () => {
    state.refreshTimer = null;
    await Promise.all([loadWall(), loadStatus(), state.selectedId ? selectCitation(state.selectedId) : null]);
  }, 400);
}

function handleEvent(envelope) {
  if (envelope.type === "citations_updated") {
    scheduleRefresh();
  } else if (envelope.type === "citation_comment_created") {
    const comment = envelope.payload;
    if (comment.citation_id === state.selectedId && state.detail) {
      if (!state.detail.comments.some((existing) => existing.id === comment.id)) {
        state.detail.comments.push(comment);
        const list = document.querySelector(".citation-comments .comment-list");
        if (list) {
          list.querySelector(".comment-empty")?.remove();
          list.append(renderComment(comment));
        }
      }
    }
    const row = state.items.find((item) => item.id === comment.citation_id);
    if (row) {
      row.comment_count += 1;
      renderList();
    }
  }
}

function setConnection(stateName) {
  const node = $("connection-state");
  node.classList.toggle("is-online", stateName === "online");
  node.classList.toggle("is-offline", stateName === "offline");
  $("connection-label").textContent = stateName;
}

// ---------- boot ----------

function boot() {
  restoreFromUrl();
  $("identity-form").addEventListener("submit", saveIdentity);
  $("identity-button").addEventListener("click", showIdentityDialog);
  $("organizer-button").addEventListener("click", () => $("organizer-dialog").showModal());
  $("organizer-form").addEventListener("submit", organizerLogin);
  $("organizer-logout").addEventListener("click", organizerLogout);
  $("conflicts-button").addEventListener("click", showConflicts);
  $("conflicts-close").addEventListener("click", () => $("conflicts-dialog").close());
  $("sync-now-button").addEventListener("click", async () => {
    $("sync-line").textContent = "syncing…";
    try {
      await runAction("sync-now", {});
    } catch (error) {
      $("sync-detail").textContent = error.message;
    }
    await Promise.all([loadStatus(), loadWall()]);
  });
  $("issue-form").addEventListener("submit", submitIssue);
  $("detail-close").addEventListener("click", closeDetail);

  const filters = $("filters");
  filters.addEventListener("submit", (event) => event.preventDefault());
  filters.addEventListener("change", loadWall);
  let searchTimer = null;
  $("filter-q").addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(loadWall, 250);
  });
  $("filter-sort").addEventListener("change", () => setOrder($("filter-order").dataset.order));
  $("filter-order").addEventListener("click", () => {
    setOrder($("filter-order").dataset.order === "desc" ? "asc" : "desc");
    loadWall();
  });
  $("filter-reset").addEventListener("click", () => {
    filters.reset();
    setOrder("desc");
    loadWall();
  });
  setOrder($("filter-order").dataset.order);

  const socket = new FairySocket({ onEvent: handleEvent, onOpen: scheduleRefresh, onState: setConnection });
  socket.start();
  window.setInterval(scheduleRefresh, 60_000);

  loadStatus().then(loadWall).then(() => {
    if (state.selectedId) selectCitation(state.selectedId);
  });
}

boot();
