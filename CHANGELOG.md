# 理论文章转视频网站 — 项目计划与进度

> 最后更新:2026-08-26
> 部署位置:**VideoLab 云服务器**(SSH `videolab`,8.130.213.80),整个项目运行在服务器上。
> 本地此文件夹保存:计划文档、源码副本、风格脚本、部署配置。

## 一、项目目标

一个可外网访问的网站:用户上传长文(纯文本 / txt / docx / md,如人民日报「人民要论」、马院论文),
选择视频风格、填写期望时长 → 服务器调用 **DeepSeek** 做内容分析(大纲、视频结构、逐页内容、样式推荐),
输出 HyperFrames 可直接消费的脚本 → 服务器用 **HyperFrames** 构建并渲染成政论视频 →
同一网站的二级页面提供 **HyperFrames 预览**。

## 二、技术架构

```
浏览器 ──▶ nginx(外网端口 20015)
              ├── /            → 前端静态页(上传页 + 预览二级页)
              └── /api/*       → FastAPI 后端(127.0.0.1:8015)
                                   ├── extract   文本提取(txt/docx/md)
                                   ├── analyze   DeepSeek 分析 → hyperframes 脚本(JSON)
                                   ├── build     HyperFrames composition 构建
                                   ├── render    HyperFrames CLI 渲染 MP4
                                   └── preview   代理 HyperFrames 预览服务器
```

- 流水线:上传 → 文本提取 → DeepSeek 分析(含风格脚本注入)→ 脚本(JSON)→ 构建 composition HTML → TTS 配音(火山豆包)→ hyperframes 渲染 → 预览/下载
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
│   ├── main.py          # FastAPI:jobs API + 播放器代理
│   ├── analyze.py       # DeepSeek 分析(本地 vLLM 优先,云 API 备份)
│   ├── extract.py       # txt/md/docx 提取(纯标准库)
│   ├── tts.py           # edge-tts 配音 + 词级时间轴
│   ├── jobs.py          # 任务状态机
│   └── builder/         # styles.py(tokens+SVG)/ templates.py(10 帧型)/ assemble.py(组装)
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
- edge-tts(pip,无豆包 key 的 TTS 方案)

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
- [ ] TTS:edge-tts(zh-CN-YunxiNeural 男声新闻 / XiaoxiaoNeural 女声,免费无 key)
- [ ] Chrome + node PATH + hyperframes CLI + 字体 安装(部署阶段执行)
