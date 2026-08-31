# MR-100 推理性能基准：复用上一单元格的 model / device，预热后连续推理并统计
import time
import statistics

import matplotlib.pyplot as plt

IMAGE_PATH = "assets/demo.jpg"
WARMUP_RUNS = 10   # 预热次数
BENCH_RUNS = 50    # 正式推理次数

# 1. 预热：触发算子调度与显存分配，使后续延迟进入稳定区间
for _ in range(WARMUP_RUNS):
    model.predict(IMAGE_PATH, device=device, imgsz=640, conf=0.25, verbose=False)

# 2. 正式推理并逐次计时
latencies_ms = []
for _ in range(BENCH_RUNS):
    t = time.perf_counter()
    model.predict(IMAGE_PATH, device=device, imgsz=640, conf=0.25, verbose=False)
    latencies_ms.append((time.perf_counter() - t) * 1000)

# 3. 统计平均延迟 / P50 / P95 / 吞吐量
avg_ms = statistics.mean(latencies_ms)
p50_ms = statistics.quantiles(latencies_ms, n=100)[49]
p95_ms = statistics.quantiles(latencies_ms, n=100)[94]
fps = 1000.0 / avg_ms

print(f"{'指标':<12}{'数值':>10}")
print(f"{'平均延迟':<12}{avg_ms:>8.1f} ms")
print(f"{'P50 延迟':<12}{p50_ms:>8.1f} ms")
print(f"{'P95 延迟':<12}{p95_ms:>8.1f} ms")
print(f"{'吞吐量':<12}{fps:>8.1f} FPS")

# 4. 绘制每次推理延迟曲线
plt.figure(figsize=(10, 4))
plt.plot(latencies_ms, color='#00f2fe', linewidth=1.5, label='per-run latency')
plt.axhline(avg_ms, color='#ff6b6b', linestyle='--', linewidth=1.2,
            label=f'avg {avg_ms:.1f} ms')
plt.title(f"MR-100 Inference Latency ({BENCH_RUNS} runs)")
plt.xlabel("Run")
plt.ylabel("Latency (ms)")
plt.legend()
plt.grid(True, linestyle='--', alpha=0.3)
plt.show()
