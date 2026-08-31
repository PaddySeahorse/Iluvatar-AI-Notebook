#!/usr/bin/env python3
"""Dry-run the three demo cells on CPU (no Iluvatar GPU required).

Verifies syntax, execution flow, figure generation and the expected
error of inference_cell / benchmark_cell / error_cell before they are
frozen into the demo mock and recorded on the MR-100 machine.

Run:  python3 demo/dryrun_cells.py
"""
import os
import sys
import traceback

os.environ.setdefault("MPLBACKEND", "Agg")

import matplotlib.pyplot as plt  # noqa: E402

CELLS_DIR = os.path.join(os.path.dirname(__file__), "cells")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)  # cells use relative paths: models/..., assets/...

failures = []

# Shared namespace across cells — mirrors the persistent Jupyter kernel.
KERNEL = {"__name__": "__main__"}


def run_cell(name, expect_error=None):
    path = os.path.join(CELLS_DIR, name)
    src = open(path, encoding="utf-8").read()
    figures_before = set(plt.get_fignums())
    try:
        exec(compile(src, path, "exec"), KERNEL)  # noqa: S102
        if expect_error:
            failures.append(f"{name}: expected {expect_error}, got none")
        else:
            new_figs = set(plt.get_fignums()) - figures_before
            status = f"OK (figures: {len(new_figs)})" if new_figs else "OK (no figure)"
            print(f"  [PASS] {name}: {status}")
    except Exception as e:  # noqa: BLE001
        if expect_error and (expect_error == type(e).__name__ or expect_error in str(e)):
            print(f"  [PASS] {name}: expected error triggered -> {type(e).__name__}: {e}")
        else:
            failures.append(f"{name}: {type(e).__name__}: {e}")
            traceback.print_exc()


print("== cell 1: inference_cell.py ==")
run_cell("inference_cell.py")

print("== cell 2: benchmark_cell.py (reuses model/device from cell 1) ==")
run_cell("benchmark_cell.py")

print("== cell 3: error_cell.py (expects FileNotFoundError) ==")
run_cell("error_cell.py", expect_error="not-exist.jpg")

print()
if failures:
    print("DRY-RUN FAILED:")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("DRY-RUN PASSED: all three cells behave as scripted.")
