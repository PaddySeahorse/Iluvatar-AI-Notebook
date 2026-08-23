# Iluvatar AI Notebook 测试策略与灰度发布方案

> 基于《Iluvatar AI Notebook 是否应该复用 Jupyter 的库？》分析报告，制定内核迁移的测试策略与灰度发布方案。

---

## 1. 测试策略概述

### 1.1 测试金字塔

```
           ┌──────┐
           │ E2E  │  少量端到端场景（启动→执行→中断→关闭）
           ├──────┤
           │ 集成  │  内核与路由集成、GPU Provisioner 集成
           ├──────┤
           │ 单元  │  KernelManager 各方法、消息处理、路由逻辑
           └──────┘
```

### 1.2 测试目标

| 维度 | 目标 |
|------|------|
| 功能正确性 | 新旧内核执行相同代码输出一致 |
| 中断可靠性 | 中断成功率 > 99%，中断延迟 < 3 秒 |
| 流式输出 | 流式输出延迟 < 100ms（从 stdout 产生到前端渲染） |
| 向后兼容 | 现有 API 响应格式不变，现有前端无需改动 |
| 性能 | 内核启动时间 < 3 秒，代码执行时间无明显退化 |
| 稳定性 | 连续运行 24 小时无崩溃，内存无泄漏 |

---

## 2. 单元测试

### 2.1 测试范围

**文件**: `tests/unit/test_kernel_manager.py`

```python
"""
KernelManager 单元测试
"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from core.kernel import KernelManager


class TestKernelManagerLifecycle:
    """内核生命周期测试"""

    @patch("core.kernel.JupyterKernelManager")
    def test_start_kernel(self, mock_jkm):
        """测试内核启动"""
        km = KernelManager()
        km.start()

        mock_jkm.assert_called_once_with(kernel_name="python3")
        mock_jkm.return_value.start_kernel.assert_called_once()
        assert km.is_alive() is True

    @patch("core.kernel.JupyterKernelManager")
    def test_warm_start_idempotent(self, mock_jkm):
        """测试 warm_start 幂等性"""
        km = KernelManager()
        km.warm_start()
        km.warm_start()  # 第二次调用不应重复启动

        assert mock_jkm.return_value.start_kernel.call_count == 1

    @patch("core.kernel.JupyterKernelManager")
    def test_shutdown(self, mock_jkm):
        """测试内核关闭"""
        km = KernelManager()
        km.start()
        km.shutdown()

        mock_jkm.return_value.shutdown_kernel.assert_called_once()


class TestKernelManagerExecution:
    """代码执行测试"""

    @patch("core.kernel.JupyterKernelManager")
    def test_execute_returns_stdout(self, mock_jkm):
        """测试同步执行返回 stdout"""
        km = KernelManager()
        km._km = mock_jkm.return_value

        # Mock IOPub 消息流
        mock_client = MagicMock()
        mock_client.iopub_channel.return_value = [
            {"parent_header": {"msg_id": "abc"}, "msg_type": "stream",
             "content": {"name": "stdout", "text": "hello\n"}},
            {"parent_header": {"msg_id": "abc"}, "msg_type": "status",
             "content": {"execution_state": "idle"}},
        ]
        mock_client.execute.return_value = "abc"
        km._kc = mock_client

        result = km.execute("print('hello')")

        assert result["stdout"] == "hello\n"
        assert result["error"] is None

    @patch("core.kernel.JupyterKernelManager")
    def test_execute_captures_error(self, mock_jkm):
        """测试同步执行捕获错误"""
        km = KernelManager()
        km._kc = mock_client = MagicMock()
        mock_client.execute.return_value = "abc"
        mock_client.iopub_channel.return_value = [
            {"parent_header": {"msg_id": "abc"}, "msg_type": "error",
             "content": {"ename": "NameError", "evalue": "name 'x' is not defined",
                         "traceback": ["Traceback...", "NameError: name 'x' is not defined"]}},
            {"parent_header": {"msg_id": "abc"}, "msg_type": "status",
             "content": {"execution_state": "idle"}},
        ]

        result = km.execute("print(x)")

        assert result["error"] is not None
        assert "NameError" in result["error"]


class TestKernelManagerStream:
    """流式执行测试"""

    @patch("core.kernel.JupyterKernelManager")
    def test_execute_stream_yields_messages(self, mock_jkm):
        """测试流式执行产出消息"""
        km = KernelManager()
        km._kc = mock_client = MagicMock()
        mock_client.execute.return_value = "abc"
        mock_client.iopub_channel.return_value = [
            {"parent_header": {"msg_id": "abc"}, "msg_type": "status",
             "content": {"execution_state": "busy"}},
            {"parent_header": {"msg_id": "abc"}, "msg_type": "stream",
             "content": {"name": "stdout", "text": "line1\n"}},
            {"parent_header": {"msg_id": "abc"}, "msg_type": "stream",
             "content": {"name": "stdout", "text": "line2\n"}},
            {"parent_header": {"msg_id": "abc"}, "msg_type": "status",
             "content": {"execution_state": "idle"}},
        ]

        messages = list(km.execute_stream("print('line1'); print('line2')"))

        assert len(messages) == 4
        assert messages[0]["type"] == "status"
        assert messages[0]["execution_state"] == "busy"
        assert messages[1]["type"] == "stream"
        assert messages[1]["text"] == "line1\n"
        assert messages[3]["type"] == "status"
        assert messages[3]["execution_state"] == "idle"


class TestKernelManagerComplete:
    """补全测试"""

    @patch("core.kernel.JupyterKernelManager")
    def test_complete_returns_matches(self, mock_jkm):
        """测试补全返回匹配"""
        km = KernelManager()
        km._kc = mock_client = MagicMock()
        mock_client.complete.return_value = {
            "content": {
                "matches": ["DataFrame", "DataFrameGroupBy"],
                "cursor_start": 0,
                "cursor_end": 2,
            }
        }

        result = km.complete("pd.Da", 4)

        assert "DataFrame" in result["matches"]
        assert result["cursor_start"] == 0
```

### 2.2 测试清单

| 测试类 | 用例数 | 覆盖方法 |
|--------|--------|---------|
| `TestKernelManagerLifecycle` | 5 | start, warm_start, shutdown, restart, is_alive |
| `TestKernelManagerExecution` | 6 | execute (stdout, stderr, error, plot, html, mixed) |
| `TestKernelManagerStream` | 4 | execute_stream (stream, display_data, error, status) |
| `TestKernelManagerComplete` | 3 | complete (matches, no_match, timeout) |
| `TestKernelManagerInspect` | 3 | inspect (found, not_found, detail) |
| `TestKernelManagerInterrupt` | 2 | interrupt (success, failure) |
| `TestKernelManagerVariables` | 2 | get_variables (normal, empty) |

---

## 3. 集成测试

### 3.1 内核集成测试

**文件**: `tests/integration/test_kernel_integration.py`

```python
"""
内核集成测试（需要真实 ipykernel）
"""
import pytest
import time
from core.kernel import KernelManager


@pytest.fixture(scope="module")
def kernel():
    """模块级 fixture：启动真实内核"""
    km = KernelManager()
    km.start()
    yield km
    km.shutdown()


class TestKernelIntegration:
    """内核集成测试"""

    def test_execute_simple_code(self, kernel):
        """测试执行简单代码"""
        result = kernel.execute("x = 1 + 1\nprint(x)")
        assert result["stdout"].strip() == "2"
        assert result["error"] is None

    def test_execute_with_error(self, kernel):
        """测试执行报错代码"""
        result = kernel.execute("1 / 0")
        assert result["error"] is not None
        assert "ZeroDivisionError" in result["error"]

    def test_execute_stream(self, kernel):
        """测试流式输出"""
        messages = list(kernel.execute_stream(
            "for i in range(3):\n    print(i)"
        ))
        stdout_texts = [m["text"].strip() for m in messages if m["type"] == "stream"]
        assert stdout_texts == ["0", "1", "2"]

    def test_interrupt_long_running(self, kernel):
        """测试中断长时间运行代码"""
        import threading

        # 在后台线程执行长时间代码
        def execute_long():
            kernel.execute("while True: pass")

        t = threading.Thread(target=execute_long)
        t.start()

        time.sleep(1)  # 等待代码开始执行
        success = kernel.interrupt()
        assert success is True

        t.join(timeout=5)
        assert not t.is_alive()  # 执行线程应已结束

    def test_complete(self, kernel):
        """测试补全"""
        kernel.execute("import pandas as pd")
        result = kernel.complete("pd.Da", 4)
        assert len(result["matches"]) > 0

    def test_inspect(self, kernel):
        """测试内省"""
        kernel.execute("x = 42")
        result = kernel.inspect("x", 1)
        assert result["found"] is True

    def test_display_data(self, kernel):
        """测试富媒体输出"""
        result = kernel.execute(
            "import matplotlib.pyplot as plt\n"
            "plt.plot([1,2,3])\n"
            "plt.show()"
        )
        assert len(result["plots"]) >= 1  # 至少有一张图片

    def test_magics(self, kernel):
        """测试 IPython Magics"""
        result = kernel.execute("%timeit 1+1")
        assert result["error"] is None
        assert "ns" in result["stdout"] or "µs" in result["stdout"]
```

### 3.2 路由集成测试

**文件**: `tests/integration/test_routes_integration.py`

```python
"""
Flask 路由集成测试
"""
import pytest
import json
from app import create_app


@pytest.fixture
def client():
    app = create_app({"TESTING": True})
    with app.test_client() as client:
        yield client


class TestKernelRoutes:
    """路由集成测试"""

    def test_run_cell(self, client):
        """测试同步执行路由"""
        resp = client.post("/api/run_cell",
                           json={"code": "print('hello')"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["stdout"].strip() == "hello"
        assert data["error"] is None

    def test_run_cell_stream(self, client):
        """测试流式执行路由"""
        resp = client.post("/api/run_cell_stream",
                           json={"code": "for i in range(3): print(i)"})
        assert resp.status_code == 200
        assert resp.content_type == "text/event-stream"

        # 解析 SSE 流
        body = resp.get_data(as_text=True)
        lines = [l for l in body.split("\n") if l.startswith("data: ")]
        assert len(lines) >= 3  # 至少 3 条消息

    def test_kernel_status(self, client):
        """测试内核状态路由"""
        resp = client.get("/api/kernel_status")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["alive"] is True

    def test_complete(self, client):
        """测试补全路由"""
        client.post("/api/run_cell", json={"code": "import pandas as pd"})
        resp = client.post("/api/complete",
                           json={"code": "pd.Da", "cursor_pos": 4})
        data = resp.get_json()
        assert len(data["matches"]) > 0
```

### 3.3 GPU Provisioner 集成测试

**文件**: `tests/integration/test_iluvatar_provisioner.py`

```python
"""
Iluvatar Provisioner 集成测试（需要在 Iluvatar 硬件上运行）
"""
import pytest
import os
from core.iluvatar_provisioner import IluvatarProvisioner


@pytest.mark.iluvatar  # 标记为需要 Iluvatar 硬件
class TestIluvatarProvisioner:
    """GPU Provisioner 集成测试"""

    @pytest.mark.asyncio
    async def test_pre_launch_sets_env(self):
        """测试 pre_launch 设置环境变量"""
        provisioner = IluvatarProvisioner()
        kwargs = await provisioner.pre_launch(env={})

        env = kwargs["env"]
        assert "IXUCA_VISIBLE_DEVICES" in env
        assert "ILUVATAR_KERNEL_TYPE" in env
        assert env["ILUVATAR_KERNEL_TYPE"] == "ai-optimized"

    @pytest.mark.asyncio
    async def test_gpu_interrupt(self):
        """测试 GPU 中断"""
        provisioner = IluvatarProvisioner()
        import signal
        await provisioner.send_signal(signal.SIGINT)
        # 不应抛出异常
```

---

## 4. 端到端测试

### 4.1 E2E 场景

| 场景 | 描述 | 验证点 |
|------|------|--------|
| **基础执行** | 启动 Notebook → 输入代码 → 执行 → 查看输出 | 输出正确，无延迟 |
| **流式输出** | 执行长时间 GPU 训练代码 → 观察输出 | 实时输出逐行出现 |
| **中断** | 执行无限循环 → 点击中断 → 观察结果 | 3 秒内中断成功 |
| **补全** | 输入 `df.` → 按 Tab → 查看补全列表 | 补全列表正确 |
| **内省** | 输入 `?plt.plot` → 查看文档 | 文档正确显示 |
| **富媒体** | 执行 `plt.plot()` → 查看图片 | 图片内联显示 |
| **GPU 训练** | 执行 `torch-iluvatar` 训练代码 → 观察 GPU 遥测 | GPU 利用率正常，输出实时 |
| **错误恢复** | 执行错误代码 → 修复 → 重新执行 | 错误展示清晰，修复后可正常执行 |
| **多 Cell** | 连续执行多个 Cell → 观察变量共享 | 变量跨 Cell 共享 |
| **重启** | 重启内核 → 执行代码 → 验证状态 | 内核重启后状态干净 |

### 4.2 E2E 测试脚本（Playwright）

```python
# tests/e2e/test_notebook_e2e.py
import pytest
from playwright.sync_api import Page, expect


@pytest.mark.e2e
class TestNotebookE2E:
    """端到端测试"""

    def test_execute_code_and_see_output(self, page: Page):
        """测试执行代码并查看输出"""
        page.goto("http://localhost:5000")
        page.fill("[data-testid='cell-input']", "print('hello world')")
        page.click("[data-testid='run-button']")
        output = page.locator("[data-testid='cell-output']")
        expect(output).to_contain_text("hello world")

    def test_streaming_output(self, page: Page):
        """测试流式输出"""
        page.goto("http://localhost:5000")
        code = "import time\nfor i in range(5):\n    print(f'Step {i}')\n    time.sleep(0.5)"
        page.fill("[data-testid='cell-input']", code)
        page.click("[data-testid='run-button']")

        # 等待输出逐步出现
        for i in range(5):
            output = page.locator("[data-testid='cell-output']")
            expect(output).to_contain_text(f"Step {i}")

    def test_interrupt_loop(self, page: Page):
        """测试中断无限循环"""
        page.goto("http://localhost:5000")
        page.fill("[data-testid='cell-input']", "while True: pass")
        page.click("[data-testid='run-button']")
        page.wait_for_timeout(1000)
        page.click("[data-testid='interrupt-button']")
        # 验证内核状态恢复为 idle
        status = page.locator("[data-testid='kernel-status']")
        expect(status).to_contain_text("idle")
```

---

## 5. 对比测试

### 5.1 新旧内核输出对比

**目标**：确保新内核执行相同代码的输出与旧内核一致。

```python
"""
新旧内核输出对比测试
"""
import pytest

# 测试用例集
COMPARISON_TEST_CASES = [
    # (code, expected_stdout_pattern)
    ("print('hello')", "hello"),
    ("x = 1 + 1\nx", "2"),
    ("import numpy as np\nnp.array([1,2,3]).mean()", "2.0"),
    ("1/0", "ZeroDivisionError"),  # 错误信息
    ("print('a', end='')\nprint('b')", "ab"),
    # 更多用例...
]


def test_output_parity(legacy_kernel, new_kernel):
    """对比新旧内核输出"""
    for code, expected in COMPARISON_TEST_CASES:
        legacy_result = legacy_kernel.execute(code)
        new_result = new_kernel.execute(code)

        # 检查 stdout 内容一致
        assert legacy_result["stdout"].strip() == new_result["stdout"].strip(), \
            f"Mismatch for code: {code}"

        # 检查错误状态一致
        assert (legacy_result["error"] is None) == (new_result["error"] is None), \
            f"Error mismatch for code: {code}"
```

---

## 6. 性能测试

### 6.1 性能基准

| 指标 | 旧内核基线 | 新内核目标 | 测量方法 |
|------|-----------|-----------|---------|
| 内核冷启动时间 | ~1s | < 3s | `time.time()` 计时 |
| 内核热启动时间 | ~0.5s | < 1s | warm_start 后计时 |
| 简单代码执行 | ~10ms | < 50ms | `print('hello')` 执行时间 |
| 流式输出首字节延迟 | N/A（阻塞） | < 100ms | 从 execute 到第一条 stream 消息 |
| 中断延迟 | 0.5-2s | < 3s | 从中断请求到 idle 状态 |
| 内存占用（空闲） | ~50MB | < 150MB | `psutil` 测量 |
| 内存占用（执行中） | ~80MB | < 200MB | 执行大数组操作后 |

### 6.2 性能测试脚本

```python
"""
内核性能基准测试
"""
import time
import pytest
from core.kernel import KernelManager


class TestPerformance:
    """性能基准测试"""

    def test_startup_time(self):
        """测试启动时间"""
        start = time.time()
        km = KernelManager()
        km.start()
        elapsed = time.time() - start
        km.shutdown()
        assert elapsed < 3.0, f"Startup too slow: {elapsed:.2f}s"

    def test_execution_latency(self, kernel):
        """测试执行延迟"""
        start = time.time()
        for _ in range(100):
            kernel.execute("1+1")
        elapsed = time.time() - start
        avg = elapsed / 100
        assert avg < 0.05, f"Average execution too slow: {avg*1000:.1f}ms"

    def test_stream_first_byte(self, kernel):
        """测试流式输出首字节延迟"""
        start = time.time()
        gen = kernel.execute_stream("print('hello')")
        first_msg = next(gen)
        elapsed = time.time() - start
        assert elapsed < 0.1, f"First byte too slow: {elapsed*1000:.1f}ms"
```

---

## 7. 灰度发布方案

### 7.1 灰度架构

```
                        ┌─────────────────┐
                        │   用户请求       │
                        └────────┬────────┘
                                 │
                        ┌────────▼────────┐
                        │  灰度路由器     │
                        │ (Feature Flag)  │
                        └───┬─────────┬───┘
                            │         │
               ┌────────────▼─┐  ┌───▼────────────┐
               │ 新内核 (95%) │  │ 旧内核 (5%)    │
               │ jupyter_     │  │ multiprocessing│
               │ client +     │  │ Queue + exec() │
               │ ipykernel    │  │                │
               └──────────────┘  └────────────────┘
```

### 7.2 Feature Flag 实现

```python
# core/feature_flags.py
"""
功能开关 / 灰度控制
"""
import os
import random
import hashlib


class FeatureFlags:
    """功能开关管理器"""

    def __init__(self):
        # 默认使用新内核
        self._use_new_kernel = os.environ.get("USE_NEW_KERNEL", "true").lower() == "true"

        # 灰度比例 (0.0 ~ 1.0)，0 表示全旧，1 表示全新
        self._new_kernel_ratio = float(os.environ.get("NEW_KERNEL_RATIO", "1.0"))

        # 白名单用户（user_id 列表）
        self._whitelist = set(
            os.environ.get("NEW_KERNEL_WHITELIST", "").split(",")
        )

        # 黑名单用户（强制使用旧内核）
        self._blacklist = set(
            os.environ.get("NEW_KERNEL_BLACKLIST", "").split(",")
        )

    def should_use_new_kernel(self, user_id: str = None) -> bool:
        """判断是否使用新内核"""
        # 全局开关关闭
        if not self._use_new_kernel:
            return False

        # 黑名单
        if user_id and user_id in self._blacklist:
            return False

        # 白名单
        if user_id and user_id in self._whitelist:
            return True

        # 灰度比例
        if user_id and self._new_kernel_ratio < 1.0:
            bucket = int(hashlib.md5(user_id.encode()).hexdigest(), 16) % 100
            return bucket < self._new_kernel_ratio * 100

        return True

    def get_kernel_manager(self, user_id: str = None):
        """根据灰度策略返回对应的 KernelManager"""
        if self.should_use_new_kernel(user_id):
            from core.kernel import KernelManager as NewKernelManager
            return NewKernelManager()
        else:
            from core.kernel_legacy import LegacyKernelManager
            return LegacyKernelManager()
```

### 7.3 灰度阶段

| 阶段 | 时长 | 新内核比例 | 目标用户 | 观察指标 | 回滚条件 |
|------|------|-----------|---------|---------|---------|
| **阶段 0：内部测试** | 2-3 天 | 100%（开发团队） | 开发团队全员 | 主观体验、Bug 数量 | 有 P0 问题立即回滚 |
| **阶段 1：金丝雀** | 2-3 天 | 1% | 随机抽样 | 错误率、中断成功率 | 错误率 > 旧内核 2x |
| **阶段 2：小范围** | 3-5 天 | 10% | 随机抽样 | 错误率、延迟、用户反馈 | 错误率 > 旧内核 1.5x |
| **阶段 3：半量** | 3-5 天 | 50% | 随机抽样 | 全量指标对比 | 错误率 > 旧内核 1.2x |
| **阶段 4：全量** | 持续 | 100% | 全部用户 | 持续监控 | 严重问题回滚到阶段 3 |

### 7.4 监控指标

```python
# core/monitoring.py
"""
内核监控埋点
"""
import time
import logging
from functools import wraps

logger = logging.getLogger("kernel.monitoring")


class KernelMetrics:
    """内核指标收集器"""

    def __init__(self):
        self.metrics = {
            "execution_count": 0,
            "execution_errors": 0,
            "interrupt_count": 0,
            "interrupt_success": 0,
            "stream_count": 0,
            "kernel_restarts": 0,
            "total_execution_time_ms": 0,
        }

    def record_execution(self, duration_ms: float, has_error: bool):
        self.metrics["execution_count"] += 1
        self.metrics["total_execution_time_ms"] += duration_ms
        if has_error:
            self.metrics["execution_errors"] += 1

    def record_interrupt(self, success: bool):
        self.metrics["interrupt_count"] += 1
        if success:
            self.metrics["interrupt_success"] += 1

    def record_restart(self):
        self.metrics["kernel_restarts"] += 1

    @property
    def error_rate(self) -> float:
        if self.metrics["execution_count"] == 0:
            return 0.0
        return self.metrics["execution_errors"] / self.metrics["execution_count"]

    @property
    def interrupt_success_rate(self) -> float:
        if self.metrics["interrupt_count"] == 0:
            return 1.0
        return self.metrics["interrupt_success"] / self.metrics["interrupt_count"]

    @property
    def avg_execution_time_ms(self) -> float:
        if self.metrics["execution_count"] == 0:
            return 0.0
        return self.metrics["total_execution_time_ms"] / self.metrics["execution_count"]

    def to_dict(self) -> dict:
        return {
            **self.metrics,
            "error_rate": self.error_rate,
            "interrupt_success_rate": self.interrupt_success_rate,
            "avg_execution_time_ms": self.avg_execution_time_ms,
        }


# 全局指标实例
kernel_metrics = KernelMetrics()
```

### 7.5 回滚流程

```
发现 P0 问题
    │
    ▼
确认问题（5 分钟内）
    │
    ├─ 修改 Feature Flag: NEW_KERNEL_RATIO=0.0
    │   （或 USE_NEW_KERNEL=false）
    │
    ├─ 重启服务（或热加载配置）
    │
    ▼
全量回滚到旧内核（< 1 分钟生效）
    │
    ▼
分析问题根因 → 修复 → 重新走灰度流程
```

---

## 8. 测试环境

| 环境 | 用途 | 配置 |
|------|------|------|
| **本地开发** | 单元测试、集成测试 | macOS/Linux，无 GPU |
| **CI/CD** | 自动化测试流水线 | Linux，pytest + GitHub Actions |
| **GPU 测试** | Iluvatar Provisioner 测试 | 天垓 100/150 服务器 |
| **预发布** | 灰度前最终验证 | 与生产环境一致的配置 |
| **生产** | 灰度发布 | 全量用户环境 |

---

**文档版本**: v1.0
**最后更新**: 2026-07-08
**负责人**: 待指定