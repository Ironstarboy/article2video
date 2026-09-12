// 前端「数字人形象」页的逻辑测试:用最小 DOM stub 在 Node 里跑 web/index.html 的**真实脚本**。
//
// 怎么跑(需要 node,无 npm 依赖):
//     node tests/avatar-page.test.js        # 从仓库根运行
//
// 它能抓什么(node --check 抓不到的那一类):
//   - 脚本里引用了不存在的变量/函数、el()/classList 用法写错;
//   - 删除没弹二次确认、确认文案里没有形象名;
//   - 「操作失败」的提示被随后的自动刷新冲掉(第一版真踩过);
//   - 环境变量钉住形象时界面没有如实标注;
//   - 卡片该显示的字段(名称/分辨率/体积/时间/默认角标/内置标记)少显示;
//   - 空库、读取失败、上传失败、删除失败的状态呈现。
//
// 它**不**负责:真实布局与视觉、浏览器 API 兼容性、接口本身的正确性
// (接口契约在 server/smoke_test.py 里测)。stub 只实现脚本真正用到的那几个 DOM 能力。
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");

// ── 最小 DOM ──
function El(tag) {
  this.tagName = (tag || "div").toUpperCase();
  this.children = []; this.attrs = {}; this.style = {}; this._text = "";
  this._classes = new Set(); this._html = "";
  this.classList = {
    add: (...c) => c.forEach(x => this._classes.add(x)),
    remove: (...c) => c.forEach(x => this._classes.delete(x)),
    toggle: (c, on) => { if (on === undefined) on = !this._classes.has(c);
                         on ? this._classes.add(c) : this._classes.delete(c); },
    contains: (c) => this._classes.has(c),
  };
  // el() 是直接赋 className 字符串的,而本 stub 用 _classes 做查找 —— 两者必须打通
  Object.defineProperty(this, "className", {
    get: () => [...this._classes].join(" "),
    set: (v) => { this._classes = new Set(String(v).split(/\s+/).filter(Boolean)); },
  });
  Object.defineProperty(this, "innerHTML", {
    get: () => this._html,
    set: (v) => {
      this._html = String(v);
      if (v === "") {
        // 真实 DOM 语义:清空 innerHTML 会把子节点**摘下来**(从文档里消失)。
        // 这一点必须模拟 —— 「改名前 wipe 掉容器,回调里再写 #proj-title」这种 bug
        // 只有摘除后才能真正复现(否则 byId 永远找得到那个节点)。
        this.children.forEach(c => { c.parentNode = null; });
        this.children = [];
      }
    },
  });
  Object.defineProperty(this, "textContent", {
    get: () => { if (this._text) return this._text;
                 return this.children.map(c => c.textContent).join(""); },
    set: (v) => {
      // 已从文档摘除的节点被写 textContent,在浏览器里是 "Cannot set properties of null"
      // (因为 $() 返回 null);这里让【分离节点】直接抛错,把这个 bug 变成测试红灯。
      if (this.detached) {
        throw new TypeError("Cannot set properties of null (setting 'textContent')");
      }
      this._text = String(v); this.children = [];
    },
  });
  Object.defineProperty(this, "detached", {
    get: () => this.parentNode === null && this._everAttached === true,
    configurable: true,
  });
  // 真实 DOM 里 childNodes 是 NodeList;beginRename 会 Array.from 它
  Object.defineProperty(this, "childNodes", { get: () => this.children.slice(),
                                              configurable: true });
}
El.prototype.appendChild = function (c) { this.children.push(c); c.parentNode = this; c._everAttached = true; return c; };
El.prototype.addEventListener = function () {};
El.prototype.focus = function () {};
El.prototype.select = function () {};
El.prototype.blur = function () {};
El.prototype.removeAttribute = function (k) { delete this.attrs[k]; };
El.prototype.getAttribute = function (k) { return this.attrs[k]; };
El.prototype.setAttribute = function (k, v) { this.attrs[k] = v; };
El.prototype.click = function () { if (this.onclick) this.onclick(); };
function walk(node, out) {
  out = out || [];
  out.push(node);
  (node.children || []).forEach(c => walk(c, out));
  return out;
}
El.prototype.find = function (cls) {
  return walk(this).filter(n => n._classes && n._classes.has(cls));
};
El.prototype.findTag = function (tag) {
  return walk(this).filter(n => n.tagName === String(tag).toUpperCase());
};
// 支持 ".cls" / "tag.cls" / "#id" 三种最简选择器(脚本只用到这几种)
El.prototype.querySelector = function (sel) {
  const s = String(sel || "").trim();
  let tag = null, cls = null, id = null;
  if (s.startsWith("#")) { id = s.slice(1); }
  else {
    const m = s.match(/^([A-Za-z][\w-]*)?\.([\w-]+)$/);
    if (m) { tag = m[1]; cls = m[2]; }
    else { tag = s; }
  }
  const hit = walk(this).find(n => n !== this
    && (!id || n.id === id)
    && (!cls || (n._classes && n._classes.has(cls)))
    && (!tag || n.tagName === tag.toUpperCase()));
  return hit || null;
};

// ── 文档树:让"节点是否还挂在文档里"这件事可判定 ──
// 真实 DOM 里 document.querySelector("#x") 找不到**已从文档摘除**的节点。
// 这里按 index.html 静态标记建一棵树(脚本 querySelector 到的 id 全部挂上;其中
// #proj-head 按真实结构挂上 #proj-title / #proj-sub,详情页改名那条路径依赖它),
// 再让 getById 只认「仍挂在树上」的节点 —— 于是"改名前清空容器、回调里再写子元素"
// 这类 bug 会真的红灯(修 2026-09-13 那个 textContent of null 就是靠它守住的)。
const DOC = new El("body");
const _rawIndex = {};

function makeEl(id, parent, tag) {
  const e = new El(tag || "div");
  e.id = id;
  _rawIndex[id] = e;
  (parent || DOC).appendChild(e);
  return e;
}

// 详情页头部:改名的宿主容器 + 它里面两个静态元素
const _projHead = makeEl("proj-head", DOC, "div");
makeEl("proj-title", _projHead, "h2").className = "proj-h-title";
makeEl("proj-sub", _projHead, "span").className = "proj-h-sub";

// 其余 id 按静态标记补全(直接从 index.html 里扫,省得手抄漏)
(() => {
  const html = fs.readFileSync(path.join(ROOT, "web", "index.html"), "utf8");
  const body = html.slice(0, html.indexOf("<script>"));
  const ids = new Set();
  for (const m of body.matchAll(/\$\("#([A-Za-z0-9_-]+)"\)/g)) ids.add(m[1]);
  for (const m of body.matchAll(/id="([A-Za-z0-9_-]+)"/g)) ids.add(m[1]);
  ids.forEach(id => { if (!_rawIndex[id]) makeEl(id, DOC); });
})();

function getById(id) {
  const e = _rawIndex[id];
  if (!e) return null;
  // 只认仍挂在文档树上的节点(与浏览器一致)
  return walk(DOC).includes(e) ? e : null;
}
global.document = {
  querySelector: (sel) => sel.startsWith("#") ? getById(sel.slice(1)) : new El("div"),
  querySelectorAll: () => [],
  getElementById: (id) => getById(id),
  createElement: (t) => new El(t),
  createTextNode: (t) => { const e = new El("#text"); e.textContent = t; return e; },
  addEventListener: () => {},
  removeEventListener: () => {},
  body: new El("body"),
  documentElement: new El("html"),
  activeElement: null,
  hidden: false,
};
const els = [];
global.window = { addEventListener: () => {}, location: { href: "", search: "" }, scrollTo: () => {} };
global.location = { href: "", search: "", hash: "" };
global.navigator = { userAgent: "node" };
global.alert = () => {};
global.confirmCalls = [];
global.confirm = (m) => { global.confirmCalls.push(m); return true; };
global.prompt = (m, d) => global.nextPrompt !== undefined ? global.nextPrompt : d;
global.setTimeout = setTimeout; global.clearTimeout = clearTimeout;
global.setInterval = () => 0; global.clearInterval = () => {};
global.requestAnimationFrame = (f) => setTimeout(f, 0);
global.matchMedia = () => ({ matches: false, addListener: () => {} });
global.getComputedStyle = () => ({ getPropertyValue: () => "" });

// ── fetch stub:记录请求,按剧本回响应 ──
const calls = [];
global.fetch = async (url, opts) => {
  calls.push({url, method: (opts && opts.method) || "GET", body: opts && opts.body});
  const lib = global.__lib;
  const mk = (obj, status) => ({ok: (status || 200) < 400, status: status || 200,
                                json: async () => obj, text: async () => JSON.stringify(obj)});
  if (url.endsWith("/api/avatars") && (!opts || !opts.method)) return mk(lib);
  // 全局偏好:新任务默认抠不抠背景
  if (url.endsWith("/api/preferences")) {
    if (opts && opts.method === "POST") {
      if (global.__prefFail) return mk({detail: "avatar_cutout_new_jobs 需要 true 或 false"}, 400);
      const sent = JSON.parse(opts.body).avatar_cutout_new_jobs;
      global.__pref = sent;
      return mk({ok: true, avatar_cutout_new_jobs: sent}, 200);
    }
    if (global.__prefNoData) return mk({}, 200);          // 老后端:响应里没有这个键
    return mk({avatar_cutout_new_jobs: global.__pref}, 200);
  }
  if (url.endsWith("/api/avatars") && opts.method === "POST") {
    if (global.__uploadFail) return mk({detail: "图片无法解析(文件完整性与格式校验不通过)"}, 400);
    return mk({ok: true, duplicate: false, item: {id: "av_new", name: "新形象"}}, 200);
  }
  if (/\/default$/.test(url)) return mk({ok: true, current: {id: "av_new", name: "新形象"}}, 200);
  if (/\/rename$/.test(url)) return mk({ok: true, item: {id: "av_new", name: "改名后"}}, 200);
  if (opts && opts.method === "DELETE") {
    if (global.__deleteFail) return mk({detail: "内置形象不可删除"}, 409);
    return mk({ok: true, items: lib.items, default_id: "jinli", current: lib.current}, 200);
  }
  // ── 设置页(分析服务 / 成片保存位置,保存即生效) ──
  if (url.endsWith("/api/settings") && (!opts || !opts.method || opts.method === "GET")) {
    if (global.__setGetFail) return mk({detail: "boom"}, 500);
    return mk(Object.assign({}, global.__settings), 200);
  }
  if (url.endsWith("/api/settings") && opts.method === "POST") {
    const body = JSON.parse(opts.body || "{}");
    if (global.__setFail) return mk({detail: "服务地址要以 http:// 或 https:// 开头"}, 400);
    if ("llm_key" in body) global.__settings.llm_key_set = !!body.llm_key;
    ["llm_url", "llm_model", "export_dir"].forEach(k => {
      if (k in body) global.__settings[k] = body[k];
    });
    return mk(Object.assign({ok: true}, global.__settings), 200);
  }
  if (url.endsWith("/api/settings/llm/test")) {
    return mk(global.__setTestResult
      || {ok: true, latency_ms: 120, message: "连接正常(用时 0.1 秒)"}, 200);
  }
  if (url.endsWith("/api/settings/reset")) {
    // 恢复默认 = 服务端删掉设置文件,于是载荷里的当前值就是**出厂默认**(与真实接口一致)
    const f = settingsPayload();
    global.__settings = Object.assign({}, f, {
      llm_url: f.factory.llm_url, llm_model: f.factory.llm_model,
      export_dir: f.factory.export_dir, llm_key_set: false, llm_key_masked: "",
    });
    return mk(Object.assign({ok: true}, global.__settings), 200);
  }
  return mk({}, 404);
};
global.FormData = class { constructor(){ this.d = {}; } append(k, v){ this.d[k] = v; } };

// ── 加载真实脚本 ──
const html = fs.readFileSync(path.join(ROOT, "web", "index.html"), "utf8");
const m = html.match(/<script>\n([\s\S]*?)<\/script>\s*<\/body>/);
if (!m) { console.error("FAIL 找不到脚本块"); process.exit(1); }
const js = m[1];

const lib = () => ({
  items: [
    {id: "jinli", name: "金立", file: "jinli.png", width: 660, height: 781, bytes: 644100,
     created_at: 1789157476.76, builtin: true},
    {id: "av_a", name: "测试A", file: "av_a.png", width: 400, height: 500, bytes: 2087,
     created_at: 1789232566.1, builtin: false},
  ],
  default_id: "av_a",
  current: {id: "av_a", name: "测试A", file: "av_a.png", path: "/tmp/av_a.png", env_override: false},
  max_bytes: 20971520, accept: [".jpeg", ".jpg", ".png", ".webp"],
});
global.__lib = lib();
global.__pref = true;          // 默认抠背景(出厂默认)

// 设置页的服务端载荷(密钥只有掩码 —— 页面永远拿不到明文)
function settingsPayload(){
  return {
    llm_url: "https://llmapi.paratera.com/v1",
    llm_model: "DeepSeek-V4-Flash",
    llm_key_masked: "••••••••ybfg", llm_key_set: true,
    export_dir: "", export_dir_used: "/data/Avatar/jobs",
    export_dir_capacity: {path: "/data/Avatar/jobs", total_gb: 97.9, free_gb: 42.2},
    factory: {llm_url: "http://8.130.213.80:20001/v1", llm_model: "DeepSeek-V4-Flash",
              export_dir: ""},
    file: "/data/Avatar/.run/settings.json",
  };
}
global.__settings = settingsPayload();

let PASS = 0, FAIL = 0;
function ok(name, cond, detail) {
  console.log((cond ? "PASS" : "FAIL") + " [" + name + "]" + (detail ? "  " + detail : ""));
  cond ? PASS++ : FAIL++;
}

// 用 eval 在全局执行(脚本是 IIFE 之外的一堆函数与顶层绑定)
try {
  eval(js + "\n;global.__api = {loadAvatarLibrary, renderAvatarLibrary, avUpload, avDelete, avAction, avRename, wireAvatarPage, fmtSize, renderUploadAvatarHint, applyAvatarMeta, renderAvatarControls, loadPreferences, saveAvatarPrefCutout, renderAvatarPref, wireSettingsPage, loadSettings, renderSettings};");
} catch (e) {
  console.error("FAIL 脚本执行抛异常:", e && e.message);
  process.exit(1);
}
ok("前端脚本在最小 DOM 下可完整执行(无未定义引用)", true);

const api = global.__api;

(async () => {
  // ① 形象页:加载一次列表并渲染
  getById("view-avatars").classList.remove("hidden");
  await api.loadAvatarLibrary(true);
  console.log("DEBUG calls:", JSON.stringify(calls.map(c=>c.url)));
  console.log("DEBUG avItems:", JSON.stringify((global.__lib||{}).items && global.__lib.items.length));
  console.log("DEBUG alert:", getById("av-alert").textContent);
  const grid = getById("av-grid");
  const cards = grid.find("av-card");
  ok("渲染出两张形象卡片", cards.length === 2, "cards=" + cards.length);
  const names = grid.find("nm").map(n => n.textContent);
  ok("卡片显示名称", names.includes("金立") && names.includes("测试A"), JSON.stringify(names));
  ok("默认形象卡片打上 isdefault 且带角标",
     cards[1]._classes.has("isdefault") && grid.find("badge").some(b => b.textContent === "当前默认"));
  ok("内置形象卡片带「内置」标记",
     grid.find("builtin").some(b => b.textContent === "内置"));
  const metas = grid.find("meta").map(m => m.textContent);
  ok("卡片显示分辨率/体积/时间",
     metas[0].includes("660×781") && metas[0].includes("KB|MB".split("|").find(u => metas[0].includes(u)) || "KB"),
     metas[0]);
  ok("缩略图指向取图接口",
     grid.find("thumb").every(t => (t.children[0].src || "").startsWith("./api/avatars/")));
  ok("当前默认行显示生效形象与说明",
     getById("av-current").textContent.includes("测试A")
     && getById("av-current").textContent.includes("当前默认形象"));
  ok("上传区提示带格式与体积上限",
     getById("av-up-small").textContent.includes("20MB")
     && getById("av-up-small").textContent.includes(".png"));
  ok("删除按钮:内置禁用、非内置可用",
     grid.find("ops")[0].children[2].disabled === true
     && grid.find("ops")[1].children[2].disabled === false);
  ok("「已是默认」按钮在默认卡片上禁用",
     grid.find("ops")[1].children[0].textContent === "已是默认"
     && grid.find("ops")[1].children[0].disabled === true);

  // ② 上传成功 → 列表刷新 + 成功 toast
  calls.length = 0;
  const fakeFile = {name: "face.png", size: 12345};
  await api.avUpload(fakeFile);
  ok("上传走 multipart POST /api/avatars",
     calls.some(c => c.method === "POST" && c.url === "./api/avatars" && c.body instanceof global.FormData));
  ok("上传成功后有 toast", getById("toast").textContent.includes("已上传"), getById("toast").textContent);
  ok("上传成功后自动刷新列表", calls.filter(c => c.url === "./api/avatars").length >= 2);

  // ③ 上传失败 → 错误提示**不被随后的刷新冲掉**(实测踩到的 bug)
  global.__uploadFail = true;
  await api.avUpload({name: "bad.png", size: 100});
  global.__uploadFail = false;
  const alertBox = getById("av-alert");
  ok("上传失败:提示条可见且写明原因",
     alertBox._classes.has("hidden") === false
     && alertBox.textContent.includes("上传失败")
     && alertBox.textContent.includes("无法解析"), alertBox.textContent);
  // 再做一次成功的读取,读类错误清空但操作类错误保留
  await api.loadAvatarLibrary(true);
  ok("读取成功不会清掉操作失败提示", alertBox.textContent.includes("上传失败"));

  // ④ 删除:必须二次确认,确认文案含形象名
  global.confirmCalls = [];
  await api.avDelete(global.__lib.items[1]);
  ok("删除前弹二次确认", global.confirmCalls.length === 1, JSON.stringify(global.confirmCalls));
  ok("确认文案含形象名", (global.confirmCalls[0] || "").includes("测试A"), global.confirmCalls[0]);

  // ⑤ 删除失败:提示保留(刷新成功后仍在)
  global.__deleteFail = true;
  await api.avDelete(global.__lib.items[1]);
  global.__deleteFail = false;
  ok("删除失败:提示条写明原因且未被刷新冲掉",
     getById("av-alert").textContent.includes("删除失败")
     && getById("av-alert").textContent.includes("不可删除"), getById("av-alert").textContent);

  // ⑥ 重命名:空名被拦、正常改名调接口
  global.nextPrompt = "   ";
  calls.length = 0;
  await api.avRename(global.__lib.items[1]);
  ok("重命名空名被前端拦下(不发请求)",
     !calls.some(c => /rename$/.test(c.url)) && getById("av-alert").textContent.includes("不能为空"));
  global.nextPrompt = "新名字";
  calls.length = 0;
  await api.avRename(global.__lib.items[1]);
  ok("重命名走 POST …/rename", calls.some(c => c.method === "POST" && /rename$/.test(c.url)));
  delete global.nextPrompt;

  // ⑦ 设为默认
  global.__lib.current = {id: "jinli", name: "金立", file: "jinli.png", path: "/p", env_override: false};
  calls.length = 0;
  await api.avAction("default", global.__lib.items[1]);
  ok("设为默认走 POST …/default", calls.some(c => c.method === "POST" && /default$/.test(c.url)));

  // ⑧ 环境变量钉住时:如实标注、不显示「默认」角标
  global.__lib.current = {id: "", name: "pinned", file: "pinned.png", path: "/tmp/pinned.png", env_override: true};
  await api.loadAvatarLibrary(true);
  ok("环境变量覆盖时:当前行如实标注并跳过缩略图",
     getById("av-current").textContent.includes("TTV_AVATAR_IMAGE")
     && getById("av-current").children.length === 1)
  const cards2 = getById("av-grid").find("av-card");
  ok("环境变量覆盖时:卡片不误标「当前默认」", !cards2.some(c => c._classes.has("isdefault")));
  global.__lib.current = lib().current;

  // ⑨ 空库
  global.__lib = {items: [], default_id: "", current: {id: "", name: "", file: "", env_override: false},
                  max_bytes: 20971520, accept: [".png"]};
  await api.loadAvatarLibrary(true);
  ok("空库显示空状态文案", getById("av-grid").textContent.includes("先上传一张"), getById("av-grid").textContent);

  // ⑩ 库读取失败:显示可重试的提示
  global.__lib = null;
  const realFetch = global.fetch;      // 存下来:本用例会把 fetch 换成"永远抛错"
  global.fetch = async () => { throw new Error("网络断了"); };
  await api.loadAvatarLibrary(true);
  ok("读取失败显示错误与重试按钮",
     getById("av-alert").textContent.includes("读取形象库失败")
     && getById("av-grid").textContent.includes("重新加载"), getById("av-alert").textContent);

  // ⑪ 创作页当前形象提示
  api.applyAvatarMeta({avatar_library: {current: {id: "av_a", name: "测试A", env_override: false}}});
  const who = getById("up-avatar-who");
  ok("创作页提示显示当前形象名与跳转链接",
     who.textContent.includes("测试A") && who.textContent.includes("管理形象")
     && who.findTag("a").length === 1 && who.findTag("a")[0].href === "./?avatars=1",
     who.textContent + " | href=" + (who.findTag("a")[0] || {}).href);

  // ⑫ 全局偏好开关「新任务默认抠掉背景」
  //     背景:抠像原来是任务级选项且默认关,换完形象还得回创作页勾一次,忘了就是"背景没抠掉"。
  global.fetch = realFetch;            // 恢复真实 stub(上一个用例故意把网络打断了)
  global.__lib = lib();
  global.__pref = true;
  await api.loadPreferences();
  const cut = getById("av-pref-cutout");
  ok("打开形象页即回显偏好(默认开启抠背景)", cut.checked === true && cut.disabled === false);
  ok("开关文案说明当前状态",
     getById("av-pref-cutout-tip").textContent.includes("已开启"), getById("av-pref-cutout-tip").textContent);

  calls.length = 0;
  await api.saveAvatarPrefCutout(false);
  const post = calls.find(c => c.method === "POST" && c.url === "./api/preferences");
  ok("关掉开关:POST /api/preferences 且只发这一个布尔字段",
     !!post && JSON.parse(post.body).avatar_cutout_new_jobs === false, post && post.body);
  ok("关掉后回显为关闭且带 toast",
     cut.checked === false && getById("toast").textContent.includes("默认保留背景"), getById("toast").textContent);

  await api.saveAvatarPrefCutout(true);
  ok("再打开:回显开启", cut.checked === true && getById("toast").textContent.includes("默认抠掉背景"));

  // 保存失败:提示可见、且不改动开关显示(不能让用户以为已经生效)
  global.__prefFail = true;
  await api.saveAvatarPrefCutout(false);
  global.__prefFail = false;
  ok("保存失败:提示可见且写明原因",
     getById("av-alert").textContent.includes("保存默认抠背景设置失败"), getById("av-alert").textContent);
  ok("保存失败:开关回到服务端的真实值(不假装已生效)", cut.checked === true);
  ok("保存失败:提示不会被随后的读取清掉", await (async () => {
       await api.loadAvatarLibrary(true);
       return getById("av-alert").textContent.includes("保存默认抠背景设置失败");
     })());

  // 老后端返回里没有这个键:开关置灰而不是误显示为「关」
  global.__prefNoData = true;
  const cut2 = getById("av-pref-cutout");
  cut2.disabled = false;
  await api.loadPreferences();
  ok("偏好拿不到时开关置灰(不误显示为关闭)",
     cut2.disabled === true && getById("av-pref-cutout-wrap")._classes.has("disabled"));
  global.__prefNoData = false;

  // 创作页:走真实的 renderAvatarControls(它就是 /api/styles 回来后渲染控件的那条路),
  // 验证偏好变了之后勾选框与形象页开关都跟着变。
  const styleData = (cut) => ({
    avatar_sizes: {default: 300, native: 464, min: 160, max: 1080, choices: [240, 300, 400, 464, 640]},
    avatar_corners: [{key: "tl", name: "左上"}, {key: "tr", name: "右上"}],
    avatar_corner_default: "tr",
    avatar_cutout_default: cut, preferences: {avatar_cutout_new_jobs: cut},
    avatar_library: {current: {id: "av_a", name: "测试A", env_override: false}},
  });
  api.renderAvatarControls(styleData(false));
  ok("创作页抠像勾选框跟随偏好(=关闭)",
     getById("up-avatar-cutout").checked === false && getById("av-pref-cutout").checked === false);
  api.renderAvatarControls(styleData(true));
  ok("偏好改成开启后,创作页勾选框与形象页开关都变(true)",
     getById("up-avatar-cutout").checked === true && getById("av-pref-cutout").checked === true,
     "up=" + getById("up-avatar-cutout").checked + " pref=" + getById("av-pref-cutout").checked);

  // ⑬ 回归:预览页「重命名」
  //     真实 bug(2026-09-13 用户报):beginRename 用 host.innerHTML = "" 把 #proj-title /
  //     #proj-sub **从文档里摘掉**,成功回调又直接写它们的 textContent → 拿到 null,
  //     报 "Cannot set properties of null (setting 'textContent')",改名看着"失败"。
  //     这条用例靠 stub 的"摘除即查不到 + 写分离节点抛错"来复现,不修就是红灯。
  {
    const head = getById("proj-head");
    const title = getById("proj-title");
    const sub = getById("proj-sub");
    ok("前置:详情页头部三个元素都在文档里",
       !!head && !!title && !!sub && !!head.querySelector(".proj-h-title"));
    title.textContent = "旧标题";
    sub.textContent = "自动总结 · #job";

    const rn = getById("btn-rename");
    rn.onclick();                                   // 进入编辑态:host 内容被换成输入框
    const inp = head.querySelector(".rename-input");
    ok("点「重命名」后出现输入框,且静态子元素已离开文档",
       !!inp && getById("proj-title") === null && getById("proj-sub") === null);

    inp.value = "用户改的标题";
    const oldFetch = global.fetch;
    global.fetch = async (url, opts) => {
      if (/\/rename$/.test(url)) return {ok: true, status: 200,
        json: async () => ({ok: true, title: "用户改的标题"})};
      return oldFetch(url, opts);
    };
    try {
      head.querySelector(".smallbtn").onclick();     // 「保存」
    } finally {
      global.fetch = oldFetch;
    }
    // commit 是 async:让挂起的 promise 跑完
    await new Promise(r => setTimeout(r, 0));
    await new Promise(r => setTimeout(r, 0));

    ok("改名成功后:标题写回、输入框撤掉(不再抛 textContent of null)",
       getById("proj-title") !== null && getById("proj-title").textContent === "用户改的标题",
       "title=" + (getById("proj-title") ? getById("proj-title").textContent : "<null>"));
    // 测试环境下没有真实 jobId(location.search 为空),所以只断言前缀
    ok("改名成功后:副标题标明手动命名",
       getById("proj-sub") !== null
       && getById("proj-sub").textContent.indexOf("手动命名 · #") === 0,
       "sub=" + (getById("proj-sub") ? getById("proj-sub").textContent : "<null>"));
    ok("改名成功后:编辑态已退出且提示已给出",
       !head.querySelector(".rename-input") && getById("toast").textContent.includes("用户改的标题"));
    ok("改名成功后:容器里的静态元素回到文档",
       !!head.querySelector(".proj-h-title"));
  }

  // ⑪ 设置页:分析服务(地址 / 密钥 / 模型)—— 保存即生效,密钥只写不读
  {
    getById("view-settings").classList.remove("hidden");
    api.wireSettingsPage();
    calls.length = 0;
    await api.loadSettings();
    ok("设置页读取 GET /api/settings", calls.some(c => c.url === "./api/settings"));
    ok("地址与模型回显到输入框",
       getById("set-llm-url").value === "https://llmapi.paratera.com/v1"
       && getById("set-llm-model").value === "DeepSeek-V4-Flash");
    ok("密钥输入框为空(不回显明文),只在说明里给掩码",
       getById("set-llm-key").value === ""
       && getById("set-llm-key").placeholder.includes("••••")
       && getById("set-key-hint").textContent.includes("••••"));
    ok("保存位置提示带当前去向与剩余空间",
       getById("set-export-hint").textContent.includes("/data/Avatar/jobs")
       && getById("set-export-hint").textContent.includes("42.2 GB"),
       getById("set-export-hint").textContent);

    // 保存:密钥留空**不能**顺手把已保存的密钥清掉(最危险的一类回归)
    calls.length = 0;
    getById("set-llm-url").value = "https://new.test/v1";
    getById("set-llm-key").value = "";
    getById("set-llm-save").onclick();
    await new Promise(r => setTimeout(r, 0)); await new Promise(r => setTimeout(r, 0));
    const saveCall = calls.find(c => c.url === "./api/settings" && c.method === "POST");
    const saveBody = saveCall ? JSON.parse(saveCall.body) : {};
    ok("保存时密钥留空 = 不改动(请求体里没有 llm_key)",
       !("llm_key" in saveBody), JSON.stringify(saveBody));
    ok("保存成功后有明确反馈", getById("set-llm-status").textContent.includes("已保存"),
       getById("set-llm-status").textContent);

    calls.length = 0;
    getById("set-llm-key").value = "sk-new-123456";
    getById("set-llm-save").onclick();
    await new Promise(r => setTimeout(r, 0)); await new Promise(r => setTimeout(r, 0));
    const b2 = JSON.parse(calls.find(c => c.url === "./api/settings" && c.method === "POST").body);
    ok("填了新密钥时随保存一起提交", b2.llm_key === "sk-new-123456");

    // 测试连接:用页面上**还没保存**的地址与密钥试
    calls.length = 0;
    getById("set-llm-url").value = "https://probe.test/v1";
    getById("set-llm-key").value = "sk-probe-1";
    global.__setTestResult = {ok: true, latency_ms: 130, message: "连接正常(用时 0.1 秒)"};
    getById("set-llm-test").onclick();
    await new Promise(r => setTimeout(r, 0)); await new Promise(r => setTimeout(r, 0));
    const t1 = calls.find(c => c.url === "./api/settings/llm/test");
    const t1b = t1 ? JSON.parse(t1.body) : {};
    ok("测试连接用页面上未保存的地址与密钥试",
       t1b.llm_url === "https://probe.test/v1" && t1b.llm_key === "sk-probe-1", JSON.stringify(t1b));
    ok("测试成功时状态行显示连接正常并标绿",
       getById("set-llm-status").textContent.includes("连接正常")
       && getById("set-llm-status")._classes.has("ok"));
    ok("测试连接结束后按钮恢复可用", getById("set-llm-test").disabled === false);

    global.__setTestResult = {ok: false, message: "连不上这个地址,请核对地址与网络"};
    getById("set-llm-test").onclick();
    await new Promise(r => setTimeout(r, 0)); await new Promise(r => setTimeout(r, 0));
    ok("测试失败时把人话原因显示出来并标红",
       getById("set-llm-status").textContent.includes("连不上这个地址")
       && getById("set-llm-status")._classes.has("err"));
    global.__setTestResult = null;

    // 保存失败(400):如实显示服务端原话,且**不清掉用户刚填的内容**
    global.__setFail = true;
    getById("set-llm-url").value = "没有协议头";
    getById("set-llm-save").onclick();
    await new Promise(r => setTimeout(r, 0)); await new Promise(r => setTimeout(r, 0));
    ok("保存失败显示服务端原话(人话)",
       getById("set-llm-status").textContent.includes("http://"),
       getById("set-llm-status").textContent);
    ok("保存失败不会把用户填的内容抹掉", getById("set-llm-url").value === "没有协议头");
    global.__setFail = false;
    await api.loadSettings();   // 回到服务端真实值

    // 清除密钥:必须二次确认,且只提交 llm_key 空串
    calls.length = 0;
    global.confirmCalls.length = 0;
    getById("set-key-clear").onclick();
    await new Promise(r => setTimeout(r, 0)); await new Promise(r => setTimeout(r, 0));
    ok("清除密钥前先弹二次确认",
       global.confirmCalls.length === 1 && global.confirmCalls[0].includes("清除"),
       JSON.stringify(global.confirmCalls));
    const cb = JSON.parse(calls.find(c => c.url === "./api/settings" && c.method === "POST").body);
    ok("清除密钥只提交 llm_key 空串", cb.llm_key === "" && Object.keys(cb).length === 1,
       JSON.stringify(cb));
  }

  // ⑫ 设置页:成片保存位置 / 默认开关 / 恢复默认
  {
    calls.length = 0;
    getById("set-export-dir").value = "/mnt/data/成片";
    getById("set-export-save").onclick();
    await new Promise(r => setTimeout(r, 0)); await new Promise(r => setTimeout(r, 0));
    const eb = JSON.parse(calls.find(c => c.url === "./api/settings" && c.method === "POST").body);
    ok("保存位置只提交 export_dir(不动分析服务)",
       eb.export_dir === "/mnt/data/成片" && Object.keys(eb).length === 1, JSON.stringify(eb));
    ok("保存位置成功后提示「以后出片会自动另存」",
       getById("set-export-status").textContent.includes("另存"),
       getById("set-export-status").textContent);

    // 默认设置里的抠像开关 = 形象页那份全局偏好(同一个接口、同一个值)
    getById("set-pref-cutout").checked = false;
    calls.length = 0;
    getById("set-pref-cutout").onchange();
    await new Promise(r => setTimeout(r, 0)); await new Promise(r => setTimeout(r, 0));
    const pc = calls.find(c => c.url === "./api/preferences" && c.method === "POST");
    ok("设置页的抠像开关走同一个 /api/preferences",
       !!pc && JSON.parse(pc.body).avatar_cutout_new_jobs === false);
    ok("形象页与设置页的开关状态保持一致",
       getById("set-pref-cutout").checked === false
       && getById("av-pref-cutout").checked === false);

    calls.length = 0;
    getById("set-reset").onclick();
    await new Promise(r => setTimeout(r, 0)); await new Promise(r => setTimeout(r, 0));
    ok("恢复默认后地址回到服务器原本的值",
       getById("set-llm-url").value === "http://8.130.213.80:20001/v1",
       getById("set-llm-url").value);
    ok("恢复默认有结果反馈", getById("set-reset-status").textContent.includes("已恢复"),
       getById("set-reset-status").textContent);
  }

  console.log("\n" + PASS + " passed, " + FAIL + " failed");
  process.exit(FAIL ? 1 : 0);
})();
