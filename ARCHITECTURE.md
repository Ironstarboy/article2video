# 项目结构文档(Theory-to-Video v2.6)

## 一、总体架构

```
浏览器 ──▶ nginx(8.130.213.80:20013 /ttv/)
             ├── /ttv/              静态前端(web/index.html,单文件 SPA;index.html no-cache)
             ├── /ttv/assets/       网页字体等静态资产(woff2 子集,immutable 长缓存)
             └── /ttv/api/      ──▶ FastAPI 后端(127.0.0.1:8015;nginx 限流每秒 10 请求、突发 20)
                                      ├── DeepSeek 分析(本地 vLLM 20001,云 API 备份;全局 LLM 并发信号量 6)
                                      ├── CosyVoice3 TTS 池(8016 GPU1 / 8018 GPU2 / 8019 GPU3,轮询并行合成;Qwen3-TTS 8017 GPU2 备用,默认停)
                                      ├── hyperframes 构建/渲染/check(CLI+Chrome;渲染全局信号量 ≤2)
                                      ├── /api/studio/<job>/  → Studio 编辑器代理(唯一预览入口,支持全 HTTP 方法)
                                      ├── /api/projects/<pid>/ → Studio 项目 API 转发(项目根/子路径/预览,'..' 拦截)
                                      └── 每任务 Studio 进程:4150-4153(4 槽,--foreground 直管,按需自愈)
```

## 二、目录结构

```
vtt/
├── README.md                使用说明
├── ARCHITECTURE.md          本文件
├── BUILD.md                 从零搭建全过程
├── frames-schema.md         DeepSeek 输出契约(hyperframes 脚本 JSON)
├── styles/                  三套经典风格详细样式脚本(设计文档)
├── server/                  后端(部署于 /mnt/workspace/ttv/server/)
│   ├── main.py              FastAPI:任务 API(项目列表 GET /api/jobs、重命名、DELETE)、自动总结项目标题、阶段历史、Studio/项目代理、流水线阶段、check 质量门、Studio 槽位管理(串行化+自愈)、并发限制(LLM 信号量 6/渲染信号量 2/进行中任务 >4 返回 429)、预览音频看门狗注入
│   ├── config.py            路径/端口/模型端点配置(CHARS_PER_SEC=4.2 语速常量全局引用)
│   ├── extract.py           txt/md/docx 提取(zip 炸弹防护;txt/md 字节预检 >1.5MB 拒绝)
│   ├── analyze.py           DeepSeek 分析:宣传视频两阶段(阶段一「分析」诊断小契约 → 阶段二「脚本」按帧计划生成)+ 讲解视频两步分析(备课方案 → 分段并行生成逐帧脚本,ThreadPoolExecutor 3 workers)+ 构建期二次拓展(expand_script)+ 项目标题自动总结(summarize_title,失败可回退)
│   ├── tts.py               配音:CosyVoice3 多实例轮询并行合成(httpx 全局共享连接池,修复 FD 耗尽)+ 词级时间轴 + 真实时长向目标靠拢(apply_real_durations);失败重试×3 → 静音占位
│   ├── tts_server.py        CosyVoice3 服务(8016/8018/8019 三实例:GPU1/GPU2/GPU3,三音色零样本克隆,speed 钳位下限 1.0;**时长验收重采**:实际/预期不落在窗口内就重采;**启动硬校验运行时钉版** `transformers==4.51.3`/`tokenizers==0.21.4`——版本不符会让语音内容乱码而时长/峰值正常,见 v2.2)
│   ├── tts_qwen_server.py   Qwen3-TTS 服务(8017,GPU2,备用引擎,默认停;<8 字 400)
│   ├── avatar.py            数字人:片段生成/时间轴/叠加(圆角卡片或抠像)+ 播报视频(音轨拼接、顺序合流、ETA 估算)+ 抠像遮罩批量补齐 + gRPC 探活
│   ├── matte.py             抠像 worker:MODNet ONNX 逐帧出 alpha → 灰度遮罩 mp4(独立解释器跑,单段/批量两种入口,模型只加载一次)
│   ├── smoke_test.py        冒烟回归:纯函数路径(extract/styles/时长靠拢/校验门/讲解校验)
│   ├── jobs.py              任务状态机(磁盘持久化,重启恢复;video_kind 持久化;重启时 uploaded 同样置 failed)+ 项目标题/阶段历史(record_history,上限 60 条)+ 启动补录(_backfill_meta:老任务从脚本与产物倒推)
│   └── builder/
│       ├── styles.py        风格系统:四维度注册表(字体×配色×背景×动效)+ 组合合成 + SVG 装饰
│       ├── templates.py     13 种帧类型(10 种宣传 + 3 种讲解:textblock/annotation/method)× 维度属性渲染(HTML+GSAP tween 生成)
│       └── assemble.py      script.json → HyperFrames 项目(index.html + assets + BGM,重建前清理陈旧产物)
├── web/index.html           前端单文件 SPA(项目历史入口页 + 创作页 + 预览页,Studio 为唯一预览;woff2 字体子集 + unicode-range 回退系统字体;骨架屏/轮询退避/删除任务/就地重命名/步骤直达)
└── deploy/                  nginx 路由 / 启动脚本(已删除一次性 patch-*.py 补丁,git 历史留档)
```

## 三、流水线状态机

```
uploaded → analyzing → analyzed → building → preview → rendering → rendered
              │                       │              │
              │ DeepSeek              │ TTS 池并行   │ hyperframes render
              │ 宣传:两阶段(诊断→脚本)│ +二次拓展     │ (并发 ≤2,--workers 1 走流式)
              │ 讲解:备课+分段并行    │ +组装+Studio │ 讲解片超时放宽到 3h
              │ (3 worker,≈3-10 分钟) │ 同步拉起     │
              └─ 失败可 /analyze 重跑 └─ 自动 check  └─ 成片就绪

analyzed ──(分析完成后即可,与上面的 PPT 主线并列)──▶ avatar_building ──▶ 回到进入前的状态
              「数字人播报视频」:配音 → 逐帧片段 → 顺序拼接(不经过 HyperFrames)
```

关键设计(v2.6 项目历史):
- **入口页 = 项目历史列表**(`GET /api/jobs`):按 `state.updated_at` 倒序,只带列表字段(不含 script);进行中的任务带 `progress`/`render_progress`,卡片上直接看"现在到哪一步";有任务进行中时前端 4 秒刷新,空闲 20 秒。路由用查询串区分:`?job=<id>` 详情页、`?new=1` 创作页、无参数 = 入口页
- **项目标题三段来源**(`state.title` + `state.title_source`):`file`(新建时的文件名占位)→ `auto`(分析完成后 `analyze.summarize_title` 用一次小调用总结,失败回退脚本标题)→ `user`(`POST /api/jobs/{id}/rename`)。**`source=user` 是硬闸**:`_auto_title` 在设置前再查一次,用户改过就绝不覆盖。标题一律单行、≤60 字(`jobs.normalize_title`,空标题 400)
- **阶段历史**(`Job.record_history`):`analyze/build/render/broadcast` 完成或失败各追加一条,每条带 `step/label/status/detail/at` 与产物线索(渲染记格式/时长/大小/是否叠数字人,播报记段数与尺寸),上限 60 条。后台阶段异常由 `run_in_background(..., step=…)` 在 failed 分支补记 —— 列表上能说清"哪一步挂了"
- **直达结果**:卡片步骤胶囊 → `?step=analyze|build|render|broadcast` → 详情页在该步目标**可见之后**滚动并高亮(`applyStepFocus` 每轮轮询都试,直到成功);详情页「历史记录」面板逐条给产物下载入口
- **老任务零迁移**:`load_from_disk` 里 `Job._backfill_meta()` 补标题(脚本标题 → 文件名)与历史(脚本/工程/产物时间戳倒推,标 `derived:true`),并把 `updated_at` 回填到最近一次历史/产物时间;缺 `updated_at` 等新键由 `setdefault` 补齐。`updated_at` 由 `set()` / `record_history()` / `_record_artifact()` 统一刷新,是列表排序的唯一依据
- **不保留成片副本**:历史只记"出了什么、多大、什么时候",同一阶段重复执行各留一条;**当前产物以 `state.artifacts` 为准**,不按次归档视频(单条几百 MB,会撑爆磁盘)

关键设计(v2.1 数字人播报视频):
- **支线状态 `avatar_building`**:只被 `POST /avatar/broadcast` 使用;进入前记住原状态,成功/失败都回到原状态(失败不毁任务)
- **配音复用**:`state.vo_sig = sha1(逐帧台词 + 音色 + 引擎 + 合成口径)`;指纹**完全相符**且配音文件齐全时跳过合成 —— 重跑/构建后重跑都是秒级。
  最后一项(合成口径 = `PINNED_TTS_DEPS` + `VO_SYNTH_VERSION`)是 v2.8 补的:transformers 4.52+ 会打乱语音 LLM 输出(乱码,但时长/峰值全正常),只钉版运行时的话,
  那些**用坏运行时烧出来的旧配音**会因"台词没变"继续被判为可复用 —— 用户重新构建、重新渲染,听到的还是乱码。口径进指纹后,这类修复会自动作废旧配音。
  复用判断里**没有**"文本一致就复用"的兜底:宁可多烧一次 GPU,也不给坏产物留门。
  **构建与播报共用同一份配音**:`stage_build` 默认也复用(`?force_voice=1` 强制重合成),所以「先构建后播报」与「先播报后构建」拿到的是同一版声音,顺序不影响结果。
- **配音可懂度抽检**(`server/voice_check.py`):每次**真正重新合成**后,用本地 whisper 抽检 2 帧(听写 vs 台词,繁简归一算 LCS)写进 `state.voice_check`;
  `warn` 时预览页弹红条 + 一键「重新合成配音」。时长/静音验收拦不住"念的是乱码",这是唯一的内容级判据;抽检只提示不阻塞(whisper 缺失/超时一律跳过)。
- **两条轨道共用片段缓存**:播报视频与成片用的是同一批 `.cache/avatar/*.mp4`(键 = 形象+音频+尺寸+帧时长+版本),所以画面与配音天然一致
- **音轨跟画面走**:拼接前逐片段 ffprobe 真实时长,音轨按真实时长铺 —— 声明时长与编码时长的毫秒差逐帧累积会让 `-shortest` 从片尾裁掉台词

关键设计(v1.0):
- **构建期 Studio 同步拉起**:组装完成后、置 preview 状态前启动 Studio(`--foreground` 直管进程,绕开 CLI 会话注册表),状态翻转瞬间编辑器即就绪(零等待);Studio 启动串行化 + 槽满回收确认端口释放,进程按需自愈
- **时长靠内容**:分析提示词按实测语速 4.2 字/秒规划旁白量;构建时旁白量不足目标自动二次拓展(两轮,加长旁白+增帧);apply_real_durations 按真实配音重算帧时长并向目标靠拢(留白仅作安全网)

关键设计(v1.1 讲解视频):
- **两步分析**:①一次调用诊断文章类型(策论/政论/综合分析/时政评论等)+ 讲解方案(章节、逐段要点、待批注句、可迁移写法);②按章节分组为 ≤7 分钟的分段,每段一次调用生成逐帧脚本,合并后整体校验。段级校验兜底(引用逐字/类型/旁白/时长),全局失败即报错可重跑
- **引用接地(grounding)+ 段级确定性修复**:模型输出不依赖自觉——textblock/annotation 引用先精确匹配,不中则模糊匹配(相似度 ≥80%、区间不膨胀),命中即用原文真实区间替换;批注类型词归一化到枚举(例证→论据、措施→对策…);data 值归一化为原文真实数字;帧时长向段目标等比缩放。修复后再校验,修不了的才反馈重试(3 次)
- **段级治愈(healing)**:接地失败的批注句直接移除(宁少一条批注,绝不显示改写的"原文");引用全灭的 annotation/textblock 帧整帧丢弃
- **重点段限流**:备课方案 line_analysis=true 的段落数 ≤ 目标分钟数×2(校验硬拦),段提示词只允许给重点段生成 textblock——引述密集的新闻稿也不会"每段一帧"撑爆时长
- **段级旁白上下限**:下限 1.6×秒数、上限 4.2×秒数(实测语速上限,超了物理上压不回目标时长);超量时确定性压缩(丢旁白最短的次要帧);帧数按段时长占比分配硬上限(总上限 200,只兜底不硬压——模型按段落要点自然铺开,实测 5 分钟档 13-23 帧)
- **「永不失败」管线**(文字类问题绝不中断工作流):模型重试 3 次(带校验反馈)→ 确定性修复(接地/治愈/截断/丢帧压缩)→ 最后兜底接受(警告放行,_meta.warning)。备课方案同样:3 次重试 + _fixup_plan 确定性修复(字段补默认/区间钳位/坏引用删除/重点段截断/章节程序化构造)+ 警告放行;合并校验失败只警告。只有模型/网络级故障才报错。讲解视频的校验用 strict=False:旁白成段、画面充实度等文字类软约束只作提示词指导
- **视频类型贯通**:video_kind(promo/lecture)持久化于任务状态;分析/校验/修订/拓展/编辑保存/渲染超时/留白参数全链路按类型分支;讲解 5-30 分钟(5 分钟一档,后端钳位到 300 的整数倍)
- **画面布局(无交叉的机制保证)**:正文区垂直中心在黄金分割点(容器限高 1080×76.5%,底部最多到 y=826,overflow 兜底);字幕为影视剧式 1-2 行窗口(每行 ≤19 字、句读断行、随旁白逐窗推进,底部 86px 起、顶部 ≥894px)——两者间恒定 78px 缓冲带,几何上不可能交叉,与具体内容无关
- **停顿节奏**:讲解档旁白后留白 1.0s、单帧可扩展上限 4s、章节页 ≤6s;段级旁白下限 3.0×段秒数 + 构建期二次拓展——时长靠内容填,不靠静默停留凑(全片无 >2s 静音段)
- **成片自动验证**:deploy/verify-layout.py——缓冲带深色像素检查(全片采样)+ 静音段检测
- **预览音频看门狗**:预览 HTML 注入脚本,自动恢复「时间线播放而音频静音/暂停」的自动播放策略死状态

- 任务持久化:`jobs/<id>/state.json`,重启后自动恢复;进行中任务(uploaded/analyzing/building/rendering)统一置 failed 可重触发
- 每任务:`input.<ext>`(原文)→ `input.txt`(提取文本)→ `script.json`(分析)→ `project/`(composition)→ `project/renders/out.mp4`

关键设计(v2.0):
- **宣传两阶段分析**:阶段一「分析」输出小契约(核心论点/论证链节拍/数据清单(逐字核验)/金句清单(逐字)/帧计划),阶段二「脚本」按帧计划生成 frames——分析深度反哺脚本,不再一次调用到底
- **金句接地**:quote 帧引语逐字接地到原文(精确→模糊匹配替换为原文区间),无法接地保留但写 `_meta.warning`
- **永不失败兜底**:模型重试 3 次仍不合规时,对最近一次成功解析的脚本做确定性修复(丢最短旁白次要帧 + 时长缩放)后接受,`_meta.warning` 记录;max_tokens 分档(≤90s:4096 / ≤180s:8192 / ≤360s:12288 / >360s:16384),检测 finish_reason=length 截断并重试;temperature 首轮 0.35、纠错重试 0.6
- **并发与限流**:httpx 全局共享连接池(修复历史上 "Too many open files" FD 耗尽);讲解视频分段脚本并行生成(ThreadPoolExecutor 3 workers,段间无依赖);全局 LLM 并发信号量 6;渲染全局信号量 2;进行中任务 >4 时新任务创建返回 429;TTS 合成按帧分发多实例并行 + ffmpeg/ffprobe 线程池化
- **语速常量统一**:config.CHARS_PER_SEC=4.2 全局引用;宣传档位旁白系数 3.0/3.8/3.9/4.0 字/秒(有意低于实测语速,余量由构建期留白分摊);拓展验收线统一 0.8
- **讲解备课覆盖校验**:chapters para_range 必须覆盖全文每个段落(无空洞/重叠,否则修复);paragraph_notes 覆盖每段(缺失程序化补,key_idea 取段首 40 字);分段 prompt 只注入本段相关章节与段落要点(瘦身);合并层 line_analysis=true 重点段未获 textblock/annotation 帧则打印警告;annotation 批注句同帧必须出自同一段
- **安全**:script title 全部 HTML 转义(修复存储型 XSS 面);api_revise body 非 dict 防护;projects 透传代理加 '..' 拦截;txt/md 上传 >1.5MB 直接拒绝;异常路径统一 logging.exception 落 logs/backend.log(日志统一收在 ROOT/logs,路径常量见 config.LOG_DIR)
- **日志布局**:`logs/backend.log`(后端)、`logs/tts/*.log`(TTS 实例)、`logs/studio/<job_id>.log`(每任务 hyperframes preview 输出;原先散落项目根目录)

## 四、关键设计决策

1. **分析 = 确定性模板管线**(非 agent 现场创作):宣传两阶段(诊断小契约 → 按帧计划生成脚本)、讲解两步 + 分段并行(3 worker),快、并发友好、输出可预期;风格 skill 规则固化在 builder 中
2. **时长自适应**:按目标时长分四档(≤90 / ≤180 / ≤360 / >360s)规定帧数、旁白量、内容策略与 max_tokens(4096/8192/12288/16384);旁白量按 config.CHARS_PER_SEC=4.2 字/秒规划,宣传档位系数 3.0/3.8/3.9/4.0(有意低于实测语速,余量由构建期留白分摊),拓展验收线统一 0.8
3. **语速恒为 1.0**(自然语速):tts_server 钳位下限 1.0,实测 speed<1 非线性恶化(0.8 → 5 倍时长怪音)
4. **帧时长以真实配音为准**:DeepSeek 的 duration 仅是初始估时,构建时按 TTS 实际时长重算
5. **字体完整版**(82MB 全 CJK):渲染必须完整版 OTF(子集字体缺生僻字会渲染成方框);网页端则用 woff2 子集化(约 3000 常用字 + 静态文案,每份 <300KB,unicode-range 回退系统字体)
6. **Studio 唯一预览**:每任务一个 hyperframes preview 进程(槽位 4150-4153,构建期同步拉起、按需自愈),经 /api/studio/ 反向代理(全 HTTP 方法)接入;HTML/JS 绝对路径窄化重写(/assets/、/api/ 前缀)。
   两处**必须自适应、不可写死**(写死的失败表现就是「构建预览一直转圈」或编辑器空转):
   - **挂载前缀**:`_client_base(request)` 从 Referer/Origin 推断(根部署 `""`、nginx `/ttv/` 部署 `"/ttv"`)—— nginx 的 proxy_pass 会把前缀剥掉,后端自己看不见它
   - **Studio 项目 id**:hyperframes 用**工作区根目录名**(`/mnt/workspace/ttv` → `ttv`,本工作区 `/data/Avatar` → `Avatar`),由 `_studio_project_id()` 向 Studio 的 `/api/projects` 探测(按 dir 匹配,失败按目录名兜底),请求与响应两侧做 id 桥接(前端 iframe 的 `#project/ttv` 保持不变)
7. **安全**:docx zip 炸弹防护(50MB/2000 条目)、文件名净化、路径防穿越(projects 代理 '..' 拦截)、txt/md 上传 >1.5MB 拒绝、script title HTML 转义(存储型 XSS)、提示词注入隔离声明、前端 textContent 防 XSS

## 五、接口清单

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/styles | 四维度选项 + 预设 |
| GET | /api/jobs | 项目历史列表(按 updated_at 倒序,`{jobs,total}`,不含 script;进行中任务带 progress/render_progress) |
| POST | /api/jobs | 上传(file/text + style/font/palette/bg/motion/duration/video_kind);进行中任务 >4 返回 429 |
| GET | /api/jobs/{id} | 状态 + 分析结果 + 项目标题(title/title_source)+ 阶段历史 history;?brief=1 轻量轮询(不含 script) |
| POST | /api/jobs/{id}/rename | 重命名项目(单行 ≤60 字,空标题 400;改后 title_source=user,自动总结不再覆盖) |
| POST | /api/jobs/{id}/analyze | 重新分析(analyzing/building/rendering 期间 409) |
| POST | /api/jobs/{id}/build | 构建(配音+组装+自动 check);默认**复用已有配音**,`?force_voice=1` 强制重新合成 |
| POST | /api/jobs/{id}/render | 渲染 MP4 |
| POST | /api/jobs/{id}/avatar/broadcast | 生成「数字人播报视频」(独立支线;analyzing/building/avatar_building/rendering 期间 409) |
| GET | /api/jobs/{id}/avatar/broadcast/video | 播报视频预览/下载(支持 Range;未生成 404) |
| DELETE | /api/jobs/{id} | 删除任务(rendered/failed 可删;building/rendering 409) |
| GET | /api/jobs/{id}/video | 下载成片(按 state.render_format 检查对应产物,非 mp4 同样有入口) |
| 全方法 | /api/studio/{id}/… | Studio 编辑器代理(原硬编码 GET 已放开为全 HTTP 方法) |

## 六、扩展点

- 新帧类型:builder/templates.py 加函数 + analyze.py FRAME_TYPES/CONTENT_REQUIRED + frames-schema.md(讲解帧加校验时注意 validate_script 的 check_quotes 分支)
- 新配色/背景:builder/styles.py 注册表加条目(前端自动出现)
- 精确字幕对齐:tts.py 词级时间轴换 whisper 对齐
- BGM:assets/bgm/ 放入同名 MP3 即生效
- 数字人形象:builder/styles.py 的 AVATARS 注册表加条目(或用 TTV_AVATAR_IMAGE 指到任意图片)

## 七、数字人片段(可选功能)

用途:让数字人在成片**选定的角落**(四角可选,默认右上)朗读该帧台词。默认关闭,任务级开关
`POST /api/jobs` 的 `avatar=true`(Web 端对应"数字人出镜"下拉:**不出镜 / 左上 / 右上(默认)/ 右下 / 左下**),
也可用 `TTV_AVATAR=1` 全局默认开启。出镜时还可以勾「只保留人像(背景透明)」把背景抠掉
(`avatar_cutout=true` / `state.avatar_geom.cutout`),见下面的「抠像」小节。

链路:

```
每帧台词音频(vo_NN.mp3,项目自身 TTS 产出)
   └─ server/avatar.py → CyberVerse AvatarService(gRPC,127.0.0.1:50051,FlashHead,原生 464×464)
        └─ RGB24 原始帧 → ffmpeg 编码成 <尺寸>×<尺寸> 片段(仅画面,丢弃服务端音轨)
             └─ 全局缓存 .cache/avatar/clip_<形象>_<音频>_<尺寸>_<帧时长>_<版本>.mp4
                  └─(抠像时)server/matte.py → clip_*.modnet<版本>.mp4 灰度遮罩,MODNet ONNX 本地推理
渲染成片后
   └─ avatar._overlay_timeline():出镜才读时间轴 → composite_onto_video(corner=…) 叠到该角落
```

> **几何按任务存**:`state.avatar_geom = {corner, size, cutout}`(默认
> `{"tr", 300, false}`),出镜开关是 `state.avatar`(bool)。创作页建任务时设置,预览页可随时改
> (`POST /api/jobs/{id}/avatar/geom`,四个字段都可选、只传哪个改哪个),下一次构建/渲染生效。
> 老任务没有 `avatar_geom` → 直接回默认值,不需要迁移。
> 「数字人播报视频」的大小默认跟随这个 `size`,但可以单独指定(见第八节)。

要点:

- **关闭出镜要盖过残留时间轴**:`stage_render` 用 `_overlay_timeline(job, project)` 取时间轴,
  它**先看 `state.avatar`** —— 任务在上次构建后改成了「不出镜」时,磁盘上的
  `avatar_timeline.json` 可能还在,只按文件判断会把不该出现的人像叠回去(成片出来才发现)。
  `stage_build` 侧同理:不出镜就删掉时间轴。

- **时间轴唯一**:片段时长 = 帧总时长(`frames[].duration`,已由真实配音回填),
  起点 = `assemble.build()` 返回的 `starts` —— 与字幕、音频同一时钟;片段自带音轨丢弃。
- **待机片段**:无台词帧(opening/closing)与帧尾留白都用"闭嘴静默"片段填充,
  每个形象只生成一段并全局缓存(`idle_*.mp4`)。
- **圆角与投影在叠加时完成**,不烘焙进片段:H.264 不支持 alpha,烘焙会把透明区变成黑底;
  叠加时用同一张灰度遮罩(`mask_<尺寸>_<半径>_v<版本>.png`)+ boxblur 投影,一次滤镜图完成。
- **抠像(可选)**:`cutout=true` 时不叠卡片,改用片段自己的 alpha —— 每段片段旁多一条
  `clip_*.modnet<版本>.mp4` 灰度遮罩(`server/matte.py`,MODNet ONNX,独立解释器),叠加时
  `[片段][遮罩]alphamerge` 得到透明背景的人像。三条硬口径:
  1. **贴画面下缘**:片段是齐胸特写、底边整行都是躯干,摆在画面中间会像悬浮的半身像;
     贴下缘后切口落在画面外沿。上下角在抠像模式下等价,只有左右由角落决定(`avatar.cutout_xy`)。
  2. **遮罩独立缓存**:`片段名.{模型标识}{遮罩版本}.mp4`,`TTV_MATTE_MODEL_TAG`/`TTV_MATTE_VERSION`
     变更即失效,而**片段缓存不受影响**;渲染前 `avatar.ensure_mattes()` 会把缺的补齐(老时间轴、
     刚打开抠像的任务都走这条),一批一个进程、模型只加载一次。
  3. **失败逐条回退**:解释器/权重缺失或单段失败只记日志,该段仍用圆角卡片;一条都没抠成时
     `avatar_error` 会说明原因。**播报视频不抠像**(独立口播片,透明无意义)。
  详见 `docs/adr/0004-抠像用独立灰度遮罩完成.md`。
- **失败不阻塞出片**:数字人任一环节失败只写入 `job.state.avatar_error`,成片照常产出(仅无人像)。
- **四角坐标**:`avatar.corner_xy(corner, size)` 按"带投影留白的卡片画布"离边 `AVATAR_X/AVATAR_Y`
  摆位(四角视觉边距一致、投影不被画面裁掉);显式传 `x/y` 时优先用它们(老调用方与
  `deploy/verify-avatar.py` 的像素校验走这条)。
- 相关环境变量:`TTV_AVATAR` / `TTV_AVATAR_ADDR` / `TTV_AVATAR_IMAGE` / `TTV_AVATAR_SIZE` /
  `TTV_AVATAR_SIZE_CHOICES` / `TTV_AVATAR_SIZE_MIN` / `TTV_AVATAR_SIZE_MAX` / `TTV_AVATAR_NATIVE_SIZE` /
  `TTV_AVATAR_CORNER` / `TTV_AVATAR_X` / `TTV_AVATAR_Y` / `TTV_AVATAR_IDLE_SECONDS` /
  `TTV_AVATAR_CLIP_VERSION`;抠像另有一组:`TTV_AVATAR_CUTOUT`(全局默认开关)/
  `TTV_AVATAR_CUTOUT_BOTTOM_MARGIN` / `TTV_MATTE_MODEL` / `TTV_MATTE_MODEL_TAG` / `TTV_MATTE_VERSION` /
  `TTV_MATTE_PYTHON` / `TTV_MATTE_REF` / `TTV_MATTE_CRF` / `TTV_MATTE_TIMEOUT` / `TTV_MATTE_URLS`。
- 验证:`python deploy/verify-avatar.py`(真跑 assemble.build + 渲染 + 叠加 + 像素校验,
  第 ⑥ 步另验抠像:人像框内应有一大块像素与纯 PPT 完全一致);
  四角摆位/抠像坐标的纯函数与"锚点确实有人像"另有 `smoke_test` 与一次性像素回归覆盖。

## 八、数字人播报视频(独立产物)

用途:不改动 PPT 成片链路,单独产出**一条数字人朗读全篇旁白的视频** —— 用于单独预览、单独交付口播片。
分析完成后即可生成,不需要先构建预览、也不需要等成片渲染。

```
分析完成(script.json)
  └─ POST /api/jobs/{id}/avatar/broadcast {"size": 480} → 状态 avatar_building
       ├─ ① 合成配音   tts.synthesize_frames(复用 state.vo_sig 命中则跳过)
       ├─ ② 逐帧片段   avatar.build_frame_clips(size=…)(缓存命中则秒过)
       └─ ③ 拼接       avatar.build_broadcast_video
            ├─ 音轨:每帧 = 0.25s 静音 + 该帧配音 + 补静音到帧时长(build_broadcast_audio)
            └─ 画面:各帧片段按时间轴顺序 concat(逐片段 ffprobe 真实时长)+ AAC 合流
                 → renders/avatar.mp4(size×size,含音轨,不含 BGM/PPT 画面;默认 300×300)
```

要点:

- **产物是第三个 artifact**:`state.artifacts.avatar`(另两个是 ppt/final);`GET .../avatar/broadcast/video` 独立入口。
- **数字人大小(可选,默认跟随任务的数字人大小,现为 300)**:前端是**手输数字**框
  (留空/非法则由后端校验兜底),档位提示与默认值由 `GET /api/styles → avatar_sizes` 下发
  (`config.AVATAR_SIZE` / `AVATAR_SIZE_CHOICES` / `AVATAR_NATIVE_SIZE`,原生上限 464,超过只是放大)。
  选中值按任务记在 `state.avatar_broadcast_size`(没单独选过就用 `state.avatar_geom.size`),接口只认偶数且落在 160–1080
  (`avatar.normalize_size`,非法值 400;读路径用 `avatar.safe_size` 防坏值把轮询打成 500)。
  每条播报视频实际生成的尺寸写在 `avatar_broadcast.size`,前端据此显示 —— 改了输入框但没重新生成时,
  界面会说明"当前这条是 X×X,重新生成会改成 Y×Y"。
  尺寸进片段缓存键(`clip_<形象>_<音频>_<尺寸>_<帧时长>_<版本>`),不同尺寸各自缓存、互不失效。
- **步骤与预计时间**:`state.avatar_broadcast = {status, size, step_index, step, detail, done, total, eta_sec, elapsed_sec, error}`,
  每一步由后端逐帧回写(前端只展示不猜);系数见 `config.AVATAR_RT_FACTOR / AVATAR_CONCAT_RT_FACTOR / AVATAR_TTS_RT_FACTOR`,
  事前预计(`avatar_broadcast_est_sec`,可带 `?avatar_size=` 按未提交的选中尺寸现算)以
  `total_sec > 脚本帧时长之和 > duration_sec` 为基准;拼接系数按**面积比**从实测基准边长
  (`config.AVATAR_CONCAT_BASE_SIZE` = 320)外推(`avatar.concat_rt_factor`)—— 基准不随默认边长漂移,
  人像推理在服务端固定 464、与目标边长无关,所以只有拼接段随尺寸变化。
- **失败不伤主线**:失败只写 `avatar_broadcast.error` + `progress` 提示,状态回到进入前的那个,
  脚本、成片、Studio 都不受影响;可反复重试。
- **与成片的关系**:成片 = PPT 渲染 + 各帧片段**叠加**(同一时钟);播报视频 = 各帧片段**顺序拼接** + 连续音轨。
  两者共用同一批缓存片段与同一份帧时长,差别只在"有没有 PPT 画面"。
- 验证:`python server/smoke_test.py`(音轨拼接/ETA 纯函数)+ 端到端(见 `CHANGELOG.md`)。

