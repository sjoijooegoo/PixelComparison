# TODO

## 对比性能优化(高优先级)

**现状**:一批 60 张 1920×1080 图片发起对比约 **44 秒**(单张 ~0.7s,同步逐张计算),前端发起后需 loading 40+ 秒。

**瓶颈**:`backend/app/service.py` 的 `run_comparison` 同步逐点位调用 `compare_images`
(逐像素 abs diff + 全局 SSIM + RMS/PSNR + RGB 直方图 + 高斯模糊热力图 + jet 上色 + 存 PNG),
1920×1080 ≈ 207 万像素全图运算,与差异大小关系不大。

**优化方向(按性价比排序)**:
1. **并行**:把 `run_comparison` 里逐点位的 for 循环改用多进程/线程池,8 核可从 44s 降到 ~6–8s。改动最小、收益最大,**优先**。
2. **异步任务队列**(Celery/RQ + Redis,WebSocket 推进度):POST /api/comparisons 立即返回任务 id,前端不阻塞、显示进度条。
3. **OpenCV / scikit-image 加速**:`cv2` 的 SSIM(windowed)、滤波、resize 比纯 numpy 快数倍;对齐后再比可抗平移。
4. **降采样比对**:差异率/SSIM 在缩略图(如 960×540)上算,热力图再上采样,单张可降到 ~0.2s。
5. (已实现)同一对批次结果持久化复用,不重复计算;`force=true` 强制重算。

> 实测命令参考:用 `backend/.venv` 跑 `app.compare.compare_images` 对两张 1920×1080 图计时。
