from playwright.sync_api import sync_playwright
import hashlib

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("http://localhost:8080/static/index.html")
    page.wait_for_load_state("networkidle")

    result = page.evaluate("""async () => {
        const resp = await fetch('/static/js/state.js');
        const text = await resp.text();
        const headers = {};
        for (const [k, v] of resp.headers) {
            headers[k] = v;
        }
        return {
            length: text.length,
            hash: Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text))))
                .map(b => b.toString(16).padStart(2, '0')).join(''),
            first200: text.slice(0, 200),
            around179: text.split('\\n').slice(170, 185).join('\\n'),
            headers: headers
        };
    }""")

    print("Content-Length from fetch:", result['length'])
    print("SHA-256:", result['hash'])
    print("Headers:", result['headers'])
    print("\n--- Around line 170-185 ---")
    print(result['around179'])

    browser.close()
