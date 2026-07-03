from playwright.sync_api import sync_playwright
import re

with open('/workspace/static/js/state.js', 'r', encoding='utf-8') as f:
    code = f.read()

# Remove import/export statements to make it parseable by new Function
stripped = re.sub(r"^\s*import\s+.*?from\s+['\"].*?['\"];?\s*$", "", code, flags=re.MULTILINE)
stripped = re.sub(r"^\s*export\s+", "", stripped, flags=re.MULTILINE)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("about:blank")

    result = page.evaluate("""({code}) => {
        try {
            new Function(code);
            return {ok: true};
        } catch (e) {
            return {ok: false, name: e.name, message: e.message, stack: e.stack};
        }
    }""", {"code": stripped})

    print(result)
    browser.close()
