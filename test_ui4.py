from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})

    # Capture page errors with stack trace
    page_errors = []
    def handle_page_error(error):
        page_errors.append({
            "message": str(error),
            "stack": getattr(error, 'stack', 'no stack')
        })
    page.on("pageerror", handle_page_error)

    page.goto("http://localhost:8080/static/index.html")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)

    print("Page errors:")
    for err in page_errors:
        print(f"  Message: {err['message']}")
        print(f"  Stack: {err['stack']}")

    browser.close()
