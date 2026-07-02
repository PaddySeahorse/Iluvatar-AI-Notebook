from playwright.sync_api import sync_playwright

with open('/workspace/static/js/state.js', 'r', encoding='utf-8') as f:
    code = f.read()

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("about:blank")

    result = page.evaluate("""({code}) => {
        return new Promise((resolve) => {
            const blob = new Blob([code], {type: 'text/javascript'});
            const url = URL.createObjectURL(blob);
            const script = document.createElement('script');
            script.type = 'module';
            script.src = url;

            let resolved = false;
            const done = (res) => {
                if (!resolved) {
                    resolved = true;
                    resolve(res);
                }
            };

            script.onload = () => done({ok: true});
            script.onerror = (e) => {
                // script.onerror for modules usually gives little info
                done({ok: false, message: 'script onerror'});
            };

            window.addEventListener('error', function handler(e) {
                if (e.filename === url || e.filename.includes(url)) {
                    window.removeEventListener('error', handler);
                    done({ok: false, message: e.message, lineno: e.lineno, colno: e.colno});
                }
            });

            document.head.appendChild(script);

            setTimeout(() => done({ok: false, message: 'timeout'}), 3000);
        });
    }""", {"code": code})

    print(result)
    browser.close()
