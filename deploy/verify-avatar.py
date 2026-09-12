#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端验证:assemble.build() → 数字人片段 → hyperframes 渲染 → ffmpeg 叠加。

与 smoke_test 的分工:
  - server/smoke_test.py 只测纯函数(不调 assemble.build,不需要 GPU/hyperframes)
  - 本脚本真正跑完整链路,需要数字人服务(50051)与 hyperframes,约 1-3 分钟

用法(在仓库根目录):
    .venv/bin/python deploy/verify-avatar.py [--keep]

退出码 0 表示:项目构建成功、片段按帧起点叠加、成片里确实出现数字人。
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

import avatar  # noqa: E402
import config  # noqa: E402
from builder import assemble  # noqa: E402

WORK = ROOT / ".cache" / "avatar-e2e"
FPS = 30
SIZE = config.AVATAR_SIZE


def sh(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def make_script() -> dict:
    """三帧:opening(无台词)→ statement(有台词)→ closing(无台词)。"""
    return {
        "title": "数字人端到端验证",
        "subtitle": "assemble.build + 叠加",
        "duration_sec": 12,
        "frames": [
            {"index": 1, "type": "opening", "scene": "title", "voiceover": "",
             "duration": 4.0, "content": {"title": "数字人验证", "subtitle": "端到端"}},
            {"index": 2, "type": "statement", "scene": "statement",
             "voiceover": "这是一次数字人端到端验证,画面应出现在左上角。",
             "duration": 4.0, "content": {"text": "数字人应出现在左上角"}},
            {"index": 3, "type": "closing", "scene": "closing", "voiceover": "",
             "duration": 4.0, "content": {"text": "验证结束"}},
        ],
    }


def make_vo(project: Path, script: dict) -> dict:
    """给有台词的帧造一段音频(正弦音,不依赖 TTS 服务)与其词级时间。"""
    vo = {}
    audio_dir = project / "assets" / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    for f in script["frames"]:
        i, text = f["index"], (f.get("voiceover") or "").strip()
        if not text:
            continue
        dst = audio_dir / f"vo_{i:02d}.mp3"
        sh(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
            "-i", f"sine=frequency=320:duration={f['duration']:.2f}",
            "-ar", "44100", "-ac", "1", str(dst)])
        # 词级时间按字数均分(与 tts 的估算方式一致)
        n = max(1, len(text))
        per = f["duration"] / n
        words = [(ch, k * per, (k + 1) * per) for k, ch in enumerate(text)]
        vo[i] = {"path": str(dst), "duration": f["duration"], "engine": "e2e", "words": words}
    return vo


def probe_avatar() -> bool:
    svc = avatar.AvatarService(config.AVATAR_IMAGE)
    try:
        return svc.available()
    finally:
        svc.close()


def pixel_patch(raw: bytes, w: int, x: int, y: int, n: int = 60, step: int = 4):
    return [tuple(raw[(yy * w + xx) * 3:(yy * w + xx) * 3 + 3])
            for yy in range(y, y + n, step) for xx in range(x, x + n, step)]


def patch_dist(a, b) -> float:
    return sum(abs(p[0] - q[0]) + abs(p[1] - q[1]) + abs(p[2] - q[2])
               for p, q in zip(a, b)) / len(a) / 3


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="保留工作目录")
    a = ap.parse_args()

    if not probe_avatar():
        print(f"跳过:数字人服务不可达({config.AVATAR_ADDR}),先启动 deploy/start-avatar 或 CyberVerse 推理服务")
        return 2

    if WORK.exists():
        shutil.rmtree(WORK)
    project = WORK / "project"
    project.mkdir(parents=True, exist_ok=True)

    script = make_script()
    vo = make_vo(project, script)

    print("① assemble.build() …")
    info = assemble.build(script, "modern-blue", vo, project)
    starts = info["starts"]
    print(f"   总时长 {info['total']}s,帧起点 {starts}")
    assert project.joinpath("index.html").exists(), "index.html 未生成"

    print("② 生成数字人片段 …")
    timeline = avatar.build_frame_clips(script, vo, starts, SIZE)
    avatar.write_timeline(timeline, project / "avatar_timeline.json")
    print(f"   {len(timeline)} 段:" +
          ", ".join(f"帧{e['index']}@{e['start']:.1f}s" for e in timeline))
    assert len(timeline) == len(script["frames"]), "片段数与帧数不一致"

    print("③ hyperframes 渲染(未叠加)…")
    raw_out = project / "renders" / "out.mp4"
    env = dict(os.environ)
    if config.NODE_BIN_DIR:
        env["PATH"] = config.NODE_BIN_DIR + os.pathsep + env.get("PATH", "")
    r = sh(["hyperframes", "render", str(project), "--output", str(raw_out),
            "--format", "mp4", "--quality", "high"], env=env)
    if r.returncode != 0 or not raw_out.exists():
        print("   渲染失败:", (r.stderr or r.stdout)[-500:])
        return 1
    print(f"   {raw_out.stat().st_size / 1e6:.2f} MB")

    print("④ ffmpeg 叠加数字人 …")
    composed = project / "renders" / "out_avatar.mp4"
    avatar.composite_onto_video(raw_out, timeline, composed,
                                x=config.AVATAR_X, y=config.AVATAR_Y, fps=FPS)
    print(f"   {composed.stat().st_size / 1e6:.2f} MB")

    print("⑤ 校验:窗口内卡片区应显著变化,窗口外应基本不变 …")
    def frame(path, t):
        # 注意:这里要的是原始像素字节,不能按文本解码
        return subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(path),
             "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            capture_output=True).stdout
    W = config.WIDTH
    e = timeline[1]                      # 中间那帧(有台词)
    inside = patch_dist(pixel_patch(frame(raw_out, e["start"] + 0.5), W, config.AVATAR_X + 130, config.AVATAR_Y + 130),
                        pixel_patch(frame(composed, e["start"] + 0.5), W, config.AVATAR_X + 130, config.AVATAR_Y + 130))
    tail_t = timeline[-1]["start"] + timeline[-1]["duration"] - 0.2
    outside = patch_dist(pixel_patch(frame(raw_out, tail_t), W, 900, 900),
                         pixel_patch(frame(composed, tail_t), W, 900, 900))
    print(f"   卡片区(窗口内)差异 {inside:5.1f}   幻灯片区(远离卡片)差异 {outside:5.1f}")
    ok = inside > 15 and outside < 12
    print("   通过 ✅" if ok else "   未通过 ❌")

    if not a.keep:
        shutil.rmtree(WORK, ignore_errors=True)
    else:
        print(f"   保留:{WORK}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
