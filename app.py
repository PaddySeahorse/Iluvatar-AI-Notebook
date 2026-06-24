import os
import sys
import io
import time
import base64
import traceback
import threading
import random
import requests
from flask import Flask, request, jsonify, send_from_directory, Response

# Load .env file manually if it exists to avoid hardcoding API secrets
if os.path.exists('.env'):
    with open('.env') as f:
        for line in f:
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                os.environ[k.strip()] = v.strip().strip("'").strip('"')

DEFAULT_API_URL = os.environ.get('OPENI_API_URL', 'https://token.openi.org.cn/v1/chat/completions')
DEFAULT_API_TOKEN = os.environ.get('OPENI_API_TOKEN', '')
DEFAULT_API_MODEL = os.environ.get('OPENI_API_MODEL', 'dsv4')

# Force matplotlib to use Agg backend so it doesn't open GUI windows
try:
    import matplotlib
    matplotlib.use('Agg')
except Exception:
    pass

app = Flask(__name__, static_folder='static')

# Thread lock for stdout redirection to prevent overlapping outputs
stdout_lock = threading.Lock()

# Persistent global namespace for cell execution (acting as the notebook kernel)
kernel_namespace = {
    '__builtins__': __builtins__,
}

# Real-time mock telemetry for Iluvatar (天数智芯) BI-150 GPU
gpu_state = {
    'name': 'Iluvatar BI-150 (天数智芯)',
    'vram_total': 32768,  # MB
    'vram_used': 3520,    # MB
    'utilization': 2.0,   # %
    'temperature': 45.0,  # °C
    'power_draw': 42.0,   # W
    'core_clock': 1350,   # MHz
    'memory_clock': 1000, # MHz
    'status': 'Idle'
}

# Thread to slowly decay GPU load back to idle
def gpu_decay_loop():
    global gpu_state
    while True:
        time.sleep(1)
        # Decay utilization
        if gpu_state['utilization'] > 5.0:
            gpu_state['utilization'] -= (gpu_state['utilization'] - 2.0) * 0.15
        else:
            gpu_state['utilization'] = max(1.0, gpu_state['utilization'] + random.uniform(-0.5, 0.5))

        # Decay VRAM
        target_vram = 3520 + (gpu_state['utilization'] - 2.0) * 80
        if gpu_state['vram_used'] > target_vram:
            gpu_state['vram_used'] -= (gpu_state['vram_used'] - target_vram) * 0.1
        else:
            gpu_state['vram_used'] += (target_vram - gpu_state['vram_used']) * 0.1
        
        # Clamp VRAM used
        gpu_state['vram_used'] = max(2000, min(gpu_state['vram_total'], int(gpu_state['vram_used'])))

        # Decay temperature
        target_temp = 42.0 + (gpu_state['utilization'] * 0.35)
        gpu_state['temperature'] += (target_temp - gpu_state['temperature']) * 0.1
        gpu_state['temperature'] = round(gpu_state['temperature'], 1)

        # Decay power draw
        target_power = 38.0 + (gpu_state['utilization'] * 2.2)
        gpu_state['power_draw'] += (target_power - gpu_state['power_draw']) * 0.15
        gpu_state['power_draw'] = round(gpu_state['power_draw'], 1)

        # Set status based on utilization
        if gpu_state['utilization'] > 50:
            gpu_state['status'] = 'Training / Computing'
        elif gpu_state['utilization'] > 15:
            gpu_state['status'] = 'Inference Active'
        else:
            gpu_state['status'] = 'Idle'

# Start the background decay thread
decay_thread = threading.Thread(target=gpu_decay_loop, daemon=True)
decay_thread.start()


@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')


@app.route('/static/<path:path>')
def serve_static(path):
    return send_from_directory(app.static_folder, path)


@app.route('/api/gpu_status', methods=['GET'])
def get_gpu_status():
    # Add a tiny bit of random jitter to parameters to feel alive
    util_jitter = max(0.0, min(100.0, gpu_state['utilization'] + random.uniform(-1.0, 1.0)))
    temp_jitter = round(max(35.0, min(95.0, gpu_state['temperature'] + random.uniform(-0.2, 0.2))), 1)
    power_jitter = round(max(30.0, min(300.0, gpu_state['power_draw'] + random.uniform(-1.5, 1.5))), 1)
    
    return jsonify({
        **gpu_state,
        'utilization': round(util_jitter, 1),
        'temperature': temp_jitter,
        'power_draw': power_jitter
    })


@app.route('/api/run_cell', methods=['POST'])
def run_cell():
    global gpu_state
    data = request.json or {}
    code = data.get('code', '')
    
    # Analyze code to simulate GPU load spikes for deep learning code
    code_lower = code.lower()
    is_dl_task = any(kw in code_lower for kw in ['torch', 'nn.module', 'tensor', 'cuda', 'device', 'train', 'fit', 'model', 'epochs'])
    
    if is_dl_task:
        # Spike the GPU stats instantly
        gpu_state['utilization'] = random.uniform(82.0, 96.0)
        gpu_state['vram_used'] = min(gpu_state['vram_total'], gpu_state['vram_used'] + random.randint(8000, 15000))
        gpu_state['temperature'] = min(85.0, gpu_state['temperature'] + 12.0)
        gpu_state['power_draw'] = random.uniform(190.0, 240.0)
        gpu_state['status'] = 'Computing (天数智芯 BI-150)'
    else:
        # Minor load spike for general code execution
        gpu_state['utilization'] = max(gpu_state['utilization'], random.uniform(12.0, 25.0))
        gpu_state['power_draw'] = max(gpu_state['power_draw'], random.uniform(70.0, 95.0))
        gpu_state['status'] = 'Active'

    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()
    
    start_time = time.time()
    success = True
    error_traceback = ""

    # Execute Python code in lock
    with stdout_lock:
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = stdout_capture
        sys.stderr = stderr_capture
        
        try:
            # Parse and execute python code or shell magic commands
            lines = code.split('\n')
            current_py_lines = []
            
            for line in lines:
                stripped = line.strip()
                if stripped.startswith('!'):
                    # Execute accumulated Python code first
                    if current_py_lines:
                        py_code = '\n'.join(current_py_lines)
                        current_py_lines = []
                        exec(py_code, kernel_namespace)
                    
                    # Execute the shell command
                    cmd = stripped[1:].strip()
                    if cmd:
                        import subprocess
                        process = subprocess.Popen(
                            cmd,
                            shell=True,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True
                        )
                        stdout_data, stderr_data = process.communicate()
                        if stdout_data:
                            sys.stdout.write(stdout_data)
                        if stderr_data:
                            sys.stderr.write(stderr_data)
                        if process.returncode != 0:
                            raise Exception(f"Command '{cmd}' failed with exit status {process.returncode}")
                else:
                    current_py_lines.append(line)
            
            # Execute remaining Python code
            if current_py_lines:
                py_code = '\n'.join(current_py_lines)
                exec(py_code, kernel_namespace)
        except Exception as e:
            success = False
            # Print the traceback directly to capture it in stderr
            traceback.print_exc(file=sys.stderr)
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

    elapsed_time = round(time.time() - start_time, 3)
    stdout_output = stdout_capture.getvalue()
    stderr_output = stderr_capture.getvalue()

    # Capture any figures created with matplotlib
    captured_plots_list = []
    try:
        import matplotlib.pyplot as plt
        if plt.get_fignums():
            for fig_num in plt.get_fignums():
                fig = plt.figure(fig_num)
                buf = io.BytesIO()
                fig.savefig(buf, format='png', bbox_inches='tight')
                buf.seek(0)
                img_base64 = base64.b64encode(buf.read()).decode('utf-8')
                captured_plots_list.append(img_base64)
            plt.close('all')
    except Exception as e:
        stderr_output += f"\n[Matplotlib Capture Warning]: Failed to capture plots: {str(e)}"

    return jsonify({
        'success': success,
        'stdout': stdout_output,
        'stderr': stderr_output,
        'elapsed_time': elapsed_time,
        'plots': captured_plots_list
    })


@app.route('/api/get_config', methods=['GET'])
def get_config():
    # Expose defaults loaded from env for initialization
    return jsonify({
        'default_url': DEFAULT_API_URL,
        'default_token': DEFAULT_API_TOKEN,
        'default_model': DEFAULT_API_MODEL
    })


@app.route('/api/ai_call', methods=['POST'])
def ai_call():
    data = request.json or {}
    url = data.get('url', DEFAULT_API_URL)
    token = data.get('token', DEFAULT_API_TOKEN)
    model = data.get('model', DEFAULT_API_MODEL)
    messages = data.get('messages', [])
    stream = data.get('stream', False)
    
    headers = {
        'Content-Type': 'application/json'
    }
    if token:
        headers['Authorization'] = f'Bearer {token}'
        
    payload = {
        'model': model,
        'messages': messages,
        'temperature': 0.7
    }
    if stream:
        payload['stream'] = True
    
    try:
        if stream:
            # Proxy streaming request to user-configured API URL
            response = requests.post(url, headers=headers, json=payload, timeout=45, stream=True)
            if response.status_code == 200:
                def generate():
                    for chunk in response.iter_lines():
                        if chunk:
                            yield chunk + b'\n'
                return Response(generate(), mimetype='text/event-stream')
            else:
                return jsonify({
                    'error': True,
                    'message': f"API returned status code {response.status_code}: {response.text}"
                }), response.status_code
        else:
            # Proxy request to user-configured API URL
            response = requests.post(url, headers=headers, json=payload, timeout=45)
            if response.status_code == 200:
                return jsonify(response.json())
            else:
                return jsonify({
                    'error': True,
                    'message': f"API returned status code {response.status_code}: {response.text}"
                }), response.status_code
        return jsonify({
            'error': True,
            'message': f"Failed to connect to the custom API server: {str(e)}"
        }), 500


@app.route('/api/lint_cell', methods=['POST'])
def lint_cell():
    import ast
    import builtins
    
    data = request.json or {}
    code = data.get('code', '')
    
    errors = []
    warnings = []
    
    # 1. Check syntax errors via AST parse
    try:
        root = ast.parse(code)
    except SyntaxError as e:
        errors.append({
            'line': e.lineno or 1,
            'col': e.offset or 1,
            'message': str(e)
        })
        return jsonify({
            'errors': errors,
            'warnings': warnings
        })
    except Exception as e:
        errors.append({
            'line': 1,
            'col': 1,
            'message': f"AST 解析未知错误: {str(e)}"
        })
        return jsonify({
            'errors': errors,
            'warnings': warnings
        })
        
    # 2. Check for undefined variables
    defined_names = set(dir(builtins))
    loaded_names = set()
    
    class NameFinder(ast.NodeVisitor):
        def visit_Name(self, node):
            if isinstance(node.ctx, ast.Store):
                defined_names.add(node.id)
            elif isinstance(node.ctx, ast.Load):
                loaded_names.add(node.id)
            self.generic_visit(node)
            
        def visit_Import(self, node):
            for alias in node.names:
                defined_names.add(alias.asname or alias.name)
            self.generic_visit(node)
            
        def visit_ImportFrom(self, node):
            for alias in node.names:
                defined_names.add(alias.asname or alias.name)
            self.generic_visit(node)
            
        def _add_func_args(self, args_node):
            for arg in args_node.args:
                defined_names.add(arg.arg)
            if args_node.vararg:
                defined_names.add(args_node.vararg.arg)
            if args_node.kwarg:
                defined_names.add(args_node.kwarg.arg)
            for arg in getattr(args_node, 'kwonlyargs', []):
                defined_names.add(arg.arg)
            
        def visit_FunctionDef(self, node):
            defined_names.add(node.name)
            self._add_func_args(node.args)
            self.generic_visit(node)

        def visit_AsyncFunctionDef(self, node):
            defined_names.add(node.name)
            self._add_func_args(node.args)
            self.generic_visit(node)

        def visit_Lambda(self, node):
            self._add_func_args(node.args)
            self.generic_visit(node)

        def visit_ClassDef(self, node):
            defined_names.add(node.name)
            self.generic_visit(node)

    NameFinder().visit(root)
    
    # Check loaded names against local definition and kernel namespace
    for name in loaded_names:
        if name not in defined_names and name not in kernel_namespace:
            class NameLocator(ast.NodeVisitor):
                def visit_Name(self, node):
                    if node.id == name and isinstance(node.ctx, ast.Load):
                        warnings.append({
                            'line': node.lineno,
                            'col': node.col_offset,
                            'message': f"未定义的变量: '{name}'"
                        })
            NameLocator().visit(root)
            
    return jsonify({
        'errors': errors,
        'warnings': warnings
    })


@app.route('/api/get_variables', methods=['GET'])
def get_variables():
    vars_list = []
    for k, v in kernel_namespace.items():
        if k.startswith('_') or k in ['__builtins__', 'sys', 'io', 'time', 'base64', 'traceback', 'threading', 'random', 'requests', 'matplotlib', 'plt', 'np', 'numpy']:
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
                if len(v_repr) > 100:
                    v_repr = v_repr[:100] + "..."
        except Exception:
            v_repr = "<Unable to display>"
            
        vars_list.append({
            'name': k,
            'type': v_type,
            'repr': v_repr,
            'shape': shape
        })
        
    vars_list.sort(key=lambda x: x['name'])
    return jsonify(vars_list)


if __name__ == '__main__':
    # Ensure static folder exists
    os.makedirs(app.static_folder, exist_ok=True)
    port = int(os.environ.get('OPENI_SELF_PORT', 5000))
    app.run(host='0.0.0.0', port=port)
