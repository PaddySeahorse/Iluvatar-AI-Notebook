"""Kernel process management.

This module contains the :class:`KernelManager` (a thread-safe supervisor that
owns a child process executing user Python code) and the :func:`kernel_worker`
entry point run inside that child process.

Concurrency safety (ISSUE-003): all mutable kernel state is encapsulated inside
:class:`KernelManager` and ``execute`` serialises send/get_result under an
execution lock so concurrent requests cannot interleave.

A watchdog thread (ISSUE-010) proactively restarts the kernel if it dies so the
next request stays warm.
"""

import os
import signal
import threading
import multiprocessing as mp


def kernel_worker(cmd_q, res_q):
    import io, sys, base64, traceback, ast, subprocess, shlex

    kernel_namespace = {'__builtins__': __builtins__}
    current_displays = []

    def custom_display(*args, **kwargs):
        for arg in args:
            if arg is not None:
                if hasattr(arg, '_repr_html_'):
                    current_displays.append({'type': 'html', 'data': arg._repr_html_()})
                else:
                    current_displays.append({'type': 'text', 'data': repr(arg)})

    kernel_namespace['display'] = custom_display

    def exec_with_capture(py_code):
        try:
            block = ast.parse(py_code)
            if block.body and isinstance(block.body[-1], ast.Expr):
                last_expr = block.body[-1]
                other_nodes = block.body[:-1]

                if other_nodes:
                    mod = ast.Module(body=other_nodes, type_ignores=[])
                    co = compile(mod, '<string>', 'exec')
                    exec(co, kernel_namespace)

                expr_mod = ast.Expression(body=last_expr.value)
                co_expr = compile(expr_mod, '<string>', 'eval')
                res = eval(co_expr, kernel_namespace)

                if res is not None:
                    if hasattr(res, '_repr_html_'):
                        current_displays.append({'type': 'html', 'data': res._repr_html_()})
                    else:
                        current_displays.append({'type': 'text_repr', 'data': repr(res)})
            else:
                exec(py_code, kernel_namespace)
        except Exception:
            raise

    while True:
        try:
            task = cmd_q.get()
            if task is None:
                break

            code = task.get('code', '')

            stdout_capture = io.StringIO()
            stderr_capture = io.StringIO()
            old_stdout = sys.stdout
            old_stderr = sys.stderr
            sys.stdout = stdout_capture
            sys.stderr = stderr_capture
            current_displays.clear()
            success = True

            try:
                lines = code.split('\n')
                current_py_lines = []
                for line in lines:
                    stripped = line.strip()
                    if stripped.startswith('!'):
                        if current_py_lines:
                            exec_with_capture('\n'.join(current_py_lines))
                            current_py_lines = []
                        cmd = stripped[1:].strip()
                        if cmd:
                            try:
                                cmd_args = shlex.split(cmd)
                            except ValueError as exc:
                                raise Exception(f"Invalid shell command syntax: {exc}") from exc

                            process = subprocess.Popen(
                                cmd_args, shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                            )
                            out, err = process.communicate()
                            if out: sys.stdout.write(out)
                            if err: sys.stderr.write(err)
                            if process.returncode != 0:
                                raise Exception(f"Command '{cmd}' failed with exit status {process.returncode}")
                    else:
                        current_py_lines.append(line)

                if current_py_lines:
                    exec_with_capture('\n'.join(current_py_lines))

            except KeyboardInterrupt:
                success = False
                sys.stderr.write("\nKeyboardInterrupt: Kernel execution interrupted by user.\n")
            except Exception:
                success = False
                traceback.print_exc(file=sys.stderr)
            finally:
                sys.stdout = old_stdout
                sys.stderr = old_stderr

            stdout_output = stdout_capture.getvalue()
            stderr_output = stderr_capture.getvalue()
            html_outputs = [d['data'] for d in current_displays if d['type'] == 'html']
            html_content = '\n'.join(html_outputs) if html_outputs else ""
            text_reprs = [d['data'] for d in current_displays if d['type'] in ('text', 'text_repr')]
            if text_reprs:
                if stdout_output and not stdout_output.endswith('\n'):
                    stdout_output += '\n'
                stdout_output += '\n'.join(text_reprs) + '\n'

            captured_plots_list = []
            try:
                import matplotlib.pyplot as plt
                if plt.get_fignums():
                    for fig_num in plt.get_fignums():
                        fig = plt.figure(fig_num)
                        buf = io.BytesIO()
                        fig.savefig(buf, format='png', bbox_inches='tight')
                        buf.seek(0)
                        captured_plots_list.append(base64.b64encode(buf.read()).decode('utf-8'))
                    plt.close('all')
            except Exception as e:
                stderr_output += f"\n[Matplotlib Capture Warning]: Failed to capture plots: {str(e)}"

            vars_list = []
            for k, v in kernel_namespace.items():
                if k.startswith('_') or k in ['__builtins__', 'display', 'sys', 'io', 'time', 'base64', 'traceback', 'threading', 'random', 'requests', 'matplotlib', 'plt', 'np', 'numpy']:
                    continue
                v_type = type(v).__name__
                v_repr = ""
                shape = None
                try:
                    if hasattr(v, 'shape'):
                        shape = str(list(v.shape)) if hasattr(v.shape, '__iter__') else str(v.shape)
                    if hasattr(v, '__len__') and not isinstance(v, (str, bytes)):
                        v_repr = f"{v_type} (len={len(v)})"
                    else:
                        v_repr = repr(v)
                        if len(v_repr) > 100: v_repr = v_repr[:100] + "..."
                except Exception:
                    v_repr = "<Unable to display>"
                vars_list.append({'name': k, 'type': v_type, 'repr': v_repr, 'shape': shape})
            vars_list.sort(key=lambda x: x['name'])

            res_q.put({
                'success': success,
                'stdout': stdout_output,
                'stderr': stderr_output,
                'html': html_content,
                'plots': captured_plots_list,
                'variables': vars_list
            })

        except KeyboardInterrupt:
            pass
        except Exception as e:
            traceback.print_exc()
            res_q.put({
                'success': False,
                'stdout': '',
                'stderr': f"Worker internal error: {str(e)}",
                'html': '',
                'plots': [],
                'variables': []
            })


class KernelManager:
    # How often (seconds) the watchdog checks kernel health
    WATCHDOG_INTERVAL = 2

    def __init__(self):
        self._lock = threading.RLock()
        self._execution_lock = threading.Lock()
        self.cmd_queue = None
        self.res_queue = None
        self.kernel_process = None
        self.cached_variables = []
        # Tracks whether we're intentionally stopping (e.g. during restart)
        self._restarting = False
        self._watchdog_thread = None
        self._watchdog_stop = threading.Event()

    # ------------------------------------------------------------------ #
    #  Internal helpers (must be called with _lock held)                   #
    # ------------------------------------------------------------------ #
    def _spawn_kernel(self):
        """Spawn a fresh kernel process. Caller must hold self._lock."""
        self.cmd_queue = mp.Queue()
        self.res_queue = mp.Queue()
        self.kernel_process = mp.Process(
            target=kernel_worker,
            args=(self.cmd_queue, self.res_queue),
            daemon=True,
        )
        self.kernel_process.start()

    # ------------------------------------------------------------------ #
    #  Watchdog                                                             #
    # ------------------------------------------------------------------ #
    def _watchdog_loop(self):
        """Background thread: restart the kernel if it dies unexpectedly."""
        while not self._watchdog_stop.is_set():
            self._watchdog_stop.wait(timeout=self.WATCHDOG_INTERVAL)
            if self._watchdog_stop.is_set():
                break
            with self._lock:
                if self._restarting:
                    continue
                if self.kernel_process is None or not self.kernel_process.is_alive():
                    # Kernel died — proactively restart so next request is warm
                    try:
                        self._spawn_kernel()
                    except Exception:
                        pass  # Will retry next cycle

    def start_watchdog(self):
        """Start the watchdog thread (idempotent)."""
        if self._watchdog_thread is not None and self._watchdog_thread.is_alive():
            return
        self._watchdog_stop.clear()
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            name="KernelWatchdog",
            daemon=True,
        )
        self._watchdog_thread.start()

    def stop_watchdog(self):
        """Stop the watchdog thread."""
        self._watchdog_stop.set()

    # ------------------------------------------------------------------ #
    #  Public API                                                           #
    # ------------------------------------------------------------------ #
    def ensure_kernel(self):
        """Ensure the kernel is running; start it if not (synchronous guarantee)."""
        with self._lock:
            if self.kernel_process is None or not self.kernel_process.is_alive():
                self._spawn_kernel()

    def warm_start(self):
        """Pre-start kernel and watchdog so the first request has no cold-start delay."""
        self.ensure_kernel()
        self.start_watchdog()

    def interrupt(self):
        with self._lock:
            if self.kernel_process and self.kernel_process.is_alive():
                try:
                    os.kill(self.kernel_process.pid, signal.SIGINT)
                    return True
                except Exception:
                    return False
            return False

    def get_variables(self):
        with self._lock:
            return list(self.cached_variables)

    def set_variables(self, variables):
        with self._lock:
            self.cached_variables = variables

    def send_code(self, code):
        with self._lock:
            if self.cmd_queue is None:
                raise RuntimeError("Kernel not initialized")
            self.cmd_queue.put({"code": code})

    def get_result(self):
        with self._lock:
            if self.res_queue is None:
                raise RuntimeError("Kernel not initialized")
            return self.res_queue.get()

    def execute(self, code):
        with self._execution_lock:
            self.ensure_kernel()
            self.send_code(code)
            result = self.get_result()
            if 'variables' in result:
                self.set_variables(result['variables'])
            return result

    def is_kernel_alive(self):
        with self._lock:
            return self.kernel_process is not None and self.kernel_process.is_alive()

    def is_watchdog_alive(self):
        return self._watchdog_thread is not None and self._watchdog_thread.is_alive()
