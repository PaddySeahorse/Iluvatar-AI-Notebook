from playwright.sync_api import sync_playwright
import sys

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("http://localhost:8080/static/js/state.js")
    text = page.evaluate("() => document.body.innerText")
    lines = text.split('\n')
    for i, line in enumerate(lines[170:190], start=171):
        print(f"{i}: {line}")
    browser.close()
