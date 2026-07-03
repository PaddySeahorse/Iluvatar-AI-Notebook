from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.goto("http://localhost:8080/static/index.html")
    page.wait_for_load_state("networkidle")

    # Test theme toggle with more debugging
    print("Before toggle:")
    has_light = page.evaluate("""() => document.body.classList.contains('light-theme')""")
    print(f"  body has light-theme: {has_light}")
    bg = page.evaluate("""() => getComputedStyle(document.body).backgroundColor""")
    print(f"  body background: {bg}")

    page.locator("#themeToggleBtn").click()
    page.wait_for_timeout(1000)

    print("After toggle:")
    has_light = page.evaluate("""() => document.body.classList.contains('light-theme')""")
    print(f"  body has light-theme: {has_light}")
    bg = page.evaluate("""() => getComputedStyle(document.body).backgroundColor""")
    print(f"  body background: {bg}")

    # Check CSS variable directly
    bg_var = page.evaluate("""() => {
        const style = getComputedStyle(document.body);
        return style.getPropertyValue('--bg-main').trim();
    }""")
    print(f"  --bg-main value: {bg_var}")

    # Test adding a cell with debugging
    print("\nBefore adding cell:")
    cell_count = page.locator(".cell-container").count()
    print(f"  cell count: {cell_count}")

    page.locator("#addCodeBtn").click()
    page.wait_for_timeout(1000)

    print("After clicking addCodeBtn:")
    cell_count = page.locator(".cell-container").count()
    print(f"  cell count: {cell_count}")

    # Check if there are any console errors
    logs = page.evaluate("""() => {
        return window._consoleErrors || [];
    }""")
    print(f"  console errors: {logs}")

    # Check if state.js loaded successfully
    state_ok = page.evaluate("""() => typeof window.state !== 'undefined'""")
    print(f"  window.state defined: {state_ok}")

    # Screenshot
    page.screenshot(path="/workspace/screenshot_test.png", full_page=True)

    browser.close()
