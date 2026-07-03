from playwright.sync_api import sync_playwright
import re

with open('/workspace/static/js/state.js', 'r', encoding='utf-8') as f:
    code = f.read()

stripped = re.sub(r"^\s*import\s+.*?from\s+['\"].*?['\"];?\s*$", "", code, flags=re.MULTILINE)
stripped = re.sub(r"^\s*export\s+", "", stripped, flags=re.MULTILINE)
lines = stripped.split('\n')

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("about:blank")

    low = 1
    high = len(lines)
    bad = high

    while low <= high:
        mid = (low + high) // 2
        partial = '\n'.join(lines[:mid])
        result = page.evaluate("""({code}) => {
            try {
                new Function(code);
                return {ok: true};
            } catch (e) {
                return {ok: false, message: e.message};
            }
        }""", {"code": partial})

        if not result['ok']:
            bad = mid
            high = mid - 1
            print(f"Lines 1-{mid}: ERROR -> {result['message']}")
        else:
            low = mid + 1
            print(f"Lines 1-{mid}: OK")

    print(f"\nFirst bad line range: 1-{bad}")
    print(f"Line {bad}: {lines[bad-1]}")
    if bad > 1:
        print(f"Line {bad-1}: {lines[bad-2]}")
    if bad > 2:
        print(f"Line {bad-2}: {lines[bad-3]}")

    browser.close()
