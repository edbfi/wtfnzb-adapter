// Executed only through the installed ego-browser CLI. Never print secrets or URLs.
const fs = await import("node:fs/promises");
const base = helperEnv.WTFNZB_BASE_URL;
const output = helperEnv.WTFNZB_AUTH_FILE;
const state = helperEnv.ADAPTER_STATE_DIR;
let spaceId = Number(helperEnv.WTFNZB_EGO_SPACE || await fs.readFile(state + "/ego-space", "utf8").catch(() => ""));
const pageLabel = helperEnv.WTFNZB_EGO_PAGE || "p1";
if (!base || !output || !state) throw new Error("Missing session helper configuration");
let task;
if (spaceId > 0 && Number.isInteger(spaceId)) {
  task = await taskSpace(spaceId);
} else {
  task = await taskSpace("WTFNZB adapter session");
  spaceId = task.spaceId;
  await fs.writeFile(state + "/ego-space", String(spaceId), {mode:0o600});
}
const page = task.page(pageLabel);
let last = 0;
async function pace() {
  await new Promise(resolve => setTimeout(resolve, Math.max(0, 10000 - (Date.now() - last))));
  last = Date.now();
}
try {
  await pace();
  await page.goto(base + "/apihelp");
  await page.waitForFunction(() => document.body.innerText.includes("/api_fast?") || !!document.querySelector('input[type="password"]') || document.body.innerText.includes("Error 1106"), undefined, {timeout:15000});
  let content = await page.evaluate(() => ({text: document.body.innerText, login: !!document.querySelector('input[type="password"]')}));
  if (content.login) {
    const blocked = await fs.stat(state + "/login-blocked").then(() => true, () => false);
    if (blocked) throw new Error("Login failure latch requires human review");
    const username = helperEnv.WTFNZB_USERNAME;
    const password = helperEnv.WTFNZB_PASSWORD;
    if (!username || !password) throw new Error("Missing login credentials");
    // Verified fields on the live WTFNZB form; no guesses or alternate attempts.
    const names = await page.evaluate(() => [...document.querySelectorAll('input')].map(e => ({name:e.name,type:e.type})));
    const user = names.find(e => e.name === "username");
    if (!user) throw new Error("Login form changed");
    await page.fill('input[name="username"]', username);
    await page.fill('input[type="password"]', password);
    const correct = await page.evaluate(({username,password}) => document.querySelector('input[name="username"]').value === username && document.querySelector('input[type="password"]').value === password, {username,password});
    if (!correct) throw new Error("Form fill verification failed");
    // Latch BEFORE submission, so a crash cannot cause another login attempt.
    await fs.writeFile(state + "/login-blocked", "Login submitted; clear only after reviewing outcome.\n", {mode:0o600});
    await pace();
    await page.click('button[type="submit"]');
    await page.waitForFunction(() => !document.querySelector('input[type="password"]'), undefined, {timeout:15000});
    await pace();
    await page.goto(base + "/apihelp");
    content = await page.evaluate(() => ({text:document.body.innerText,login:!!document.querySelector('input[type="password"]')}));
  }
  const matches = content.text.match(/https?:\/\/\S+\/api_fast\?[^\s]+/g) || [];
  const example = matches.map(value => new URL(value)).find(url => url.searchParams.has("apikey") && url.searchParams.has("i"));
  if (content.login || !example || example.origin !== new URL(base).origin) throw new Error("Authenticated API help unavailable; manual browser action required");
  const key = example.searchParams.get("apikey");
  const encoded = example.searchParams.get("i");
  const userId = /^\d+$/.test(encoded) ? encoded : Buffer.from(encoded, "base64").toString("utf8");
  if (!/^\d+$/.test(userId) || !key) throw new Error("API credentials changed format");
  const cookies = await page.cdp("Network.getCookies", {urls:[base]});
  const session = cookies.cookies.find(cookie => cookie.name === "PHPSESSID")?.value;
  if (!session) throw new Error("Session cookie unavailable");
  const auth = {base_url:base.replace(/\/$/, ""),api_key:key,user_id:userId,session};
  await fs.writeFile(output + ".tmp", JSON.stringify(auth), {mode:0o600});
  await fs.chmod(output + ".tmp", 0o600);
  await fs.rename(output + ".tmp", output);
  await fs.rm(state + "/login-blocked", {force:true});
  console.log("Session captured successfully");
} catch (_) {
  // Browser receipts/errors may include credential-bearing URLs; do not propagate them.
  console.log("Session refresh failed; inspect the authorized Ego page and login latch");
  process.exitCode = 1;
}
