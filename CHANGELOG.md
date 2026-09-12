# 理论文章转视频网站 — 项目计划与进度

> 最后更新:2026-09-12
> 部署位置:**VideoLab 云服务器**(SSH `videolab`,8.130.213.80),整个项目运行在服务器上。
> 本地此文件夹保存:计划文档、源码副本、风格脚本、部署配置。

## v2.2(2026-09-12)

**修复:渲染期间「长时间没有反应、没有进度」**
- `stage_render` 由 `subprocess.run` 一次性收走输出,改为**流式**读取并解析 hyperframes 的帧级进度(`Streaming frame n/N` / `Capturing frame n/N` / `Calibration: capturing test frame n/N`),界面显示「捕获帧 n/N · 已用 · 预计剩余」与进度条(两步:渲染 PPT 视频 → 叠加数字人片段);捕获阶段一旦有帧数,预计剩余改用**实测速率**反推
- 叠加步骤解析 ffmpeg `-progress`,显示「叠加数字人片段 57% · 已用 0:08 · 预计剩余 0:06」
- 速率系数实测校准并进 config:`RENDER_RT_FACTOR=0.8`(81s 片≈85s、152s 片≈200s)、`OVERLAY_RT_FACTOR=4.5`(81s 片 15s、152s 片≈40s)——只影响展示
- **`ppt`/`final` 产物显式写进 `state.artifacts`**:此前渲染完只记 `avatar`,最终版靠 `render_format` 反推文件名,现在三个产物都在 state 里
- 实测 81 秒成片:渲染 85s + 叠加 15s,进度从「准备中」→ 帧级 → 「编码封装」→ 叠加百分比全程可见(无头 Chrome 抓页面 DOM 复核)

**修复:Studio 预览一直转圈(部署相关,两个硬编码)**- **硬编码 `/ttv/` 资源前缀**:Studio 代理把页面里的 `/assets/`、`/api/` 一律改写成 `/ttv/api/studio/<job>/…`。这在文档里的 nginx `/ttv/` 部署下成立,但应用挂在根路径时(直接访问后端、或未剥前缀的转发),Studio 的 JS/CSS 全部 404 —— 壳页面能加载、bundle 永远不到,表现就是「构建预览一直转圈」。改为按请求推断挂载前缀(`_client_base`:从 Referer/Origin 取 `/ttv` 或空),两种部署都对
- **硬编码 Studio 项目 id `ttv`**:hyperframes 用**工作区根目录名**当项目 id(文档部署 `/mnt/workspace/ttv` → `ttv`;本工作区根 `/data/Avatar` → **`Avatar`**),写死导致 `/api/projects/ttv`、`/preview`、`/lint`、`/files/*` 全 404。改为向 Studio 的 `/api/projects` 探测真实 id(按 dir 匹配,失败按目录名兜底),请求/响应两侧做 id 桥接,前端 iframe 的 `#project/ttv` 无需改动
- **`/api/studio/*` 只注册了 GET**:编辑器的保存/选择类请求走 PUT/POST,遇到 405。改为放开 GET/POST/PUT/PATCH/DELETE
- 实测(根部署,无头 Chrome):Studio bundle 与其全部接口 200(`/api/projects/ttv`、`/preview`、`/lint`、`/files/index.html`、`/renders`),`PUT …/selection` 由 405 变 200,Studio SPA 正常启动

**修复:两条轨道共用同一版配音(顺序不再影响结果)**
- `stage_build` 改为默认**复用已有配音**(原先每次都删掉重合成)。本地 TTS 逐次结果并不稳定(实测同一句 4.08s / 20.00s / 20.00s),「先播报后构建」会拿到与播报视频不同的另一版声音;现在谁先跑谁定义配音,另一方复用,`state.vo_sig` + `project/script.json` 逐帧文本双重判定,脚本一改立刻重新合成
- 副作用收益:每次「重新构建」省掉 1-3 分钟 TTS(实测 40s → 4s,配音文件逐字节不变)
- 新增逃生口 `POST /api/jobs/{id}/build?force_voice=1`(强制重新合成,用于重掷不理想的配音)
- 播报视频的 `stale` 标记只在**真的重新合成了配音**时打(复用同一版声音则仍然有效)

**数字人播报视频(新功能:分析完成即可单独出片)**
- 新增独立支线:分析完成后,页面「数字人播报视频」区块一键生成 —— 把逐帧数字人画面按时间轴顺序拼成一条 320×320 视频(含完整配音音轨),**不经过 HyperFrames 渲染**,不需要先构建预览、也不需要等成片
- 生成步骤与预计时间:区块按「合成配音 → 生成数字人片段 → 拼接播报视频」三步展示,逐帧回写进度条、已用时间与预计剩余;点击前先给出预计耗时
- 完成后就地独立预览(`<video>` 播放,支持 Range 拖动)与下载(显示格式 + 大小);产物记为第三个 artifact `state.artifacts.avatar → renders/avatar.mp4`
- 配音复用:`state.vo_sig`(逐帧台词 + 音色 + 引擎摘要)未变且配音文件齐全时跳过合成,重跑由分钟级降到秒级
- 音轨跟画面走:拼接前逐片段 ffprobe 真实时长,音轨按真实时长铺(帧首 0.25s 静音与成片 `data-start` 同口径),避免毫秒差逐帧累积被 `-shortest` 裁掉片尾
- 失败无害:失败只写 `avatar_broadcast.error` 并回到进入前的状态,脚本/成片/Studio 均不受影响,可反复重试
- 并发与状态:新增进行中状态 `avatar_building`(计入 `MAX_INFLIGHT_JOBS`,重启自动置 failed 可重跑);`/analyze`、`DELETE`、`/avatar/broadcast` 全部拒绝在其期间重入

**接口与前端**
- `POST /api/jobs/{id}/avatar/broadcast`(守卫用拒绝列表,已渲染的任务同样可再生成)、`GET /api/jobs/{id}/avatar/broadcast/video`
- `GET /api/jobs/{id}` 新增 `avatar_broadcast_est_sec`(事前预计,基准取 `total_sec > 脚本帧时长之和 > duration_sec`)
- 前端新增「数字人播报视频」面板(步骤芯片 / 进度条 / 已用与预计 / 错误条 / 播放器 / 下载);`avatar_building` 轮询 2s
- 速度系数集中进 `server/config.py`(`TTV_AVATAR_RT_FACTOR`=0.85 实测、`TTV_AVATAR_CONCAT_RT_FACTOR`=15、`TTV_AVATAR_TTS_RT_FACTOR`=2.5),只影响展示不影响产物

**重构与测试**
- `stage_build` 的「拓展 + 配音 + 时长回填」抽成 `_synthesize_and_fit()` 与播报支线共用,构建行为不变(顺序、进度文案、清理时机逐条对齐)
- `build_frame_clips` 增加 `on_frame` 结构化回调(逐帧进度);`tts.synthesize_frames` 增加 `progress_cb`;词级时间轴抽成 `tts.word_times()` 供配音复用路径重建
- `jobs.Job` 增加 `artifact_path()` / `script()`;`artifacts` 报告改为遍历 `ARTIFACTS`
- smoke_test 新增 15 项:音轨时长/采样率/帧首静音、耗时估算与三档 ETA、播报产物读写与缺失兜底、`word_times` 口径
- 端到端实测(30 秒档宣传片):分析 → 播报视频首次 116s / 重跑 1.9s,产物 320×320 h264 + AAC 44.1k 单声道 74.75s;音轨静音段与帧结构逐段吻合(开场 5.17s 静音、句间 0.7-0.9s、结尾 3.5s),浏览器实测进度/ETA/播放器均正常

## v2.1(2026-09-10)

**运维**
- 日志统一收进 `/mnt/workspace/ttv/logs/`:`backend.log`(后端)、`tts/*.log`(CosyVoice3 三实例 / Qwen3-TTS)、`studio/<job_id>.log`(每任务 Studio 输出),项目根目录不再落日志文件
- 路径常量集中在 `server/config.py`(LOG_DIR / BACKEND_LOG / STUDIO_LOG_DIR / TTS_LOG_DIR,可用 `TTV_LOG_DIR` 覆盖),`server/main.py` 写 Studio 日志前自动建目录
- `deploy/start.sh`、`start-tts.sh`、`start-tts-qwen.sh`、`setup.sh` 的重定向与目录创建同步更新;start.sh 增加 `uvicorn server.main:app` 进程匹配(此前只杀 `uvicorn main:app`,以 `server.main:app` 方式启动的实例会漏杀)

## v2.0(2026-08-28)

**效率与硬件**
- CosyVoice3 扩为三实例(GPU1@8016 / GPU2@8018 / GPU3@8019),客户端按帧轮询分发并行合成;Qwen3-TTS 备用 GPU2@8017(默认停)
- 讲解视频分段脚本并行生成(ThreadPoolExecutor 3 workers,段间无依赖)
- httpx 全局共享连接池,修复历史上 "Too many open files" FD 耗尽
- 并发限制:全局 LLM 信号量 6、渲染信号量 2(同时最多 2 个)、进行中任务 >4 时新任务创建返回 429
- 轮询轻量化:GET /api/jobs/{id}?brief=1 不含 script;terminal 状态(rendered/failed)停止轮询、active 期指数退避(2.5s→5s→10s 封顶)、页面隐藏暂停
- 构建期字体复制去除(渲染项目直接引用 assets/fonts/,避免每任务重复拷贝大字体)

**工作流**
- 宣传视频改两阶段分析:阶段一「分析」输出小契约(核心论点/论证链节拍/数据清单(逐字核验)/金句清单(逐字)/帧计划),阶段二「脚本」按帧计划生成 frames,分析深度反哺脚本
- 金句接地:quote 帧引语逐字接地到原文,无法接地保留但写 `_meta.warning`
- 永不失败兜底:模型重试 3 次仍不合规时,对最近一次成功解析的脚本做确定性修复(丢最短旁白次要帧 + 时长缩放)后接受,`_meta.warning` 记录
- max_tokens 分档(≤90s:4096 / ≤180s:8192 / ≤360s:12288 / >360s:16384),检测 finish_reason=length 截断并重试;temperature 首轮 0.35、纠错重试 0.6
- 语速换算统一:config.CHARS_PER_SEC=4.2 全局引用,宣传档位旁白系数 3.0/3.8/3.9/4.0 字/秒(有意低于实测语速,余量由构建期留白分摊),拓展验收线统一 0.8
- 讲解备课方案校验:chapters para_range 必须覆盖全文每个段落(无空洞/重叠,否则修复),paragraph_notes 缺失程序化补(key_idea 取段首 40 字);分段 prompt 只注入本段相关章节与段落要点(瘦身);line_analysis 重点段未获 textblock/annotation 帧打印警告;annotation 批注句同帧必须出自同一段

**前端**
- 字体子集化 woff2(UI 用字约 3000 常用字 + 静态文案,每份 <300KB),unicode-range 回退系统字体,配合 nginx assets 长缓存(immutable)与 index.html no-cache,修复此前 @font-face 引 /ttv/assets/ 但无 nginx 路由导致字体 404 从未生效的问题
- 轮询修复:script 内容变化(JSON 比对)才重渲染,编辑模式不被轮询覆盖
- 骨架屏(分析与逐帧区)、banner ok/err 状态样式实际使用、重新分析按钮(failed 且无 script)、删除任务按钮、下载按钮显示格式 + 文件大小
- 无障碍:focus-visible 全局样式、上传区键盘可达

**修复**
- script title 全部 HTML 转义(修复存储型 XSS 面)
- has_video 按 state.render_format 检查对应产物(修复非 mp4 格式刷新后无下载入口)
- /api/studio/ 代理放开全 HTTP 方法(原硬编码 GET);api_reanalyze 增加状态守卫(analyzing/building/rendering 409);api_edit_script 守卫改为 analyzed/preview/failed
- 服务重启时 uploaded 任务同样标记 failed(原只处理 analyzing/building/rendering)
- api_revise body 非 dict 防护;projects 透传代理加 '..' 拦截;txt/md 上传字节数预检(>1.5MB 直接拒绝)
- tts_server.py speed 钳位下限改 1.0(实测 speed<1 非线性恶化);tts_qwen_server.py 补 <8 字 400
- fonttools 补入 server/requirements.txt(此前漏声明,全新部署构建必崩);deploy/setup.sh 字体改完整版
- 死代码清理:tts.py 的 VOICES/FALLBACK_VOICE/words_meta_json/_synth_local 死块、main.py 未用 STYLES 导入;服务器遗留 server/styles.py、server/templates.py、server/assemble.py 三个旧模块已删除(builder/ 取代);deploy/patch-*.py 一次性补丁已移除;.gitignore 合并运行时产物与资产
- 异常路径统一 logging.exception 落 backend.log

## 版本历史(近期)

| 版本 | 内容 |
|---|---|
| **v1.1** | 新增「讲解视频」:与宣传视频并列的第二种视频类型——老师逐段精讲(申论讲解/政论解读式授课,非主旨提炼)。两步分析:①诊断文章类型与讲解方案(备课)②按章节分段生成逐帧脚本后合并;新增 3 种讲解帧 textblock(原文段)/annotation(逐句批注)/method(可迁移写法),原文引用逐字硬校验 + 引用接地(模型改写自动替换为原文区间)、批注类型归一化、段级旁白上下限(3.8-4.2×秒数)与确定性修复管线;讲解时长 5-30 分钟(5 分钟一档,与宣传滑杆合并为视频类型切换);复用四维风格系统;构建期讲解拓展/修订/脚本编辑均按类型走对应校验。**修复 v1.0 回归**:assemble 清理 audio 目录导致构建成片无声(配音清理移至合成前) |
| **v1.0** | 里程碑版本。健壮性加固:docx 异常友好报错、TTS 服务文本上限、脚本编辑/修改状态守卫(构建/渲染中拒绝)、AI 修改失败保留原脚本、渲染完成后回收 Studio 进程、Studio 自愈覆盖渲染期、自愈失败留痕、重建前清理陈旧构建产物、requirements 移除已废弃 edge-tts;新增 `server/smoke_test.py` 冒烟回归;README/ARCHITECTURE/使用说明 同步至最新架构 |
| v0.9.11 | 内容充实度全面加强:每帧旁白 2-4 句(禁止一句话带过)、画面元素填满上限(卡片≥3/要点≥4/步骤≥4/对比≥3/数据≥2 硬校验)、分析部分详实化、模板适配更丰富元素 |
| v0.9.10 | 时长滑杆修复:规划语速 1.6-1.9 字/秒 → 实测 4.2 字/秒(3 分钟文章只得 1.5 分钟视频的根因);构建期二次拓展(两轮,内容级)+ 真实时长向目标靠拢;Studio 预览音频看门狗注入。实测 60s→59.99s、180s→180.0s、300s→258s |
| v0.9.9 | Studio 零等待启动:改用 `--foreground` 直管进程(绕开 CLI 会话注册表死会话复用坑);构建期同步拉起,preview 翻转瞬间就绪;重建前停旧进程防泄漏 |
| v0.9.8 | 预览区改为纯 Studio 编辑器(删除 hyperframes play 播放器全套);Studio 组件列表修复(项目根路径转发,FastAPI 307 陷阱);Studio 槽位竞态修复(串行化+端口释放确认+按需自愈) |
| v0.9.7 | 预览音频修复(EXT_MIME 音频类型+preload)、Studio 闪退修复(poll 不再重建播放器 iframe 踢回标签) |
| v0.9.6 及更早 | 详见 git log(Studio 全链路、三引擎 TTS、字体方框根治、四维度风格系统等) |

## 一、项目目标

一个可外网访问的网站:用户上传长文(纯文本 / txt / docx / md,如人民日报「人民要论」、马院论文),
选择视频风格、填写期望时长 → 服务器调用 **DeepSeek** 做内容分析(大纲、视频结构、逐页内容、样式推荐),
输出 HyperFrames 可直接消费的脚本 → 服务器用 **HyperFrames** 构建并渲染成政论视频 →
同一网站的二级页面提供 **HyperFrames 预览**。

## 二、技术架构

```
浏览器 ──▶ nginx(外网 20013,/ttv/ 子路径)
              ├── /ttv/         → 前端静态页(上传页 + 预览二级页)
              └── /ttv/api/*    → FastAPI 后端(127.0.0.1:8015)
                                   ├── extract   文本提取(txt/docx/md)
                                   ├── analyze   DeepSeek 分析 → hyperframes 脚本(JSON)
                                   ├── build     HyperFrames composition 构建 + TTS 配音
                                   ├── render    HyperFrames CLI 渲染 MP4
                                   └── studio    代理每任务 HyperFrames Studio(4150-4153 槽位)
```

- 流水线:上传 → 文本提取 → DeepSeek 分析(含风格脚本注入)→ 脚本(JSON)→ 构建 composition HTML → TTS 配音(CosyVoice3 三实例并行)→ hyperframes 渲染 → Studio 预览/下载
- 三套风格各有一份**详细样式脚本**(配色 tokens、字体、背景装饰 SVG、版式规范、字幕样式、转场、开场/结尾模板),随分析请求注入 DeepSeek prompt,并在构建阶段作为渲染模板。

## 三、三套风格

| # | 名称 | 定位 | 主色 | 适用文章 |
|---|---|---|---|---|
| 1 | 庄重肃穆·中国红 | 政论经典 | 中国红 #C8161D / 深红 #8F1118 / 暖白 | 人民日报评论、时政理论 |
| 2 | 清雅学术·墨黛青 | 书香学术 | 黛青 #1F4E5F / 墨色 / 宣纸米白 | 马院论文、学术理论 |
| 3 | 现代锐意·科技蓝 | 时代前沿 | 科技蓝 #0A4DA3 / 亮青 #00A8CC / 冷白 | 改革、科技、新质生产力类 |

详见 `styles/` 目录下三份风格脚本。

## 四、里程碑

- [x] M0 服务器环境侦察
- [x] M1 项目计划文档(本文件)
- [x] M2 三套风格详细脚本(`styles/style-1~3.md`)
- [x] M3 后端 API(上传/提取/DeepSeek 分析/任务状态,`server/`)
- [x] M4 前端(上传页 + 预览二级页,`web/index.html`)
- [x] M5 构建器(`server/builder/`:script.json → composition,10 种帧类型 × 3 风格)
- [x] M6a 部署:代码上传 / pip 依赖 / 字体(4 个 OTF)/ gsap / nginx /ttv/ 路由 / 后端服务启动 —— **站点已公网可达**:http://8.130.213.80:20013/ttv/
- [x] M6b 验证:外网上传→提取→DeepSeek 分析 全链路通(solemn-red 与 academic-ink 各测一次)
- [x] M6c 部署:hyperframes CLI 0.8.15 全局安装 + Chrome 152(chrome-headless-shell)✓(doctor 全绿,仅 whisper-cpp/Kokoro 可选缺失)
- [x] M6d 部署:BGM 素材(按用户意见**推迟**;缺文件时自动静音占位,后续放入 `assets/bgm/{solemn-red,academic-ink,modern-blue}.mp3` 即可生效)
- [x] M7 端到端:构建(配音+组装)→ check(0 错误,WCAG 65/65)→ 渲染出片(edge-tts 版 102.7s / **CosyVoice3 版 137.8s**,1920×1080,画面/音轨/对比度全部验证通过);外网播放器代理(HTML 路径重写)全链路 200
- [x] M8 TTS 升级:**CosyVoice3-0.5B 已部署并跑通**
  - 权重 9.1GB → `/mnt/models/CosyVoice3-0.5B`(ModelScope 下载,HuggingFace 文件下载网络不通)
  - 运行时:GitHub 仓库源码(`/mnt/workspace/ttv/cosyvoice-src` + Matcha-TTS 子模块)+ venv,PYTHONPATH 引用;**不装官方 requirements**(会降级 torch 2.3.1 破坏 PPU 专用 torch 2.10;onnxruntime-gpu/tensorrt 无 PPU wheel 跳过,onnx CPU 版可用)
  - 服务:127.0.0.1:8016(GPU1),启动脚本 `deploy/start-tts.sh`(**必须 source /usr/local/PPU_SDK/envsetup.sh**,否则 PPU 内核 JIT 报错)
  - 三音色:edge-tts 新闻腔(云扬/云霞/云健)生成种子 wav → CosyVoice3 零样本克隆;prompt 文本需带 `You are a helpful assistant.<|endofprompt|>` 前缀
  - 踩坑记录:torchaudio 2.10 无 torchcodec → monkeypatch soundfile;短文本(<15 字)会触发 vocoder 卷积错误 → 服务返回 400,流水线回落 edge-tts;start-tts.sh 的 pkill 模式必须 `tts_serve[r]`(uvicorn 进程 cmdline 是 `tts_server:app`,不带 .py)
  - 合成速度:首次含模型加载 ~27s,热态 ~10-17s/句(CPU onnxruntime 做 tokenizer+embedding,LLM/Flow 在 PPU)
- [x] M9 前端修复(2026-08-27,用户反馈 bug):JS 语法错误修复(对象键 `{solemn-red:…}` 未加引号 → 整段脚本解析失败,上传/风格/滑杆全部无响应)+ 新增「粘贴文字」直输模式(后端 `text` 字段)+ docx 上传扩展名保留(此前存成 input.txt 会解析失败)
- [x] M10 前端改版(taste-skill + DeepSeek vision 两轮评审):编辑部气质设计 —— 深藏蓝 #1E3A5F 结构色 + 赭红 #A61B29 强调色 + 暖白纸感底 #F8F6F3 + 思源宋体标题(网页端 @font-face 自 `/ttv/assets/fonts/`)+ 统一 8px 圆角 + 滑杆填充 + 禁用态改透明度;skill 安装于本地 `.agents/skills/design-taste-frontend`;vision 模型 `deepseek-v4-flash-vision-exp`(答案在 reasoning_content 字段)
- [x] M11 质量与健壮性修复轮(2026-08-27,用户验收反馈):
  - 预览 500:渲染阶段不再停播放器 + 代理返回友好提示页(404/503 带 meta-refresh)+ api_job 轮询自愈重建播放器
  - 分析引擎时长自适应:按目标时长决定帧数(6-20)/旁白量/详略;**压缩与拓展策略**(长文短时只留核心论据,短文长时逐层展开+重述+结构化帧);旁白字数按 **CosyVoice3 实测语速(~1.8-2.6 字/秒)规划**;≥15 字防 TTS 失败;长视频单帧上限 100 字
  - 时长范围:30-600 秒(滑杆+后端)
  - **字体根治方框**:SubsetOTF 子集 → 完整版(Noto Sans SC 16-17MB + Source Han Serif SC 24MB,总 82MB,全 CJK 覆盖)
  - 画面丰富:全帧页脚「《标题》· 帧序」+ statement 关键词 chips
  - TTS 保障:引擎逐帧追踪(cosyvoice3×N 显示在任务状态)、失败重试、**speed 锁定 1.0/1.05(实测 0.8 会产生 5 倍时长怪音,不可用)**
  - 质量门:构建后自动 `hyperframes check`(结果入任务状态);服务器 `hyperframes skills` 26 个官方 skills 安装完成
  - 验证:60s 任务渲染验收(73.7s 成片、页脚带密度、音轨正常);480s 任务 cosyvoice3×13 零回落 + check 0 错误

## 四.五、代码地图

```
理论文章转视频/
├── PLAN.md              # 本文件
├── frames-schema.md     # DeepSeek 输出契约(hyperframes 脚本 JSON)
├── styles/              # 三套风格详细脚本(注入分析 prompt + 构建器实现依据)
│   ├── style-1-solemn-red.md   庄重肃穆·中国红
│   ├── style-2-academic-ink.md 清雅学术·墨黛青
│   └── style-3-modern-blue.md  现代锐意·科技蓝
├── server/              # 后端(部署于 /mnt/workspace/ttv/server/)
│   ├── main.py          # FastAPI:jobs API(含 DELETE)+ Studio/项目代理
│   ├── analyze.py       # DeepSeek 分析(本地 vLLM 优先,云 API 备份;宣传两阶段/讲解分段并行)
│   ├── extract.py       # txt/md/docx 提取(纯标准库 + 字节预检)
│   ├── tts.py           # CosyVoice3 多实例轮询并行配音 + 词级时间轴
│   ├── tts_server.py    # CosyVoice3 服务(8016/8018/8019 三实例)
│   ├── jobs.py          # 任务状态机
│   └── builder/         # styles.py(tokens+SVG)/ templates.py(13 帧型)/ assemble.py(组装)
├── web/index.html       # 前端(上传页 + 预览二级页,单文件 SPA)
└── deploy/              # nginx-ttv.conf / setup.sh / start.sh
```

## 五、服务器侦察结论(2026-08-26)

### 已确认可用
- **分析引擎:本地 vLLM DeepSeek-V4-Flash**(无需 API 费用!)
  - 从服务器调用:`http://8.130.213.80:20001/v1`(纯 HTTP,OpenAI 兼容),模型 id `DeepSeek-V4-Flash`
  - vllm-0.23.0-tp8,W8A8-INT8,1M 上下文,实测 0.5s/35token,跑在 PPU 上
  - 备份:DEEPSEEK_API_KEY 在服务器 `/mnt/workspace/wsh/cot/.env`(api.deepseek.com 可达)
- Python 3.12 + FastAPI 0.115 + uvicorn + httpx + openai ✓
- ffmpeg 6.1.1 ✓
- Node 在 `/mnt/workspace/node/bin/node`(不在 PATH,服务启动时需 export PATH)
- 外网可达:registry.npmjs.org / DeepSeek / 字体源 ✓
- 磁盘:/mnt/workspace 剩余 5.3T ✓;GPU 4×PPU-ZW810E 正常 ✓

### 缺口(需安装)
- Chrome/Chromium(hyperframes check/render 需要)→ 装 puppeteer chrome 或 apt chromium
- hyperframes CLI → npx 安装
- CJK 字体 → 下载思源宋体/黑体
- TTS 引擎(已通过 CosyVoice3-0.5B 本地部署解决,见 M8;不采用 edge-tts)

### 外网端口现状(安全组已放行,无空闲端口)
| 端口 | 现状 |
|---|---|
| 20001 | 本地 DeepSeek vLLM(网关,占用) |
| 20002 | 另一项目(SQL 生成工具前端,占用) |
| 20010 / 20012 / 20013 / 20014 | 现有业务,占用 |
| 20085 | SSH,占用 |

→ 新站点入口:**待定**(见 §五 选项)

## 六、待确认/依赖

- [x] 分析引擎:本地 DeepSeek-V4-Flash(20001)✓
- [ ] 站点外网入口:20012/ttv/ 子路径(推荐)或控制台新开端口
- [x] TTS:CosyVoice3-0.5B 本地部署(M8,三音色零样本克隆,替代 edge-tts 方案)
- [ ] Chrome + node PATH + hyperframes CLI + 字体 安装(部署阶段执行)
