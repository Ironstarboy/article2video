# -*- coding: utf-8 -*-
"""一次性补丁:前端文本直输模式 + 后端 text 字段 + docx 扩展名保留。服务器上执行:python3 - < 此文件"""
import re

# ══ 后端 ══
p = 'server/main.py'
s = open(p, encoding='utf-8').read()

old_stage = '''def stage_analyze(job):
    job.set(status="analyzing", progress="提取文本")
    p = job.paths()
    text = extract.extract_text(p["input"])
    p["input"].write_text(text, encoding="utf-8")'''
new_stage = '''def stage_analyze(job):
    job.set(status="analyzing", progress="提取文本")
    p = job.paths()
    # 上传文件保留原扩展名(txt/md/docx);粘贴文本模式直接就是 input.txt
    upload = next(job.dir.glob("input.*"))
    text = extract.extract_text(upload)
    p["input"].write_text(text, encoding="utf-8")'''
assert old_stage in s, 'stage_analyze 未匹配'
s = s.replace(old_stage, new_stage)

old_api = '''@app.post("/api/jobs")
async def api_create(file: UploadFile = File(...), style: str = Form("solemn-red"),
                     duration: int = Form(120)):
    if style not in STYLES:
        raise HTTPException(400, f"未知风格:{style}")
    duration = max(60, min(600, duration))
    filename = file.filename or "article.txt"
    if not filename.lower().endswith((".txt", ".md", ".markdown", ".docx")):
        raise HTTPException(400, "仅支持 txt / md / docx")
    job = create_job(style, duration, filename)
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(400, "文件超过 20MB")
    job.paths()["input"].write_bytes(data)
    run_in_background(job, stage_analyze)
    return job.to_dict()'''
new_api = '''@app.post("/api/jobs")
async def api_create(file: UploadFile = File(None), style: str = Form("solemn-red"),
                     duration: int = Form(120), text: str = Form("")):
    if style not in STYLES:
        raise HTTPException(400, f"未知风格:{style}")
    duration = max(60, min(600, duration))
    text = (text or "").strip()
    if file is not None and file.filename:
        filename = file.filename or "article.txt"
        if not filename.lower().endswith((".txt", ".md", ".markdown", ".docx")):
            raise HTTPException(400, "仅支持 txt / md / docx")
        data = await file.read()
        if len(data) > 20 * 1024 * 1024:
            raise HTTPException(400, "文件超过 20MB")
        job = create_job(style, duration, filename)
        ext = "." + filename.lower().rsplit(".", 1)[-1]
        (job.dir / ("input" + ext)).write_bytes(data)
    elif len(text) >= 50:
        job = create_job(style, duration, "粘贴文本.txt")
        job.dir.joinpath("input.txt").write_text(text, encoding="utf-8")
    else:
        raise HTTPException(400, "请上传文件或粘贴不少于 50 字的文本")
    run_in_background(job, stage_analyze)
    return job.to_dict()'''
assert old_api in s, 'api_create 未匹配'
s = s.replace(old_api, new_api)
open(p, 'w', encoding='utf-8').write(s)
print('main.py patched')

# ══ 前端 ══
p = 'web/index.html'
h = open(p, encoding='utf-8').read()

css_add = '''
.modetabs{display:flex;gap:0;margin-bottom:16px;border:1px solid var(--line);border-radius:10px;overflow:hidden;width:fit-content;background:#fff;}
.mtab{padding:10px 22px;font-size:14px;border:none;background:transparent;cursor:pointer;color:var(--muted);}
.mtab.sel{background:linear-gradient(135deg,#0a4da3,#0077b6);color:#fff;}
#textinput{width:100%;min-height:220px;border:2px dashed #b9c6d8;border-radius:12px;padding:16px;font-size:14px;line-height:1.8;resize:vertical;font-family:inherit;background:#fbfcfe;}
#textinput:focus{outline:none;border-color:var(--accent);background:#eef4fc;}
</style>'''
assert '</style>' in h, 'style 未匹配'
h = h.replace('</style>', css_add, 1)

old_drop = '''    <div id="drop"><div class="big">点击选择文件,或拖拽到此处</div><div class="small">.txt · .md · .docx</div></div>
    <input type="file" id="file" accept=".txt,.md,.markdown,.docx" class="hidden"/>
    <div id="fileinfo">已选择:<b id="fname"></b>(<span id="fsize"></span>)</div>'''
new_drop = '''    <div class="modetabs">
      <button type="button" class="mtab sel" id="mtab-file">📄 上传文件</button>
      <button type="button" class="mtab" id="mtab-text">✍️ 粘贴文字</button>
    </div>
    <div id="drop"><div class="big">点击选择文件,或拖拽到此处</div><div class="small">.txt · .md · .docx</div></div>
    <input type="file" id="file" accept=".txt,.md,.markdown,.docx" class="hidden"/>
    <div id="fileinfo">已选择:<b id="fname"></b>(<span id="fsize"></span>)</div>
    <textarea id="textinput" class="hidden" placeholder="把文章全文粘贴到这里(不少于 50 字),支持人民日报评论、马院论文等长文…"></textarea>'''
assert old_drop in h, 'drop 未匹配'
h = h.replace(old_drop, new_drop)

old_js = '''let picked = null;
function pickFile(f){
  picked = f;
  $("#fname").textContent = f.name;
  $("#fsize").textContent = (f.size/1024/1024).toFixed(2)+" MB";
  $("#fileinfo").style.display = "block";
  $("#submit").disabled = false;
}'''
new_js = '''let picked = null, mode = "file";
function setMode(m){
  mode = m;
  $("#mtab-file").classList.toggle("sel", m==="file");
  $("#mtab-text").classList.toggle("sel", m==="text");
  $("#drop").classList.toggle("hidden", m!=="file");
  $("#fileinfo").classList.toggle("hidden", m!=="file" || !picked);
  $("#textinput").classList.toggle("hidden", m!=="text");
  updateSubmit();
}
function updateSubmit(){
  $("#submit").disabled = mode==="file" ? !picked : $("#textinput").value.trim().length < 50;
}
$("#mtab-file").onclick = ()=>setMode("file");
$("#mtab-text").onclick = ()=>setMode("text");
$("#textinput").oninput = updateSubmit;
function pickFile(f){
  picked = f;
  $("#fname").textContent = f.name;
  $("#fsize").textContent = (f.size/1024/1024).toFixed(2)+" MB";
  $("#fileinfo").style.display = "block";
  updateSubmit();
}'''
assert old_js in h, 'pickFile 未匹配'
h = h.replace(old_js, new_js)

old_sub = '''  const fd = new FormData();
  fd.append("file", picked);
  fd.append("style", chosenStyle || "solemn-red");
  fd.append("duration", dur.value);'''
new_sub = '''  const fd = new FormData();
  if (mode === "file") { fd.append("file", picked); }
  else { fd.append("text", $("#textinput").value.trim()); }
  fd.append("style", chosenStyle || "solemn-red");
  fd.append("duration", dur.value);'''
assert old_sub in h, 'submit 未匹配'
h = h.replace(old_sub, new_sub)

open(p, 'w', encoding='utf-8').write(h)
print('index.html patched')

# JS 语法校验
js = re.search(r'<script>(.*?)</script>', h, re.S).group(1)
open('/tmp/ttv-web.js', 'w', encoding='utf-8').write(js)
print('done')
