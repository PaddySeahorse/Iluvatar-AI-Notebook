# Iluvatar AI Notebook 依赖管理与环境构建方案

> 基于《Iluvatar AI Notebook 是否应该复用 Jupyter 的库？》分析报告，制定内核迁移的依赖管理策略与环境构建方案。

---

## 1. 新增依赖总览

### 1.1 依赖清单

| 包名 | 版本 | 大小 | 用途 | 必要性 | 许可证 |
|------|------|------|------|--------|--------|
| `jupyter_client` | >= 8.0 | ~400KB | 内核管理、ZMQ 五通道通信 | **必须** | BSD-3 |
| `ipykernel` | >= 6.25 | ~500KB | Python 内核实现（IPython 执行引擎） | **必须** | BSD-3 |
| `ipython` | >= 8.0 | ~5MB | 交互式 Python shell（ipykernel 依赖） | **必须** | BSD-3 |
| `pyzmq` | >= 25.0 | ~3MB | ZeroMQ Python 绑定（jupyter_client 依赖） | **必须** | BSD-3 |
| `tornado` | >= 6.3 | ~1.5MB | 异步 IOLoop（ipykernel 内部使用） | **必须** | Apache-2.0 |
| `nbformat` | >= 5.9 | ~200KB | `.ipynb` 文件格式标准读写 | **推荐** | BSD-3 |
| `jedi` | >= 0.19 | ~2MB | Python 代码补全引擎 | **推荐** | MIT |
| `traitlets` | >= 5.0 | ~300KB | 配置系统（Jupyter 生态基础库） | **间接依赖** | BSD-3 |
| `jupyter_core` | >= 5.0 | ~200KB | Jupyter 核心工具（路径、配置） | **间接依赖** | BSD-3 |

**合计新增依赖：约 12-15 MB（不含 torch-iluvatar 等现有 GPU 依赖）**

### 1.2 现有依赖（保持不变）

| 包名 | 版本 | 用途 |
|------|------|------|
| Flask | >= 3.0 | Web 框架 |
| matplotlib | >= 3.7 | 图表绘制 |
| requests | 最新 | HTTP 客户端 |
| pynvml | 最新 | NVIDIA GPU 监控（可替换为 IXUCA SDK） |
| torch-iluvatar | 天数智芯官方 | Iluvatar GPU 深度学习框架 |
| IXUCA SDK | 天数智芯官方 | Iluvatar GPU 管理工具 |

---

## 2. 依赖图谱

### 2.1 直接依赖关系

```
Iluvatar AI Notebook
├── jupyter_client ──────► ZMQ 五通道通信协议
│   ├── pyzmq (ZeroMQ)
│   ├── tornado (IOLoop)
│   ├── traitlets (配置)
│   └── jupyter_core (工具)
│
├── ipykernel ───────────► Python 内核执行引擎
│   ├── ipython (shell 引擎)
│   │   ├── jedi (补全)
│   │   └── ...
│   ├── jupyter_client (通信)
│   └── tornado (IOLoop)
│
├── nbformat ────────────► .ipynb 文件读写
│   └── jsonschema
│
└── Flask ───────────────► Web 服务（保持不变）
```

### 2.2 与现有 Flask 应用的兼容性

| 潜在冲突点 | 分析 | 解决方案 |
|-----------|------|---------|
| Tornado vs Flask | `ipykernel` 内部使用 Tornado IOLoop，但 Flask 使用同步模型 | ipykernel 运行在子进程中，IOLoop 在子进程内，与 Flask 主进程隔离 |
| ZMQ 端口冲突 | jupyter_client 使用随机端口分配 | 默认行为已避免冲突，可配置 `connection_file_dir` 指定连接文件目录 |
| Python 版本要求 | jupyter_client 8.x 要求 Python >= 3.8 | 与 Iluvatar 项目当前 Python 版本要求一致 |
| 国产芯片系统兼容 | pyzmq 依赖 libzmq C 库 | 天数智芯系统预装 libzmq 或通过 pip 安装预编译 wheel |

---

## 3. 环境构建方案

### 3.1 requirements.txt 更新

```txt
# requirements.txt — Iluvatar AI Notebook

# ── Web 框架 ──────────────────────────────────────
Flask>=3.0
flask-cors>=4.0

# ── Jupyter 内核生态（新增）────────────────────────
jupyter_client>=8.0
ipykernel>=6.25
ipython>=8.0
nbformat>=5.9
pyzmq>=25.0

# ── 数据科学 ──────────────────────────────────────
matplotlib>=3.7
numpy>=1.24
pandas>=2.0

# ── 代码分析 ──────────────────────────────────────
pylint>=3.0

# ── GPU 监控 ──────────────────────────────────────
# pynvml  # 如果不再需要 NVIDIA 监控，可移除
# 替换为天数智芯 SDK（由系统管理员预装）

# ── 工具库 ────────────────────────────────────────
requests>=2.31
python-dotenv>=1.0

# ── 开发依赖 ──────────────────────────────────────
pytest>=7.0
pytest-asyncio>=0.21
pytest-mock>=3.12
```

### 3.2 安装步骤

```bash
# 步骤 1：确认 Python 环境
python --version  # 需要 >= 3.8

# 步骤 2：安装新增依赖
pip install --break-system-packages \
    jupyter_client>=8.0 \
    ipykernel>=6.25 \
    nbformat>=5.9 \
    pyzmq>=25.0

# 步骤 3：验证安装
python -c "import jupyter_client; print('jupyter_client', jupyter_client.__version__)"
python -c "import ipykernel; print('ipykernel', ipykernel.__version__)"
python -c "import zmq; print('pyzmq', zmq.__version__)"

# 步骤 4：安装 ipykernel 到 Jupyter 内核注册表
python -m ipykernel install --user --name=python3 --display-name="Python 3"
```

### 3.3 天数智芯 GPU 环境安装

```bash
# 步骤 1：确认 Iluvatar SDK 已安装
ixuca-smi --version  # 验证 IXUCA SDK 可用

# 步骤 2：确认 torch-iluvatar 可调用 GPU
python -c "
import torch
print('torch-iluvatar version:', torch.__version__)
print('GPU available:', torch.cuda.is_available())
print('GPU count:', torch.cuda.device_count())
"

# 步骤 3：确保 LD_LIBRARY_PATH 包含 IXUCA 库路径
export LD_LIBRARY_PATH=/usr/local/ixuca/lib:$LD_LIBRARY_PATH
```

---

## 4. Docker 构建方案

### 4.1 Dockerfile

```dockerfile
# Dockerfile — Iluvatar AI Notebook
FROM python:3.10-slim

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libzmq3-dev \
    && rm -rf /var/lib/apt/lists/*

# 创建应用目录
WORKDIR /app

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir --break-system-packages -r requirements.txt

# 安装 ipykernel 到内核注册表
RUN python -m ipykernel install --user --name=python3 --display-name="Python 3"

# 复制应用代码
COPY . .

# 创建内核连接文件目录
RUN mkdir -p /tmp/iluvatar-kernels

# 暴露端口
EXPOSE 5000

# 启动应用
CMD ["python", "app.py"]
```

### 4.2 Docker Compose（GPU 版本）

```yaml
# docker-compose.yml
version: '3.8'

services:
  iluvatar-notebook:
    build: .
    ports:
      - "5000:5000"
    environment:
      - ILUVATAR_KERNEL_TYPE=ai-optimized
      - IXUCA_VISIBLE_DEVICES=0
      - LD_LIBRARY_PATH=/usr/local/ixuca/lib
      - ILUVATAR_CACHE_DIR=/tmp/iluvatar-cache
      - USE_NEW_KERNEL=true
      - NEW_KERNEL_RATIO=1.0
    volumes:
      - ./notebooks:/app/notebooks
      - /usr/local/ixuca:/usr/local/ixuca:ro  # 挂载 IXUCA SDK
    tmpfs:
      - /tmp/iluvatar-kernels:size=100M
      - /tmp/iluvatar-cache:size=1G
    restart: unless-stopped
    # GPU 直通（天数智芯环境）
    devices:
      - /dev/ixuca:/dev/ixuca
    deploy:
      resources:
        reservations:
          devices:
            - driver: ixuca
              count: 1
              capabilities: [gpu]
```

### 4.3 多阶段构建（可选，减小镜像体积）

```dockerfile
# 多阶段 Dockerfile — 生产优化
FROM python:3.10-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libzmq3-dev && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --break-system-packages \
    --target=/install -r requirements.txt

# ── 运行时镜像 ─────────────────────────────────────
FROM python:3.10-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libzmq5 && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local/lib/python3.10/site-packages/
COPY . /app
WORKDIR /app

RUN python -m ipykernel install --user --name=python3 --display-name="Python 3"
RUN mkdir -p /tmp/iluvatar-kernels

EXPOSE 5000
CMD ["python", "app.py"]
```

---

## 5. 版本锁定策略

### 5.1 版本约束原则

| 约束级别 | 说明 | 示例 |
|---------|------|------|
| **最低版本** | 使用 `>=` 确保获取功能 | `jupyter_client>=8.0` |
| **兼容范围** | 使用 `~=` 允许补丁更新 | `ipykernel~=6.25` |
| **精确锁定** | 生产环境使用 `pip freeze` 锁定 | `jupyter_client==8.6.0` |

### 5.2 生成锁定文件

```bash
# 开发环境：生成宽松版本
pip freeze | grep -E "jupyter|ipykernel|ipython|pyzmq|nbformat|tornado|traitlets|jedi" > requirements-jupyter.txt

# 生产环境：完整锁定
pip freeze > requirements-lock.txt
```

### 5.3 依赖更新策略

| 场景 | 策略 |
|------|------|
| 安全补丁 | 第一时间更新，回归测试通过后部署 |
| 小版本升级 | 月度审查，非阻塞更新 |
| 大版本升级 | 季度评估，需完整测试 + 灰度发布 |
| jupyter_client 大版本 | 关注 Changelog，确保 Provisioner API 兼容 |

---

## 6. 构建自动化

### 6.1 Makefile

```makefile
# Makefile — Iluvatar AI Notebook

.PHONY: install install-dev test lint build-docker run clean

# 安装生产依赖
install:
	pip install --break-system-packages -r requirements.txt
	python -m ipykernel install --user --name=python3 --display-name="Python 3"

# 安装开发依赖
install-dev: install
	pip install --break-system-packages pytest pytest-asyncio pytest-mock

# 运行测试
test:
	pytest tests/ -v --tb=short

# 代码检查
lint:
	pylint core/ --disable=C0114,C0115,C0116

# 构建 Docker 镜像
build-docker:
	docker build -t iluvatar-ai-notebook:latest .

# 运行开发服务器
run:
	python app.py

# 清理临时文件
clean:
	rm -rf /tmp/iluvatar-kernels/*
	rm -rf __pycache__ core/__pycache__ core/routes/__pycache__
	find . -name "*.pyc" -delete
```

### 6.2 GitHub Actions CI

```yaml
# .github/workflows/test.yml
name: Test

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.9", "3.10", "3.11"]

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}

      - name: Install system dependencies
        run: |
          sudo apt-get update
          sudo apt-get install -y libzmq3-dev

      - name: Install Python dependencies
        run: |
          pip install --break-system-packages -r requirements.txt
          pip install --break-system-packages pytest pytest-asyncio pytest-mock
          python -m ipykernel install --user --name=python3 --display-name="Python 3"

      - name: Run tests
        run: pytest tests/ -v --tb=short --ignore=tests/e2e --ignore=tests/integration/test_iluvatar_provisioner.py

  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.10"
      - run: pip install pylint
      - run: pylint core/ --disable=C0114,C0115,C0116
```

---

## 7. 依赖安全审计

### 7.1 审计工具

```bash
# 使用 pip-audit 检查已知漏洞
pip install pip-audit
pip-audit

# 使用 safety 检查
pip install safety
safety check --full-report

# 使用 pip-licenses 检查许可证合规性
pip install pip-licenses
pip-licenses --summary
```

### 7.2 关键依赖安全性评估

| 依赖 | 维护状态 | 已知漏洞 | 供应链风险 |
|------|---------|---------|-----------|
| jupyter_client | 活跃维护 | 无高危 | 低（Jupyter 官方维护，10 年+ 历史） |
| ipykernel | 活跃维护 | 无高危 | 低（Jupyter 官方维护） |
| pyzmq | 活跃维护 | 无高危 | 低（ZMQ 官方 Python 绑定） |
| tornado | 活跃维护 | 无高危 | 低（Facebook 维护，广泛使用） |
| ipython | 活跃维护 | 无高危 | 低（Jupyter 官方维护） |

---

## 8. 依赖移除计划

### 8.1 迁移完成后可移除的旧依赖

| 依赖 | 原因 |
|------|------|
| `pynvml` | 替换为 IXUCA SDK 遥测 |
| 旧 `core/kernel.py` 中的自定义 IPC 逻辑 | 由 jupyter_client 替代 |

### 8.2 不可移除的依赖

| 依赖 | 原因 |
|------|------|
| Flask | 整个 Web 服务的基础 |
| matplotlib | 用户代码中可能使用 |
| torch-iluvatar | GPU 深度学习核心依赖 |

---

## 9. 故障排查

### 9.1 常见问题

| 问题 | 症状 | 解决方案 |
|------|------|---------|
| pyzmq 安装失败 | `pip install pyzmq` 报编译错误 | 安装系统包 `libzmq3-dev`：`apt-get install libzmq3-dev` |
| ipykernel 找不到 | `No module named 'ipykernel'` | 检查 pip 安装路径，确认 `python -m ipykernel` 可用 |
| ZMQ 端口冲突 | `Address already in use` | 配置 `KERNEL_CONFIG["connection_file_dir"]` 到独立目录 |
| Flask + Tornado 冲突 | 应用启动后无响应 | ipykernel 运行在子进程，不应有冲突；如有，检查是否在 Flask 主线程运行了 Tornado IOLoop |
| 天数智芯系统 libzmq 缺失 | 内核启动失败 | 编译安装 libzmq 或使用纯 Python zmq fallback |

### 9.2 诊断命令

```bash
# 检查 Python 环境
python -c "import sys; print(sys.version); print(sys.executable)"

# 检查关键依赖是否安装
python -c "
import jupyter_client; print('jupyter_client:', jupyter_client.__version__)
import ipykernel; print('ipykernel:', ipykernel.__version__)
import zmq; print('pyzmq:', zmq.__version__)
import tornado; print('tornado:', tornado.version)
"

# 检查内核规范文件
jupyter kernelspec list

# 测试内核启动
python -c "
from jupyter_client import KernelManager
km = KernelManager(kernel_name='python3')
km.start_kernel()
print('Kernel started:', km.is_alive())
km.shutdown_kernel()
print('Kernel shutdown OK')
"
```

---

**文档版本**: v1.0
**最后更新**: 2026-07-08
**负责人**: 待指定