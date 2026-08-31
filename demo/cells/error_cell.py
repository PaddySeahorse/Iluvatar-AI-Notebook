# 故障演示：输入图片路径不存在，触发 AI Debug 定位问题
results = model.predict("assets/not-exist.jpg", device=device, imgsz=640, verbose=False)
print(results[0].boxes)
