# MR-100 目标检测推理：加载 YOLOv8s 并对测试图片执行检测
import os
import time

import torch
from ultralytics import YOLO

import matplotlib.pyplot as plt
import cv2

MODEL_PATH = "models/yolov8s.pt"
IMAGE_PATH = "assets/demo.jpg"
device = 0 if torch.cuda.is_available() else "cpu"

# 1. 加载本地 YOLOv8s 模型（GPU 0）
t0 = time.perf_counter()
model = YOLO(MODEL_PATH)
model.to(device)
load_time = time.perf_counter() - t0

device_name = torch.cuda.get_device_name(0) if device == 0 else "CPU"
print(f"设备: {device_name} | 模型加载: {load_time:.2f}s")

# 2. 执行目标检测（首次推理包含 CUDA 上下文初始化）
t1 = time.perf_counter()
results = model.predict(IMAGE_PATH, device=device, imgsz=640, conf=0.25, verbose=False)
first_infer = time.perf_counter() - t1

r = results[0]
print(f"首次推理（含预热）: {first_infer * 1000:.1f} ms | 检出目标: {len(r.boxes)} 个")

# 3. 打印检测到的目标：类别 / 置信度 / 边界框
print(f"\n{'类别':<10}{'置信度':>8}   边界框 (x1, y1, x2, y2)")
for box in r.boxes:
    cls = r.names[int(box.cls)]
    conf = float(box.conf)
    x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].tolist()]
    print(f"{cls:<10}{conf:>8.3f}   ({x1}, {y1}, {x2}, {y2})")

# 4. 显示带检测框的结果图片
annotated = cv2.cvtColor(r.plot(), cv2.COLOR_BGR2RGB)
plt.figure(figsize=(10, 6))
plt.imshow(annotated)
plt.axis("off")
plt.title("MR-100 Inference Result")
plt.show()
