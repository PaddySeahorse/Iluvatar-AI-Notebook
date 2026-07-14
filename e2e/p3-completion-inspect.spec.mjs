// P3 completion & introspection E2E suite — uses Playwright + Google Chrome.
//
// Spins up nothing itself: the Flask backend on http://127.0.0.1:5000 must
// already be running (background process). Scenarios cover the P3 acceptance
// criteria from docs/plan/frontend-adaptation-plan.md §3 and
// docs/plan/testing-and-rollout.md §4.1 (补全 / 内省):
//   - Tab completion: type "np." → Tab → completion popup appears
//   - Shift+Tab inspect: type "print" → Shift+Tab → inspect panel appears
//   - Completion keyboard navigation: Down/Enter applies a match
//   - Markdown MIME rendering: display_data text/markdown renders as HTML

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

// Set up a single code cell with the given content and run it to make the
// imports / variables available in the kernel scope. Waits for execution to
// finish before resolving.
async function setupAndRunCell(page, code) {
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
    () => window.__appState.cells[0] && window.__appState.cells[0].isExecuting === false,
    null,
    { timeout: 60000 }
  );
}

// Focus the CodeMirror editor in the first cell and replace its content.
async function setEditorContent(page, text) {
  await page.waitForSelector('.cell-container .CodeMirror', { timeout: 5000 });
  await page.evaluate((t) => {
    // Find the first CodeMirror instance via the global activeEditors map
    // (set by renderer.js) or fall back to cmInstance on the DOM node.
    const cmEl = document.querySelector('.cell-container .CodeMirror');
    if (cmEl && cmEl.CodeMirror) {
      cmEl.CodeMirror.setValue(t);
      // Move cursor to end so Tab triggers on the full text
      const lastLine = cmEl.CodeMirror.lastLine();
      cmEl.CodeMirror.setCursor({ line: lastLine, ch: cmEl.CodeMirror.getLine(lastLine).length });
    }
  }, text);
}

// Focus the CodeMirror editor so keyboard events reach it.
async function focusEditor(page) {
  await page.click('.cell-container .CodeMirror');
}

test.beforeAll(async () => {
  const res = await fetch('http://127.0.0.1:5000/api/kernel_status');
  if (!res.ok) throw new Error('Flask backend not reachable on 5000');
});

test('P3-1: Tab on "np." opens completion popup with matches', async () => {
  const browser = await chromium.launch({
    headless: true, executablePath: CHROME_PATH,
    args: ['--no-sandbox', '--disable-gpu'],
  });
  const ctx = await browser.newContext();
  const page = await freshNotebook(ctx);

  // Make numpy available in the kernel scope
  await setupAndRunCell(page, 'import numpy as np');

  // Type "np." in the editor
  await setEditorContent(page, 'np.');
  await focusEditor(page);

  // Press Tab to trigger completion
  await page.keyboard.press('Tab');

  // The completion popup should appear with at least one item
  const popup = page.locator('.completion-box').first();
  await expect(popup).toBeVisible({ timeout: 10000 });
  const itemCount = await page.locator('.completion-item').count();
  expect(itemCount).toBeGreaterThan(0);

  await page.screenshot({ path: path.join(SHOT_DIR, 'p3-01-completion.png') });
  await browser.close();
});

test('P3-2: Down + Enter applies a completion match to the editor', async () => {
  const browser = await chromium.launch({
    headless: true, executablePath: CHROME_PATH,
    args: ['--no-sandbox', '--disable-gpu'],
  });
  const ctx = await browser.newContext();
  const page = await freshNotebook(ctx);

  await setupAndRunCell(page, 'import numpy as np');
  await setEditorContent(page, 'np.');
  await focusEditor(page);
  await page.keyboard.press('Tab');

  const popup = page.locator('.completion-box').first();
  await expect(popup).toBeVisible({ timeout: 10000 });

  // Navigate down one item and apply with Enter
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('Enter');

  // The popup should close and the editor content should have grown beyond "np."
  await expect(popup).not.toBeVisible({ timeout: 5000 });
  const content = await page.evaluate(() => {
    const cmEl = document.querySelector('.cell-container .CodeMirror');
    return cmEl && cmEl.CodeMirror ? cmEl.CodeMirror.getValue() : '';
  });
  expect(content.length).toBeGreaterThan(4); // longer than "np."

  await page.screenshot({ path: path.join(SHOT_DIR, 'p3-02-completion-apply.png') });
  await browser.close();
});

test('P3-3: Escape closes the completion popup', async () => {
  const browser = await chromium.launch({
    headless: true, executablePath: CHROME_PATH,
    args: ['--no-sandbox', '--disable-gpu'],
  });
  const ctx = await browser.newContext();
  const page = await freshNotebook(ctx);

  await setupAndRunCell(page, 'import numpy as np');
  await setEditorContent(page, 'np.');
  await focusEditor(page);
  await page.keyboard.press('Tab');

  const popup = page.locator('.completion-box').first();
  await expect(popup).toBeVisible({ timeout: 10000 });

  await page.keyboard.press('Escape');
  await expect(popup).not.toBeVisible({ timeout: 5000 });

  await browser.close();
});

test('P3-4: Shift+Tab on "print" opens inspect panel with documentation', async () => {
  const browser = await chromium.launch({
    headless: true, executablePath: CHROME_PATH,
    args: ['--no-sandbox', '--disable-gpu'],
  });
  const ctx = await browser.newContext();
  const page = await freshNotebook(ctx);

  // No setup needed — print is a builtin
  await setEditorContent(page, 'print');
  await focusEditor(page);

  // Press Shift+Tab to trigger inspect
  await page.keyboard.press('Shift+Tab');

  const panel = page.locator('.inspect-panel').first();
  await expect(panel).toBeVisible({ timeout: 10000 });

  // The panel body should contain some documentation text
  const bodyText = await page.locator('.inspect-body').first().textContent();
  expect(bodyText.length).toBeGreaterThan(0);
  // IPython's docstring for print includes "print" somewhere
  expect(bodyText.toLowerCase()).toContain('print');

  await page.screenshot({ path: path.join(SHOT_DIR, 'p3-04-inspect.png') });
  await browser.close();
});

test('P3-5: Inspect panel close button hides the panel', async () => {
  const browser = await chromium.launch({
    headless: true, executablePath: CHROME_PATH,
    args: ['--no-sandbox', '--disable-gpu'],
  });
  const ctx = await browser.newContext();
  const page = await freshNotebook(ctx);

  await setEditorContent(page, 'print');
  await focusEditor(page);
  await page.keyboard.press('Shift+Tab');

  const panel = page.locator('.inspect-panel').first();
  await expect(panel).toBeVisible({ timeout: 10000 });

  await page.click('.inspect-panel .inspect-close');
  await expect(panel).not.toBeVisible({ timeout: 5000 });

  await browser.close();
});

test('P3-6: Tab with no completion trigger falls through to indent', async () => {
  const browser = await chromium.launch({
    headless: true, executablePath: CHROME_PATH,
    args: ['--no-sandbox', '--disable-gpu'],
  });
  const ctx = await browser.newContext();
  const page = await freshNotebook(ctx);

  // Empty editor: Tab should insert spaces (indent), not show a popup
  await setEditorContent(page, '');
  await focusEditor(page);
  await page.keyboard.press('Tab');

  // No popup should appear (give it a moment to be sure)
  await page.waitForTimeout(500);
  const popupVisible = await page.locator('.completion-box').first().isVisible();
  expect(popupVisible).toBe(false);

  // The editor should now contain spaces (indent)
  const content = await page.evaluate(() => {
    const cmEl = document.querySelector('.cell-container .CodeMirror');
    return cmEl && cmEl.CodeMirror ? cmEl.CodeMirror.getValue() : '';
  });
  expect(content).toMatch(/^\s+$/);

  await browser.close();
});

test('P3-7: display_data text/markdown renders as HTML (not plain text pre)', async () => {
  const browser = await chromium.launch({
    headless: true, executablePath: CHROME_PATH,
    args: ['--no-sandbox', '--disable-gpu'],
  });
  const ctx = await browser.newContext();
  const page = await freshNotebook(ctx);

  // Use IPython.display.Markdown to emit a text/markdown display_data
  await setupAndRunCell(
    page,
    'from IPython.display import display, Markdown\n' +
    'display(Markdown("# Title\\n\\n**bold** text"))'
  );

  // The markdown output should render as an .output-markdown div containing
  // an <h2> (from "# Title") and a <strong> (from "**bold**"), NOT a plain <pre>.
  const mdContainer = page.locator('.output-markdown').first();
  await expect(mdContainer).toBeVisible({ timeout: 10000 });
  const html = await mdContainer.innerHTML();
  expect(html).toContain('<h2>');
  expect(html).toContain('<strong>bold</strong>');

  await page.screenshot({ path: path.join(SHOT_DIR, 'p3-07-markdown.png') });
  await browser.close();
});
