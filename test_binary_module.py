from playwright.sync_api import sync_playwright

with open('/workspace/static/js/state.js', 'r', encoding='utf-8') as f:
    lines = f.read().split('\n')

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
            return new Promise((resolve) => {
                const blob = new Blob([code], {type: 'text/javascript'});
                const url = URL.createObjectURL(blob);
                const script = document.createElement('script');
                script.type = 'module';
                script.src = url;

                let resolved = false;
                const done = (res) => {
                    if (!resolved) { resolved = true; resolve(res); }
                };

                script.onload = () => done({ok: true});
                window.addEventListener('error', function handler(e) {
                    if (e.filename.includes(url)) {
                        window.removeEventListener('error', handler);
                        done({ok: false, message: e.message, lineno: e.lineno, colno: e.colno});
                    }
                });
                document.head.appendChild(script);
                setTimeout(() => done({ok: true}), 2000);
            });
        }""", {"code": partial})

        if not result['ok']:
            bad = mid
            high = mid - 1
            print(f"Lines 1-{mid}: ERROR -> {result['message']} at line {result.get('lineno', '?')}")
        else:
            low = mid + 1
            print(f"Lines 1-{mid}: OK")

    print(f"\nFirst bad prefix: 1-{bad}")
    if bad <= len(lines):
        for i in range(max(0, bad-5), min(len(lines), bad+2)):
            print(f"{i+1}: {lines[i]}")

    browser.close()
