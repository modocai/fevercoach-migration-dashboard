// Optional browser validation; Playwright is a verification tool, not a site dependency.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(__dirname, '..');

(async () => {
  const browser = await chromium.launch({headless: true, ...(process.env.BROWSER_PATH ? {executablePath: process.env.BROWSER_PATH} : {})});
  const report = [];
  fs.mkdirSync(path.join(root, 'artifacts'), {recursive: true});
  try {
    for (const width of [1440, 390, 320]) {
      const page = await browser.newPage({viewport: {width, height: 1000}});
      const errors = [], requests = [];
      page.on('pageerror', e => errors.push(e.message));
      page.on('request', req => { if (/^https?:/.test(req.url())) requests.push(req.url()); });
      await page.goto(pathToFileURL(path.join(root, 'index.html')).href);
      const expected = JSON.parse(fs.readFileSync(path.join(root, 'data/plan.json'), 'utf8')).tasks.length;
      assert.equal(await page.locator('.row:visible').count(), expected);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `overflow at ${width}`);
      const counts = await page.locator('.row').evaluateAll(rows => rows.reduce((out, row) => {
        out[row.dataset.status] = (out[row.dataset.status] || 0) + 1; return out;
      }, {}));
      for (const status of ['done', 'todo', 'doing', 'blocked', 'unknown', 'excluded']) {
        const button = page.locator(`[data-filter="${status}"]`);
        await button.focus();
        await page.keyboard.press('Enter');
        assert.equal(await button.getAttribute('aria-pressed'), 'true');
        assert.equal(await page.locator('.row:visible').count(), counts[status] || 0);
        assert.equal(await page.locator('#empty-filter').isVisible(), !counts[status]);
      }
      await page.locator('.phases a').first().click();
      assert.equal(await page.locator('.row:visible').count(), expected, 'phase links must reset filters');
      const gate = page.locator('.gates summary').first();
      await gate.focus();
      await page.keyboard.press('Enter');
      assert.equal(await page.locator('.gates').first().getAttribute('open'), '');
      await page.locator('header').scrollIntoViewIfNeeded();
      await page.screenshot({path: path.join(root, `artifacts/dashboard-${width}.png`), fullPage: true});
      await page.screenshot({path: path.join(root, `artifacts/dashboard-${width}-top.png`)});
      await page.locator('#baselines').screenshot({path: path.join(root, `artifacts/baselines-${width}.png`)});
      assert.deepEqual(errors, []);
      assert.deepEqual(requests, []);
      report.push({width, counts, overflow: false, errors, externalRequests: requests.length});
      await page.close();
    }
    const page = await browser.newPage({javaScriptEnabled: false});
    await page.goto(pathToFileURL(path.join(root, 'index.html')).href);
    assert.equal(await page.locator('.row:visible').count(), 28);
    report.push({javascriptDisabled: true, visibleTasks: 28});
    console.log(JSON.stringify(report, null, 2));
    fs.writeFileSync(path.join(root, 'artifacts/browser-validation.json'), JSON.stringify(report, null, 2) + '\n');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
