from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("about:blank")
    version = page.evaluate("() => navigator.userAgent")
    print("User-Agent:", version)
    browser.close()
