from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})

    errors = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.on("console", lambda msg: print(f"[CONSOLE {msg.type}] {msg.text}"))

    page.goto("http://localhost:8080/static/index.html")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1500)

    # 1. Screenshot initial state
    page.screenshot(path="/workspace/test_screenshots/01_initial.png", full_page=False)
    print("Screenshot 01_initial.png saved")

    # 2. Check theme toggle button exists and click it
    theme_btn = page.locator("#themeToggleBtn")
    if theme_btn.count() > 0:
        print("Theme toggle button found")
        theme_btn.click()
        page.wait_for_timeout(800)
        page.screenshot(path="/workspace/test_screenshots/02_light_theme.png", full_page=False)
        print("Screenshot 02_light_theme.png saved")
        # Toggle back to dark
        theme_btn.click()
        page.wait_for_timeout(800)
    else:
        print("Theme toggle button NOT found")

    # 3. Click GPU mini dashboard to open modal
    gpu_dashboard = page.locator(".gpu-mini-dashboard")
    if gpu_dashboard.count() > 0:
        print("GPU dashboard found")
        gpu_dashboard.click()
        page.wait_for_timeout(800)
        page.screenshot(path="/workspace/test_screenshots/03_gpu_modal.png", full_page=False)
        print("Screenshot 03_gpu_modal.png saved")
        # Close modal
        close_modal = page.locator("#closeGpuBottomBtn")
        if close_modal.count() > 0:
            close_modal.click()
            page.wait_for_timeout(800)
        # Fallback: force remove open class via JS
        page.evaluate("() => document.getElementById('gpuModal').classList.remove('open')")
        page.wait_for_timeout(300)
    else:
        print("GPU dashboard NOT found")

    # 4. Click add cell button (code cell) from top toolbar
    add_code_btn = page.locator("#addCodeBtn")
    if add_code_btn.count() > 0:
        print("Top add code button found")
        add_code_btn.click()
        page.wait_for_timeout(800)
        page.screenshot(path="/workspace/test_screenshots/04_added_cell_top.png", full_page=False)
        print("Screenshot 04_added_cell_top.png saved")
    else:
        print("Top add code button NOT found")

    # 5. Click bottom add markdown button
    add_md_btn = page.locator("#addMarkdownBottomBtn")
    if add_md_btn.count() > 0:
        print("Bottom add markdown button found")
        add_md_btn.click()
        page.wait_for_timeout(800)
        page.screenshot(path="/workspace/test_screenshots/05_added_cell_bottom.png", full_page=False)
        print("Screenshot 05_added_cell_bottom.png saved")
    else:
        print("Bottom add markdown button NOT found")

    if errors:
        print(f"\nTotal page errors: {len(errors)}")
        for e in errors:
            print(f"  - {e}")
    else:
        print("\nNo page errors detected.")

    browser.close()
