from playwright.sync_api import sync_playwright
import sys

errors = []
logs = []

def handle_console(msg):
    text = msg.text
    logs.append(text)
    if msg.type == 'error':
        errors.append(text)
        print(f"[CONSOLE ERROR] {text}", file=sys.stderr)
    else:
        print(f"[CONSOLE {msg.type.upper()}] {text}")

def handle_page_error(err):
    err_str = str(err)
    errors.append(err_str)
    print(f"[PAGE ERROR] {err_str}", file=sys.stderr)
    # Try to get stack if available via evaluation

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.on("console", handle_console)
    page.on("pageerror", handle_page_error)

    # Inject a global error listener to capture file/line before pageerror
    page.add_init_script("""
    window._capturedErrors = [];
    window.addEventListener('error', function(e) {
        window._capturedErrors.push({
            message: e.message,
            filename: e.filename,
            lineno: e.lineno,
            colno: e.colno,
            stack: e.error && e.error.stack ? e.error.stack : ''
        });
    });
    """)

    page.goto("http://localhost:8080/static/index.html")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)

    captured = page.evaluate("() => window._capturedErrors")
    print("\n--- Captured window.onerror ---")
    for e in captured:
        print(f"File: {e.get('filename')}")
        print(f"Line: {e.get('lineno')}, Col: {e.get('colno')}")
        print(f"Message: {e.get('message')}")
        print(f"Stack: {e.get('stack')}")
        print("---")

    state_defined = page.evaluate("() => typeof window.state !== 'undefined'")
    print(f"\nwindow.state defined: {state_defined}")

    # Also check which scripts loaded successfully
    scripts = page.evaluate("""() => {
        return Array.from(document.scripts).map(s => ({src: s.src, readyState: s.readyState}));
    }""")
    print("\n--- Scripts ---")
    for s in scripts:
        print(s)

    if errors:
        print(f"\nTotal page errors: {len(errors)}")
    else:
        print("\nNo JS errors detected.")

    browser.close()
