// Real Chromium against synthetic publications. No private API or live deployment.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const http = require('node:http');
const {execFileSync} = require('node:child_process');
const {pathToFileURL} = require('node:url');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'dashboard-check-'));
let published = 1, manifestMode = 'normal', cachedHtml = false;
const requests = [];
const sites = [null, path.join(temporary, 'one'), path.join(temporary, 'two')];
for (const generation of [1, 2]) execFileSync('python3', ['tests/publication_fixture.py', sites[generation], String(generation)], {cwd: root});
console.log('Synthetic publications ready.');
const manifests = [null, ...sites.slice(1).map(site => JSON.parse(fs.readFileSync(path.join(site, 'manifest.json'))))];
const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://localhost');
  requests.push({path: url.pathname, authorization: req.headers.authorization, cookie: req.headers.cookie});
  if (url.pathname.endsWith('manifest.json')) {
    if (manifestMode === 'offline') { res.writeHead(503).end('unavailable'); return; }
    const value = {...manifests[published]};
    if (manifestMode === 'stale') value.last_success_at = '2020-01-01T00:00:00Z';
    if (manifestMode === 'degraded') value.degraded = true;
    res.setHeader('Content-Type', 'application/json');
    res.end(manifestMode === 'invalid' ? '{bad' : manifestMode === 'oversize' ? 'x'.repeat(5000) : JSON.stringify(value));
    return;
  }
  if (url.pathname === '/data/content-comparison.json') {
    res.setHeader('Content-Type', 'application/json');
    res.end(fs.readFileSync(path.join(sites[published], 'data/content-comparison.json')));
    return;
  }
  const filename = url.pathname.endsWith('auto-refresh.js') ? 'assets/auto-refresh.js' :
    url.pathname.endsWith('migration-dashboard.html') ? 'migration-dashboard.html' : 'index.html';
  res.setHeader('Content-Type', filename.endsWith('.js') ? 'application/javascript' : 'text/html');
  res.setHeader('Cache-Control', 'public, max-age=600');
  res.end(fs.readFileSync(path.join(sites[cachedHtml ? 1 : published], filename)));
});

(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${server.address().port}/`;
  const browser = await chromium.launch({headless: true, ...(process.env.BROWSER_PATH ? {executablePath: process.env.BROWSER_PATH} : {})});
  console.log('Chromium ready.');
  const watchdog = setTimeout(() => { console.error('Browser verification exceeded 120 seconds.'); process.exit(1); }, 120000);
  watchdog.unref();
  async function newPage(options) {
    const result = await browser.newPage(options);
    result.setDefaultTimeout(15000);
    result.setDefaultNavigationTimeout(15000);
    return result;
  }
  let checks = 0;
  const errors = [];
  let page = await newPage({viewport: {width: 1440, height: 900}});
  page.on('pageerror', error => errors.push(error.message));
  async function notice(text) { await page.waitForFunction(text => document.querySelector('#auto-update-status').textContent.includes(text), text); checks++; }
  async function poll() {
    const response = page.waitForResponse(response => response.url().includes('/manifest.json?'));
    await page.evaluate(() => dispatchEvent(new Event('focus')));
    await (await response).finished();
  }
  async function idle() { await page.waitForTimeout(250); }
  try {
    await page.goto(base);
    console.log('Initial publication loaded.');
    await idle();
    assert.equal(await page.locator('.content-score').innerText(), '0%'); checks++;
    // Prove manifest polling omits cookies even when this origin has one.
    await page.evaluate(() => { document.cookie = 'dashboard_test_canary=synthetic; path=/'; });
    assert.equal(await page.locator('.row:visible').count(), 28); checks++;
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false); checks++;
    await page.locator('[data-filter="doing"]').click();
    await page.locator('#phase-0 details').evaluate(node => { node.open = true; });
    await page.evaluate(() => scrollTo(0, 450));
    published = 2;
    console.log('Checking refresh to second publication.');
    await poll();
    await page.waitForURL(url => url.searchParams.get('v') === manifests[2].build_id);
    await page.waitForFunction(() => document.querySelector('[data-filter="doing"]').getAttribute('aria-pressed') === 'true');
    assert.equal(await page.locator('.row:visible').count(), 1); checks++;
    assert.equal(await page.locator('.content-score').innerText(), '50.0%'); checks++;
    const reportLink = await page.locator('#content-completion a').getAttribute('href');
    const reportResponse = await page.request.get(new URL(reportLink, base).href);
    assert.equal(reportResponse.status(), 200); checks++;
    assert.equal((await reportResponse.json()).percentage, 50); checks++;
    assert.equal(await page.locator('#phase-0 details').evaluate(node => node.open), true); checks++;
    assert.ok(await page.evaluate(() => scrollY > 0)); checks++;
    for (const [mode, message] of [['offline', '확인하지 못했습니다'], ['invalid', '확인하지 못했습니다'],
                                  ['oversize', '확인하지 못했습니다'], ['stale', '45분'], ['degraded', '마지막 확인값']]) {
      manifestMode = mode;
      await idle(); await poll(); await notice(message);
      assert.equal(await page.locator('.row:visible').count(), 1); checks++;
    }
    manifestMode = 'normal';
    console.log('Checking stale CDN handling.');
    // A stale CDN manifest must not downgrade a newer HTML publication.
    published = 1;
    await idle(); await poll(); await notice('확인하지 못했습니다');
    assert.equal(new URL(page.url()).searchParams.get('v'), manifests[2].build_id); checks++;

    // CDN returns old HTML even for a new query: only one navigation, then a notice.
    published = 2; cachedHtml = true;
    await page.close();
    page = await newPage({viewport: {width: 1440, height: 900}});
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(base);
    await page.waitForURL(url => url.searchParams.get('v') === manifests[2].build_id);
    await notice('새 자료가 있습니다');
    const htmlRequests = () => requests.filter(r => r.path === '/').length;
    const before = htmlRequests();
    await idle(); await poll(); await idle(); await poll(); await idle();
    assert.equal(htmlRequests(), before); checks++;

    // Session storage blocked still cannot create a reload loop.
    console.log('Checking blocked storage and script-free fallback.');
    const blocked = await newPage({viewport: {width: 1280, height: 800}});
    await blocked.addInitScript(() => Object.defineProperty(window, 'sessionStorage', {get() { throw new Error('blocked'); }}));
    await blocked.goto(base);
    await blocked.waitForURL(url => url.searchParams.get('v') === manifests[2].build_id);
    await blocked.waitForFunction(() => document.getElementById('auto-update-status').textContent.includes('새 자료가 있습니다'));
    assert.equal(await blocked.evaluate(() => document.documentElement.scrollWidth > innerWidth), false); checks++;
    await blocked.close();

    const noJs = await newPage({javaScriptEnabled: false, viewport: {width: 1280, height: 800}});
    await noJs.goto(base);
    assert.equal(await noJs.locator('.row:visible').count(), 28); checks++;
    await noJs.close();
    const local = await newPage();
    const external = [];
    local.on('request', req => { if (/^https?:/.test(req.url())) external.push(req.url()); });
    await local.goto(pathToFileURL(path.join(sites[1], 'index.html')).href);
    assert.equal(await local.locator('.row:visible').count(), 28); checks++;
    assert.deepEqual(external, []); checks++;
    await local.close();
    assert.deepEqual(errors, []); checks++;
    assert.equal(requests.some(req => req.authorization), false); checks++;
    assert.equal(requests.filter(req => req.path.endsWith('manifest.json')).some(req => req.cookie), false); checks++;
    console.log(`Automatic update browser checks passed: ${checks} assertions (1440px / 1280px, synthetic sources).`);
  } finally {
    await browser.close();
    server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
    fs.rmSync(temporary, {recursive: true, force: true});
    clearTimeout(watchdog);
  }
})().catch(error => { console.error(error); server.close(); fs.rmSync(temporary, {recursive: true, force: true}); process.exitCode = 1; });

