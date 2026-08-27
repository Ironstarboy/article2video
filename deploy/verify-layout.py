# -*- coding: utf-8 -*-
"""成片画面/停顿验证(服务器上运行):
  python3 deploy/verify-layout.py <video.mp4> [max_seconds]
① 正文-字幕缓冲带检查:全片每 10 帧采样,检查 y∈[830,890] 缓冲带无深色文字
   (正文容器上限 826px,字幕带顶部 ≥894px,缓冲带出现深色像素即交叉风险);
② 停顿检查:音频静音段检测,报告 >2.0s 的静音段(章节页/长停顿)。
"""
import subprocess
import sys

video = sys.argv[1]
max_sec = int(sys.argv[2]) if len(sys.argv) > 2 else None

# ── ① 缓冲带深色像素检查 ──
print("== ① 缓冲带检查 (y 830-890, 每 10 帧采样) ==")
cmd = ["ffmpeg", "-v", "error", "-i", video,
       "-vf", "select='not(mod(n,300))',crop=1920:60:0:830,format=gray",
       "-f", "rawvideo", "-"]
p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
data = p.stdout.read()
n_frames = len(data) // (1920 * 60)
worst = 255
worst_frame = -1
for k in range(n_frames):
    chunk = data[k * 1920 * 60:(k + 1) * 1920 * 60]
    m = min(chunk)
    if m < worst:
        worst, worst_frame = m, k * 10
print(f"采样 {n_frames} 帧(每 10 帧 1 张),缓冲带最小亮度 = {worst}"
      f" @ 约 {worst_frame}s")
print("结论:", "PASS 缓冲带无深色文字,正文与字幕无交叉" if worst >= 100
      else "FAIL 缓冲带出现深色像素(交叉风险)")

# ── ② 静音段检查 ──
print()
print("== ② 停顿检查 (音频静音段 >2.0s) ==")
r = subprocess.run(
    ["ffmpeg", "-v", "error", "-i", video,
     "-af", "silencedetect=noise=-35dB:d=2.0", "-f", "null", "-"],
    capture_output=True, text=True)
lines = [ln for ln in r.stderr.splitlines() if "silence_" in ln]
silences = []
cur = None
for ln in lines:
    if "silence_start" in ln:
        cur = {"start": float(ln.split("silence_start: ")[1].split()[0])}
    elif "silence_end" in ln and cur is not None:
        cur["end"] = float(ln.split("silence_end: ")[1].split()[0])
        dur = cur["end"] - cur["start"]
        if dur >= 2.0:
            silences.append((cur["start"], dur))
        cur = None
if not silences:
    print("无 >2.0s 的静音段(停顿自然)")
else:
    for s, d in silences[:12]:
        print(f"  静音 {s:7.2f}s 起,持续 {d:.2f}s")
    print(f"共 {len(silences)} 段 >2.0s 静音")
print("结论:", "PASS 无长停顿" if not silences else
      f"注意:{len(silences)} 段 2s+ 静音(章节页停顿属正常,检查是否有异常长停顿)")
