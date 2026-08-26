# -*- coding: utf-8 -*-
"""前端:配音引擎 + 音色选择器。"""
import re

p = 'web/index.html'
s = open(p, encoding='utf-8').read()

# 1) HTML:时长步骤前插入配音选择(并入「视频风格」步骤底部)
old = '''  <div class="step">
    <div class="step-head"><h2>时长与生成</h2><span class="no">叁</span></div>'''
new = '''  <div class="step">
    <div class="step-head"><h2>配音</h2><span class="no">叁</span></div>
    <div class="dimrow">
      <div class="dl"><b>配音引擎</b></div>
      <div class="dim-chips" id="voice-engines"></div>
    </div>
    <div class="dimrow">
      <div class="dl"><b>音色</b></div>
      <div class="dim-chips" id="voice-list"></div>
    </div>
    <p class="hint" id="voice-hint"></p>
  </div>

  <div class="step">
    <div class="step-head"><h2>时长与生成</h2><span class="no">肆</span></div>'''
assert old in s, 'html 未匹配'
s = s.replace(old, new)

# 2) JS:引擎/音色状态与渲染
old = '''renderStyles();'''
new = '''let chosenEngine = "cosyvoice3";
let chosenVoice = "male";
let engineData = [];
function renderVoices(){
  fetch("./api/styles").then(r=>r.json()).then(data=>{
    engineData = data.voice_engines || [];
    const eb = $("#voice-engines"); eb.innerHTML = "";
    engineData.forEach(e=>{
      const c = document.createElement("button"); c.type="button";
      c.className="dim-chip"; c.setAttribute("data-key", e.key);
      c.innerHTML = '<div class="nm"></div><div class="ds"></div>';
      c.querySelector(".nm").textContent = e.name;
      c.querySelector(".ds").textContent = e.key === "doubao" ? "云 API" : "GPU 本地";
      c.onclick = ()=>{ eb.querySelectorAll(".dim-chip").forEach(x=>x.classList.remove("sel"));
        c.classList.add("sel"); chosenEngine = e.key;
        if (!e.voices.includes(chosenVoice)) chosenVoice = e.voices[0];
        renderVoiceList();
        $("#voice-hint").textContent = e.key === "doubao" ? "豆包云引擎需在火山控制台开通 seed-tts-2.0 服务并开启后付费。" : "";
      };
      eb.appendChild(c);
    });
    renderVoiceList();
  }).catch(()=>{ $("#voice-engines").innerHTML = '<p class="hint">配音接口加载失败</p>'; });
}
function renderVoiceList(){
  const e = engineData.find(x=>x.key===chosenEngine);
  const vl = $("#voice-list"); vl.innerHTML = "";
  (e ? e.voices : ["male"]).forEach(v=>{
    const c = document.createElement("button"); c.type="button";
    c.className="dim-chip"+(v===chosenVoice ? " sel":"");
    c.innerHTML = '<div class="nm"></div>';
    c.querySelector(".nm").textContent = v;
    c.onclick = ()=>{ vl.querySelectorAll(".dim-chip").forEach(x=>x.classList.remove("sel"));
      c.classList.add("sel"); chosenVoice = v; };
    vl.appendChild(c);
  });
}
renderVoices();
renderStyles();'''
assert old in s, 'renderStyles 调用未匹配'
s = s.replace(old, new, 1)

# 3) 提交参数
old = '''  fd.append("motion", chosenCombo.motion);
  fd.append("duration", dur.value);'''
new = '''  fd.append("motion", chosenCombo.motion);
  fd.append("voice_engine", chosenEngine);
  fd.append("voice", chosenVoice);
  fd.append("duration", dur.value);'''
assert old in s, 'submit 未匹配'
s = s.replace(old, new)

open(p, 'w', encoding='utf-8').write(s)
print('frontend voice selector patched')
js = re.search(r'<script>(.*?)</script>', s, re.S).group(1)
open('/tmp/ttv-web-final.js', 'w', encoding='utf-8').write(js)
