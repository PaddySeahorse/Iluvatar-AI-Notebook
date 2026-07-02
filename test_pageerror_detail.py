from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    page.on("pageerror", lambda err: print(f"PAGEERROR name={err.name}, message={err.message}, stack={getattr(err, 'stack', 'N/A')}"))
    page.on("console", lambda msg: print(f"CONSOLE {msg.type}: {msg.text}"))

    page.goto("http://localhost:8080/static/index.html")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)

    browser.close()
