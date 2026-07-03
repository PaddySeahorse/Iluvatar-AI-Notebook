from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})

    # Capture console logs
    console_logs = []
    def handle_console(msg):
        console_logs.append(f"{msg.type}: {msg.text}")
    page.on("console", handle_console)

    # Capture page errors
    page_errors = []
    def handle_page_error(error):
        page_errors.append(str(error))
    page.on("pageerror", handle_page_error)

    page.goto("http://localhost:8080/static/index.html")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)

    print("Console logs:")
    for log in console_logs:
        print(f"  {log}")

    print("\nPage errors:")
    for err in page_errors:
        print(f"  {err}")

    print(f"\nwindow.state defined: {page.evaluate('() => typeof window.state !== \"undefined\"')}")
    print(f"document.body classList: {page.evaluate('() => Array.from(document.body.classList)')}")

    # Check if main.js loaded
    main_js = page.evaluate("""() => {
        return Array.from(document.querySelectorAll('script')).map(s => s.src).filter(src => src.includes('main.js'));
    }""")
    print(f"main.js script src: {main_js}")

    # Check network requests
    # We need to use browser context route for this, but for now let's just screenshot
    page.screenshot(path="/workspace/screenshot_debug.png", full_page=True)

    browser.close()
