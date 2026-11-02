/** Local UI regression fixture; all API responses are synthetic and no external URL is visited.
 * Run from the repository root with Playwright available to Node, or set
 * PLAYWRIGHT_MODULE to its installed ESM entry point. Chrome must be installed.
 */
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdir, readFile } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || "playwright");
const staticDirectory = new URL("../../src/jobtology_db/admin/static/", import.meta.url);
const assets = { "/": "index.html", "/static/app.js": "app.js", "/static/style.css": "style.css" };
const server = createServer(async (request, response) => {
  const asset = assets[request.url];
  if (!asset) { response.writeHead(404); response.end(); return; }
  const type = asset.endsWith(".js") ? "text/javascript" : asset.endsWith(".css") ? "text/css" : "text/html";
  response.writeHead(200, { "Content-Type": type });
  response.end(await readFile(fileURLToPath(new URL(asset, staticDirectory))));
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({ channel: "chrome", headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
const resourceErrors = [];
const injectedErrors = [];
page.on("pageerror", (error) => errors.push(error.message));
page.on("console", (message) => {
  if (message.type() !== "error") return;
  const resource = message.text().match(/^Failed to load resource: the server responded with a status of (\d+)/);
  if (resource) resourceErrors.push(Number(resource[1])); else errors.push(message.text());
});
page.on("dialog", (dialog) => dialog.accept());
const identifier = "74163956-6d3c-4b54-901a-043f1c79eacb";
const invitation = { id: identifier, label: "Pilot", code_hint: "ONCE", max_uses: 1, use_count: 0, access_hours: 0.5, expires_at: null, revoked_at: null };
const created = { invitation, code: "fixture-creation-only-code", invite_url: "https://app.example/#invite=fixture-creation-only-code", qr_svg: '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><rect width="20" height="20" fill="white"/><path d="M0 0h10v10H0z" fill="black"/></svg>' };
const commonUser = { status: "ACTIVE", access_source: "INVITATION", active_sessions: 1 };
const users = [
  { ...commonUser, id: "aaaaaaaa-0000-4000-8000-000000000001", display_name: "Unlimited user", access_expires_at: null },
  { ...commonUser, id: "aaaaaaaa-0000-4000-8000-000000000002", display_name: "Known expiry", access_expires_at: "2050-01-01T00:00:00Z" },
  { ...commonUser, id: "aaaaaaaa-0000-4000-8000-000000000003", display_name: "Missing expiry" },
  { ...commonUser, id: "aaaaaaaa-0000-4000-8000-000000000004", display_name: "Malformed expiry", access_expires_at: "bad-date" },
  { ...commonUser, id: "aaaaaaaa-0000-4000-8000-000000000005", display_name: "Invalid calendar", access_expires_at: "2050-02-30T00:00:00Z" },
  { ...commonUser, id: "aaaaaaaa-0000-4000-8000-000000000006", display_name: "Expired user", access_expires_at: "2000-01-01T00:00:00Z" },
];
const sessions = [
  { id: identifier, user_id: users[0].id, display_name: "Expired session", created_at: "2000-01-01T00:00:00Z", expires_at: "2000-01-02T00:00:00Z", revoked_at: null },
  { id: users[1].id, user_id: users[1].id, display_name: "Unknown session", expires_at: "2050", revoked_at: null },
];
const dashboard = {
  mode: "live", generated_at: new Date().toISOString(),
  summary: { source_postings: 22635, total_nodes: 52300, total_relationships: 100000, active_runs: 0, failed_runs_24h: 0 },
  graph: { status: "healthy", checked_at: new Date().toISOString(), node_counts: [{ label: "SourcePosting", count: 22635 }], relationship_counts: [{ type: "HAS_SOURCE", count: 22635 }], postings_by_source: [{ source_id: "archive", count: 22635 }], inference: [{ kind: "INFERRED_NCS_OCCUPATION", total: 5000, reviewed: 20, unreviewed: 4980, confidence: "UNASSESSED" }] },
  services: [{ id: "postgres", label: "PostgreSQL", status: "healthy" }, { id: "neo4j", label: "Neo4j", status: "unavailable", message: "Authentication failed. Check the configured credentials." }],
  sources: [{ id: "archive", name: "Local archive", mode: "LOCAL_ONLY", postings: 22635, records: 22635, last_success_at: new Date().toISOString(), state: "ready" }],
  runs: [{ id: identifier, source_id: "archive", source_name: "Local archive", operation: "Import", state: "succeeded", started_at: new Date().toISOString(), duration_seconds: 60, records: 22635 }],
  jobs: [], actions: [{ id: "fixture-profile", label: "Fixture operation", description: "Synthetic profile only.", enabled: true }], notices: [],
};
const requests = [];
const holds = [];
let authenticated = false;
let operator = "";
function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}
function holdNext(matches) {
  const received = deferred(); const response = deferred();
  holds.push({ matches, received, response });
  return { received: received.promise, release: response.resolve };
}
const sessionPayload = () => ({ authenticated, username: operator, csrf_token: "fixture-csrf-" + operator, mode: "live" });
await page.route("**/*", async (route) => {
  const request = route.request(); const url = new URL(request.url());
  assert.equal(url.origin, origin, "fixture must not make external HTTP requests");
  if (!url.pathname.startsWith("/api/")) { await route.continue(); return; }
  if (request.method() !== "GET" && url.pathname !== "/api/login") {
    assert.equal(request.headers()["x-csrf-token"], "fixture-csrf-" + operator, "authenticated writes keep their session CSRF token");
  }
  const record = { path: url.pathname, method: request.method(), body: request.postDataJSON() };
  requests.push(record);
  const index = holds.findIndex((hold) => hold.matches(record));
  if (index >= 0) {
    const hold = holds.splice(index, 1)[0]; hold.received.resolve(record);
    const response = await hold.response.promise;
    await route.fulfill({ status: response.status, contentType: "application/json", body: JSON.stringify(response.body) }); return;
  }
  let data = { ok: true };
  if (record.path === "/api/session") data = sessionPayload();
  else if (record.path === "/api/login") { authenticated = true; operator = record.body.username; data = sessionPayload(); }
  else if (record.path === "/api/logout") authenticated = false;
  else if (record.path === "/api/dashboard") data = dashboard;
  else if (record.path === "/api/application/users") data = { items: users, total: users.length };
  else if (record.path === "/api/application/sessions") data = { items: sessions, total: sessions.length };
  else if (record.path === "/api/application/invitations") data = record.method === "GET" ? { items: [invitation], total: 1 } : created;
  else if (record.path.startsWith("/api/application/invitations/") && record.method === "PATCH") data = invitation;
  await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(data) });
});
async function login(name) {
  await page.locator("#username").fill(name); await page.locator("#password").fill("fixture-password");
  await page.locator("#login-submit").click(); await page.locator("#app-view").waitFor({ state: "visible" });
}
async function logout() {
  await page.locator("#logout-button").click();
  await page.locator("#login-view").waitFor({ state: "visible" });
}
async function showUsers() {
  await page.locator("#tab-users").click(); await page.locator("#users-list tbody tr").first().waitFor();
}
const row = (name) => page.locator("#users-list tbody tr").filter({ hasText: name });
const userWrites = () => requests.filter((request) => request.method === "PATCH" && request.path.startsWith("/api/application/users/"));
async function openExpiry(name) { await row(name).getByRole("button", { name: "Edit expiry", exact: true }).click(); }
async function saveExpiry() {
  await page.getByRole("button", { name: "Save expiry", exact: true }).click();
  await page.locator("#user-access-dialog").waitFor({ state: "hidden" });
  await page.locator("#users-list tbody tr").first().waitFor();
}
async function releaseAndWait(hold, status, body) {
  const request = await hold.received;
  if (status >= 400) injectedErrors.push(status);
  const response = page.waitForResponse((response) => response.status() === status && new URL(response.url()).pathname === request.path && response.request().method() === request.method);
  hold.release({ status, body }); await response; await page.waitForTimeout(100);
}
async function screenshot(name) {
  if (!process.env.ADMIN_SCREENSHOT_DIR) return;
  await mkdir(process.env.ADMIN_SCREENSHOT_DIR, { recursive: true });
  await page.locator("#toast").evaluate((node) => { node.hidden = true; });
  await page.screenshot({ path: join(process.env.ADMIN_SCREENSHOT_DIR, name + ".png"), fullPage: true });
}
async function fitsViewport() {
  const layout = await page.evaluate(() => ({ width: innerWidth, scrollWidth: document.documentElement.scrollWidth }));
  assert(layout.scrollWidth <= layout.width, JSON.stringify(layout));
}
try {
  await page.goto(origin); await page.locator("#login-view").waitFor({ state: "visible" });
  await screenshot("login-1440"); await login("operator-1");
  await page.locator("#metrics dd").first().waitFor();
  assert.match(await page.locator("#services-list").textContent(), /Authentication failed/);
  await screenshot("overview-1440");
  await page.locator("#tab-overview").focus(); await page.keyboard.press("ArrowRight");
  assert.equal(await page.locator("#tab-activity").getAttribute("aria-selected"), "true");
  await page.getByRole("button", { name: "Review & run", exact: true }).click();
  assert.equal(await page.locator("#confirmation-profile").textContent(), "fixture-profile");
  await page.locator("#cancel-operation").click();
  await page.locator("#tab-graph").click();
  assert.equal(await page.locator("#node-details tbody tr td").first().textContent(), "SourcePosting");
  assert.equal(await page.locator("#relationship-details tbody tr td").first().textContent(), "HAS_SOURCE");
  await showUsers();
  assert.match(await row("Expired user").locator("td").nth(1).textContent(), /ACTIVE/);
  assert.match(await row("Expired user").locator("td").nth(2).textContent(), /^Expired/);
  for (const name of ["Missing expiry", "Malformed expiry", "Invalid calendar"]) {
    assert.equal(await row(name).locator("td").nth(2).textContent(), "Unavailable");
    await openExpiry(name);
    assert.equal(await page.locator('#user-access-form [name="unlimited"]').isChecked(), false);
    assert.equal(await page.locator('#user-access-form [name="access_expires_at"]').inputValue(), "");
    const before = userWrites().length;
    await page.getByRole("button", { name: "Save expiry", exact: true }).click();
    await page.locator("#user-access-form").evaluate((form) => form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
    assert.equal(userWrites().length, before, "unknown expiry must not silently clear access restrictions");
    assert.match(await page.locator("#user-access-error").textContent(), /explicitly select unlimited/);
    await page.locator('#user-access-form [name="unlimited"]').check(); await saveExpiry();
    assert.equal(userWrites().at(-1).body.access_expires_at, null);
  }
  await openExpiry("Known expiry"); await page.locator('#user-access-form [name="access_expires_at"]').fill("");
  let before = userWrites().length;
  await page.getByRole("button", { name: "Save expiry", exact: true }).click();
  assert.equal(userWrites().length, before, "clearing a known expiry requires deliberate unlimited selection");
  await page.locator('#user-access-form [name="unlimited"]').check(); await saveExpiry();
  assert.equal(userWrites().at(-1).body.access_expires_at, null);
  await openExpiry("Unlimited user"); assert.equal(await page.locator('#user-access-form [name="unlimited"]').isChecked(), true);
  await saveExpiry(); assert.equal(userWrites().at(-1).body.access_expires_at, null);
  await openExpiry("Missing expiry"); await page.locator('#user-access-form [name="access_expires_at"]').fill("2050-05-03T09:30");
  await saveExpiry(); assert.match(userWrites().at(-1).body.access_expires_at, /^2050-05-03T/);

  const expiryDate = page.locator('#user-access-form [name="access_expires_at"]');
  const expirySave = page.getByRole("button", { name: "Save expiry", exact: true });
  const expiryCancel = page.locator('[data-close-dialog="user-access-dialog"]');
  async function pendingExpiry(name, value) {
    const user = users.find((user) => user.display_name === name);
    const hold = holdNext((request) => request.method === "PATCH" && request.path.endsWith(user.id) && "access_expires_at" in request.body);
    await openExpiry(name);
    await page.locator('#user-access-form [name="unlimited"]').uncheck();
    await expiryDate.fill(value); await expirySave.click(); await hold.received;
    return hold;
  }
  // A canceled submission must never close, report errors in, or unlock a newer edit.
  for (const scenario of [
    { user: "Known expiry", oldStatus: 200, pending: false, cancel: "button" },
    { user: "Known expiry", oldStatus: 409, pending: true, newStatus: 200, cancel: "Escape" },
    { user: "Unlimited user", oldStatus: 200, pending: true, newStatus: 409, cancel: "native" },
  ]) {
    const old = await pendingExpiry("Unlimited user", "2051-01-02T09:30");
    if (scenario.cancel === "button") await expiryCancel.click();
    else if (scenario.cancel === "Escape") await page.keyboard.press("Escape");
    else await page.locator("#user-access-dialog").evaluate((dialog) => dialog.close());
    await page.locator("#user-access-dialog").waitFor({ state: "hidden" });
    let current;
    if (scenario.pending) current = await pendingExpiry(scenario.user, "2052-03-04T10:45");
    else { await openExpiry(scenario.user); await expiryDate.fill("2052-03-04T10:45"); }
    const reads = requests.filter((request) => request.method === "GET" && request.path === "/api/application/users").length;
    await releaseAndWait(old, scenario.oldStatus, scenario.oldStatus === 200 ? { ok: true } : { detail: "fixture obsolete edit" });
    assert.equal(await page.locator("#user-access-dialog").isVisible(), true);
    assert.equal(await expiryDate.inputValue(), "2052-03-04T10:45");
    assert.equal(await page.locator("#user-access-error").isVisible(), false);
    assert.equal(await expirySave.isDisabled(), scenario.pending, "old finally must not unlock a newer pending submission");
    assert.equal(requests.filter((request) => request.method === "GET" && request.path === "/api/application/users").length, reads);
    if (current) {
      await releaseAndWait(current, scenario.newStatus, scenario.newStatus === 200 ? { ok: true } : { detail: "fixture current edit rejected" });
      if (scenario.newStatus === 200) await page.locator("#user-access-dialog").waitFor({ state: "hidden" });
      else {
        assert.equal(await page.locator("#user-access-dialog").isVisible(), true);
        assert.match(await page.locator("#user-access-error").textContent(), /current edit rejected/);
        assert.equal(await expirySave.isEnabled(), true); await expiryCancel.click();
      }
    } else await expiryCancel.click();
    await page.locator("#users-list tbody tr").first().waitFor();
  }
  const oldOperatorEdit = await pendingExpiry("Unlimited user", "2051-01-02T09:30");
  await expiryCancel.click(); await logout(); await login("expiry-new-operator"); await showUsers();
  await openExpiry("Known expiry"); await expiryDate.fill("2052-03-04T10:45");
  await releaseAndWait(oldOperatorEdit, 401, { detail: "fixture previous operator expired" });
  assert.equal(await page.locator("#app-view").isVisible(), true);
  assert.equal(await page.locator("#user-access-dialog").isVisible(), true);
  assert.equal(await expiryDate.inputValue(), "2052-03-04T10:45");
  assert.equal(await page.locator("#user-access-error").isVisible(), false);
  assert.equal(await expirySave.isEnabled(), true); await expiryCancel.click();

  // Both stale successes and errors must be inert after a new operator signs in.
  for (const status of [200, 401, 409]) {
    const held = holdNext((request) => request.method === "PATCH" && request.body?.status === "DEACTIVATED");
    await row("Unlimited user").getByRole("button", { name: "Suspend", exact: true }).click(); await held.received;
    await logout(); await login("operator-" + status); await showUsers();
    await page.locator("#toast").evaluate((toast) => { toast.hidden = true; });
    const reads = requests.filter((request) => request.method === "GET" && request.path === "/api/application/users").length;
    await releaseAndWait(held, status, status === 200 ? { ok: true } : { detail: "fixture stale response" });
    assert.equal(await page.locator("#app-view").isVisible(), true, "stale 401 must not sign out the new operator");
    assert.equal(await page.locator("#user-name").textContent(), "operator-" + status);
    assert.equal(await page.locator("#users-error").isVisible(), false);
    assert.equal(await page.locator("#toast").isVisible(), false);
    assert.equal(requests.filter((request) => request.method === "GET" && request.path === "/api/application/users").length, reads);
  }

  await page.locator("#tab-invitations").click(); await page.locator("#invitations-list tbody tr").waitFor();
  await page.locator("#create-invitation").click(); await page.locator('#invitation-form [name="label"]').fill("New fixture");
  const pendingCreate = holdNext((request) => request.method === "POST" && request.path === "/api/application/invitations");
  await page.getByRole("button", { name: "Save invitation", exact: true }).click(); await pendingCreate.received;
  assert.equal(await page.locator('[data-close-dialog="invitation-dialog"]').isDisabled(), true);
  await page.keyboard.press("Escape"); assert.equal(await page.locator("#invitation-dialog").evaluate((dialog) => dialog.open), true);
  await page.locator("#invitation-dialog").evaluate((dialog) => dialog.requestClose?.());
  assert.equal(await page.locator("#invitation-dialog").evaluate((dialog) => dialog.open), true);
  await page.locator("#invitation-dialog").evaluate((dialog) => dialog.close());
  await page.waitForFunction(() => document.querySelector("#invitation-dialog").open);
  await page.locator("#invitations-list button").filter({ hasText: /^Edit$/ }).evaluate((button) => button.click());
  assert.equal(await page.locator("#invitation-dialog-title").textContent(), "Create invitation");
  await releaseAndWait(pendingCreate, 201, created);
  await page.locator("#created-invitation").waitFor({ state: "visible" });
  assert.match(await page.locator("#created-invitation").textContent(), /fixture-creation-only-code/);
  assert.equal(await page.locator(".invitation-qr").evaluate((image) => image.complete && image.naturalWidth > 0), true);
  assert.match(await page.locator("#created-invitation").textContent(), /Share the link or scan the QR, then sign in with Google/);
  assert.equal(await page.locator("#created-invitation").evaluate((node) => document.activeElement === node), true);
  assert.match(await page.getByRole("link", { name: "Download QR", exact: true }).getAttribute("href"), /^data:image\/svg\+xml/);
  assert.equal(await page.getByRole("link", { name: "Download QR", exact: true }).getAttribute("download"), "jobtology-invitation.svg");
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: 900 }); await fitsViewport(); await screenshot("invitation-created-" + width);
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.locator("#create-invitation").click();
  assert.equal(await page.locator("#invitation-dialog").evaluate((dialog) => dialog.open), false, "undismissed code must not be overwritten by another creation");
  await page.getByRole("button", { name: "Edit", exact: true }).click();
  await page.getByRole("button", { name: "Save invitation", exact: true }).click();
  await page.locator("#invitation-dialog").waitFor({ state: "hidden" });
  assert.match(await page.locator("#created-invitation").textContent(), /fixture-creation-only-code/);
  await page.getByRole("button", { name: "Dismiss code", exact: true }).click();
  await page.locator("#create-invitation").click(); await page.locator('#invitation-form [name="label"]').fill("Failed fixture");
  const failedCreate = holdNext((request) => request.method === "POST" && request.path === "/api/application/invitations");
  await page.getByRole("button", { name: "Save invitation", exact: true }).click(); await failedCreate.received;
  await releaseAndWait(failedCreate, 503, { detail: "fixture backend unavailable" });
  assert.equal(await page.getByRole("button", { name: "Save invitation", exact: true }).isEnabled(), true);
  assert.equal(await page.locator('[data-close-dialog="invitation-dialog"]').isEnabled(), true);
  await page.locator('[data-close-dialog="invitation-dialog"]').click();

  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    for (const tab of ["overview", "activity", "graph", "invitations", "users", "sessions"]) {
      await page.locator("#tab-" + tab).click();
      if (["invitations", "users", "sessions"].includes(tab)) await page.locator(`#${tab}-list tbody tr`).first().waitFor();
      await fitsViewport(); await screenshot(tab + "-" + width);
    }
    await page.locator("#tab-invitations").click(); await page.locator("#create-invitation").click();
    await fitsViewport(); await screenshot("invitation-form-" + width);
    await page.locator('[data-close-dialog="invitation-dialog"]').click();
    await page.locator("#tab-users").click(); await page.locator("#users-list tbody tr").first().waitFor();
    await openExpiry("Known expiry"); await fitsViewport(); await screenshot("expiry-form-" + width);
    await expiryCancel.click(); await page.locator("#tab-sessions").click(); await page.locator("#sessions-list tbody tr").first().waitFor();
  }
  assert.equal(await page.locator("#sessions-list tbody tr").nth(0).locator("td").nth(3).textContent(), "Expired");
  assert.equal(await page.locator("#sessions-list tbody tr").nth(1).locator("td").nth(3).textContent(), "Unavailable");
  await logout(); assert.equal(await page.locator("#created-invitation").textContent(), ""); await fitsViewport(); await screenshot("login-320");
  assert.deepEqual(errors, []);
  assert.deepEqual(resourceErrors.sort(), injectedErrors.sort(), "only deliberately injected resource errors are expected");
  assert.equal(holds.length, 0);
  console.log(JSON.stringify({ passed: true, viewports: [1440, 390, 320], staleRowResponses: [200, 401, 409], explicitExpiryClearing: true, reusedExpiryDialogsPreserved: true, pendingInvitationPreserved: true, sessionCsrfPreserved: true, noExternalRequests: true, javascriptErrors: errors }));
} finally {
  await browser.close(); await new Promise((resolve) => server.close(resolve));
}
