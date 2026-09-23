const { chromium } = require(process.argv[2]);
const path = require('node:path');
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const failures = [];
    const sockets = [];
    page.on("websocket", ws => { sockets.push(ws.url()); ws.on("socketerror", e => failures.push(String(e))); });
    page.on('pageerror', e => failures.push(e.message));
    page.on('response', r => { if (r.status() >= 400 && r.url().includes('/n8n/')) failures.push(r.status() + ' ' + r.url()); });
    await page.goto('http://127.0.0.1:8766');
    await page.waitForFunction(async () => (await (await fetch('/api/status')).json()).n8n.ready, { timeout: 60000 });
    await page.locator('[data-mode="n8n"]').click();
    const frame = page.frameLocator('#n8nFrame');
    await frame.locator('input').first().waitFor({ timeout: 45000 });
    if (await frame.getByText('Set up owner account', { exact: true }).isVisible()) {
      await frame.getByLabel('Email', { exact: false }).fill('ui-test@example.invalid');
      await frame.getByLabel('First Name', { exact: false }).fill('UI');
      await frame.getByLabel('Last Name', { exact: false }).fill('Test');
      await frame.getByLabel('Password', { exact: false }).fill('UiTest2026!OnlyLocal');
      await frame.getByRole('checkbox').uncheck();
      await frame.getByRole('button', { name: 'Next', exact: true }).click();
      await frame.getByText('Set up owner account', { exact: true }).waitFor({ state: 'hidden' });
    }
    const signIn = frame.getByRole('button', { name: 'Sign in', exact: true });
    if (await signIn.isVisible()) {
      await frame.getByLabel('Email', { exact: false }).fill('ui-test@example.invalid');
      await frame.getByLabel('Password', { exact: false }).fill('UiTest2026!OnlyLocal');
      await signIn.click();
      await signIn.waitFor({ state: 'hidden' });
    }
    const build = frame.getByRole('button', { name: 'Build a workflow', exact: true });
    if (await build.isVisible()) await build.click();
    const actual = page.frames().find(f => f.url().includes('/n8n/'));
    await actual.goto('http://127.0.0.1:8766/n8n/workflow/new');
    await actual.waitForFunction(() => document.body.innerText.includes('Add first step'));
    await actual.goto(actual.url());
    await actual.waitForFunction(() => document.body.innerText.includes('Add first step'));
    console.log('EDITOR AND DEEP-LINK REFRESH OK');
    console.log('WEBSOCKETS', JSON.stringify(sockets));
    console.log((await frame.locator('body').innerText()).slice(0, 4000));
    const unexpected = failures.filter(x => !x.startsWith('401 ') && !x.includes('WebSocket is closed before the connection is established'));
    console.log('FAILURES', JSON.stringify(unexpected));
    if (unexpected.length) throw new Error('Unexpected n8n load failures');
    await page.screenshot({ path: path.join(__dirname, 'ui-n8n.png'), fullPage: true });
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
