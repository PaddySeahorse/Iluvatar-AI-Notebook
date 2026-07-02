from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()

    # Disable cache
    context.set_extra_http_headers({"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"})

    errors = []
    def handle_page_error(err):
        errors.append(str(err))
        print(f"[PAGE ERROR] {err}")

    page.on("pageerror", handle_page_error)

    # Clear any existing service workers or cache
    page.goto("http://localhost:8080/static/index.html")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)

    state_defined = page.evaluate("() => typeof window.state !== 'undefined'")
    print(f"window.state defined: {state_defined}")

    if errors:
        print("Errors detected.")
    else:
        print("No JS errors detected.")

    browser.close()
