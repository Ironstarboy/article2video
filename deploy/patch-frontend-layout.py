# -*- coding: utf-8 -*-
"""前端预览页排版:分析|脚本并排,视频(播放器/Studio)独占一行。"""
import re

p = 'web/index.html'
s = open(p, encoding='utf-8').read()

# 1) CSS:columns 改为等宽双列;视频区全宽;Studio tab 样式
css = '''
.columns{display:grid;grid-template-columns:1fr 1fr;gap:22px;align-items:start;}
@media(max-width:980px){.columns{grid-template-columns:1fr;}.styles{grid-template-columns:1fr;}}
.video-row{margin-top:22px;}
.vtabs{display:flex;gap:0;margin-bottom:14px;border-bottom:1px solid var(--line);}
.vtab{padding:10px 22px;font-size:14px;border:none;background:transparent;cursor:pointer;color:var(--muted);font-family:inherit;border-bottom:2px solid transparent;}
.vtab.sel{color:var(--navy);border-bottom-color:var(--navy);font-weight:600;}
.studio-box{background:#0b1220;border-radius:8px;overflow:hidden;height:860px;display:flex;align-items:center;justify-content:center;color:#8CA0B3;font-size:14px;}
.studio-box iframe{width:100%;height:100%;border:none;display:block;}
</style>'''
assert '</style>' in s
s = s.replace('</style>', css, 1)

# 2) HTML:视频卡移到 columns 之外并全宽,加 tab
old_html = '''  <div class="columns">
    <div>
      <div class="step panel" style="padding:24px 26px;">
        <h3>DeepSeek 分析结果</h3>
        <div class="meta" id="meta-chips"></div>
        <div id="analysis-body"><pre class="analysis">分析中,请稍候…</pre></div>
      </div>
      <div class="step panel" style="padding:24px 26px;margin-top:22px;">
        <h3>逐帧脚本</h3>
        <div id="frames-body"><pre class="analysis">分析完成后显示逐帧脚本。</pre></div>
      </div>
    </div>
    <div>
      <div class="step panel" style="padding:24px 26px;">
        <h3>视频预览</h3>
        <div class="player-box" id="player-box">构建后在此预览</div>
        <div class="btnrow">
          <button id="btn-build" disabled>构建预览</button>
          <button id="btn-render" class="primary" disabled>渲染成片</button>
        </div>
        <div id="dl"><a id="dl-link" target="_blank">下载成片(MP4)</a></div>
      </div>
    </div>
  </div>'''
new_html = '''  <div class="columns">
    <div>
      <div class="step panel" style="padding:24px 26px;">
        <h3>DeepSeek 分析结果</h3>
        <div class="meta" id="meta-chips"></div>
        <div id="analysis-body"><pre class="analysis">分析中,请稍候…</pre></div>
      </div>
    </div>
    <div>
      <div class="step panel" style="padding:24px 26px;">
        <h3>逐帧脚本</h3>
        <div id="frames-body"><pre class="analysis">分析完成后显示逐帧脚本。</pre></div>
      </div>
    </div>
  </div>

  <div class="step panel video-row" style="padding:24px 26px;">
    <h3>视频预览</h3>
    <div class="vtabs">
      <button type="button" class="vtab sel" id="vtab-player">播放器</button>
      <button type="button" class="vtab" id="vtab-studio">Studio 编辑器(完整功能)</button>
    </div>
    <div class="player-box" id="player-box" style="display:none;">构建后在此预览</div>
    <div class="studio-box" id="studio-box" style="display:none;">点击「Studio 编辑器」标签后加载</div>
    <div class="btnrow">
      <button id="btn-build" disabled>构建预览</button>
      <button id="btn-render" class="primary" disabled>渲染成片</button>
    </div>
    <div id="dl"><a id="dl-link" target="_blank">下载成片(MP4)</a></div>
  </div>'''
assert old_html in s, 'html 未匹配'
s = s.replace(old_html, new_html)

# 3) JS:tab 切换 + Studio iframe 懒加载;渲染完成时切回播放器显示视频
old_js = '''  if (j.status==="preview" && !$("#player-box").querySelector("iframe")) {
    const f = document.createElement("iframe");
    f.src = "./api/player/" + j.job_id + "/";
    $("#player-box").innerHTML = "";
    $("#player-box").appendChild(f);
  }'''
new_js = '''  if (j.status==="preview" && !$("#player-box").querySelector("iframe")) {
    const f = document.createElement("iframe");
    f.src = "./api/player/" + j.job_id + "/";
    $("#player-box").innerHTML = "";
    $("#player-box").appendChild(f);
  }
  if (j.status==="preview") {
    $("#vtab-player").style.display = "";
    $("#vtab-studio").style.display = "";
  }'''
assert old_js in s, 'player js 未匹配'
s = s.replace(old_js, new_js)

old_tab = '''$("#btn-build").onclick = ()=>{'''
new_tab = '''/* 视频区 tab:播放器 / Studio */
let currentTab = "player";
function switchTab(t){
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
}
$("#vtab-player").onclick = ()=>switchTab("player");
$("#vtab-studio").onclick = ()=>switchTab("studio");
$("#btn-build").onclick = ()=>{'''
assert old_tab in s, 'tab js anchor 未匹配'
s = s.replace(old_tab, new_tab, 1)

# 渲染完成:显示视频时把 player-box 置为可见、studio 保持
old_rend = '''  if (j.status==="rendered" && j.has_video) {
    $("#dl").style.display = "block";
    $("#dl-link").href = "./api/jobs/" + j.job_id + "/video";
    const f = $("#player-box").querySelector("iframe");
    if (f) { f.remove(); const v=document.createElement("video"); v.src=$("#dl-link").href; v.controls=true; v.style.cssText="width:100%;height:100%;"; $("#player-box").appendChild(v); }
  }'''
new_rend = '''  if (j.status==="rendered" && j.has_video) {
    $("#dl").style.display = "block";
    $("#dl-link").href = "./api/jobs/" + j.job_id + "/video";
    const f = $("#player-box").querySelector("iframe");
    if (f) { f.remove(); const v=document.createElement("video"); v.src=$("#dl-link").href; v.controls=true; v.style.cssText="width:100%;height:100%;"; $("#player-box").appendChild(v); }
    switchTab("player");
  }'''
assert old_rend in s, 'rendered js 未匹配'
s = s.replace(old_rend, new_rend)

open(p, 'w', encoding='utf-8').write(s)
print('frontend layout patched')
js = re.search(r'<script>(.*?)</script>', s, re.S).group(1)
open('/tmp/ttv-web8.js', 'w', encoding='utf-8').write(js)
print('js extracted')
