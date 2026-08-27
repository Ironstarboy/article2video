# -*- coding: utf-8 -*-
"""修复:1)预览自动弹出画面 2)标签切换销毁对方 iframe(杜绝双声源) 3)Studio 启动前清会话+日志。"""
import re

# ══ 1. 前端:自动显示 + iframe 互斥 + autoplay ══
p = 'web/index.html'
s = open(p, encoding='utf-8').read()

old = '''  if (j.status==="preview" && !$("#player-box").querySelector("iframe")) {
    const f = document.createElement("iframe");
    f.src = "./api/player/" + j.job_id + "/";
    $("#player-box").innerHTML = "";
    $("#player-box").appendChild(f);
  }'''
new = '''  if (j.status==="preview" && !$("#player-box").querySelector("iframe")) {
    const f = document.createElement("iframe");
    f.src = "./api/player/" + j.job_id + "/";
    f.allow = "autoplay";
    $("#player-box").innerHTML = "";
    $("#player-box").appendChild(f);
    // 构建完成后自动弹出播放器画面(此前需手动切标签)
    if (currentTab === "player") {
      $("#player-box").style.display = "";
    } else {
      switchTab("player");
    }
  }'''
assert old in s, 'updateActions 未匹配'
s = s.replace(old, new)

old = '''function switchTab(t){
  currentTab = t;
  $("#vtab-player").classList.toggle("sel", t==="player");
  $("#vtab-studio").classList.toggle("sel", t==="studio");
  const isRendered = $("#player-box").querySelector("video");
  $("#player-box").style.display = (t==="player" && !isRendered) ? "" : (t==="player" ? "" : "none");
  $("#studio-box").style.display = (t==="studio") ? "" : "none";
  if (t==="player" && isRendered) { $("#player-box").style.display = ""; }
  if (t==="studio" && !$("#studio-box").querySelector("iframe") && jobId) {
    const f = document.createElement("iframe");
    f.src = "./api/studio/" + jobId + "/#project/project";
    $("#studio-box").innerHTML = "";
    $("#studio-box").appendChild(f);
  }
}'''
new = '''function switchTab(t){
  currentTab = t;
  $("#vtab-player").classList.toggle("sel", t==="player");
  $("#vtab-studio").classList.toggle("sel", t==="studio");
  const isRendered = !!$("#player-box").querySelector("video");
  if (t === "player") {
    // 切到播放器:销毁 Studio iframe(否则其自动播放的音频在后台持续发声)
    if ($("#studio-box").querySelector("iframe")) { $("#studio-box").innerHTML = "点击「Studio 编辑器」标签后加载"; }
    $("#studio-box").style.display = "none";
    $("#player-box").style.display = "";
  } else {
    // 切到 Studio:销毁播放器 iframe(单声源原则)
    if ($("#player-box").querySelector("iframe")) { $("#player-box").innerHTML = "构建后在此预览"; }
    $("#player-box").style.display = "none";
    $("#studio-box").style.display = "";
    if (!$("#studio-box").querySelector("iframe") && jobId) {
      const f = document.createElement("iframe");
      f.src = "./api/studio/" + jobId + "/#project/project";
      f.allow = "autoplay";
      $("#studio-box").innerHTML = "";
      $("#studio-box").appendChild(f);
    }
  }
  if (isRendered && t === "player") { $("#player-box").style.display = ""; }
}'''
assert old in s, 'switchTab 未匹配'
s = s.replace(old, new)

old = '''  if (j.status==="rendered" && j.has_video) {
    $("#dl").style.display = "block";
    $("#dl-link").href = "./api/jobs/" + j.job_id + "/video";
    const f = $("#player-box").querySelector("iframe");
    if (f) { f.remove(); const v=document.createElement("video"); v.src=$("#dl-link").href; v.controls=true; v.style.cssText="width:100%;height:100%;"; $("#player-box").appendChild(v); }
    switchTab("player");
  }'''
new = '''  if (j.status==="rendered" && j.has_video) {
    $("#dl").style.display = "block";
    $("#dl-link").href = "./api/jobs/" + j.job_id + "/video";
    const f = $("#player-box").querySelector("iframe");
    if (f) { f.remove(); const v=document.createElement("video"); v.src=$("#dl-link").href; v.controls=true; v.style.cssText="width:100%;height:100%;"; $("#player-box").appendChild(v); }
    // 渲染完成:清理 Studio iframe,只留成片播放
    if ($("#studio-box").querySelector("iframe")) { $("#studio-box").innerHTML = "已渲染成片"; $("#studio-box").style.display = "none"; }
    switchTab("player");
  }'''
assert old in s, 'rendered 未匹配'
s = s.replace(old, new)
open(p, 'w', encoding='utf-8').write(s)
print('frontend preview fixes patched')
js = re.search(r'<script>(.*?)</script>', s, re.S).group(1)
open('/tmp/ttv-web-pf.js', 'w', encoding='utf-8').write(js)

# ══ 2. Studio:启动前清会话 + 日志落盘 + 换端口重试 ══
p = 'server/main.py'
s = open(p, encoding='utf-8').read()
old = '''def start_studio(job):
    """启动 HyperFrames Studio(preview --background 是 CLI 托管会话,命令返回后服务仍在)。

    以端口可达性判定存活,不再跟踪包装进程。
    """
    port = _studio_slot(job.id)
    subprocess.run(
        ["hyperframes", "preview", "--background", "--port", str(port)],
        cwd=str(job.paths()["project"]),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=_hf_env(),
        timeout=120,
    )
    # 等待端口就绪(冷启动含大页面解析,最多 90s)
    import time as _t
    for _ in range(90):
        if not _port_free(port):
            STUDIOS[job.id] = port
            return port
        _t.sleep(1.0)
    raise RuntimeError(f"Studio 启动超时(端口 {port})")'''
new = '''def start_studio(job):
    """启动 HyperFrames Studio(preview --background 是 CLI 托管会话,命令返回后服务仍在)。

    以端口可达性判定存活,不再跟踪包装进程。
    启动前先 --stop 清理可能残留的托管会话(否则 CLI 会「复用」死会话而不监听新端口)。
    """
    proj = str(job.paths()["project"])
    log = open(f"/mnt/workspace/ttv/studio-{job.id}.log", "a")
    try:
        subprocess.run(["hyperframes", "preview", proj, "--stop"],
                       stdout=log, stderr=log, env=_hf_env(), timeout=60)
    except Exception:
        pass
    import time as _t
    for retry in range(2):
        port = _studio_slot(job.id)
        log.write(f"[{_t.time()}] starting studio for {job.id} on {port}\\n")
        log.flush()
        try:
            subprocess.run(
                ["hyperframes", "preview", "--background", "--port", str(port)],
                cwd=proj,
                stdout=log, stderr=log, env=_hf_env(),
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            log.write("preview 命令超时\\n")
        # 等待端口就绪(冷启动含大页面解析,最多 90s)
        for _ in range(90):
            if not _port_free(port):
                STUDIOS[job.id] = port
                log.write(f"studio ready on {port}\\n")
                log.close()
                return port
            _t.sleep(1.0)
        log.write(f"端口 {port} 未就绪,重试下一端口\\n")
    log.close()
    raise RuntimeError("Studio 启动超时(两个端口均未就绪)")'''
assert old in s, 'start_studio 未匹配'
s = s.replace(old, new)
open(p, 'w', encoding='utf-8').write(s)
print('main.py studio retry patched')
