"""Measure page load time and kernel startup time of the Flask app."""
import time
import statistics
from playwright.sync_api import sync_playwright


def main() -> None:
    url = 'http://localhost:5000'
    runs = 3

    load_times: list[float] = []
    kernel_start_times: list[float] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        for i in range(runs):
            ctx = browser.new_context()
            page = ctx.new_page()
            page.on('console', lambda msg: print(f'[browser:{msg.type}] {msg.text}'))

            t0 = time.perf_counter()
            page.goto(url, wait_until='load')
            t_load = (time.perf_counter() - t0) * 1000

            page.wait_for_load_state('networkidle')
            t_full = (time.perf_counter() - t0) * 1000

            perf = page.evaluate(
                '''() => {
                    const e = performance.getEntriesByType("navigation")[0];
                    const paints = performance.getEntriesByType("paint");
                    const fcp = paints.find(p => p.name === "first-contentful-paint");
                    return {
                        domContentLoaded: e.domContentLoadedEventEnd,
                        loadEvent: e.loadEventEnd,
                        fcp: fcp ? fcp.startTime : null,
                        transferSize: e.transferSize,
                        encodedBodySize: e.encodedBodySize,
                    };
                }'''
            )
            resources = page.evaluate(
                '''() => performance.getEntriesByType("resource").map(r => ({
                    name: r.name.replace(location.origin, ""),
                    duration: Math.round(r.duration),
                    transferSize: r.transferSize,
                }))'''
            )

            print(f'\n--- Run {i + 1}/{runs} ---')
            print(f'goto(load)         : {t_load:7.1f} ms')
            print(f'goto->networkidle  : {t_full:7.1f} ms')
            print(f'DOMContentLoaded   : {perf["domContentLoaded"]:7.1f} ms')
            print(f'loadEventEnd       : {perf["loadEvent"]:7.1f} ms')
            print(f'First Contentful P.: {perf["fcp"]:7.1f} ms')
            print(f'resources          : {len(resources)}')
            for r in resources:
                print(f'  {r["duration"]:>5} ms  {r["transferSize"]:>7} B  {r["name"]}')

            t_k0 = time.perf_counter()
            kernels = page.evaluate(
                '''async () => {
                    const tries = ["/api/kernel/status", "/api/kernels", "/api/kernel"];
                    for (const u of tries) {
                        try {
                            const r = await fetch(u);
                            if (r.ok) return { url: u, status: r.status };
                        } catch (e) {}
                    }
                    return null;
                }'''
            )
            t_k1 = (time.perf_counter() - t_k0) * 1000
            if kernels:
                print(f'kernel probe OK    : {kernels["url"]} -> HTTP {kernels["status"]} in {t_k1:.1f} ms')
            else:
                print('kernel probe       : no /api/kernel/* endpoint exposed (client-side only)')

            load_times.append(t_full)
            kernel_start_times.append(t_k1)

            ctx.close()

        browser.close()

    print('\n========== Summary ==========')
    print(f'page full-load per run (ms): {[round(x, 1) for x in load_times]}')
    print(f'  median = {statistics.median(load_times):.1f} ms')
    print(f'  mean   = {statistics.mean(load_times):.1f} ms')
    print(f'kernel API probe latency per run (ms): {[round(x, 1) for x in kernel_start_times]}')
    print(f'  median = {statistics.median(kernel_start_times):.1f} ms')


if __name__ == '__main__':
    main()
