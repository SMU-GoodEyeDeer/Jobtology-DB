"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const state = { session: null, data: null, statusError: null, tab: "overview", request: null, timer: null, toastTimer: null, checkedAt: null, operation: null, operationKey: null, submitting: false, loggingOut: false };
  const numberFormatter = new Intl.NumberFormat("en-US");
  const dateFormatter = new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Seoul", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false });
  const icons = {
    overview: ["M3 3h7v7H3z", "M14 3h7v7h-7z", "M3 14h7v7H3z", "M14 14h7v7h-7z"],
    activity: ["M3 12h4l3-8 4 16 3-8h4"],
    graph: ["M9 6l6 3M8 8l-1 8M10 18l7-6", "M8 5a3 3 0 1 1-6 0 3 3 0 0 1 6 0", "M22 10a3 3 0 1 1-6 0 3 3 0 0 1 6 0", "M10 19a3 3 0 1 1-6 0 3 3 0 0 1 6 0"],
    layers: ["M12 3l10 5-10 5L2 8z", "M2 12l10 5 10-5M2 16l10 5 10-5"],
    refresh: ["M20 7v5h-5", "M19 12a7 7 0 1 0-2 5M20 12l-3-6"],
    menu: ["M4 6h16M4 12h16M4 18h16"],
    pulse: ["M3 12h4l3-7 4 14 3-7h4"],
    shield: ["M12 3l8 3v6c0 5-8 9-8 9s-8-4-8-9V6z", "M8 12l3 3 5-6"],
    connections: ["M8 6h8M8 18h8M5 9v6M19 9v6", "M8 6a3 3 0 1 1-6 0 3 3 0 0 1 6 0", "M22 6a3 3 0 1 1-6 0 3 3 0 0 1 6 0", "M8 18a3 3 0 1 1-6 0 3 3 0 0 1 6 0", "M22 18a3 3 0 1 1-6 0 3 3 0 0 1 6 0"],
    database: ["M3 6c0-5 18-5 18 0s-18 5-18 0", "M3 6v12c0 5 18 5 18 0V6", "M3 12c0 5 18 5 18 0"],
    briefcase: ["M8 7V4h8v3", "M3 7h18v13H3z", "M3 12c6 3 12 3 18 0M10 13v3h4v-3"],
    alert: ["M12 3L2 21h20z", "M12 9v5M12 17v.2"],
    clock: ["M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0", "M12 6v6l4 2"],
  };
  function element(tag, className, content) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (content !== undefined && content !== null) node.textContent = String(content);
    return node;
  }
  function icon(name) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("aria-hidden", "true");
    for (const d of icons[name] || icons.database) {
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", d);
      svg.append(path);
    }
    return svg;
  }
  document.querySelectorAll("[data-icon]").forEach((node) => node.replaceChildren(icon(node.dataset.icon)));
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
    node.append(icon("layers"), element("div", "", title));
    if (description) node.append(element("p", "", description));
    target.replaceChildren(node);
  }
  function notice(level, title, body) {
    const node = element("div", "notice " + (level === "error" ? "error" : level === "info" ? "info" : ""));
    const content = element("div");
    content.append(element("strong", "", title), element("p", "", body));
    node.append(icon(level === "info" ? "shield" : "alert"), content);
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
    $("user-avatar").textContent = name.slice(0, 1).toUpperCase();
    $("user-menu").hidden = true;
    setEnvironment(session.mode);
    document.title = "Overview · Jobtology Admin";
    renderLoading();
    refreshDashboard(false);
  }
  function setEnvironment(mode) {
    const target = $("environment-badge");
    target.classList.toggle("demo", mode === "demo");
    target.replaceChildren(element("span"), document.createTextNode(mode === "demo" ? "DEMO DATA" : mode === "live" ? "LIVE WORKSPACE" : "CONNECTING"));
  }
  function renderLoading() {
    $("metrics").replaceChildren(...Array.from({ length: 4 }, () => element("div", "loading-block")));
    const row = element("tr");
    const cell = element("td");
    cell.colSpan = 4;
    cell.append(element("div", "loading-block"));
    row.append(cell);
    $("sources-body").replaceChildren(row);
    ["services-list", "node-preview", "relationship-preview", "recent-activity"].forEach((id) => $(id).replaceChildren(element("div", "loading-block")));
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
    $("refresh-indicator").classList.add("busy");
    const session = state.session;
    state.request = api("/api/dashboard" + (force ? "?refresh=true" : ""));
    try {
      const data = await state.request;
      if (state.session !== session || state.loggingOut) return;
      state.data = data;
      state.checkedAt = Date.now();
      renderDashboard();
      $("refresh-indicator").classList.remove("offline");
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
      $("refresh-indicator").classList.add("offline");
      $("last-checked").textContent = "Status check failed";
      if (!state.data) renderUnavailable();
    } finally {
      state.request = null;
      refreshButton.disabled = false;
      refreshButton.classList.remove("spinning");
      refreshButton.lastElementChild.textContent = "Check status";
      $("refresh-indicator").classList.remove("busy");
      scheduleRefresh();
    }
  }
  function renderUnavailable() {
    renderMetrics({});
    const row = element("tr");
    const cell = element("td", "empty-state", "Source status is unavailable.");
    cell.colSpan = 4; row.append(cell); $("sources-body").replaceChildren(row);
    ["services-list", "node-preview", "relationship-preview", "recent-activity", "all-activity", "node-details", "relationship-details", "source-posting-details"].forEach((id) => empty($(id), "Data unavailable", "Run a status check to retry."));
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
    renderBars($("node-preview"), data.graph?.node_counts, "label", 4);
    renderBars($("relationship-preview"), data.graph?.relationship_counts, "type", 4, true);
    renderBars($("node-details"), data.graph?.node_counts, "label", null);
    renderBars($("relationship-details"), data.graph?.relationship_counts, "type", null, true);
    const sourceNames = new Map(array(data.sources).map((source) => [source.id, source.name]));
    renderBars($("source-posting-details"), array(data.graph?.postings_by_source).map((row) => ({ ...row, name: sourceNames.get(row.source_id) || row.source_id })), "name", null);
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
    const failed = numeric(summary.failed_runs_24h) ? count(summary.failed_runs_24h) + " failed runs in the past 24h" : "Run health not reported";
    const metrics = [
      ["Source postings", summary.source_postings, "briefcase", "Unique postings across source datasets"],
      ["Graph nodes", summary.total_nodes, "graph", "All nodes in the connected graph"],
      ["Relationships", summary.total_relationships, "connections", "All graph relationship types"],
      ["Unfinished imports", summary.active_runs, "activity", failed],
    ];
    $("metrics").replaceChildren(...metrics.map(([label, value, iconName, note]) => {
      const card = element("article", "metric");
      const heading = element("div", "metric-label", label); heading.append(icon(iconName));
      const valueNode = element("div", "metric-value" + (numeric(value) ? "" : " unavailable"), count(value));
      if (!numeric(value)) valueNode.style.fontSize = "20px";
      const foot = element("div", "metric-note");
      foot.append(document.createTextNode(note));
      card.append(heading, valueNode, foot);
      return card;
    }));
    $("metrics").setAttribute("aria-busy", "false");
    $("source-total").textContent = numeric(summary.configured_sources) ? summary.configured_sources : "";
  }
  function renderSources(sources) {
    $("source-total").textContent = sources.length ? String(sources.length) : "";
    $("source-total").title = sources.length + " sources shown";
    if (!sources.length) {
      const row = element("tr"); const cell = element("td", "empty-state", "No source status has been reported."); cell.colSpan = 4; row.append(cell); $("sources-body").replaceChildren(row); return;
    }
    $("sources-body").replaceChildren(...sources.map((source) => {
      const row = element("tr");
      const identityCell = element("td"); const identity = element("div", "source-identity");
      const id = String(source.id || "").toLowerCase();
      const sourceClass = id.includes("korea") ? "jobkorea" : id.includes("nara") ? "nara" : id.includes("alio") ? "alio" : "";
      const monogram = sourceClass === "jobkorea" ? "JK" : sourceClass === "nara" ? "NR" : sourceClass === "alio" ? "JA" : textValue(source.name, "S").slice(0, 2).toUpperCase();
      const name = element("div", "source-name", textValue(source.name, source.id));
      name.append(element("span", "source-mode", source.mode === "LOCAL_ONLY" ? "LOCAL ARCHIVE" : source.mode === "SCHEDULED" ? "SCHEDULED SOURCE" : textValue(source.mode, "MODE NOT REPORTED")));
      identity.append(element("span", "source-monogram " + sourceClass, monogram), name); identityCell.append(identity);
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
      const name = element("span", "service-name"); name.append(icon(String(service.id || "").includes("graph") || String(service.id || "").includes("neo4j") ? "graph" : "database"), document.createTextNode(textValue(service.label, service.id)));
      const info = statusInfo(service.status);
      const value = element("span", "service-state " + info.className, info.label.charAt(0).toUpperCase() + info.label.slice(1));
      row.title = textValue(service.message, "") + (service.checked_at ? " · " + date(service.checked_at) : "");
      row.append(name, value); return row;
    }));
  }
  function renderBars(target, rows, labelField, limit, relationship = false) {
    target.classList.toggle("relationship-bars", relationship);
    const items = array(rows).slice().sort((a, b) => (numeric(b.count) ? b.count : -1) - (numeric(a.count) ? a.count : -1));
    const displayed = limit ? items.slice(0, limit) : items;
    if (!displayed.length) { empty(target, "Composition not available", "Counts appear when the graph reports them."); return; }
    const max = Math.max(0, ...items.map((row) => numeric(row.count) ? row.count : 0));
    target.replaceChildren(...displayed.map((row) => {
      const container = element("div", "bar-row");
      const info = element("div", "bar-info");
      const name = element("span", "bar-name", textValue(row[labelField])); name.title = name.textContent;
      info.append(name, element("span", "bar-value", count(row.count)));
      const track = element("div", "bar-track"); const fill = element("span", "bar-fill");
      fill.style.width = numeric(row.count) && max ? Math.min(100, row.count / max * 100) + "%" : "0%";
      if (!numeric(row.count) || row.count === 0) fill.style.minWidth = "0";
      track.append(fill); container.append(info, track); return container;
    }));
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
    activityTable(runs.slice(0, 5), $("recent-activity"));
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
      const card = element("article", "card action-card"); const glyph = element("span", "mini-icon"); glyph.append(icon("activity"));
      const button = element("button", "button secondary", "Review & run");
      const enabled = action.enabled === true && state.data?.mode === "live" && typeof action.id === "string" && !!action.id;
      button.disabled = !enabled;
      button.addEventListener("click", () => openOperation(action));
      card.append(glyph, element("h3", "", textValue(action.label, action.id)), element("p", "", textValue(action.description, "Run this configured operation.")), element("code", "action-profile", textValue(action.id)), button);
      if (!enabled) card.append(element("div", "disabled-reason", state.data?.mode === "demo" ? "Operations are disabled in demo mode." : textValue(action.disabled_reason, "This operation is not enabled.")));
      return card;
    }));
  }
  function renderInference(inference) {
    if (!inference.length) { empty($("inference-list"), "No inference counts reported", "Reference catalogue data and inferred posting matches are separate."); return; }
    $("inference-list").replaceChildren(...inference.map((row) => {
      const card = element("article", "card inference-card");
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
  function selectTab(tab) {
    if (!["overview", "activity", "graph"].includes(tab)) return;
    state.tab = tab;
    const titles = { overview: ["Overview", "Operations overview", "The latest on your sources, pipelines, and knowledge graph."], activity: ["Activity", "Execution activity", "Track reported runs and manage configured operations."], graph: ["Knowledge graph", "Knowledge graph", "Explore graph composition, source coverage, and inferred matches."] };
    const [crumb, title, description] = titles[tab];
    $("breadcrumb-current").textContent = crumb;
    $("page-title").replaceChildren(document.createTextNode(title), element("span", "title-dot", "."));
    $("page-description").textContent = description;
    document.title = crumb + " · Jobtology Admin";
    for (const name of ["overview", "activity", "graph"]) {
      $("panel-" + name).hidden = name !== tab;
      const tabButton = $("tab-" + name); tabButton.classList.toggle("active", name === tab); tabButton.setAttribute("aria-selected", String(name === tab)); tabButton.tabIndex = name === tab ? 0 : -1;
    }
    document.querySelectorAll(".nav-item").forEach((node) => { const selected = node.dataset.tab === tab; node.classList.toggle("selected", selected); if (selected) node.setAttribute("aria-current", "page"); else node.removeAttribute("aria-current"); });
    renderNotices();
    requestAnimationFrame(updateTableCues);
    closeMenu();
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
  function closeMenu() { $("sidebar").classList.remove("open"); $("menu-toggle").setAttribute("aria-expanded", "false"); }
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
      state.submitting = false; button.disabled = false; button.textContent = "Run operation ↗"; $("cancel-operation").disabled = false;
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
    } finally { button.disabled = false; button.textContent = "Sign in ↗"; }
  });
  $("refresh-button").addEventListener("click", () => refreshDashboard(true));
  $("auto-refresh").addEventListener("change", scheduleRefresh);
  $("source-filter").addEventListener("change", renderActivity);
  $("state-filter").addEventListener("change", renderActivity);
  $("confirm-operation").addEventListener("click", submitOperation);
  $("confirmation-dialog").addEventListener("cancel", (event) => { if (state.submitting) event.preventDefault(); });
  $("confirmation-dialog").addEventListener("close", () => { state.operation = null; state.operationKey = null; });
  $("menu-toggle").addEventListener("click", () => { const open = $("sidebar").classList.toggle("open"); $("menu-toggle").setAttribute("aria-expanded", String(open)); });
  $("user-menu-button").addEventListener("click", () => { const menu = $("user-menu"); menu.hidden = !menu.hidden; $("user-menu-button").setAttribute("aria-expanded", String(!menu.hidden)); });
  document.addEventListener("click", (event) => {
    const tab = event.target.closest("[data-tab]"); if (tab) selectTab(tab.dataset.tab);
    if (!event.target.closest(".topbar-right")) { $("user-menu").hidden = true; $("user-menu-button").setAttribute("aria-expanded", "false"); }
    if (!event.target.closest("#sidebar") && !event.target.closest("#menu-toggle")) closeMenu();
  });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") { closeMenu(); $("user-menu").hidden = true; $("user-menu-button").setAttribute("aria-expanded", "false"); } });
  document.querySelector(".view-tabs").addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault(); const tabs = ["overview", "activity", "graph"]; const index = tabs.indexOf(state.tab);
    const target = event.key === "Home" ? 0 : event.key === "End" ? 2 : (index + (event.key === "ArrowRight" ? 1 : 2)) % 3;
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
