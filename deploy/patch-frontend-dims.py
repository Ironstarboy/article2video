# -*- coding: utf-8 -*-
"""前端风格区:预设 + 四维度选择器。"""
import re

p = 'web/index.html'
s = open(p, encoding='utf-8').read()

# 1) CSS
css = '''
.presets{display:flex;gap:12px;margin-bottom:22px;flex-wrap:wrap;}
.preset-btn{padding:9px 20px;border:1.5px solid var(--line);border-radius:999px;background:var(--card);font-size:13.5px;cursor:pointer;color:var(--muted);font-family:inherit;}
.preset-btn:hover{border-color:var(--line-strong);}
.preset-btn.sel{border-color:var(--red);color:var(--red);background:#FBF7F5;}
.dimrow{margin-bottom:20px;}
.dimrow .dl{font-size:13px;color:var(--muted);margin-bottom:9px;}
.dimrow .dl b{color:var(--ink);font-weight:600;margin-right:4px;}
.dim-chips{display:flex;flex-wrap:wrap;gap:10px;}
.dim-chip{padding:8px 16px;border:1.5px solid var(--line);border-radius:6px;background:var(--card);font-size:13.5px;cursor:pointer;color:var(--ink);font-family:inherit;}
.dim-chip:hover{border-color:var(--line-strong);}
.dim-chip.sel{border-color:var(--navy);background:#EEF2F8;color:var(--navy);}
</style>'''
assert '</style>' in s
s = s.replace('</style>', css, 1)

# 2) HTML:风格卡容器 → 预设 + 维度
old_html = '''    <p class="hint">三套风格均有详尽的视觉脚本,涵盖配色、字体、版式、动效与音轨。</p>
    <div class="styles" id="styles"></div>'''
new_html = '''    <p class="hint">可快速套用经典预设,或按字体 / 配色 / 背景 / 动效四个维度自由组合。</p>
    <div class="presets" id="presets"></div>
    <div id="dims"></div>'''
assert old_html in s, 'styles html 未匹配'
s = s.replace(old_html, new_html)

# 3) JS:整段替换 renderStyles(从 "/* ── 上传页逻辑 ── */" 到 "renderStyles();")
old_js_start = '/* ── 上传页逻辑 ── */'
i0 = s.index(old_js_start)
i1 = s.index('renderStyles();') + len('renderStyles();')
new_js = '''/* ── 上传页逻辑 ── */
let chosenCombo = {font:"song-title",palette:"china-red",bg:"orbit",motion:"dignified"};
let chosenStyle = "solemn-red";
const DIM_MAP = {fonts:"font",palettes:"palette",backgrounds:"bg",motions:"motion"};
function refreshChips(data){
  for (const [k,v] of Object.entries(chosenCombo)) {
    const box = $("#dim-"+k);
    if (!box) continue;
    box.querySelectorAll(".dim-chip").forEach(x=>{
      const key = x.getAttribute("data-key");
      x.classList.toggle("sel", key === v);
    });
  }
}
function renderStyles(){
  fetch("./api/styles").then(r=>r.json()).then(data=>{
    const pb = $("#presets"); pb.innerHTML = "";
    data.presets.forEach(p=>{
      const b = document.createElement("button");
      b.type="button"; b.className="preset-btn"+(p.key==="solemn-red" ? " sel":"");
      b.textContent = p.name;
      b.onclick = ()=>{ pb.querySelectorAll(".preset-btn").forEach(x=>x.classList.remove("sel"));
        b.classList.add("sel"); chosenCombo = {...p.combo}; chosenStyle = p.key; refreshChips(data); };
      pb.appendChild(b);
    });
    const db = $("#dims"); db.innerHTML = "";
    const dims = [["font","字体","fonts",data.fonts],["palette","配色","palettes",data.palettes],
                  ["bg","背景","backgrounds",data.backgrounds],["motion","动效","motions",data.motions]];
    dims.forEach(([key,label,listKey,opts])=>{
      const row = document.createElement("div"); row.className="dimrow";
      row.innerHTML = '<div class="dl"><b>'+label+'</b></div><div class="dim-chips" id="dim-'+key+'"></div>';
      db.appendChild(row);
      const box = row.querySelector(".dim-chips");
      opts.forEach(o=>{
        const c = document.createElement("button"); c.type="button";
        c.className="dim-chip"; c.textContent=o.name; c.title=o.desc;
        c.setAttribute("data-key", o.key);
        c.onclick = ()=>{ box.querySelectorAll(".dim-chip").forEach(x=>x.classList.remove("sel"));
          c.classList.add("sel"); chosenCombo[key] = o.key; chosenStyle = null;
          pb.querySelectorAll(".preset-btn").forEach(x=>x.classList.remove("sel")); };
        box.appendChild(c);
      });
    });
    refreshChips(data);
  }).catch(()=>{ $("#dims").innerHTML = '<p class="hint">风格接口加载失败,请刷新重试。</p>'; });
}
renderStyles();'''
s = s[:i0] + new_js + s[i1:]

# 4) 提交:组合字段
old_sub = '''  fd.append("style", chosenStyle || "solemn-red");
  fd.append("duration", dur.value);'''
new_sub = '''  if (chosenStyle) { fd.append("style", chosenStyle); }
  fd.append("font", chosenCombo.font);
  fd.append("palette", chosenCombo.palette);
  fd.append("bg", chosenCombo.bg);
  fd.append("motion", chosenCombo.motion);
  fd.append("duration", dur.value);'''
assert old_sub in s, 'submit 未匹配'
s = s.replace(old_sub, new_sub)

open(p, 'w', encoding='utf-8').write(s)
print('frontend patched')
# JS 校验
js = re.search(r'<script>(.*?)</script>', s, re.S).group(1)
open('/tmp/ttv-web5.js', 'w', encoding='utf-8').write(js)
print('js extracted')
