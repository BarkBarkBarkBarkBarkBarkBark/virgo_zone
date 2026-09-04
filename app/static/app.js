"use strict";

const elements = {
  connection: document.querySelector("#connection-state"),
  connectionLabel: document.querySelector("#connection-label"),
  identityButton: document.querySelector("#identity-button"),
  identityDialog: document.querySelector("#identity-dialog"),
  identityForm: document.querySelector("#identity-form"),
  identityInput: document.querySelector("#display-name"),
  identityError: document.querySelector("#identity-error"),
  schedule: document.querySelector("#schedule-list"),
  media: document.querySelector("#media-grid"),
  chat: document.querySelector("#chat-log"),
  fairyState: document.querySelector("#fairy-state"),
  chatForm: document.querySelector("#chat-form"),
  chatInput: document.querySelector("#chat-input"),
  chatSend: document.querySelector("#chat-form button[type='submit']"),
  uploadButton: document.querySelector("#upload-button"),
  uploadDialog: document.querySelector("#upload-dialog"),
  uploadForm: document.querySelector("#upload-form"),
  uploadFile: document.querySelector("#media-file"),
  uploadCaption: document.querySelector("#media-caption"),
  uploadError: document.querySelector("#upload-error"),
  uploadSubmit: document.querySelector("#upload-submit"),
  lightbox: document.querySelector("#media-lightbox"),
  lightboxMedia: document.querySelector("#lightbox-media"),
  lightboxNotes: document.querySelector("#lightbox-notes"),
  hosakaStatusMark: document.querySelector("#hosaka-status-mark"),
  hosakaPanelState: document.querySelector("#hosaka-panel-state"),
  scheduleAdminButton: document.querySelector("#schedule-admin-button"),
  adminDialog: document.querySelector("#admin-dialog"),
  adminForm: document.querySelector("#admin-form"),
  adminPassword: document.querySelector("#admin-password"),
  adminStorage: document.querySelector("#admin-storage"),
  adminError: document.querySelector("#admin-error"),
  adminSubmit: document.querySelector("#admin-submit"),
  adminLogout: document.querySelector("#admin-logout"),
  scheduleDialog: document.querySelector("#schedule-dialog"),
  scheduleForm: document.querySelector("#schedule-form"),
  scheduleFormTitle: document.querySelector("#schedule-form-title"),
  scheduleId: document.querySelector("#schedule-id"),
  scheduleTitle: document.querySelector("#schedule-title"),
  scheduleDescription: document.querySelector("#schedule-description"),
  scheduleStart: document.querySelector("#schedule-start"),
  scheduleEnd: document.querySelector("#schedule-end"),
  scheduleLocation: document.querySelector("#schedule-location"),
  scheduleError: document.querySelector("#schedule-error"),
  scheduleSubmit: document.querySelector("#schedule-submit"),
  navButtons: Array.from(document.querySelectorAll("[data-view]")),
  panels: Array.from(document.querySelectorAll(".panel")),
};

const identityKey = "virgozone.identity.v1";
const applicationState = {
  schedule: new Map(),
  media: new Map(),
  chat: new Map(),
  comments: new Map(),
};
let pendingEvents = [];
let syncing = false;
let syncPromise = null;
let hasBootstrapped = false;
let activeMediaId = null;
let adminConfigured = false;
let adminAuthenticated = false;
let hosakaActivityCount = 0;
let hosakaOnline = false;

function createEmptyState(text) {
  const node = document.createElement("div");
  node.className = "empty-state";
  node.textContent = text;
  return node;
}

function readIdentity() {
  try {
    const value = JSON.parse(localStorage.getItem(identityKey));
    if (value && typeof value.id === "string" && typeof value.displayName === "string") {
      return value;
    }
  } catch (error) {
    console.debug("Ignoring invalid local identity", error);
  }
  return null;
}

function makeBrowserId() {
  if (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  return `${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}`;
}

function showIdentityDialog() {
  const identity = readIdentity();
  elements.identityInput.value = identity?.displayName ?? "";
  if (!elements.identityDialog.open) {
    elements.identityDialog.showModal();
  }
}

function saveIdentity(event) {
  event.preventDefault();
  const displayName = elements.identityInput.value.trim().replace(/\s+/g, " ");
  if (!displayName || displayName.length > 40) {
    elements.identityError.textContent = "Choose a name between 1 and 40 characters.";
    return;
  }
  const existing = readIdentity();
  localStorage.setItem(identityKey, JSON.stringify({
    id: existing?.id ?? makeBrowserId(),
    displayName,
  }));
  elements.identityError.textContent = "";
  elements.identityDialog.close();
}

function setConnection(state, label) {
  elements.connection.classList.toggle("is-online", state === "online");
  elements.connection.classList.toggle("is-offline", state === "offline");
  elements.connectionLabel.textContent = label;
}

function setHosakaStatus(status) {
  const labels = {
    listening: "listening",
    thinking: "thinking…",
    offline: "offline",
  };
  const label = labels[status] ?? status;
  elements.hosakaPanelState.textContent = label;
  elements.hosakaStatusMark.textContent = status === "thinking" ? "✦" : "✧";
  elements.fairyState.title = `Hosaka is ${status}`;
}

function sortedValues(collection, direction = "asc") {
  return Array.from(collection.values()).sort((left, right) => {
    const leftTime = left.created_at ?? left.starts_at ?? "";
    const rightTime = right.created_at ?? right.starts_at ?? "";
    const result = leftTime.localeCompare(rightTime) || left.id.localeCompare(right.id);
    return direction === "asc" ? result : -result;
  });
}

function renderSchedule(events) {
  elements.schedule.replaceChildren();
  if (events.length === 0) {
    elements.schedule.append(createEmptyState("nothing scheduled · time is fake here"));
    return;
  }
  let previousGroup = null;
  for (const event of events) {
    const startDate = new Date(event.starts_at);
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const eventDay = new Date(startDate.getFullYear(), startDate.getMonth(), startDate.getDate());
    const dayOffset = Math.round((eventDay - today) / 86_400_000);
    const group = dayOffset === 0 ? "Today" : dayOffset === 1 ? "Tomorrow" : "Upcoming";
    if (group !== previousGroup) {
      const heading = document.createElement("h2");
      heading.className = "schedule-group";
      heading.textContent = group;
      elements.schedule.append(heading);
      previousGroup = group;
    }
    const item = document.createElement("article");
    item.className = "schedule-item";
    const time = document.createElement("time");
    time.className = "schedule-time";
    time.dateTime = event.starts_at;
    time.textContent = new Intl.DateTimeFormat(undefined, {
      hour: "numeric",
      minute: "2-digit",
    }).format(new Date(event.starts_at));
    const copy = document.createElement("div");
    copy.className = "schedule-copy";
    const title = document.createElement("p");
    title.className = "schedule-title";
    title.textContent = event.title;
    copy.append(title);
    const supportingText = [event.description, event.location].filter(Boolean).join(" · ");
    if (supportingText) {
      const place = document.createElement("p");
      place.className = "schedule-place";
      place.textContent = supportingText;
      copy.append(place);
    }
    item.append(time, copy);
    if (adminAuthenticated) {
      const actions = document.createElement("div");
      actions.className = "schedule-actions";
      const edit = document.createElement("button");
      edit.type = "button";
      edit.textContent = "Edit";
      edit.addEventListener("click", () => openScheduleForm(event));
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "Delete";
      remove.addEventListener("click", () => deleteScheduleEvent(event.id));
      actions.append(edit, remove);
      item.append(actions);
    }
    elements.schedule.append(item);
  }
}

function openMedia(post) {
  activeMediaId = post.id;
  elements.lightboxMedia.replaceChildren();
  elements.lightboxNotes.replaceChildren();
  let mediaNode;
  if (post.media_type.startsWith("video/")) {
    mediaNode = document.createElement("video");
    mediaNode.controls = true;
    mediaNode.preload = "metadata";
    mediaNode.src = post.original_url;
    if (post.thumbnail_url) {
      mediaNode.poster = post.thumbnail_url;
    }
  } else {
    mediaNode = document.createElement("img");
    mediaNode.src = post.original_url;
    mediaNode.alt = post.caption || `Photo by ${post.author_name}`;
  }
  const author = document.createElement("p");
  author.className = "lightbox-author";
  author.textContent = post.author_name;
  const caption = document.createElement("p");
  caption.className = "lightbox-caption";
  caption.textContent = post.caption || "No caption. The evidence speaks for itself.";
  const meta = document.createElement("p");
  meta.className = "lightbox-meta";
  meta.textContent = `${post.comment_count} comments · ${new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(post.created_at))}`;
  const commentsHeading = document.createElement("h3");
  commentsHeading.className = "comments-heading";
  commentsHeading.textContent = "Thread";
  const comments = document.createElement("div");
  comments.className = "comment-list";
  comments.id = "lightbox-comments";
  const fairyComment = document.createElement("button");
  fairyComment.type = "button";
  fairyComment.className = "fairy-comment-button";
  fairyComment.textContent = "✦ ask Hosaka";
  fairyComment.addEventListener("click", () => requestFairyComment(post.id, fairyComment, error));
  const form = document.createElement("form");
  form.className = "comment-composer";
  const input = document.createElement("input");
  input.type = "text";
  input.maxLength = 2000;
  input.placeholder = "leave a comment";
  input.setAttribute("aria-label", "Comment");
  const submit = document.createElement("button");
  submit.type = "submit";
  submit.className = "send-button";
  submit.title = "Send comment";
  submit.setAttribute("aria-label", "Send comment");
  submit.textContent = "↗";
  const error = document.createElement("p");
  error.className = "comment-error";
  error.setAttribute("role", "alert");
  form.append(input, submit);
  form.addEventListener("submit", (event) => sendMediaComment(event, post.id, input, submit, error));
  elements.lightboxMedia.append(mediaNode);
  elements.lightboxNotes.append(author, caption, meta, fairyComment, commentsHeading, comments, form, error);
  elements.lightbox.showModal();
  renderCommentThread(post.id);
  loadComments(post.id);
}

function renderCommentThread(mediaId) {
  if (activeMediaId !== mediaId) {
    return;
  }
  const container = document.querySelector("#lightbox-comments");
  if (!container) {
    return;
  }
  container.replaceChildren();
  const collection = applicationState.comments.get(mediaId);
  const comments = collection ? sortedValues(collection) : [];
  if (comments.length === 0) {
    const empty = document.createElement("p");
    empty.className = "comment-empty";
    empty.textContent = "no witnesses yet";
    container.append(empty);
    return;
  }
  for (const comment of comments) {
    const item = document.createElement("article");
    item.className = `comment${comment.is_ai ? " is-ai" : ""}`;
    const author = document.createElement("p");
    author.className = "comment-author";
    author.textContent = comment.is_ai ? `✦ ${comment.author_name}` : comment.author_name;
    const text = document.createElement("p");
    text.className = "comment-text";
    text.textContent = comment.text;
    item.append(author, text);
    container.append(item);
  }
}

async function loadComments(mediaId) {
  try {
    const response = await fetch(`/api/media/${encodeURIComponent(mediaId)}/comments`, {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      throw new Error(`Comments failed: ${response.status}`);
    }
    const page = await response.json();
    const collection = applicationState.comments.get(mediaId) ?? new Map();
    for (const comment of page.items) {
      collection.set(comment.id, comment);
    }
    applicationState.comments.set(mediaId, collection);
    renderCommentThread(mediaId);
  } catch (error) {
    console.error(error);
  }
}

function applyComment(comment) {
  const collection = applicationState.comments.get(comment.media_id) ?? new Map();
  const isNew = !collection.has(comment.id);
  collection.set(comment.id, comment);
  applicationState.comments.set(comment.media_id, collection);
  if (isNew) {
    const post = applicationState.media.get(comment.media_id);
    if (post) {
      applicationState.media.set(post.id, { ...post, comment_count: post.comment_count + 1 });
      renderMedia(sortedValues(applicationState.media, "desc"));
    }
  }
  renderCommentThread(comment.media_id);
}

function renderMedia(media, highlightedId = null) {
  elements.media.replaceChildren();
  if (media.length === 0) {
    elements.media.append(createEmptyState("the wall is listening"));
    return;
  }
  for (const post of media) {
    const card = document.createElement("article");
    card.className = "media-card";
    const open = document.createElement("button");
    open.type = "button";
    open.className = "media-open";
    open.addEventListener("click", () => openMedia(post));
    if (post.thumbnail_url) {
      const thumbnail = document.createElement("img");
      thumbnail.src = post.thumbnail_url;
      thumbnail.alt = post.caption || `Media by ${post.author_name}`;
      thumbnail.loading = "lazy";
      thumbnail.decoding = "async";
      open.append(thumbnail);
    } else {
      const placeholder = document.createElement("div");
      placeholder.className = "media-placeholder";
      placeholder.textContent = post.media_type.startsWith("video/") ? "▷" : "◇";
      open.append(placeholder);
    }
    const copy = document.createElement("div");
    copy.className = "media-copy";
    const caption = document.createElement("p");
    caption.textContent = post.caption || `${post.author_name} sent an artifact`;
    const meta = document.createElement("p");
    meta.className = "media-meta";
    meta.textContent = `${post.author_name} · ${post.comment_count} comments`;
    copy.append(caption, meta);
    open.append(copy);
    card.append(open);
    elements.media.append(card);
    window.fairyEffects?.observeCard(card);
    if (post.id === highlightedId) {
      window.fairyEffects?.markNew(card);
    }
  }
}

function renderChat(messages) {
  elements.chat.replaceChildren();
  if (messages.length === 0) {
    elements.chat.append(createEmptyState("quiet enough to hear the router thinking"));
  }
  for (const message of messages) {
    const item = document.createElement("article");
    item.className = "chat-message";
    const author = document.createElement("p");
    author.className = "chat-author";
    author.textContent = message.is_ai ? `✦ ${message.author_name}` : message.author_name;
    const text = document.createElement("p");
    text.className = "chat-text";
    text.textContent = message.text;
    item.append(author, text);
    elements.chat.append(item);
  }
  if (hosakaActivityCount > 0) {
    const thinking = document.createElement("article");
    thinking.className = "chat-message hosaka-thinking";
    const author = document.createElement("p");
    author.className = "chat-author";
    author.textContent = "✦ HOSAKA";
    const dots = document.createElement("span");
    dots.className = "thinking-dots";
    dots.setAttribute("aria-label", "Hosaka is thinking");
    dots.append(document.createElement("span"), document.createElement("span"), document.createElement("span"));
    thinking.append(author, dots);
    elements.chat.append(thinking);
  }
  elements.chat.scrollTop = elements.chat.scrollHeight;
}

function replaceCollection(collection, values) {
  collection.clear();
  for (const value of values) {
    collection.set(value.id, value);
  }
}

function renderApplication() {
  renderSchedule(sortedValues(applicationState.schedule));
  renderMedia(sortedValues(applicationState.media, "desc"));
  renderChat(sortedValues(applicationState.chat));
}

function applyEvent(envelope) {
  if (envelope.type === "chat_created" && envelope.payload?.id) {
    applicationState.chat.set(envelope.payload.id, envelope.payload);
    renderChat(sortedValues(applicationState.chat));
  }
  if (envelope.type === "media_created" && envelope.payload?.id) {
    applicationState.media.set(envelope.payload.id, envelope.payload);
    renderMedia(sortedValues(applicationState.media, "desc"), envelope.payload.id);
  }
  if (envelope.type === "media_comment_created" && envelope.payload?.id) {
    applyComment(envelope.payload);
  }
  if (envelope.type === "fairy_typing") {
    hosakaActivityCount += 1;
    setHosakaStatus("thinking");
    if (envelope.payload?.scope === "chat") {
      renderChat(sortedValues(applicationState.chat));
    }
  }
  if (envelope.type === "fairy_finished") {
    hosakaActivityCount = Math.max(0, hosakaActivityCount - 1);
    setHosakaStatus(hosakaActivityCount > 0 ? "thinking" : hosakaOnline ? "listening" : "offline");
    if (envelope.payload?.scope === "chat") {
      renderChat(sortedValues(applicationState.chat));
    }
  }
  if (["schedule_created", "schedule_updated"].includes(envelope.type) && envelope.payload?.id) {
    applicationState.schedule.set(envelope.payload.id, envelope.payload);
    renderSchedule(sortedValues(applicationState.schedule));
  }
  if (envelope.type === "schedule_deleted" && envelope.payload?.id) {
    applicationState.schedule.delete(envelope.payload.id);
    renderSchedule(sortedValues(applicationState.schedule));
  }
  if (envelope.type === "media_deleted" && envelope.payload?.id) {
    applicationState.media.delete(envelope.payload.id);
    renderMedia(sortedValues(applicationState.media, "desc"));
    if (activeMediaId === envelope.payload.id) {
      elements.lightbox.close();
      activeMediaId = null;
    }
  }
}

function receiveEvent(envelope) {
  if (syncing) {
    pendingEvents.push(envelope);
    return;
  }
  applyEvent(envelope);
}

async function synchronize() {
  if (syncPromise !== null) {
    return syncPromise;
  }
  syncPromise = (async () => {
    syncing = true;
    try {
      const response = await fetch("/api/bootstrap", { headers: { Accept: "application/json" } });
      if (!response.ok) {
        throw new Error(`Bootstrap failed: ${response.status}`);
      }
      const state = await response.json();
      document.title = state.app_name;
      replaceCollection(applicationState.schedule, state.schedule);
      replaceCollection(applicationState.media, state.media);
      replaceCollection(applicationState.chat, state.chat);
      renderApplication();
      hosakaOnline = state.feature_flags.fairy;
      setHosakaStatus(hosakaOnline ? "listening" : "offline");
      adminConfigured = state.feature_flags.admin;
      await refreshAdminSession();
      hasBootstrapped = true;
      for (const envelope of pendingEvents) {
        applyEvent(envelope);
      }
      pendingEvents = [];
    } catch (error) {
      console.error(error);
      if (!hasBootstrapped) {
        renderApplication();
      }
      setConnection("offline", "offline");
    } finally {
      syncing = false;
      syncPromise = null;
    }
  })();
  return syncPromise;
}

function selectView(view) {
  for (const panel of elements.panels) {
    panel.classList.toggle("is-active", panel.id === view);
  }
  for (const button of elements.navButtons) {
    button.classList.toggle("is-active", button.dataset.view === view);
  }
}

async function sendChat(event) {
  event.preventDefault();
  const identity = readIdentity();
  if (!identity) {
    showIdentityDialog();
    return;
  }
  const text = elements.chatInput.value.trim();
  if (!text) {
    return;
  }
  elements.chatInput.disabled = true;
  elements.chatSend.disabled = true;
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        browser_id: identity.id,
        author: identity.displayName,
        text,
        reply_to: null,
      }),
    });
    if (!response.ok) {
      throw new Error(`Message failed: ${response.status}`);
    }
    const message = await response.json();
    applicationState.chat.set(message.id, message);
    renderChat(sortedValues(applicationState.chat));
    elements.chatInput.value = "";
  } catch (error) {
    console.error(error);
    setConnection("offline", "send failed");
  } finally {
    elements.chatInput.disabled = false;
    elements.chatSend.disabled = false;
    elements.chatInput.focus();
  }
}

async function uploadMedia(event) {
  event.preventDefault();
  const identity = readIdentity();
  if (!identity) {
    elements.uploadDialog.close();
    showIdentityDialog();
    return;
  }
  const file = elements.uploadFile.files[0];
  if (!file) {
    elements.uploadError.textContent = "Choose a photo or video.";
    return;
  }
  const data = new FormData();
  data.append("file", file);
  data.append("browser_id", identity.id);
  data.append("author", identity.displayName);
  data.append("caption", elements.uploadCaption.value.trim());
  elements.uploadSubmit.disabled = true;
  elements.uploadError.textContent = "uploading through the local ether…";
  try {
    const response = await fetch("/api/media", { method: "POST", body: data });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || `Upload failed: ${response.status}`);
    }
    applicationState.media.set(payload.id, payload);
    renderMedia(sortedValues(applicationState.media, "desc"));
    elements.uploadForm.reset();
    elements.uploadError.textContent = "";
    elements.uploadDialog.close();
  } catch (error) {
    console.error(error);
    elements.uploadError.textContent = error.message;
  } finally {
    elements.uploadSubmit.disabled = false;
  }
}

async function sendMediaComment(event, mediaId, input, submit, errorNode) {
  event.preventDefault();
  const identity = readIdentity();
  if (!identity) {
    elements.lightbox.close();
    showIdentityDialog();
    return;
  }
  const text = input.value.trim();
  if (!text) {
    return;
  }
  input.disabled = true;
  submit.disabled = true;
  errorNode.textContent = "";
  try {
    const response = await fetch(`/api/media/${encodeURIComponent(mediaId)}/comments`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        browser_id: identity.id,
        author: identity.displayName,
        text,
      }),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || `Comment failed: ${response.status}`);
    }
    applyComment(payload);
    input.value = "";
  } catch (error) {
    console.error(error);
    errorNode.textContent = error.message;
  } finally {
    input.disabled = false;
    submit.disabled = false;
    input.focus();
  }
}

async function requestFairyComment(mediaId, button, errorNode) {
  button.disabled = true;
  button.classList.add("is-working");
  button.textContent = "✦ consulting council…";
  errorNode.textContent = "";
  try {
    const response = await fetch(`/api/media/${encodeURIComponent(mediaId)}/fairy`, {
      method: "POST",
      headers: { Accept: "application/json" },
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || `Fairy failed: ${response.status}`);
    }
    applyComment(payload);
  } catch (error) {
    console.error(error);
    errorNode.textContent = error.message;
  } finally {
    button.disabled = false;
    button.classList.remove("is-working");
    button.textContent = "✦ ask Hosaka";
  }
}

async function refreshAdminSession() {
  if (!adminConfigured) {
    adminAuthenticated = false;
    elements.scheduleAdminButton.disabled = true;
    elements.scheduleAdminButton.title = "Admin password is not configured";
    return;
  }
  try {
    const response = await fetch("/api/admin/session", { headers: { Accept: "application/json" } });
    const session = await response.json();
    adminAuthenticated = session.authenticated;
    elements.scheduleAdminButton.disabled = false;
    elements.scheduleAdminButton.textContent = adminAuthenticated ? "＋" : "⌁";
    elements.scheduleAdminButton.title = adminAuthenticated ? "Add schedule event" : "Schedule admin";
    elements.adminLogout.hidden = !adminAuthenticated;
    elements.adminPassword.hidden = adminAuthenticated;
    elements.adminSubmit.hidden = adminAuthenticated;
    renderSchedule(sortedValues(applicationState.schedule));
  } catch (error) {
    console.error(error);
  }
}

async function showAdminDialog() {
  elements.adminError.textContent = "";
  try {
    const response = await fetch("/api/status", { headers: { Accept: "application/json" } });
    const status = await response.json();
    const free = (status.disk_free_bytes / (1024 ** 3)).toFixed(1);
    const media = (status.media_bytes / (1024 ** 3)).toFixed(2);
    elements.adminStorage.textContent = `${free} GB free · ${media} GB media`;
  } catch (error) {
    elements.adminStorage.textContent = "storage status unavailable";
  }
  elements.adminDialog.showModal();
}

async function loginAdmin(event) {
  event.preventDefault();
  elements.adminError.textContent = "";
  try {
    const response = await fetch("/api/admin/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: elements.adminPassword.value }),
    });
    if (!response.ok) {
      const payload = await response.json();
      throw new Error(payload.detail || "Admin login failed");
    }
    elements.adminPassword.value = "";
    await refreshAdminSession();
    elements.adminDialog.close();
    openScheduleForm();
  } catch (error) {
    elements.adminError.textContent = error.message;
  }
}

async function logoutAdmin() {
  await fetch("/api/admin/logout", { method: "POST" });
  adminAuthenticated = false;
  await refreshAdminSession();
  elements.adminDialog.close();
}

function toLocalInput(isoString) {
  if (!isoString) {
    return "";
  }
  const date = new Date(isoString);
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

function openScheduleForm(event = null) {
  elements.scheduleForm.reset();
  elements.scheduleError.textContent = "";
  elements.scheduleId.value = event?.id ?? "";
  elements.scheduleFormTitle.textContent = event ? "Edit event" : "New event";
  elements.scheduleTitle.value = event?.title ?? "";
  elements.scheduleDescription.value = event?.description ?? "";
  elements.scheduleStart.value = toLocalInput(event?.starts_at);
  elements.scheduleEnd.value = toLocalInput(event?.ends_at);
  elements.scheduleLocation.value = event?.location ?? "";
  elements.scheduleDialog.showModal();
}

async function saveScheduleEvent(event) {
  event.preventDefault();
  const eventId = elements.scheduleId.value;
  const body = {
    title: elements.scheduleTitle.value.trim(),
    description: elements.scheduleDescription.value.trim() || null,
    starts_at: new Date(elements.scheduleStart.value).toISOString(),
    ends_at: elements.scheduleEnd.value ? new Date(elements.scheduleEnd.value).toISOString() : null,
    location: elements.scheduleLocation.value.trim() || null,
  };
  elements.scheduleSubmit.disabled = true;
  elements.scheduleError.textContent = "";
  try {
    const response = await fetch(eventId ? `/api/schedule/${eventId}` : "/api/schedule", {
      method: eventId ? "PATCH" : "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
    });
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail?.[0]?.msg || payload.detail || "Schedule update failed");
    }
    applicationState.schedule.set(payload.id, payload);
    renderSchedule(sortedValues(applicationState.schedule));
    elements.scheduleDialog.close();
  } catch (error) {
    elements.scheduleError.textContent = error.message;
  } finally {
    elements.scheduleSubmit.disabled = false;
  }
}

async function deleteScheduleEvent(eventId) {
  const response = await fetch(`/api/schedule/${eventId}`, { method: "DELETE" });
  if (response.ok) {
    applicationState.schedule.delete(eventId);
    renderSchedule(sortedValues(applicationState.schedule));
  }
}

elements.identityButton.addEventListener("click", showIdentityDialog);
elements.identityForm.addEventListener("submit", saveIdentity);
elements.chatForm.addEventListener("submit", sendChat);
elements.uploadButton.addEventListener("click", () => elements.uploadDialog.showModal());
elements.uploadForm.addEventListener("submit", uploadMedia);
elements.scheduleAdminButton.addEventListener("click", () => {
  if (adminAuthenticated) {
    openScheduleForm();
  } else {
    showAdminDialog();
  }
});
elements.adminForm.addEventListener("submit", loginAdmin);
elements.adminLogout.addEventListener("click", logoutAdmin);
elements.scheduleForm.addEventListener("submit", saveScheduleEvent);
for (const closeButton of document.querySelectorAll("[data-close-dialog]")) {
  closeButton.addEventListener("click", () => {
    const dialog = document.querySelector(`#${closeButton.dataset.closeDialog}`);
    const video = dialog.querySelector("video");
    if (video) {
      video.pause();
      video.removeAttribute("src");
      video.load();
    }
    if (dialog === elements.lightbox) {
      activeMediaId = null;
    }
    dialog.close();
  });
}
elements.chatInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    elements.chatForm.requestSubmit();
  }
});
for (const button of elements.navButtons) {
  button.addEventListener("click", () => selectView(button.dataset.view));
}
window.addEventListener("online", synchronize);
window.addEventListener("offline", () => setConnection("offline", "offline"));

if (!readIdentity()) {
  showIdentityDialog();
}

const fairySocket = new window.FairySocket({
  onEvent: receiveEvent,
  onOpen: synchronize,
  onState: (state) => {
    const label = state === "online" ? "local · live" : state;
    setConnection(state, label);
  },
});
fairySocket.start();
window.setTimeout(() => {
  if (!hasBootstrapped) {
    synchronize();
  }
}, 750);
