const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');

async function main() {
  const root = path.resolve(__dirname, '..');
  const output = path.join(root, 'work', 'v6-1-web-qa');
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true, executablePath: 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe' });
  const errors = [];
  let result;
  try {
    const page = await browser.newPage({ viewport: { width: 1360, height: 1000 } });
    page.on('pageerror', error => errors.push(error.message));
    const response = await page.goto(process.env.V6_QA_URL || 'http://127.0.0.1:4174/', { waitUntil: 'networkidle', timeout: 60000 });
    assert.equal(response.status(), 200);
    await page.addStyleTag({ content: '.topbar { position: static !important; }' });
    await page.getByPlaceholder('搜索学校或城市').fill('合肥工业大学');
    const row = page.locator('.ranking-panel tbody tr').first();
    await row.click();
    assert.match(await row.locator('.prob-cell').textContent(), /不宜精算/);
    assert.equal(await row.locator('.prob-cell').getByRole('progressbar').count(), 0);
    assert.match(await page.locator('.risk-orb').textContent(), /需复核.*不宜精算/);
    await page.getByRole('slider').first().focus();
    await page.keyboard.press('End');
    assert.equal((await page.locator('.score-value strong').textContent()).trim(), '460');
    assert.equal((await page.locator('.risk-orb small').textContent()).trim(), '不宜精算');
    await page.locator('.detail-panel').screenshot({ path: path.join(output, 'wide-upper-desktop.png') });
    await page.getByRole('tab', { name: '院校地图', exact: true }).click();
    const mapRisk = page.locator('.map-school-metrics > div').filter({ has: page.getByText('风险刻度', { exact: true }) });
    assert.equal((await mapRisk.locator('dd').textContent()).trim(), '不宜精算');
    await page.getByRole('tab', { name: '模型原理', exact: true }).click();
    assert.match(await page.locator('.decision-result').textContent(), /不宜精算.*需复核/);
    assert.match(await page.locator('.decision-rule').textContent(), /暂不据此给稳保结论/);
    await page.getByRole('button', { name: /^个人决策：/ }).click();
    const example = await page.locator('.live-example').textContent();
    assert.match(example, /不宜精算/);
    assert.doesNotMatch(example, /\d+%/);
    assert.equal(await page.locator('.research-role-strip > div').count(), 3);
    assert.match(await page.locator('.stat-year-coverage').textContent(), /2024：9\/10.*2025：27\/27.*2026：14\/17/);
    await page.locator('.statistical-research').screenshot({ path: path.join(output, 'research-desktop.png') });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator('.statistical-research').screenshot({ path: path.join(output, 'research-mobile.png') });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    assert.ok(overflow <= 2, `Horizontal overflow ${overflow}`);
    const duplicateIds = await page.evaluate(() => { const ids = [...document.querySelectorAll('[id]')].map(x => x.id); return ids.filter((id, i) => ids.indexOf(id) !== i); });
    assert.equal(duplicateIds.length, 0);
    await page.getByRole('tab', { name: '风险排名', exact: true }).click();
    await page.locator('.detail-panel').screenshot({ path: path.join(output, 'wide-upper-mobile.png') });
    await page.getByPlaceholder('搜索学校或城市').fill('华东师范大学');
    await page.locator('.ranking-panel tbody tr').first().click();
    assert.equal((await page.locator('.risk-orb small').textContent()).trim(), '≥95%');
    await page.getByRole('slider').first().focus();
    await page.keyboard.press('Home');
    assert.equal((await page.locator('.risk-orb small').textContent()).trim(), '≤5%');
    result = { http: 200, runtimeErrors: errors, horizontalOverflow: overflow, duplicateIds,
               wideSchoolGuard: ['ranking', 'detail', 'map', 'theory', 'pipeline'],
               ordinaryTailLabels: true, annualCoverageCounts: [9, 27, 14], numericalForecastRefitted: false };
    assert.equal(errors.length, 0);
  } finally {
    await browser.close();
  }
  fs.writeFileSync(path.join(output, 'summary.json'), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result));
}

main().catch(error => { console.error(error); process.exit(1); });
