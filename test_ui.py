from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.goto("http://localhost:8080/static/index.html")
    page.wait_for_load_state("networkidle")

    # Screenshot full page
    page.screenshot(path="/workspace/screenshot_full.png", full_page=True)

    # Screenshot viewport
    page.screenshot(path="/workspace/screenshot_viewport.png")

    # Get page title
    title = page.title()
    print(f"Page title: {title}")

    # Check for key elements
    elements = {
        "top-nav": page.locator(".top-nav").count(),
        "file-sidebar": page.locator(".file-sidebar").count(),
        "notebook-container": page.locator(".notebook-container").count(),
        "ai-sidebar": page.locator(".ai-sidebar").count(),
        "settings-modal": page.locator("#settingsModal").count(),
        "gpu-modal": page.locator("#gpuModal").count(),
        "theme-toggle-btn": page.locator("#themeToggleBtn").count(),
        "skip-link": page.locator(".skip-link").count(),
        "h1": page.locator("h1").count(),
        "aria-label-buttons": page.locator("button[aria-label]").count(),
        "aria-hidden-icons": page.locator("i[aria-hidden='true']").count(),
    }

    for name, count in elements.items():
        print(f"{name}: {count}")

    # Check computed styles for key elements
    nav_bg = page.evaluate("""() => {
        const el = document.querySelector('.top-nav');
        return el ? getComputedStyle(el).backgroundColor : 'not found';
    }""")
    print(f"top-nav background: {nav_bg}")

    body_bg = page.evaluate("""() => {
        return getComputedStyle(document.body).backgroundColor;
    }""")
    print(f"body background: {body_bg}")

    # Check if modals are hidden
    settings_modal_display = page.evaluate("""() => {
        const el = document.querySelector('#settingsModal');
        return el ? getComputedStyle(el).display + ' / opacity: ' + getComputedStyle(el).opacity : 'not found';
    }""")
    print(f"settings modal display/opacity: {settings_modal_display}")

    # Check focus-visible styles
    focus_outline = page.evaluate("""() => {
        const btn = document.querySelector('#themeToggleBtn');
        if (!btn) return 'not found';
        // Simulate focus-visible
        btn.focus();
        const style = getComputedStyle(btn);
        return style.outlineWidth + ' ' + style.outlineColor + ' ' + style.outlineOffset;
    }""")
    print(f"themeToggleBtn focus outline: {focus_outline}")

    # Test adding a cell
    page.locator("#addCodeBtn").click()
    page.wait_for_timeout(500)
    cell_count = page.locator(".cell-container").count()
    print(f"cell count after adding code cell: {cell_count}")

    # Screenshot after adding cell
    page.screenshot(path="/workspace/screenshot_with_cell.png", full_page=True)

    # Test theme toggle
    page.locator("#themeToggleBtn").click()
    page.wait_for_timeout(500)
    body_bg_after = page.evaluate("""() => {
        return getComputedStyle(document.body).backgroundColor;
    }""")
    print(f"body background after theme toggle: {body_bg_after}")

    # Check theme-color meta
    theme_color = page.evaluate("""() => {
        const meta = document.querySelector('meta[name=theme-color]');
        return meta ? meta.content : 'not found';
    }""")
    print(f"theme-color meta: {theme_color}")

    # Check color-scheme
    color_scheme = page.evaluate("""() => {
        return getComputedStyle(document.documentElement).colorScheme;
    }""")
    print(f"html color-scheme: {color_scheme}")

    browser.close()
