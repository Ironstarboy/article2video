# 理论文章转视频网站 — 项目计划与进度

> 最后更新:2026-09-12
> 部署位置:**VideoLab 云服务器**(SSH `videolab`,8.130.213.80),整个项目运行在服务器上。
> 本地此文件夹保存:计划文档、源码副本、风格脚本、部署配置。

## v2.8(2026-09-12)

**修:运行时修好了,成片里的配音却还是乱码 —— 旧配音被"复用"了(补内容级抽检 + 一键重烧)**

- **现象**:用户报「配音坏了非常混乱」。内容级抽检(whisper 听写 vs 台词 LCS)三个老任务的配音是 **0.016 / 0.006 / 0.000**(念出来完全是别的内容),而 v2.3 修复后合成的 `e868f32bec3d` 是 0.895 —— 时长、峰值、静音比例却全部"健康"
- **根因(v2.3 的尾巴)**:乱码根因(transformers 4.52+ 打乱语音 LLM 输出)当时只做了**运行时钉版**,而**配音复用指纹里没有运行时口径**。那三个任务的 `vo_NN.mp3` 是在坏运行时下烧的(03:41 / 04:06 / 18:41),重新构建、重新渲染都判它们"可复用",于是原样接着用 —— 用户重跑了流程,听到的还是乱码
- **修(结构)**:`config.VO_SYNTH_VERSION`(合成口径版本,默认 2)+ `config.vo_runtime_fingerprint()`(钉版依赖 + 口径版本)进 `_vo_signature`;**复用条件收紧成"指纹完全相符"**,去掉"上次构建用的就是这段文字就复用"的兜底(`_built_source_matches`)—— 那正是坏配音溜过去的入口。换模型/改解码参数/改验收口径/换钉版 → 旧配音自动作废,普通的「构建预览」就会重烧,不需要谁记得加 `force_voice=1`
- **修(检测)**:`server/voice_check.py` 接入构建流水线 —— 每次**真正重新合成**后自动抽检 2 帧(whisper 听写 vs 台词,繁简归一后算 LCS),结果写 `state.voice_check`;`warn=true` 时预览页弹红条 + 「**重新合成配音**」按钮(= `POST /api/jobs/{id}/build?force_voice=1`)。whisper 不可用/超时/异常一律跳过,绝不阻塞构建;阈值 0.35(好音频实测 0.6~0.99,乱码 ≈0);模型缓存在 `models/whisper`
- **回收**:三个受影响任务按 v2.3 文档 §七的产线动作重烧并重出成片(配音 LCS:0.016→**0.715**、0.006→**0.796**、0.000→**0.776**);数字人片段与抠像遮罩跟着新配音自动重算(片段缓存键含音频指纹),播报视频一并重出
- **验证**:`smoke_test.py` 新增 12 项(配音指纹随合成口径/台词/音色/引擎变化、口径含钉版依赖、LCS 边界与空听写、抽检帧选择优先长句);真机复核:重烧后的成片 ASR 与台词逐字对应(仅 whisper 自身的同音字误差)
- **教训**:`docs/问题修复说明-配音乱码.md` §十一 —— **"修好运行时"不等于"修好产物"**:任何被缓存/复用的产物(配音、数字人片段、抠像遮罩),其复用指纹都必须包含**产生它的口径**;且修复要带**回收动作**,只改代码,用户手里的成片不会自己变好

## v2.7(2026-09-12)

**新增:数字人抠像出镜 —— 只保留人像、背景透明,不再遮挡 PPT 内容**

- **需求**:成片里那块不透明的圆角卡片会盖住幻灯片内容,希望"把数字人的背景抠掉,只把人像叠上去"
- **做法**:每段数字人片段旁多生成一条**灰度遮罩**(`clip_*.modnet<版本>.mp4`),由新增的 `server/matte.py` 用 MODNet ONNX(Apache-2.0,权重 25MB,本机推理)逐帧算 alpha;叠加时 `[片段][遮罩]alphamerge` —— **复用现有叠加管线**,只是把"几何遮罩"换成"内容遮罩",片段本身仍是 H.264(见 `docs/adr/0004-抠像用独立灰度遮罩完成.md`)。选 MODNet 而不是 RVM(RVM 是 GPL-3.0)或 BiRefNet(885MB、慢 5–10 倍)
- **贴画面下缘**:实测片段是"齐胸特写"、底边整行都是躯干(alpha≈1),摆在画面中间会像一块悬浮的半身像 —— 抠像模式由 `avatar.cutout_xy()` 把人像**贴画面下缘**(切口落在画面外沿),因此上下角等价(`tl≡bl`、`tr≡br`),只有左右仍由角落选择决定
- **缓存与失效**:遮罩名 = `片段名.{TTV_MATTE_MODEL_TAG}{TTV_MATTE_VERSION}.mp4`,换模型/改预处理只失效遮罩,**片段缓存与旧遮罩都不受影响**;渲染前 `avatar.ensure_mattes()` 批量补齐缺的遮罩(老时间轴、刚打开抠像的任务都走这条),一批一个进程、模型只加载一次,进度写进 `job.progress`
- **失败逐条回退**:抠像解释器/权重缺失或单段失败只记日志,该段仍用圆角卡片;一条都没抠成时 `avatar_error` 写明原因(`_cutout_missing`)—— 抠像是增强项,绝不阻塞出片。**播报视频不抠像**(独立口播片,透明无意义)
- **接口与前端**:`POST /api/jobs` 新增 `avatar_cutout`、`POST /api/jobs/{id}/avatar/geom` 新增 `cutout`(只认真布尔,字符串 `"true"` 会 400)、`GET /api/styles` 下发 `avatar_cutout_default`;`state.avatar_geom` 变成 `{corner, size, cutout}`(老任务无该键 → 回默认 `false`,零迁移);创作页与预览页的「数字人出镜」栏各加一个「**只保留人像(背景透明)**」勾选(选「不出镜」时置灰)
- **修**:`composite_onto_video` 的抠像分支一开始只缩放了片段没缩放遮罩,真机渲染直接报 `Input frame sizes do not match (300x300 vs 320x320)` —— `alphamerge` 要求两路尺寸完全一致,而遮罩跟着**片段**尺寸缓存、叠加要的是任务选的 `size`;现在遮罩这一路也一起缩放(smoke_test 加了这条回归)
- **修**:渲染历史原来按"时间轴非空"就写「已叠加数字人(n 段)」,叠加失败(退成纯 PPT)时也说叠上了;现在按**真的叠上去了**才写,失败如实记「纯 PPT」
- **验证**:`smoke_test.py` 新增 22 项(抠像滤镜内容与"遮罩同缩放"回归、遮罩名/版本/路径派生、抠像开关只认布尔、贴下缘坐标与上下角等价、provider 选择、模型输入缩放、降级提示、几何解析四字段);真机跑通 `jobs/5590965bf587`(81 秒、6 段片段):遮罩 6/6 生成(CPU 共 191 秒,≈8.5 帧/秒),再走一遍 `POST /api/jobs/{id}/render` 全链路(渲染 → 补遮罩 → 叠加 → 产物/历史)完成;成片与纯 PPT 逐像素比对 —— **人像框内 40.9% 的像素与纯 PPT 完全一致**(改之前的卡片版是 0%),框外平均色差 0.16(压缩噪声级,画面其余部分没被动);回退路径也实测过:权重缺失 → 记日志用卡片;解释器缺 onnxruntime → worker 报 `ModuleNotFoundError` 被捕获,成片照出
- **注意**:抠像按片段缓存,只算一次;CPU 上 300/320px 约 8 帧/秒,长视频(20 分钟档)首次抠像需几十分钟 —— 装了 `onnxruntime-gpu` 的解释器会被自动优先使用(`matte.resolve_providers`:CUDA 优先、CPU 兜底,此路径未在本机实测);`TTV_MATTE_PYTHON` 可指向任何装有 onnxruntime 的解释器。切换抠像开关后需重新构建预览、重新渲染才生效

## v2.6(2026-09-12)

**新增:项目历史入口页 —— 每一步的结果都留档、可改名、可直达**

- **需求**:渲染很花时间,关掉页面回来既不知道任务走到哪一步,也没有历史工作记录。进入页应能看到之前渲染过的项目(可重命名);开始分析进入新页面时由**大模型自动总结项目标题**(也能手动改);渲染每一步后保存历史结果,下次打开直接点到对应结果
- **入口页(项目历史)**:`web/index.html` 新增视图 `#view-home` —— 打开站点先看到项目列表(按最近更新倒序)。每张卡片显示项目标题、视频类型/目标时长/成片时长、更新于多久前、当前状态与阶段进度(`analyzing/building/rendering` 带 spinner;**有任务进行中时列表每 4 秒自动刷新**,全部空闲 20 秒),空闲时不用一直盯着页面。路由:`?new=1` 创作页、`?job=<id>` 项目详情页、其余为入口页
- **重命名**:卡片与详情页都能就地改名(输入框 + 保存/取消,Enter 保存、Esc 取消);新增 `POST /api/jobs/{id}/rename`,标题压成单行、限 60 字、空标题 400。`state.title_source` 记住来源:`user`(用户改过)/`auto`(大模型总结)/`file`(文件名占位)—— **来源是 user 时自动总结绝不覆盖**
- **大模型自动总结项目标题**(`analyze.summarize_title`):分析完成后用一次小调用(256 tokens)把脚本标题/核心论点/开头旁白/文章开头压成 12–22 字的短标题,失败逐级回退(脚本标题 → 文件名 → job_id),整条链路不抛异常、不影响分析结果;`clean_title` 负责取一行、剪掉书名号与标点、限长。新建任务时先落一个文件名级占位标题,列表立刻有名字可认
- **每一步的历史结果**(`state.history`,每任务最多 60 条):`analyze/build/render/broadcast` 每个阶段**完成或失败**各记一条(`step/label/status/detail/at`;渲染记格式/时长/大小/是否叠数字人,播报记段数与尺寸);后台阶段异常由 `run_in_background(..., step=…)` 自动补一条 failed 历史 —— 界面上能说清"哪一步挂了"
- **直达对应结果**:卡片上的四个步骤胶囊(分析脚本 / 构建预览 / 渲染成片 / 播报视频)显示完成时间,点一下进详情页 `?step=…` 并自动滚到那一步的结果(分析面板 / Studio 编辑器 / 成片播放与下载 / 播报播放器)并高亮;详情页新增「历史记录」面板,逐条列出时间与结果摘要,渲染/播报产物直接给下载入口
- **接口**:新增 `GET /api/jobs`(项目列表 `{jobs,total}`,不含 script;进行中的任务带 progress 与 render_progress)、`POST /api/jobs/{id}/rename`;`GET /api/jobs/{id}` 回传 `title/title_source/history`
- **老任务零迁移成本**:`load_from_disk` 一次性补录(`Job._backfill_meta`)—— 标题取脚本标题或文件名,历史按磁盘上脚本/工程/产物的时间戳倒推(标 `derived:true`),`updated_at` 回填到最近一次历史/产物时间(否则老项目按"建任务时间"排序,刚重渲染过的会排到后面)。现有 7 个任务重启后直接出现在列表里,不再是空白
- **验证**:`smoke_test.py` 新增 27 项(标题清洗/prompt、标题规范化/单行化/回退链、历史追加与 60 条上限、summary 不含 script、旧任务补录与 updated_at 回填、后台失败落历史);`fastapi.testclient` 走了一遍列表排序/重命名/非法标题 400/不存在 404/标题限长/详情带 history;真机重启后 `GET /api/jobs` 返回 7 个历史项目(含各自的阶段历史,按最近活动倒序),自动总结对真实脚本跑通(「以科技创新引领产业创新加快形成新质生产力」),前端做了 `node --check`、DOM id 全量核对与标签闭合检查
- **注意**:历史记的是"每一步出了什么",**不保留每次渲染的成片副本**(一条成片几百 MB,按次留档会撑爆磁盘);同一阶段重复执行会各留一条记录,当前产物始终以 `state.artifacts` 为准

## v2.5(2026-09-12)

**新增:数字人出镜可选可关 —— 不出镜 / 四个角落(默认右上)+ 默认 300×300 + 可手输**

- **需求**:数字人放在**右上角**(位置四角可选、默认右上)、默认 **300×300**、大小能**手动输入数字**;「数字人出镜」那一栏里**还要有「不出镜」这个选项**;播报视频那边的大小设置一并保留
- **出镜开关**:「不出镜」不再是一个额外的勾选框,而是和四个角落并列的选项(同一个下拉的第一项)—— 用户看到的那一栏就是"要不要出镜 + 出在哪"。`state.avatar`(bool)继续是唯一开关,默认 false(不出镜,保持"数字人默认关"的老行为);`POST /api/jobs/{id}/avatar/geom` 新增 `avatar` 字段(只认真正的 JSON 布尔,字符串 `"false"` 会 400 而不是被当假值),三个字段都可选、只传哪个改哪个
- **修(关键)**:`stage_render` 原来只看 `avatar_timeline.json` 在不在就叠加 —— 关了出镜但上次构建的时间轴还留在磁盘上时,**人像会照旧被叠回去**。现在收敛成 `_overlay_timeline(job, project)`:先看 `state.avatar`,不出镜一律返回空(纯 PPT 版)
- **位置**(`server/avatar.py` / `server/main.py`):新增 `normalize_corner`(接受 `tl/tr/br/bl` 与「左上/右上/右下/左下」,非法值 400)/`safe_corner`/`corner_xy`(按"带投影留白的卡片画布"离边 `AVATAR_X/AVATAR_Y` 摆位,四角视觉边距一致且投影不被裁);`config.AVATAR_CORNER` 默认 `tr`、`AVATAR_CORNERS` 四角表;`composite_onto_video(..., corner=…)` 缺省按角算坐标,**显式 x/y 仍优先**(老调用方与 `deploy/verify-avatar.py` 的像素校验不受影响)
- **几何按任务存**:`state.avatar_geom = {corner, size}`(默认 `{tr, 300}`)。创作页建任务时随表单提交(`POST /api/jobs` 的 `avatar_corner`/`avatar_size`),分析完成后还能在预览页「视频预览」上方改,否则想关掉出镜、或换个角落,都得重新提交文章、重新分析。老任务没有该键 → 直接回默认值,零迁移
- **大小 / 前端**:三处控件都改成**手输数字**(创作页 `#up-avatar-size`、预览页 `#geom-size`、播报面板 `#bc-size`),档位只作 `datalist` 提示;提交/保存前在前端先校验(偶数、160–1080),后端 `avatar.normalize_size` 再兜一层。默认值统一为 **300**(`config.AVATAR_SIZE`,档位改成 240/300/400/464/640);出镜模式下拉(不出镜 + 四角)在创作页与预览页共用同一份清单,选「不出镜」时大小输入框置灰但保留值
- **播报视频**:尺寸默认**跟随任务的数字人大小**(`state.avatar_geom.size`),可单独指定;其余(按任务记住、实际尺寸写 `avatar_broadcast.size`、不同尺寸各自缓存)沿用 v2.4
- **拼接系数不再被默认边长带偏**:新增 `config.AVATAR_CONCAT_BASE_SIZE`(=320,系数实测处的边长),`concat_rt_factor` 按面积比从**基准**外推 —— 默认改成 300 后,预计时间不会把 320 的实测值当成 300 的
- **修**:`api_create` 的入参 `avatar`(布尔)会遮住模块 `avatar`,几何解析抽到模块级 `_normalize_geom` 里(否则 TypeError)
- **验证**:`smoke_test.py` 新增 20 项 —— 四角坐标/留白对称/越界不为负/中文名/非法值/清单/拼接基准,以及**关掉出镜后旧时间轴也不叠加**(临时 ROOT 里真跑 `main._overlay_timeline`);`fastapi.testclient` 走了一遍建任务(出镜/不出镜)、单字段更新、非法值 400、`"false"` 字符串 400、老任务回默认;**真 ffmpeg 像素回归**:合成片段按 `tr/tl/br/bl` 叠加到 1080p 黑底,四个锚点亮度 255、非锚点 0,显式 x/y 仍生效;又用 `jobs/5590965bf587` 的真实 1080p PPT 帧 + 缓存人像片段叠了一次,右上角画面复杂度从 8.3 升到 56.0(左上角 0.0 未被动)
- **注意**:换大小/换角落/切不出镜后要对已有任务重新「构建预览」「渲染成片」才生效;片段与缓存都留着,切回出镜不用重新生成

## v2.4(2026-09-12)

**新增:数字人大小可选(「数字人播报视频」区块,默认 320×320)**

- **需求**:播报视频的画面大小要能在页面上设置,且有默认值
- **前端**(`web/index.html`):「数字人播报视频」区块新增「数字人大小」下拉(240/320/400/464/640,标出默认档;超过原生 464 的档位标注"放大"),默认值来自后端 `GET /api/styles → avatar_sizes`,接口不可用时用同值兜底;面板提示、按钮 toast、"画面 X×X"信息行都跟着所选尺寸走。用户改过下拉后轮询不再覆盖其选择;若当前这条播报视频的尺寸与下拉不同,提示"重新生成会改成 Y×Y"
- **接口**(`server/main.py`):`POST /api/jobs/{id}/avatar/broadcast` 接受 `{"size": N}`(或 `?size=N`),省略则沿用该任务上次选的尺寸,再回退 `config.AVATAR_SIZE`;选中值随任务持久化在 `state.avatar_broadcast_size`,实际生成尺寸写在 `avatar_broadcast.size`;`GET /api/jobs/{id}` 回传 `avatar_broadcast_size`,并支持 `?avatar_size=N` 让「预计耗时」按**尚未提交**的选中尺寸现算;`GET /api/styles` 下发 `avatar_sizes{default,native,min,max,choices}`
- **尺寸口径**(`server/avatar.py` / `config.py`):新增 `normalize_size`(偶数 + 160–1080,非法值接口层 400)/`safe_size`(读路径防坏值打成 500)/`concat_rt_factor`(拼接系数按面积比从 320×320 实测值外推)/`config.avatar_size_options()`;尺寸本就进片段缓存键,不同尺寸各自缓存、互不失效(来回切换不重复烧 GPU)
- **验证**:`smoke_test.py` 新增 14 项(尺寸校验/宽松回退/下拉清单/拼接系数/估算随尺寸增长);接口契约用 `fastapi.testclient` 走了一遍(400 与持久化、`?avatar_size=` 现算、无脚本 409);前端做了 `node --check` 与 DOM id 全量核对
- **注意**:播报面板的"下拉"在 v2.5 改成手输数字,默认值也由 320 改为 300

## v2.3(2026-09-12)

**修复:配音「读音完全不正常、断断续续」根因 —— transformers 版本**

> 与 v2.2 同一天发布:v2.2 的两条修复(播报音轨字节对齐、配音时长/静音验收)都对,
> 但没有解决「内容乱码」这一层;v2.3 才是配音可懂度的根因修复。

- **现象**:整片人声是与台词无关的乱码语音,但**时长与峰值完全正常** —— v2.2 加的两层验收(时长窗口 + 非静音)全部放行,坏音直接上线
- **反馈环**:whisper(small)听写 + 与台词算 LCS,做成可懂度判据。参考音频 `asset-v2/male.wav` 能 100% 听对(证明 ASR 与被测音频都正常),而当时的配音 5/5 全是乱码(时长验收毫无区分度)
- **差分实验**(同一模型,一次加载跑多条路径):
  - `inference_vc`(speech tokenizer → flow → vocoder,**不经过 LLM**)输出完全正确(「希望你以后能够做得比我还好」)→ tokenizer / flow / vocoder 都是好的
  - `inference_zero_shot` / `inference_cross_lingual` / `inference_instruct2` 全部乱码 → 坏的是**语音 LLM** 这一环
  - 同时排除了:注意力实现(强制 eager 与 sdpa 输出逐字节相同)、权重精度(fp16 / fp32 都乱码)、GPU 数值(matmul/conv/softmax/SDPA 各后端与 CPU 一致)、官方示例调用本身(原样跑同样乱码)
- **根因**:`transformers` 版本。把官方 `requirements.txt` 锁定的 **4.51.3**(+ `tokenizers==0.21.4`)装回 tts-venv,官方示例立刻出正确语音;换成工作区自己的 `male/female/male_narrator` 参考音频同样正常(4/4 音色 7.4–7.6s,听写全部正确)。4.52+ 的 Qwen2 实现会让 CosyVoice3 的 speech token 序列乱掉。**为什么会装上 4.57**:tts-venv 用 `--system-site-packages` 建、又故意没装官方 requirements(怕 torch 被降到 2.3.1),于是静默继承了系统里更新的 transformers
- **修复**:`tts-venv` 钉 `transformers==4.51.3` / `tokenizers==0.21.4`(其余保持本机新 torch);`config.PINNED_TTS_DEPS` 单点声明 + `tts_server` 启动硬校验(不符即拒启,`TTV_TTS_ALLOW_UNPINNED=1` 可绕过)+ `/health` 回报实际版本;`smoke_test` 新增 5 项(钉版判定 4 项纯函数 + tts-venv 实际环境 1 项);BUILD.md 第四节补上安装与坑位说明
- **效果**:同一台机器、同一模型,5 条真实台词样本听写 LCS **0.83–0.97**(修复前 0.00–0.06),时长 ratio 0.79–0.95,且不再出现 0.03×/2.36× 的极端样本(重采几乎不再触发);已按新运行时重合成成片配音与数字人播报视频
- **教训**:这类「时长/音量都正常、内容全错」的失败,只有**内容级判据**(ASR/可懂度)或**版本钉死 + 启动校验**才拦得住;时长与静音验收只是兜底

**运行时版本记录(本机已验证组合,2026-09-12 实测可懂)**

| 组件 | 版本 | 说明 |
|---|---|---|
| GPU / 驱动 | NVIDIA GeForce RTX 5090 32GB,595.58.03 | 单卡,sm_120 |
| Python | 3.10.12 | `tts-venv`(用 `--system-site-packages` 建) |
| torch / torchaudio | **2.8.0+cu128** | 不能用官方 requirements 的 2.3.1(无 sm_120 内核) |
| **transformers** | **4.51.3** | **必须钉死**:4.52+ 会让语音 LLM 输出乱码 |
| **tokenizers** | **0.21.4** | 与 4.51.3 配套 |
| onnxruntime | 1.23.2(仅 CPU provider) | CUDA provider 无轮子,只用 tokenizer/embedding 小头 |
| soundfile | 0.14.0 | 替代 torchaudio 的 torchcodec 后端 |
| CosyVoice3 权重 | `FunAudioLLM/Fun-CosyVoice3-0.5B-2512`(工作区 `models/CosyVoice3-0.5B`) | 源码 `cosyvoice-src` 为 GitHub 浅克隆,无版本号可记 |
| 可懂度复核工具 | openai-whisper 20250625(`small`) | 一次性排查工具,非服务依赖 |

## v2.2(2026-09-12)

**修复:数字人播报视频人声全损(我自己的字节对齐 bug)**
- `build_broadcast_audio()` 里帧首静音写的是 `head = int(rate * VO_OFFSET)`,那是**采样数**(11025)却被当成**字节数**用;16bit 单声道下每个采样 2 字节,奇数偏移 → **整条人声每个采样错位一个字节**,听感就是「支离破碎」的噪声,而静音段依旧正常(所以静音检测、时长检查全都发现不了)
- 修复:字节/采样换算显式化(`bytes_per_sample = 2`),`head` 与 `need` 一律按字节计算
- 回归测试:`smoke_test` 用一段已知正弦当源配音,**逐字节**比对播报音轨(错半个字节即失败)
- 验证:修复后播报视频平均音量 **-28.3 dB**,与成片同窗口 -27.4 dB 同量级(修复前是 -9 dB 的错位噪声)

**修复:配音「支离破碎」(本地 CosyVoice3 解码不稳定)**
- **定位**:同一句话,模型会随机给出 0.04s–36.8s 的音频(残句/复读),成片与播报视频同源所以一起坏。把**官方 CosyVoice3 示例**原样在本机跑也复现(甚至 0 token → vocoder 报 kernel 错误),所以不是 prompt / 文本 / 调用写错,而是本机的模型解码本身不稳定
- **逐项排除**(全部无效):fp16↔fp32、`sampling`/`top_p`/`top_k`/贪心解码、prompt 长短与文本-音频对齐、`text_frontend` 开关、ONNX provider(CPU/CUDA)、换成 `llm.rl.pt`。顺带查清一个坑:`llm.sampling` 默认走 `ras_sampling` → `nucleus_sampling(top_p=0.8, top_k=25)`,**完全忽略 `inference` 传入的 `sampling`**,这正是此前"调参没反应"的原因。另:同输入在**新进程里是可复现的**(固定种子),同进程内重试才会推进 RNG 拿到不同样本 —— 这给了兜底的空间
- **修复(TTS 服务侧)**:合成后**按时长验收** —— 实际/预期(字数 ÷ `CHARS_PER_SEC`)落在 `[0.65, 1.8]` 才算通过,否则重采(默认最多 6 次,取最接近预期的一次);`TTV_TTS_ACCEPT_LO/HI`、`TTV_TTS_ATTEMPTS` 可覆盖;响应头带 `X-TTS-Ratio` / `X-TTS-Attempts` 便于观测
- **修复(客户端)**:`tts.py` 再兜一层(验收不过就换实例再采样),并把 `ratio` 写进 vo 条目;`tts.ACCEPT_RATIO` 可调
- **效果**(同一任务 11 个台词帧):修复前 5/11 在合理区间(含 0.07× / 0.15× / 0.25× 的残句),修复后 **11/11**;整片真实时长 152s → **224s**(把原先被截断的内容补了回来)。代价:坏样本要重采,TTS 阶段 ~137s → ~200s
- **仍未根治**:根因在本机 CosyVoice3 运行时/权重(官方 fun-cosyvoice3-0.5b-2512 + RTX 5090 sm_120 + torch 2.8)。要彻底解决需重装 TTS 运行时或接一个稳定引擎(仓库预留了豆包云与 Qwen3-TTS,但当前既无密钥也无权重)→ **当天已根治:见 v2.3「配音乱码根因」(transformers 必须钉 4.51.3)**

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
