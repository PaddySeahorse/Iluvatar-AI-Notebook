#!/usr/bin/env bash
# MR-100 真机演示环境准备脚本（在 MR-100 机器的 notebook 工作目录执行）
#
# 用法:  bash demo/prep_inference_env.sh
# 产出:  - ultralytics 已安装（国内镜像）
#        - assets/demo.jpg（取自 ultralytics 自带测试图，免外网）
#        - models/yolov8s.pt（多镜像源下载，已存在则跳过）
#        - GPU 环境体检报告
set -uo pipefail

PIP_INDEX="${PIP_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"
YOLO_RELEASE="https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8s.pt"
# 国内 GitHub release 加速镜像，依次尝试
YOLO_MIRRORS=(
    "https://mirror.ghproxy.com/${YOLO_RELEASE}"
    "https://ghfast.top/${YOLO_RELEASE}"
    "https://gh-proxy.com/${YOLO_RELEASE}"
)
YOLO_MIN_BYTES=$((20 * 1024 * 1024))   # yolov8s.pt 约 21.5MB，低于 20MB 视为下载不完整

PASS=()
FAIL=()

report() {
    echo ""
    echo "==================== 环境体检报告 ===================="
    for item in "${PASS[@]}"; do echo "  [PASS] $item"; done
    for item in "${FAIL[@]}"; do echo "  [FAIL] $item"; done
    echo "======================================================"
    if [ "${#FAIL[@]}" -gt 0 ]; then
        echo "存在未通过项，请先解决再进行演示录制。"
        exit 1
    fi
    echo "环境就绪，可以开始真机验证。"
}

# --- 1. Python 运行时 ---
if python3 -c "" 2>/dev/null; then
    PASS+=("python3 可用")
else
    FAIL+=("python3 不可用")
    report
    exit 1
fi

# --- 2. ultralytics ---
if python3 -c "import ultralytics" 2>/dev/null; then
    PASS+=("ultralytics 已安装")
else
    echo "安装 ultralytics（镜像: ${PIP_INDEX}）..."
    if pip3 install --break-system-packages -q -i "${PIP_INDEX}" ultralytics; then
        PASS+=("ultralytics 安装成功")
    else
        FAIL+=("ultralytics 安装失败（检查 pip 与网络）")
        report
        exit 1
    fi
fi

# --- 3. 关闭 ultralytics 遥测与联网同步（避免录制时卡顿/外联） ---
python3 - <<'PY' 2>/dev/null && PASS+=("ultralytics 遥测已关闭") || FAIL+=("关闭 ultralytics 遥测失败（不影响功能，可忽略）")
from ultralytics import settings
settings.update({"sync": False})
PY

# --- 4. 测试图片 assets/demo.jpg（ultralytics 自带街景图，含公交/行人） ---
mkdir -p assets
if python3 - <<'PY'
import os, shutil, ultralytics
src = os.path.join(os.path.dirname(ultralytics.__file__), "assets", "bus.jpg")
dst = "assets/demo.jpg"
if not os.path.exists(dst) or os.path.getsize(dst) == 0:
    shutil.copyfile(src, dst)
print("ok")
PY
then
    PASS+=("assets/demo.jpg 就绪 ($(du -h assets/demo.jpg | cut -f1))")
else
    FAIL+=("assets/demo.jpg 生成失败")
fi

# --- 5. 模型 models/yolov8s.pt ---
mkdir -p models
if [ -f "models/yolov8s.pt" ] && [ "$(stat -c%s models/yolov8s.pt 2>/dev/null || echo 0)" -ge "${YOLO_MIN_BYTES}" ]; then
    PASS+=("models/yolov8s.pt 已存在 ($(du -h models/yolov8s.pt | cut -f1))")
else
    echo "下载 yolov8s.pt（多镜像尝试）..."
    ok=0
    for url in "${YOLO_MIRRORS[@]}"; do
        echo "  尝试: ${url}"
        if curl -fL --connect-timeout 10 --max-time 300 -o models/yolov8s.pt "${url}" \
           && [ "$(stat -c%s models/yolov8s.pt 2>/dev/null || echo 0)" -ge "${YOLO_MIN_BYTES}" ]; then
            ok=1
            PASS+=("models/yolov8s.pt 下载成功 ($(du -h models/yolov8s.pt | cut -f1))")
            break
        fi
    done
    if [ "${ok}" -eq 0 ]; then
        FAIL+=("models/yolov8s.pt 下载失败 — 请手动放置到 models/yolov8s.pt（任何国内网盘/镜像均可）")
    fi
fi

# --- 6. GPU 体检 ---
GPU_INFO=$(python3 - <<'PY'
import torch
if not torch.cuda.is_available():
    print("NO_GPU")
else:
    print(f"{torch.cuda.device_count()}|{torch.cuda.get_device_name(0)}|"
          f"{torch.cuda.get_device_properties(0).total_memory // (1024**3)}GB")
PY
)
if [ "${GPU_INFO}" = "NO_GPU" ]; then
    FAIL+=("torch.cuda 不可用 — 检查 IXUCA torch 是否正确安装（演示必须真实 GPU）")
else
    IFS='|' read -r gpu_count gpu_name gpu_mem <<< "${GPU_INFO}"
    PASS+=("GPU: ${gpu_name} x${gpu_count} (${gpu_mem})")
fi

if command -v ixsmi >/dev/null 2>&1; then
    IXSMI_OUT=$(ixsmi --query-gpu=name,temperature.gpu,power.draw,memory.used --format=csv,noheader 2>/dev/null | head -1)
    if [ -n "${IXSMI_OUT}" ]; then
        PASS+=("ixsmi 遥测: ${IXSMI_OUT}")
    else
        FAIL+=("ixsmi 存在但查询失败")
    fi
else
    FAIL+=("ixsmi 不在 PATH — 顶部 GPU 看板将无法显示真实遥测")
fi

report
