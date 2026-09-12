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
    set: (v) => { this._html = String(v); if (v === "") this.children = []; },
  });
  Object.defineProperty(this, "textContent", {
    get: () => { if (this._text) return this._text;
                 return this.children.map(c => c.textContent).join(""); },
    set: (v) => { this._text = String(v); this.children = []; },
  });
}
El.prototype.appendChild = function (c) { this.children.push(c); c.parentNode = this; return c; };
El.prototype.addEventListener = function () {};
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

// ── id → 元素(脚本一启动就 querySelector 一堆 id,全部预建) ──
const byId = {};
function getById(id) {
  if (!byId[id]) { byId[id] = new El("div"); byId[id].id = id; }
  return byId[id];
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

let PASS = 0, FAIL = 0;
function ok(name, cond, detail) {
  console.log((cond ? "PASS" : "FAIL") + " [" + name + "]" + (detail ? "  " + detail : ""));
  cond ? PASS++ : FAIL++;
}

// 用 eval 在全局执行(脚本是 IIFE 之外的一堆函数与顶层绑定)
try {
  eval(js + "\n;global.__api = {loadAvatarLibrary, renderAvatarLibrary, avUpload, avDelete, avAction, avRename, wireAvatarPage, fmtSize, renderUploadAvatarHint, applyAvatarMeta, renderAvatarControls, loadPreferences, saveAvatarPrefCutout, renderAvatarPref};");
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

  console.log("\n" + PASS + " passed, " + FAIL + " failed");
  process.exit(FAIL ? 1 : 0);
})();
