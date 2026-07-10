// P2 streaming E2E suite — uses Playwright + Google Chrome.
//
// Spins up nothing itself: the Flask backend on http://127.0.0.1:5000 must
// already be running (background process). For each scenario, the test
// navigates the live /index.html, replaces notebook state with a single
// code cell, clicks the per-cell run button, and asserts on the rendered
// output DOM. Scenarios cover the streaming-frontend acceptance criteria
// from docs/plan/frontend-adaptation-plan.md + docs/plan/testing-and-rollout.md.

import { test, expect, chromium } from '@playwright/test';
import fs from 'fs';
import path from 'path';

const BASE = 'http://127.0.0.1:5000/';
const CHROME_PATH = '/tmp/install/chrome-extracted/opt/google/chrome/chrome';
const SHOT_DIR = '/tmp/e2e-shots';
fs.mkdirSync(SHOT_DIR, { recursive: true });

async function freshNotebook(context) {
  const page = await context.newPage();
  page.on('pageerror', (err) => console.error('[page error]', err.message));
  page.on('console', (msg) => {
    if (msg.type() === 'error') console.error('[console error]', msg.text());
  });
  await page.goto(BASE, { waitUntil: 'networkidle' });
  await page.waitForFunction(
    () => document.getElementById('cellsList') !== null,
    null,
    { timeout: 10000 }
  );
  return page;
}

// Run the given code in the (only) cell. Waits for the run to finish
// (i.e. isExecuting false) before resolving.
async function runOnlyCell(page, code) {
  await page.evaluate((c) => {
    const s = window.__appState;
    s.cells = [{
      id: 'cell_test_' + Math.random().toString(36).slice(2, 9),
      type: 'code',
      content: c,
      output: null,
      elapsedTime: null,
      success: true,
      isExecuting: false,
    }];
    s.activeCellId = s.cells[0].id;
    if (window.__triggerRender) window.__triggerRender();
  }, code);
  await page.waitForSelector('.cell-container .run-cell-btn', { timeout: 5000 });
  await page.click('.cell-container .run-cell-btn');
  await page.waitForFunction(
    () => {
      const s = window.__appState;
      const c = s.cells[0];
      return c && c.isExecuting === false;
    },
    null,
    { timeout: 60000 }
  );
}

test.beforeAll(async () => {
  const res = await fetch('http://127.0.0.1:5000/api/kernel_status');
  if (!res.ok) throw new Error('Flask backend not reachable on 5000');
});

test('app loads and renders initial empty notebook', async () => {
  const browser = await chromium.launch({
    headless: true, executablePath: CHROME_PATH,
    args: ['--no-sandbox', '--disable-gpu'],
  });
  const ctx = await browser.newContext();
  const page = await freshNotebook(ctx);
  await expect(page.locator('.status-dot').first()).toBeVisible();
  await browser.close();
});

test('P2-1: print() streams stdout into .output-stdout', async () => {
  const browser = await chromium.launch({
    headless: true, executablePath: CHROME_PATH,
    args: ['--no-sandbox', '--disable-gpu'],
  });
  const ctx = await browser.newContext();
  const page = await freshNotebook(ctx);
  await runOnlyCell(page, 'print("hello-streaming")');
  const stdout = await page.locator('.output-stdout').first();
  await expect(stdout).toBeVisible();
  const text = (await stdout.textContent()) || '';
  expect(text).toContain('hello-streaming');
  const count = await page.locator('.execution-count').first().textContent();
  expect(count).toMatch(/^\[\d+\]$/);
  await page.screenshot({ path: path.join(SHOT_DIR, '01-print.png') });
  await browser.close();
});

test('P2-2: tqdm-style carriage return renders single updating line', async () => {
  const browser = await chromium.launch({
    headless: true, executablePath: CHROME_PATH,
    args: ['--no-sandbox', '--disable-gpu'],
  });
  const ctx = await browser.newContext();
  const page = await freshNotebook(ctx);
  await runOnlyCell(
    page,
    'import sys\n' +
    'for i in range(20):\n' +
    '    sys.stdout.write("\\rprogress=%d" % i)\n' +
    '    sys.stdout.flush()\n' +
    'sys.stdout.write("\\n")\n'
  );
  const stdout = (await page.locator('.output-stdout').first().textContent()) || '';
  expect(stdout).toContain('progress=19');
  expect(stdout.split('\n').filter(l => l.trim().length > 0).length).toBeLessThanOrEqual(2);
  await page.screenshot({ path: path.join(SHOT_DIR, '02-tqdm.png') });
  await browser.close();
});

test('P2-3: matplotlib display_data renders image via image/png', async () => {
  const browser = await chromium.launch({
    headless: true, executablePath: CHROME_PATH,
    args: ['--no-sandbox', '--disable-gpu'],
  });
  const ctx = await browser.newContext();
  const page = await freshNotebook(ctx);
  await runOnlyCell(
    page,
    'import matplotlib\n' +
    'matplotlib.use("Agg")\n' +
    'import matplotlib.pyplot as plt\n' +
    'from io import BytesIO\n' +
    'from IPython.display import Image, display\n' +
    'fig = plt.figure(); plt.plot([1, 2, 3])\n' +
    'buf = BytesIO(); fig.savefig(buf, format="png")\n' +
    'display(Image(buf.getvalue()))\n'
  );
  const img = page.locator('.output-plot-img').first();
  await expect(img).toBeVisible();
  const src = await img.getAttribute('src');
  expect(src).toMatch(/^data:image\/png;base64,/);
  await page.screenshot({ path: path.join(SHOT_DIR, '03-plot.png') });
  await browser.close();
});

test('P2-4: 1/0 ZeroDivisionError renders error block + AI debug bar', async () => {
  const browser = await chromium.launch({
    headless: true, executablePath: CHROME_PATH,
    args: ['--no-sandbox', '--disable-gpu'],
  });
  const ctx = await browser.newContext();
  const page = await freshNotebook(ctx);
  await runOnlyCell(page, '1/0');
  const errHeader = page.locator('.output-error-header').first();
  await expect(errHeader).toBeVisible();
  const headerText = (await errHeader.textContent()) || '';
  expect(headerText).toMatch(/ZeroDivisionError/);
  const traceback = await page.locator('.output-error-traceback').first();
  await expect(traceback).toBeVisible();
  const debugBar = page.locator('.ai-debug-bar').first();
  await expect(debugBar).toBeVisible();
  await page.screenshot({ path: path.join(SHOT_DIR, '04-error.png') });
  await browser.close();
});

test('P2-5: while True interrupt stops the infinite loop', async () => {
  const browser = await chromium.launch({
    headless: true, executablePath: CHROME_PATH,
    args: ['--no-sandbox', '--disable-gpu'],
  });
  const ctx = await browser.newContext();
  const page = await freshNotebook(ctx);
  await page.evaluate(() => {
    const s = window.__appState;
    s.cells = [{
      id: 'cell_intr_' + Math.random().toString(36).slice(2, 9),
      type: 'code', content: 'while True:\n    pass', output: null,
      elapsedTime: null, success: true, isExecuting: false,
    }];
    s.activeCellId = s.cells[0].id;
    if (window.__triggerRender) window.__triggerRender();
  });
  await page.waitForSelector('.cell-container .run-cell-btn', { timeout: 5000 });
  await page.click('.cell-container .run-cell-btn');
  await page.waitForTimeout(1500);
  await page.click('#interruptKernelBtn');
  await page.waitForFunction(
    () => window.__appState.cells[0].isExecuting === false,
    null, { timeout: 15000 }
  );
  const cell = await page.evaluate(() => {
    const c = window.__appState.cells[0];
    return { success: c.success, hasErrorInOutput: !!(c.output && c.output.stderr) };
  });
  expect(cell.success).toBe(false);
  expect(cell.hasErrorInOutput).toBe(true);
  await page.screenshot({ path: path.join(SHOT_DIR, '05-interrupt.png') });
  await browser.close();
});

test('P2-6: execute_result renders Out[N] label with DataFrame HTML', async () => {
  const browser = await chromium.launch({
    headless: true, executablePath: CHROME_PATH,
    args: ['--no-sandbox', '--disable-gpu'],
  });
  const ctx = await browser.newContext();
  const page = await freshNotebook(ctx);
  await runOnlyCell(
    page,
    'import pandas as pd\npd.DataFrame({"a": [1, 2], "b": [3, 4]})'
  );
  const resultLabel = page.locator('.output-result-label').first();
  await expect(resultLabel).toBeVisible();
  expect((await resultLabel.textContent()) || '').toMatch(/^Out\[\d+\]:$/);
  const table = page.locator('.cell-output-area table.dataframe, .cell-output-area table').first();
  await expect(table).toBeVisible();
  await page.screenshot({ path: path.join(SHOT_DIR, '06-result.png') });
  await browser.close();
});
