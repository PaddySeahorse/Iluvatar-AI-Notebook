from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})

    time.sleep(1)
    page.goto("http://localhost:8080/static/index.html", wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")

    # Wait for 3 failed GPU fetches (3 * 1500ms = 4.5s, plus some margin)
    page.wait_for_timeout(7000)

    # Read GPU mini dashboard values
    util_val = page.locator("#gpuUtilVal").inner_text()
    vram_val = page.locator("#gpuVramVal").inner_text()
    power_val = page.locator("#gpuPowerVal").inner_text()
    temp_val = page.locator("#gpuTempVal").inner_text()

    print(f"GPU Utilization: {util_val}")
    print(f"GPU VRAM: {vram_val}")
    print(f"GPU Power: {power_val}")
    print(f"GPU Temp: {temp_val}")

    page.screenshot(path="/workspace/test_screenshots/06_gpu_unavailable.png", full_page=False)
    print("Screenshot 06_gpu_unavailable.png saved")

    # Open GPU modal to verify modal also shows unavailable state
    gpu_dashboard = page.locator(".gpu-mini-dashboard")
    gpu_dashboard.click()
    page.wait_for_timeout(500)

    modal_status = page.locator("#gpuModalStatus").inner_text()
    modal_temp = page.locator("#gpuModalTemp").inner_text()
    modal_power = page.locator("#gpuModalPower").inner_text()
    modal_vram = page.locator("#gpuModalVramUsed").inner_text()

    print(f"\nModal Status: {modal_status}")
    print(f"Modal Temp: {modal_temp}")
    print(f"Modal Power: {modal_power}")
    print(f"Modal VRAM: {modal_vram}")

    page.screenshot(path="/workspace/test_screenshots/07_gpu_modal_unavailable.png", full_page=False)
    print("Screenshot 07_gpu_modal_unavailable.png saved")

    # Verify: none of the values should contain fake numbers like 2.0%, 3520, 42.0, 45.0
    all_vals = [util_val, vram_val, power_val, temp_val, modal_status, modal_temp, modal_power, modal_vram]
    fake_markers = ["2.0%", "3520", "42.0", "45.0", "Idle"]
    found_fake = [m for m in fake_markers if any(m in v for v in all_vals)]

    if found_fake:
        print(f"\nFAIL: Found fake GPU data still showing: {found_fake}")
    else:
        print("\nPASS: No fake GPU data found. GPU unavailable state is correctly shown.")

    browser.close()
