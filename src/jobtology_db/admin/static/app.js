"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const state = { session: null, data: null, statusError: null, tab: "overview", request: null, timer: null, toastTimer: null, checkedAt: null, operation: null, operationKey: null, submitting: false, loggingOut: false };
  const numberFormatter = new Intl.NumberFormat("en-US");
  const dateFormatter = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Seoul", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });
  function element(tag, className, content) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (content !== undefined && content !== null) node.textContent = String(content);
    return node;
  }
  const array = (value) => Array.isArray(value) ? value : [];
  const numeric = (value) => typeof value === "number" && Number.isFinite(value) && value >= 0;
  const count = (value) => numeric(value) ? numberFormatter.format(value) : "Unavailable";
  const textValue = (value, fallback = "Unavailable") => value === null || value === undefined || value === "" ? fallback : String(value);
  function date(value) {
    if (!value) return "Not reported";
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? "Not reported" : dateFormatter.format(parsed) + " KST";
  }
  function timeAgo(value) {
    if (!value) return "Not reported";
    const delta = Math.max(0, Date.now() - new Date(value).getTime());
    if (!Number.isFinite(delta)) return "Not reported";
    if (delta < 60000) return "Just now";
    if (delta < 3600000) return Math.floor(delta / 60000) + "m ago";
    if (delta < 86400000) return Math.floor(delta / 3600000) + "h ago";
    return Math.floor(delta / 86400000) + "d ago";
  }
  function duration(value) {
    if (!numeric(value)) return "—";
    if (value < 60) return Math.round(value) + "s";
    const minutes = Math.floor(value / 60);
    return minutes < 60 ? minutes + "m " + Math.round(value % 60) + "s" : Math.floor(minutes / 60) + "h " + (minutes % 60) + "m";
  }
  function statusInfo(value) {
    if (value === null || value === undefined || value === "") return { className: "neutral", label: "Not reported" };
    const status = String(value || "unknown").toLowerCase();
    if (["healthy", "ready", "verified", "complete", "completed", "succeeded", "success", "done", "idle"].includes(status)) return { className: "", label: status === "healthy" ? "Connected" : status.replaceAll("_", " ") };
    if (["running", "queued", "pending", "starting", "processing", "active", "claimed", "loading", "fetching"].includes(status)) return { className: "active", label: status.replaceAll("_", " ") };
    if (["failed", "error", "unavailable", "rejected", "offline"].includes(status)) return { className: "danger", label: status.replaceAll("_", " ") };
    if (["stale", "partial", "warning", "blocked", "unfinished", "unknown"].includes(status)) return { className: "warning", label: status };
    return { className: "neutral", label: status === "not_configured" ? "Not configured" : status.replaceAll("_", " ") };
  }
  function badge(value) {
    const info = statusInfo(value);
    const node = element("span", "status " + info.className, info.label.charAt(0).toUpperCase() + info.label.slice(1));
    return node;
  }
  function empty(target, title, description) {
    const node = element("div", "empty-state");
    node.append(element("div", "", title));
    if (description) node.append(element("p", "", description));
    target.replaceChildren(node);
  }
  function notice(level, title, body) {
    const node = element("div", "notice " + (level === "error" ? "error" : level === "info" ? "info" : ""));
    const content = element("div");
    content.append(element("strong", "", title), element("p", "", body));
    node.append(content);
    return node;
  }
  function renderNotices(error) {
    if (arguments.length) state.statusError = error || null;
    error = state.statusError;
    const container = $("notice-region");
    container.replaceChildren();
    if (error) container.append(notice("error", "Status check unavailable.", error + (state.data ? " Showing the last received snapshot from " + date(state.data.generated_at) + "." : " Check the service connection and try again.")));
    if (state.data?.mode === "demo") container.append(notice("warning", "Demo workspace.", "All values are illustrative demo data. Operations are disabled; no production connection is implied."));
    const context = $("contextual-notices");
    context.replaceChildren();
    for (const item of array(state.data?.notices)) {
      if (state.data?.mode === "demo" && /demo/i.test(String(item.title || ""))) continue;
      if (item.level === "info") {
        if (state.tab === "graph" && item.title === "Evidence boundaries") continue;
        const paragraph = element("p");
        paragraph.append(element("strong", "", textValue(item.title, "Note") + ". "), document.createTextNode(textValue(item.body, "")));
        context.append(paragraph);
      } else container.append(notice(item.level, textValue(item.title, "Notice"), textValue(item.body, "")));
    }
  }
  async function api(path, options = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 40000);
    try {
      const headers = { Accept: "application/json", ...options.headers };
      if (options.body) headers["Content-Type"] = "application/json";
      const response = await fetch(path, { credentials: "same-origin", cache: "no-store", ...options, headers, signal: controller.signal });
      let payload = null;
      try { payload = await response.json(); } catch { /* An upstream error may be non-JSON. */ }
      if (!response.ok) {
        const error = new Error(response.status === 401 ? "Your session has expired. Sign in to continue." : response.status === 403 ? "The request was rejected. Check your session and try again." : typeof payload?.detail === "string" ? payload.detail : "The server could not complete this request (" + response.status + ").");
        error.status = response.status;
        throw error;
      }
      if (payload === null) throw new Error("The server returned an unexpected response.");
      return payload;
    } catch (error) {
      if (error.name === "AbortError") throw new Error("The service did not respond within 40 seconds.");
      if (error instanceof TypeError) throw new Error("Could not reach the admin service.");
      throw error;
    } finally { clearTimeout(timeout); }
  }
  function setLoginError(message) {
    $("login-error").textContent = message || "";
    $("login-error").hidden = !message;
  }
  function showLogin(message) {
    clearTimeout(state.timer);
    managementGeneration += 1;
    invitationSubmission = null; setInvitationPending(false); userEditing = null;
    $("created-invitation").replaceChildren(); $("created-invitation").hidden = true;
    managementTabs.forEach((name) => $(name + "-list").replaceChildren());
    ["invitation-dialog", "user-access-dialog"].forEach((name) => { if ($(name).open) $(name).close(); });
    state.session = null;
    state.data = null;
    state.statusError = null;
    if ($("confirmation-dialog").open) $("confirmation-dialog").close();
    $("app-view").hidden = true;
    $("boot").hidden = true;
    $("login-view").hidden = false;
    $("password").value = "";
    setLoginError(message);
    document.title = "Sign in · Jobtology Admin";
  }
  function setSession(session) {
    state.session = session;
    $("boot").hidden = true;
    $("login-view").hidden = true;
    $("app-view").hidden = false;
    const name = textValue(session.username, "Operator");
    $("user-name").textContent = name;
    setEnvironment(session.mode);
    document.title = "Overview · Jobtology Admin";
    renderLoading();
    refreshDashboard(false);
  }
  function setEnvironment(mode) {
    const target = $("environment-badge");
    target.textContent = mode === "demo" ? "Demo data" : mode === "live" ? "Live" : "Connecting";
  }
  function renderLoading() {
    $("metrics").replaceChildren(element("dt", "", "Loading…"));
    const row = element("tr");
    const cell = element("td");
    cell.colSpan = 4;
    cell.append(element("div", "loading-block"));
    row.append(cell);
    $("sources-body").replaceChildren(row);
    ["services-list"].forEach((id) => $(id).replaceChildren(element("div", "loading-block")));
    $("metrics").setAttribute("aria-busy", "true");
  }
  function scheduleRefresh() {
    clearTimeout(state.timer);
    if (!state.session || !$("auto-refresh").checked || document.hidden) return;
    const interval = numeric(state.data?.refresh_interval_seconds) ? Math.max(15, state.data.refresh_interval_seconds) : 30;
    $("refresh-period").textContent = interval + "s";
    state.timer = setTimeout(() => refreshDashboard(false), interval * 1000);
  }
  async function refreshDashboard(force = false) {
    if (state.request || !state.session || state.loggingOut) return;
    const refreshButton = $("refresh-button");
    refreshButton.disabled = true;
    refreshButton.classList.add("spinning");
    refreshButton.lastElementChild.textContent = "Checking…";
    const session = state.session;
    state.request = api("/api/dashboard" + (force ? "?refresh=true" : ""));
    try {
      const data = await state.request;
      if (state.session !== session || state.loggingOut) return;
      state.data = data;
      state.checkedAt = Date.now();
      renderDashboard();
      $("last-checked").textContent = "Checked just now";
    } catch (error) {
      if (state.session !== session || state.loggingOut) return;
      if (error.status === 401) { showLogin(error.message); return; }
      if (error.status === 403) {
        try {
          const current = await api("/api/session");
          if (!current.authenticated) { showLogin("Your session has expired. Sign in to continue."); return; }
          state.session = current;
        } catch { /* Keep the current screen with the explicit error. */ }
      }
      renderNotices(error.message);
      $("last-checked").textContent = "Status check failed";
      if (!state.data) renderUnavailable();
    } finally {
      state.request = null;
      refreshButton.disabled = false;
      refreshButton.classList.remove("spinning");
      refreshButton.lastElementChild.textContent = "Check status";
      scheduleRefresh();
    }
  }
  function renderUnavailable() {
    renderMetrics({});
    const row = element("tr");
    const cell = element("td", "empty-state", "Source status is unavailable.");
    cell.colSpan = 4; row.append(cell); $("sources-body").replaceChildren(row);
    ["services-list", "all-activity", "node-details", "relationship-details", "source-posting-details"].forEach((id) => empty($(id), "Data unavailable", "Run a status check to retry."));
    empty($("actions-list"), "Operations unavailable", "Configured profiles could not be loaded.");
    empty($("inference-list"), "Inference status unavailable");
    $("graph-status").replaceChildren(badge("unavailable"));
  }
  function renderDashboard() {
    const data = state.data;
    setEnvironment(data.mode);
    renderNotices(null);
    renderMetrics(data.summary || {});
    renderSources(array(data.sources));
    renderServices(array(data.services));
    renderCounts($("node-details"), data.graph?.node_counts, "label", "Label");
    renderCounts($("relationship-details"), data.graph?.relationship_counts, "type", "Type");
    const sourceNames = new Map(array(data.sources).map((source) => [source.id, source.name]));
    renderCounts($("source-posting-details"), array(data.graph?.postings_by_source).map((row) => ({ ...row, name: sourceNames.get(row.source_id) || row.source_id })), "name", "Source");
    renderFilters();
    renderActivity();
    renderActions(array(data.actions));
    renderInference(array(data.graph?.inference));
    const graphStatus = $("graph-status");
    graphStatus.replaceChildren(badge(data.graph?.status), element("span", "", "Knowledge graph connection"), element("span", "", "Checked " + date(data.graph?.checked_at)));
    $("data-timestamp").textContent = "Snapshot: " + date(data.generated_at);
    const active = data.summary?.active_runs;
    $("activity-badge").hidden = !numeric(active) || active === 0;
    $("activity-badge").textContent = count(active);
    $("activity-badge").title = "Unfinished imports reported by the ledger";
  }
  function renderMetrics(summary) {
    const metrics = [
      ["Source postings", summary.source_postings],
      ["Graph nodes", summary.total_nodes],
      ["Relationships", summary.total_relationships],
      ["Unfinished imports", summary.active_runs],
      ["Failed runs (24h)", summary.failed_runs_24h],
    ];
    $("metrics").replaceChildren(...metrics.flatMap(([label, value]) => [element("dt", "", label), element("dd", "", count(value))]));
    $("metrics").setAttribute("aria-busy", "false");
  }
  function renderSources(sources) {
    $("source-total").textContent = sources.length ? "(" + sources.length + ")" : "";
    $("source-total").title = sources.length + " sources shown";
    if (!sources.length) {
      const row = element("tr"); const cell = element("td", "empty-state", "No source status has been reported."); cell.colSpan = 4; row.append(cell); $("sources-body").replaceChildren(row); return;
    }
    $("sources-body").replaceChildren(...sources.map((source) => {
      const row = element("tr");
      const identityCell = element("td"); const identity = element("div", "source-identity");
      const name = element("div", "source-name", textValue(source.name, source.id));
      name.append(element("span", "source-mode", source.mode === "LOCAL_ONLY" ? "Local archive" : source.mode === "SCHEDULED" ? "Scheduled source" : textValue(source.mode, "Mode not reported")));
      identity.append(name); identityCell.append(identity);
      const records = element("td", "numeric", numeric(source.postings) ? count(source.postings) : count(source.records));
      records.append(element("span", "secondary-line", numeric(source.postings) ? "postings" : numeric(source.records) ? "records" : "count not reported"));
      if (numeric(source.postings) && numeric(source.records)) records.title = count(source.records) + " accepted records";
      const last = element("td", "", timeAgo(source.last_success_at)); last.title = date(source.last_success_at);
      last.append(element("span", "secondary-line", date(source.last_success_at)));
      const statusCell = element("td"); statusCell.append(badge(source.state));
      if (source.progress) statusCell.append(renderProgress(source.progress));
      if (source.graph_state) {
        const graphStatus = element("span", "secondary-line graph-state " + statusInfo(source.graph_state).className, "Graph: " + statusInfo(source.graph_state).label);
        statusCell.append(graphStatus);
      }
      if (source.next_due_at) {
        const due = element("span", "secondary-line", "Due estimate: " + date(source.next_due_at));
        due.title = "Interval estimate; dependencies, retries, graph state, and operation fences can affect scheduling.";
        statusCell.append(due);
      }
      row.append(identityCell, records, last, statusCell); return row;
    }));
    trackTableOverflow($("sources-body").closest(".table-scroll"));
  }
  function renderServices(services) {
    if (!services.length) { empty($("services-list"), "No service checks reported"); return; }
    $("services-list").replaceChildren(...services.map((service) => {
      const row = element("div", "service-row");
      const name = element("span", "service-name", textValue(service.label, service.id));
      const info = statusInfo(service.status);
      const value = element("span", "service-state " + info.className, info.label.charAt(0).toUpperCase() + info.label.slice(1));
      row.title = textValue(service.message, "") + (service.checked_at ? " · " + date(service.checked_at) : "");
      const identity = element("div"); identity.append(name);
      if (service.status !== "healthy") identity.append(element("p", "service-diagnostic", textValue(service.message, "")));
      row.append(identity, value); return row;
    }));
  }
  function renderCounts(target, rows, labelField, heading) {
    const items = array(rows).slice().sort((a, b) => (numeric(b.count) ? b.count : -1) - (numeric(a.count) ? a.count : -1));
    if (!items.length) { empty(target, "Counts unavailable", "Counts appear when the graph reports them."); return; }
    const scroll = element("div", "table-scroll");
    const table = element("table", "count-table");
    const head = element("thead"); const header = element("tr");
    header.append(element("th", "", heading), element("th", "", "Count")); head.append(header);
    const body = element("tbody");
    for (const item of items) {
      const row = element("tr"); row.append(element("td", "", textValue(item[labelField])), element("td", "", count(item.count))); body.append(row);
    }
    table.append(head, body); scroll.append(table); target.replaceChildren(scroll); trackTableOverflow(scroll);
  }
  function getRuns() {
    const runs = array(state.data?.runs).map((run) => ({ ...run, isJob: false }));
    const jobs = array(state.data?.jobs).map((job) => ({ ...job, isJob: true, operation: job.action_id, source_id: "admin", source_name: "Admin operation", message: job.summary, started_at: job.started_at || job.created_at, duration_seconds: job.started_at && job.finished_at ? Math.max(0, (new Date(job.finished_at) - new Date(job.started_at)) / 1000) : null }));
    return [...runs, ...jobs].sort((a, b) => (new Date(b.started_at).getTime() || 0) - (new Date(a.started_at).getTime() || 0));
  }
  function renderFilters() {
    const select = $("source-filter"); const selected = select.value;
    const sources = new Map(getRuns().map((run) => [textValue(run.source_id, "unknown"), textValue(run.source_name, run.source_id)]));
    select.replaceChildren(new Option("All sources", "all"), ...Array.from(sources, ([id, name]) => new Option(name, id)));
    select.value = sources.has(selected) ? selected : "all";
  }
  function renderProgress(progress) {
    const node = element("div", "run-progress");
    let percent = numeric(progress.percent) ? Math.min(100, progress.percent) : numeric(progress.completed) && numeric(progress.total) && progress.total > 0 ? Math.min(100, progress.completed / progress.total * 100) : null;
    if (percent !== null) {
      const track = element("div", "progress-track"); const fill = element("span"); fill.style.width = percent + "%"; track.append(fill);
      track.setAttribute("role", "progressbar"); track.setAttribute("aria-valuemin", "0"); track.setAttribute("aria-valuemax", "100"); track.setAttribute("aria-valuenow", String(Math.round(percent))); track.setAttribute("aria-label", "Reported execution progress");
      node.append(track, element("span", "", Math.round(percent) + "%"));
    } else node.append(element("span", "", "Progress not reported"));
    if (numeric(progress.completed)) node.title = count(progress.completed) + (numeric(progress.total) ? " / " + count(progress.total) : "") + " " + textValue(progress.unit, "records");
    return node;
  }
  function activityTable(runs, target) {
    if (!runs.length) { empty(target, "No executions to show", "Reported runs and admin operations will appear here."); return; }
    const scroll = element("div", "table-scroll"); const table = element("table", "activity-table");
    const head = element("thead"); const headRow = element("tr"); ["Operation / source", "Started", "Duration", "Records", "Status"].forEach((name) => headRow.append(element("th", "", name))); head.append(headRow);
    const body = element("tbody");
    for (const run of runs) {
      const row = element("tr");
      const identity = element("td");
      const operation = element("div", "run-operation", textValue(run.operation, "Ingestion")); operation.title = textValue(run.message, textValue(run.operation));
      identity.append(operation, element("span", "secondary-line", textValue(run.source_name, run.source_id)));
      const id = element("span", "run-id secondary-line", textValue(run.id, "")); id.title = textValue(run.id, ""); identity.append(id);
      const started = element("td", "", timeAgo(run.started_at)); started.title = date(run.started_at); started.append(element("span", "secondary-line", date(run.started_at)));
      const runStatus = element("td"); runStatus.append(badge(run.state)); if (run.progress) runStatus.append(renderProgress(run.progress));
      row.append(identity, started, element("td", "numeric", duration(run.duration_seconds)), element("td", "numeric", count(run.records)), runStatus); body.append(row);
    }
    table.append(head, body); scroll.append(table); target.replaceChildren(scroll);
    trackTableOverflow(scroll);
  }
  function renderActivity() {
    const runs = getRuns();
    const source = $("source-filter").value; const filter = $("state-filter").value;
    activityTable(runs.filter((run) => {
      if (source !== "all" && textValue(run.source_id, "unknown") !== source) return false;
      if (filter === "all") return true;
      const className = statusInfo(run.state).className;
      return filter === "active" ? className === "active" : filter === "failed" ? className === "danger" : className === "";
    }), $("all-activity"));
  }
  function renderActions(actions) {
    if (!actions.length) { empty($("actions-list"), "No operation profiles configured", "Operations become available when the server has an allowed profile."); return; }
    $("actions-list").replaceChildren(...actions.map((action) => {
      const card = element("article", "action-card");
      const button = element("button", "button secondary", "Review & run");
      const enabled = action.enabled === true && state.data?.mode === "live" && typeof action.id === "string" && !!action.id;
      button.disabled = !enabled;
      button.addEventListener("click", () => openOperation(action));
      card.append(element("h3", "", textValue(action.label, action.id)), element("p", "", textValue(action.description, "Run this configured operation.")), element("code", "action-profile", textValue(action.id)), button);
      if (!enabled) card.append(element("div", "disabled-reason", state.data?.mode === "demo" ? "Operations are disabled in demo mode." : textValue(action.disabled_reason, "This operation is not enabled.")));
      return card;
    }));
  }
  function renderInference(inference) {
    if (!inference.length) { empty($("inference-list"), "No inference counts reported", "Reference catalogue data and inferred posting matches are separate."); return; }
    $("inference-list").replaceChildren(...inference.map((row) => {
      const card = element("article", "inference-card");
      const names = { INFERRED_NCS_OCCUPATION: "NCS occupations", INFERRED_ONET_OCCUPATION: "O*NET occupations" };
      const heading = element("div", "inference-title");
      const title = element("h3", "", names[row.kind] || textValue(row.kind, "Inferred occupation")); title.title = textValue(row.kind);
      heading.append(title, element("span", "status neutral", "Inferred metadata"));
      const stats = element("div", "inference-stats");
      for (const [label, value] of [["Total matches", row.total], ["Individually reviewed", row.reviewed], ["Unreviewed", row.unreviewed]]) {
        const stat = element("div", "inference-stat"); stat.append(element("strong", "", count(value)), element("span", "", label)); stats.append(stat);
      }
      card.append(heading, stats, element("p", "", "Confidence: " + textValue(row.confidence, "UNASSESSED") + " · Review status is preserved for each match.")); return card;
    }));
  }
  const managementTabs = ["invitations", "users", "sessions"];
  const allTabs = ["overview", "activity", "graph", ...managementTabs];
  const management = { invitations: {offset: 0, total: 0}, users: {offset: 0, total: 0}, sessions: {offset: 0, total: 0} };
  let invitationEditing = null;
  let invitationSubmission = null;
  let userEditing = null;
  let managementGeneration = 0;
  const localDateInput = (value) => {
    if (!value) return "";
    const parsed = new Date(value);
    if (!Number.isFinite(parsed.getTime())) return "";
    return new Date(parsed.getTime() - parsed.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  };
  function managementError(name, message) {
    const target = $(name + "-error"); target.hidden = !message; target.textContent = message || "";
  }
  async function loadManagement(name) {
    if (!state.session || state.loggingOut || !managementTabs.includes(name)) return;
    const current = management[name]; const generation = managementGeneration;
    const requestNumber = current.request = (current.request || 0) + 1;
    managementError(name, "");
    empty($(name + "-list"), "Loading…");
    const params = new URLSearchParams({limit: "50", offset: String(current.offset)});
    const userId = $("session-user-filter").value.trim();
    if (name === "sessions" && userId) params.set("user_id", userId);
    try {
      const result = await api("/api/application/" + name + "?" + params);
      if (!state.session || generation !== managementGeneration || current.request !== requestNumber) return;
      current.total = result.total;
      renderManagement(name, array(result.items));
      $(name + "-page").textContent = result.total ? (current.offset + 1) + "–" + Math.min(current.offset + 50, result.total) + " of " + result.total : "0 results";
      document.querySelectorAll('[data-page="' + name + '"]').forEach((button) => { button.disabled = button.dataset.direction === "-1" ? current.offset === 0 : current.offset + 50 >= result.total; });
    } catch (error) {
      if (generation !== managementGeneration || !state.session || current.request !== requestNumber) return;
      if (error.status === 401) { showLogin(error.message); return; }
      managementError(name, error.message); empty($(name + "-list"), "Application management unavailable", "Check configuration or refresh to retry.");
    }
  }
  async function managementWrite(name, suffix, method, body, button) {
    const activeSession = state.session;
    if (!activeSession || state.loggingOut || button.disabled) return;
    button.disabled = true;
    try {
      await api("/api/application/" + name + "/" + suffix, {method, headers: {"X-CSRF-Token": activeSession.csrf_token}, ...(body ? {body: JSON.stringify(body)} : {})});
      if (state.session !== activeSession || state.loggingOut) return;
      toast("Change saved."); await loadManagement(name);
    } catch (error) {
      if (state.session !== activeSession || state.loggingOut) return;
      if (error.status === 401) showLogin(error.message); else managementError(name, error.message);
    } finally { button.disabled = false; }
  }
  function managementButton(label, callback) {
    const button = element("button", "button secondary", label); button.addEventListener("click", () => callback(button)); return button;
  }
  function expiryInstant(value) {
    if (typeof value !== "string") return NaN;
    const parts = value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/);
    if (!parts || Number(parts[4]) > 23 || Number(parts[5]) > 59 || Number(parts[6]) > 59) return NaN;
    const calendar = new Date(value.slice(0, 10) + "T00:00:00Z");
    if (calendar.getUTCFullYear() !== Number(parts[1]) || calendar.getUTCMonth() + 1 !== Number(parts[2]) || calendar.getUTCDate() !== Number(parts[3])) return NaN;
    return new Date(value).getTime();
  }
  function accessExpiry(value, hasAdmission) {
    if (!hasAdmission) return "No admission";
    if (value === null) return "Unlimited";
    if (typeof value !== "string" || !value.trim()) return "Unavailable";
    const expires = expiryInstant(value);
    if (!Number.isFinite(expires)) return "Unavailable";
    return (expires <= Date.now() ? "Expired · " : "") + date(value);
  }
  function sessionStatus(row) {
    if (row.revoked_at !== null) {
      if (typeof row.revoked_at !== "string" || !row.revoked_at.trim()) return "Unavailable";
      return Number.isFinite(expiryInstant(row.revoked_at)) ? "Revoked · " + date(row.revoked_at) : "Revocation time unavailable";
    }
    if (typeof row.expires_at !== "string" || !row.expires_at.trim()) return "Unavailable";
    const expires = expiryInstant(row.expires_at);
    if (!Number.isFinite(expires)) return "Unavailable";
    return expires <= Date.now() ? "Expired" : "Active";
  }
  function renderManagement(name, rows) {
    if (!rows.length) { empty($(name + "-list"), "No " + name + " found"); return; }
    const columns = name === "invitations" ? ["Label / code hint", "Redemptions", "Code expiry", "Access duration", "Actions"] : name === "users" ? ["User", "Status / access", "Access expiry", "Sessions", "Actions"] : ["User / session", "Created", "Expires", "Status", "Actions"];
    const scroll = element("div", "table-scroll"); const table = element("table", "management-table"); const head = element("thead"); const tr = element("tr"); columns.forEach((column) => tr.append(element("th", "", column))); head.append(tr); const tbody = element("tbody");
    for (const row of rows) {
      const tr = element("tr"); const actions = element("td", "management-row-actions");
      const values = name === "invitations" ? [row.label + " · " + textValue(row.code_hint, ""), count(row.use_count) + " / " + (row.max_uses === null ? "Unlimited" : count(row.max_uses)), row.expires_at ? date(row.expires_at) : "No expiry", row.access_hours === null ? "Unlimited" : row.access_hours + " hours"] : name === "users" ? [textValue(row.display_name, row.id), textValue(row.status) + " · " + textValue(row.access_source) + (row.invitation_label ? " · " + row.invitation_label : ""), accessExpiry(row.access_expires_at, ["LEGACY", "INVITATION"].includes(row.access_source)), count(row.active_sessions)] : [textValue(row.display_name, row.user_id) + " · " + row.id, date(row.created_at), date(row.expires_at), sessionStatus(row)];
      values.forEach((value, index) => { const cell = element("td", "", value); if (index === 0) cell.append(element("span", "secondary-line", name === "sessions" ? row.user_id : row.id)); tr.append(cell); });
      if (name === "invitations") {
        if (row.revoked_at) actions.append(badge("revoked"));
        else actions.append(managementButton("Edit", () => openInvitation(row)), managementButton("Revoke code", (button) => { if (confirm("Revoke this invitation? Admitted users keep their access.")) managementWrite(name, row.id + "/revoke", "POST", null, button); }));
      } else if (name === "users") {
        actions.append(managementButton(row.status === "ACTIVE" ? "Suspend" : "Restore", (button) => { if (confirm("Change access for " + textValue(row.display_name, row.id) + "?")) managementWrite(name, row.id, "PATCH", {status: row.status === "ACTIVE" ? "DEACTIVATED" : "ACTIVE"}, button); }), managementButton("Edit expiry", () => openUserExpiry(row)), managementButton("Revoke sessions", (button) => { if (confirm("Revoke all sessions for this user?")) managementWrite(name, row.id + "/revoke-sessions", "POST", null, button); }));
      } else if (!row.revoked_at) actions.append(managementButton("Revoke session", (button) => { if (confirm("Revoke this session?")) managementWrite(name, row.id + "/revoke", "POST", null, button); }));
      tr.append(actions); tbody.append(tr);
    }
    table.append(head, tbody); scroll.append(table); $(name + "-list").replaceChildren(scroll); trackTableOverflow(scroll);
  }
  function openUserExpiry(row) {
    userEditing = {id: row.id, submission: null};
    const form = $("user-access-form"); form.reset();
    form.querySelector('[type="submit"]').disabled = false;
    const explicitlyUnlimited = row.access_expires_at === null;
    const knownExpiry = Number.isFinite(expiryInstant(row.access_expires_at));
    form.elements.access_expires_at.value = knownExpiry ? localDateInput(row.access_expires_at) : "";
    form.elements.unlimited.checked = explicitlyUnlimited;
    $("user-access-current").textContent = explicitlyUnlimited ? "Current access: Unlimited." : knownExpiry ? "Current access expires " + date(row.access_expires_at) + "." : "Current expiry is unavailable. Choose a date or explicitly select unlimited access.";
    syncUserExpiryFields();
    $("user-access-error").hidden = true; $("user-access-dialog").showModal();
  }
  function syncUserExpiryFields() {
    const fields = $("user-access-form").elements;
    fields.access_expires_at.disabled = fields.unlimited.checked;
    fields.access_expires_at.required = !fields.unlimited.checked;
  }
  $("user-access-form").elements.unlimited.addEventListener("change", syncUserExpiryFields);
  function setInvitationPending(pending) {
    const form = $("invitation-form"); form.setAttribute("aria-busy", String(pending));
    form.querySelectorAll("input,select,button").forEach((control) => { control.disabled = pending; });
  }
  function openInvitation(row = null) {
    if (invitationSubmission) return;
    if (!row && !$("created-invitation").hidden) {
      toast("Save or dismiss the displayed invitation before creating another.");
      $("created-invitation").scrollIntoView({block: "nearest"}); return;
    }
    invitationEditing = row?.id || null; const form = $("invitation-form"); form.reset();
    form.elements.label.value = row?.label || ""; form.elements.expires_at.value = localDateInput(row?.expires_at);
    form.elements.access_hours.value = row?.access_hours ?? "";
    form.elements.usage.value = row ? row.max_uses === null ? "unlimited" : row.max_uses === 1 ? "single" : "multi" : "single";
    form.elements.max_uses.value = row?.max_uses > 1 ? row.max_uses : 10;
    $("max-uses-field").hidden = form.elements.usage.value !== "multi";
    $("invitation-dialog-title").textContent = row ? "Edit invitation" : "Create invitation";
    $("invitation-form-error").hidden = true; $("invitation-dialog").showModal();
  }
  $("create-invitation").addEventListener("click", () => openInvitation());
  $("invitation-form").elements.usage.addEventListener("change", (event) => { $("max-uses-field").hidden = event.target.value !== "multi"; });
  $("invitation-form").addEventListener("submit", async (event) => {
    event.preventDefault(); const form = event.target; const button = form.querySelector('[type="submit"]'); if (button.disabled || !state.session) return;
    const fields = form.elements; const body = {label: fields.label.value.trim(), expires_at: fields.expires_at.value ? new Date(fields.expires_at.value).toISOString() : null, access_hours: fields.access_hours.value ? Number(fields.access_hours.value) : null, max_uses: fields.usage.value === "single" ? 1 : fields.usage.value === "unlimited" ? null : Number(fields.max_uses.value)};
    const activeSession = state.session;
    if (invitationSubmission || state.loggingOut) return;
    const submission = {editingId: invitationEditing, session: activeSession, handled: false};
    invitationSubmission = submission;
    setInvitationPending(true); $("invitation-form-error").hidden = true;
    try {
      const result = await api("/api/application/invitations" + (submission.editingId ? "/" + submission.editingId : ""), {method: submission.editingId ? "PATCH" : "POST", headers: {"X-CSRF-Token": activeSession.csrf_token}, body: JSON.stringify(body)});
      if (state.session !== activeSession || state.loggingOut) return;
      if (!submission.editingId) {
        const target = $("created-invitation"); const image = element("img", "invitation-qr"); image.alt = "Invitation QR code"; image.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(result.qr_svg);
        const link = element("a", "button secondary", "Download QR"); link.href = image.src; link.download = "jobtology-invitation.svg";
        const copy = (label, value) => managementButton(label, async () => { try { await navigator.clipboard.writeText(value); toast("Copied."); } catch { toast("Copy failed. Select and copy the displayed value."); } });
        const actions = element("div", "invitation-actions");
        actions.append(copy("Copy code", result.code), copy("Copy link", result.invite_url), link, managementButton("Dismiss code", () => { target.replaceChildren(); target.hidden = true; }));
        target.replaceChildren(
          element("h2", "", "Invitation created"),
          element("p", "", "Save now. The code is shown only once."),
          element("strong", "", "Code"), element("code", "invitation-secret", result.code),
          element("strong", "", "Signup link"), element("p", "invitation-secret", result.invite_url),
          element("p", "", "Share the link or scan the QR, then sign in with Google."),
          image, actions
        );
        target.hidden = false;
      }
      submission.handled = true;
      $("invitation-dialog").close();
      if (!submission.editingId) $("created-invitation").focus();
      await loadManagement("invitations");
    } catch (error) { if (state.session !== activeSession || state.loggingOut) return; if (error.status === 401) showLogin(error.message); else { $("invitation-form-error").textContent = error.message; $("invitation-form-error").hidden = false; } }
    finally {
      if (invitationSubmission === submission) { invitationSubmission = null; setInvitationPending(false); }
    }
  });
  $("invitation-dialog").addEventListener("cancel", (event) => { if (invitationSubmission) event.preventDefault(); });
  $("invitation-dialog").addEventListener("close", () => {
    const pending = invitationSubmission;
    if (pending && !pending.handled && state.session === pending.session && !state.loggingOut && !$("invitation-dialog").open) $("invitation-dialog").showModal();
  });
  $("user-access-form").addEventListener("submit", async (event) => {
    event.preventDefault(); const button = event.target.querySelector('[type="submit"]');
    if (button.disabled || !state.session || state.loggingOut || !userEditing || !$("user-access-dialog").open) return;
    const fields = event.target.elements;
    const input = fields.access_expires_at.value;
    const unlimited = fields.unlimited.checked;
    if (!unlimited && (!input || !Number.isFinite(new Date(input).getTime()))) {
      $("user-access-error").textContent = "Choose an expiry date or explicitly select unlimited access.";
      $("user-access-error").hidden = false; button.disabled = false; return;
    }
    const activeSession = state.session;
    // Reopening even the same user's dialog creates a different editing identity.
    const editing = userEditing; const submission = {};
    editing.submission = submission; button.disabled = true;
    const ownsDialog = () => state.session === activeSession && userEditing === editing && editing.submission === submission;
    const canApply = () => ownsDialog() && !state.loggingOut && $("user-access-dialog").open;
    try { await api("/api/application/users/" + editing.id, {method: "PATCH", headers: {"X-CSRF-Token": activeSession.csrf_token}, body: JSON.stringify({access_expires_at: unlimited ? null : new Date(input).toISOString()})}); if (!canApply()) return; $("user-access-dialog").close(); await loadManagement("users"); }
    catch (error) { if (!canApply()) return; if (error.status === 401) showLogin(error.message); else { $("user-access-error").textContent = error.message; $("user-access-error").hidden = false; } }
    finally { if (ownsDialog()) { editing.submission = null; button.disabled = false; } }
  });
  document.querySelectorAll("[data-close-dialog]").forEach((button) => button.addEventListener("click", () => { if (button.dataset.closeDialog === "invitation-dialog" && invitationSubmission) return; $(button.dataset.closeDialog).close(); }));
  document.querySelectorAll("[data-reload]").forEach((button) => button.addEventListener("click", () => loadManagement(button.dataset.reload)));
  document.querySelectorAll("[data-page]").forEach((button) => button.addEventListener("click", () => { const name = button.dataset.page; management[name].offset = Math.max(0, management[name].offset + Number(button.dataset.direction) * 50); loadManagement(name); }));
  $("filter-sessions").addEventListener("click", () => { management.sessions.offset = 0; loadManagement("sessions"); });
  function selectTab(tab) {
    if (!allTabs.includes(tab)) return;
    state.tab = tab;
    const titles = {
      overview: ["Overview", "Source ingestion and system health."],
      activity: ["Activity", "Reported runs and configured operations."],
      graph: ["Graph", "Graph counts, source coverage and inferred matches."],
      invitations: ["Invitations", "Create an invitation to get a signup link and QR."],
      users: ["Users", "Manage account status, access expiry and sessions."],
      sessions: ["Sessions", "View session metadata and revoke sessions."],
    };
    const [title, description] = titles[tab];
    $("page-title").textContent = title;
    $("page-description").textContent = description;
    $("status-controls").hidden = managementTabs.includes(tab);
    $("status-footer").hidden = managementTabs.includes(tab);
    document.title = title + " · Jobtology Admin";
    for (const name of allTabs) {
      $("panel-" + name).hidden = name !== tab;
      const tabButton = $("tab-" + name); tabButton.setAttribute("aria-selected", String(name === tab)); tabButton.tabIndex = name === tab ? 0 : -1;
    }
    renderNotices();
    if (managementTabs.includes(tab)) loadManagement(tab);
    requestAnimationFrame(updateTableCues);
  }
  const tableCues = new Map();
  function updateTableCues() {
    for (const [scroll, cue] of tableCues) {
      if (!scroll.isConnected) { tableObserver?.unobserve(scroll); tableCues.delete(scroll); continue; }
      cue.hidden = scroll.clientWidth === 0 || scroll.scrollWidth <= scroll.clientWidth + 1;
    }
  }
  const tableObserver = typeof ResizeObserver === "function" ? new ResizeObserver(updateTableCues) : null;
  function trackTableOverflow(scroll) {
    if (!tableCues.has(scroll)) {
      const cue = element("div", "table-scroll-hint", "Swipe to see more →");
      cue.hidden = true;
      scroll.after(cue);
      tableCues.set(scroll, cue);
      tableObserver?.observe(scroll);
    }
    requestAnimationFrame(updateTableCues);
  }
  window.addEventListener("resize", updateTableCues);
  function newIdempotencyKey() {
    if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
  }
  function openOperation(action) {
    if (state.data?.mode !== "live" || !action.enabled || state.submitting) return;
    state.operation = action;
    state.operationKey = newIdempotencyKey();
    $("confirmation-title").textContent = textValue(action.label, action.id);
    $("confirmation-description").textContent = textValue(action.description, "Submit this configured operation?");
    $("confirmation-profile").textContent = action.id;
    $("operation-error").hidden = true;
    $("confirmation-dialog").showModal();
    $("cancel-operation").focus();
  }
  function toast(message) {
    clearTimeout(state.toastTimer); $("toast").textContent = message; $("toast").hidden = false;
    state.toastTimer = setTimeout(() => { $("toast").hidden = true; }, 7000);
  }
  async function submitOperation() {
    const action = state.operation;
    if (!action || state.submitting || !state.session || state.data?.mode !== "live") return;
    state.submitting = true;
    const button = $("confirm-operation"); button.disabled = true; button.textContent = "Submitting…";
    $("cancel-operation").disabled = true; $("operation-error").hidden = true;
    try {
      const result = await api("/api/jobs", { method: "POST", headers: { "X-CSRF-Token": state.session.csrf_token }, body: JSON.stringify({ action_id: action.id, idempotency_key: state.operationKey }) });
      $("confirmation-dialog").close();
      toast("Operation submitted · " + textValue(result.job?.id, action.label));
      selectTab("activity");
      refreshDashboard(true);
    } catch (error) {
      if (error.status === 401) { showLogin(error.message); return; }
      $("operation-error").textContent = error.message;
      $("operation-error").hidden = false;
      if (error.status === 403) {
        try {
          const session = await api("/api/session");
          if (!session.authenticated) showLogin("Your session has expired. Sign in to continue.");
          else state.session = session;
        } catch { /* Keep the explicit operation error visible. */ }
      }
    } finally {
      state.submitting = false; button.disabled = false; button.textContent = "Run operation"; $("cancel-operation").disabled = false;
    }
  }
  $("login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = $("login-submit"); if (button.disabled) return;
    button.disabled = true; button.textContent = "Signing in…"; setLoginError("");
    try {
      const session = await api("/api/login", { method: "POST", body: JSON.stringify({ username: $("username").value.trim(), password: $("password").value }) });
      $("password").value = "";
      if (session.authenticated) { selectTab("overview"); setSession(session); }
      else setLoginError("Sign-in did not establish an authenticated session.");
    } catch (error) {
      setLoginError(error.status === 401 ? "The username or password is incorrect." : error.message);
    } finally { button.disabled = false; button.textContent = "Sign in"; }
  });
  $("refresh-button").addEventListener("click", () => refreshDashboard(true));
  $("auto-refresh").addEventListener("change", scheduleRefresh);
  $("source-filter").addEventListener("change", renderActivity);
  $("state-filter").addEventListener("change", renderActivity);
  $("confirm-operation").addEventListener("click", submitOperation);
  $("confirmation-dialog").addEventListener("cancel", (event) => { if (state.submitting) event.preventDefault(); });
  $("confirmation-dialog").addEventListener("close", () => { state.operation = null; state.operationKey = null; });
  document.addEventListener("click", (event) => {
    const tab = event.target.closest("[data-tab]"); if (tab) selectTab(tab.dataset.tab);
  });
  document.querySelector(".view-tabs").addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault(); const tabs = allTabs; const index = tabs.indexOf(state.tab);
    const target = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : (index + (event.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length;
    selectTab(tabs[target]); $("tab-" + tabs[target]).focus();
  });
  $("logout-button").addEventListener("click", async () => {
    if (!state.session || state.loggingOut) return;
    state.loggingOut = true; $("logout-button").disabled = true; clearTimeout(state.timer);
    try { await api("/api/logout", { method: "POST", headers: { "X-CSRF-Token": state.session.csrf_token } }); showLogin(); }
    catch (error) {
      if (error.status === 401) showLogin();
      else if (error.status === 403) {
        try {
          const current = await api("/api/session");
          if (current.authenticated) {
            state.session = current;
            await api("/api/logout", { method: "POST", headers: { "X-CSRF-Token": current.csrf_token } });
          }
          showLogin();
        } catch (retryError) { toast("Sign out failed. " + retryError.message); }
      } else toast("Sign out failed. " + error.message);
    }
    finally { state.loggingOut = false; $("logout-button").disabled = false; scheduleRefresh(); }
  });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) clearTimeout(state.timer);
    else if (state.session && $("auto-refresh").checked && (!state.checkedAt || Date.now() - state.checkedAt > 30000)) refreshDashboard(false);
    else scheduleRefresh();
  });
  async function start() {
    try { const session = await api("/api/session"); if (session.authenticated) setSession(session); else showLogin(); }
    catch (error) { showLogin(error.message); }
  }
  start();
})();
