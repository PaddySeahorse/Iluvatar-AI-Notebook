from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()

    with open('/workspace/static/js/state.js', 'r', encoding='utf-8') as f:
        state_js_content = f.read()
    with open('/workspace/static/js/api.js', 'r', encoding='utf-8') as f:
        api_js_content = f.read()
    with open('/workspace/static/js/renderer.js', 'r', encoding='utf-8') as f:
        renderer_js_content = f.read()
    with open('/workspace/static/js/main.js', 'r', encoding='utf-8') as f:
        main_js_content = f.read()

    def handle_route(route, request):
        url = request.url
        if url.endswith('/state.js'):
            route.fulfill(status=200, content_type='text/javascript', body=state_js_content)
        elif url.endswith('/api.js'):
            route.fulfill(status=200, content_type='text/javascript', body=api_js_content)
        elif url.endswith('/renderer.js'):
            route.fulfill(status=200, content_type='text/javascript', body=renderer_js_content)
        elif url.endswith('/main.js'):
            route.fulfill(status=200, content_type='text/javascript', body=main_js_content)
        else:
            route.continue_()

    page.route("**/*.js", handle_route)

    page.on("pageerror", lambda err: print(f"PAGEERROR name={err.name}, message={err.message}"))
    page.on("console", lambda msg: print(f"CONSOLE {msg.type}: {msg.text}"))

    page.goto("http://localhost:8080/static/index.html")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)

    state_defined = page.evaluate("() => typeof window.state !== 'undefined'")
    print(f"window.state defined: {state_defined}")

    browser.close()
