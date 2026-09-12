# 理论文章转视频(Theory-to-Video)

> 把人民日报「人民要论」、马院论文等理论长文,自动生成庄重的政论视频(PPT 式成片 + 数字人播报视频)。
> 前端 + 后端 + 配音全部跑在本机,分析用 OpenAI 兼容的 DeepSeek 网关,渲染用 HyperFrames + 无头 Chrome。

| 入口 | 地址 |
|---|---|
| 本地默认 | **http://localhost:8015/**(接口文档 `/docs`) |
| 生产部署 | **http://8.130.213.80:20013/ttv/**(nginx `/ttv/` 路由) |

## 一、部署到新机器(从零)

代码仓**只跟踪 60 个左右的源码/文档文件**,权重、字体、venv 全部不入库(`.gitignore`)。所以新机器 = 拉代码 + 按下面清单重新下载资产 + 起服务。

### 1.1 环境要求

| 项 | 要求 | 本机实测 |
|---|---|---|
| 系统 | Linux x86_64(Ubuntu 22.04) | Ubuntu 22.04 |
| GPU | NVIDIA,显存 ≥16GB(配音/数字人需要) | RTX 5090 32GB(sm_120) |
| 驱动 / CUDA | 支持 torch 2.8+ | 595.58.03 / CUDA 12.8 |
| Node.js | 22(hyperframes CLI 用) | v22.20.0 |
| Python | 3.10+(后端;配音用系统 3.10) | 3.10.12 / 主 venv 3.12.14 |
| 其它 | `ffmpeg` / `ffprobe`、`curl`、`npm` | ffmpeg 4.4.2 |
| 磁盘 | 仅主线 ≥30GB;含数字人 ≥100GB | 现状 51GB |
| 网络 | 能访问 DeepSeek 网关(见 §1.4) | paratera 云网关 |

### 1.2 获取代码

```bash
git clone git@github.com:Ironstarboy/article2video.git <仓库根>
cd <仓库根>          # 本机即 /data/Avatar
```

> 没有 SSH key 时,直接从旧机器拷贝整个工作区(同型号机器 + 同路径 `/data/Avatar` 时 venv 可直接复用)。

### 1.3 组件与下载清单

#### ① 主站(必需):后端 8015 + 网页

| 内容 | 来源 / 链接 | 落地位置 |
|---|---|---|
| Python 依赖 | `server/requirements.txt`(fastapi/uvicorn/httpx/python-multipart/jieba/fonttools/grpcio/protobuf) | `.venv` |
| 完整版字体 ×4 | 见下方字体链接(**必须完整版 OTF**,子集版会把生僻字渲染成方框) | `assets/fonts/` |
| GSAP 3.14.2 | https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js | `assets/vendor/gsap.min.js` |
| BGM ×3(占位) | https://freepd.com/music (CC0: Epic Boss Battle / Ambient Classical Guitar / In The Clouds) | `assets/bgm/{solemn-red,academic-ink,modern-blue}.mp3` |
| hyperframes CLI | `npm install -g hyperframes@0.8.15`(本机实际 0.8.34) | 全局 npm |
| 无头 Chrome | `hyperframes browser ensure`(chrome-headless-shell) | `~/.cache/hyperframes/chrome/` |

字体下载链接(保存成代码期望的文件名):

```bash
SH=https://raw.githubusercontent.com/adobe-fonts/source-han-serif/release/OTF/SimplifiedChinese
NOTO=https://raw.githubusercontent.com/notofonts/noto-cjk/main/Sans/OTF/SimplifiedChinese
curl -fL -o assets/fonts/SourceHanSerifCN-Heavy.otf    $SH/SourceHanSerifSC-Heavy.otf
curl -fL -o assets/fonts/SourceHanSerifCN-Regular.otf  $SH/SourceHanSerifSC-Regular.otf
curl -fL -o assets/fonts/NotoSansSC-Regular.otf        $NOTO/NotoSansCJKsc-Regular.otf
curl -fL -o assets/fonts/NotoSansSC-Bold.otf           $NOTO/NotoSansCJKsc-Bold.otf
```

> 上面这些 `deploy/setup.sh` 会全自动完成(含 ≥10MB 完整性校验、BGM 缺失时静音占位、npm 安装、Chrome 下载、nginx 路由可选安装)。

#### ② CosyVoice3 本地配音(必需)

| 内容 | 来源 / 链接 | 落地位置 | 体积 |
|---|---|---|---|
| 模型权重 | ModelScope **FunAudioLLM/Fun-CosyVoice3-0.5B-2512**<br>https://modelscope.cn/models/FunAudioLLM/Fun-CosyVoice3-0.5B-2512 | `models/CosyVoice3-0.5B/` | 9.1GB |
| 源码 | https://github.com/FunAudioLLM/CosyVoice(浅克隆 + `git submodule update --init` 取 `third_party/Matcha-TTS`) | `cosyvoice-src/` | 5MB |
| 运行时依赖 | 见下方 pip 列表 | `tts-venv/` | 7GB |
| **种子音色 ×3** | ⚠️ **上游没有,必须从旧机器拷**(本地自制克隆种子) | `models/CosyVoice3-0.5B/asset-v2/{male,female,male_narrator}.wav` | 1MB |

```bash
python3 - <<'EOF'
from modelscope import snapshot_download
snapshot_download('FunAudioLLM/Fun-CosyVoice3-0.5B-2512', local_dir='models/CosyVoice3-0.5B')
EOF

git clone --depth 1 https://github.com/FunAudioLLM/CosyVoice.git cosyvoice-src
(cd cosyvoice-src && git submodule update --init)          # Matcha-TTS

python3.10 -m venv --system-site-packages tts-venv          # 复用系统 torch 2.8.0+cu128
tts-venv/bin/pip install modelscope wetext sentencepiece hydra-core HyperPyYAML \
  omegaconf librosa soundfile inflect pyworld conformer gdown wget lightning
tts-venv/bin/pip install "transformers==4.51.3" "tokenizers==0.21.4"   # 🔴 必须钉版
```

**🔴 `transformers==4.51.3` / `tokenizers==0.21.4` 不能改**:语音 LLM 跑在 Qwen2 backbone 上,4.52+ 会让 speech token 乱掉,听感是「读音完全不正常、断断续续」而**时长与峰值全正常**(时长/静音验收拦不住)。`tts_server` 启动时会硬校验(不符即拒启,`TTV_TTS_ALLOW_UNPINNED=1` 可绕过),`smoke_test` 也会校验 `tts-venv` 实际版本。

#### ③ 数字人 CyberVerse / FlashHead(可选,选「数字人出镜」的角落才需要)

| 内容 | 来源 / 链接 | 落地位置 | 体积 |
|---|---|---|---|
| CyberVerse 源码 | https://github.com/dsd2077/CyberVerse | `CyberVerse-main/` | — |
| 数字人权重 | ModelScope **Soul-AILab/SoulX-FlashHead-1_3B** https://modelscope.cn/models/Soul-AILab/SoulX-FlashHead-1_3B | `CyberVerse-main/checkpoints/SoulX-FlashHead-1_3B` | 14GB |
| 音频编码器 | ModelScope `facebook/wav2vec2-base-960h`(备选 `HF_ENDPOINT=https://hf-mirror.com`) | `CyberVerse-main/checkpoints/wav2vec2-base-960h` | 1.1GB |
| Go 1.25 | https://dl.google.com/go/go1.25.0.linux-amd64.tar.gz | `.tools/go` | 70MB |
| protoc 29.3 | https://github.com/protocolbuffers/protobuf/releases/download/v29.3/protoc-29.3-linux-x86_64.zip | `.tools/protobuf-29.3` | — |
| uv | `curl -LsSf https://astral.sh/uv/install.sh \| env UV_INSTALL_DIR=.tools/bin sh` | `.tools/bin` | — |

完整步骤(系统依赖、离线 wheel、`generate_proto.sh`、踩坑速查)见 **`CyberVerse-DEPLOY-GPU.md`**;本仓库的集成方式见 `ARCHITECTURE.md` 第七、八节。数字人**失败不阻塞出片**:任一环节失败只记录 `state.avatar_error`,成片照常产出(仅无人像)。

#### ④ 必须手工搬运(任何源上都下不到)

1. `models/CosyVoice3-0.5B/asset-v2/*.wav` —— 三个零样本种子音色(约 1MB);
2. `.secrets/llm.env` —— LLM 端点与 key(见 §1.4);
3. `CyberVerse-main/config/`(上游是 `infra/config` 拷贝 + 本地 provider/key 改动)与 `checkpoints/`;
4. 若用了正式授权 BGM,拷贝 `assets/bgm/*.mp3`(否则 `setup.sh` 下 CC0 占位)。

### 1.4 配置

**LLM 分析端点**(两份可选,写入 `.secrets/llm.env`,`deploy/start.sh` 自动加载):

```bash
# 方案 A:本机/内网 vLLM(默认值,零成本)
TTV_DEEPSEEK_URL=http://8.130.213.80:20001/v1
TTV_DEEPSEEK_MODEL=DeepSeek-V4-Flash

# 方案 B:云上 OpenAI 兼容网关(本机当前用法)
TTV_DEEPSEEK_URL=https://llmapi.paratera.com/v1
TTV_DEEPSEEK_MODEL=DeepSeek-V4-Flash
TTV_DEEPSEEK_KEY=sk-...
```

**常用环境变量**(全部可选,默认值见 `server/config.py`):

| 变量 | 默认 | 说明 |
|---|---|---|
| `TTV_ROOT` | 仓库根 | 部署目录(不改代码换路径) |
| `TTV_PORT` | `8015` | 后端端口 |
| `TTV_PYTHON` | `<根>/.venv/bin/python` | 后端解释器 |
| `TTV_NODE_BIN` | 自动探测 | Node 不在 PATH 时指向其 bin 目录 |
| `TTV_TTS_URL` | `http://127.0.0.1:8016` | TTS 池入口 |
| `TTV_TTS_GPUS` / `TTV_TTS_PORTS` | `0` / `8016` | 多卡多实例,如 `"1 2 3"` / `"8016 8018 8019"` |
| `TTV_TTS_VENV` / `TTV_COSYVOICE_SRC` | `<根>/tts-venv` / `<根>/cosyvoice-src` | 配音环境与源码 |
| `TTV_MODELS_DIR` / `TTV_COSYVOICE_DIR` | `<根>/models` / `<根>/models/CosyVoice3-0.5B` | 权重位置 |
| `TTV_AVATAR` | `0` | `1` = 全局默认开启数字人出镜(也可按任务选角落) |
| `TTV_AVATAR_ADDR` / `TTV_AVATAR_IMAGE` / `TTV_AVATAR_SIZE` | `127.0.0.1:50051` / `assets/avatars/jinli.png` / `320` | 数字人服务、形象、边长 |
| `TTV_CYBERVERSE_DIR` | `<根>/CyberVerse-main` | 数字人服务目录 |
| `TTV_SKIP_NGINX` | `0` | `1` = 跳过 nginx 配置(没装 nginx 自动跳过) |
| `TTV_TTS_ALLOW_UNPINNED` | `0` | `1` = 跳过 transformers 钉版校验(**仅排障用**) |

**端口一览**:8015 后端 · 8016/8018/8019 CosyVoice3 实例池 · 8017 Qwen3-TTS 备用(默认停) · 4150–4153 每任务 Studio 编辑器 · 50051 数字人 gRPC ·(CyberVerse 自带的 8080/5173/8443 只在用它的网页版时才需要)。

**nginx(可选)**:`deploy/setup.sh` 会把 `deploy/nginx-ttv.conf` 装到 `/etc/nginx/ttv-locations.conf` 并 include 进站点;不装 nginx 时直接访问 `http://<host>:8015/` 即可(前端静态页由后端挂载)。

### 1.5 启动

```bash
# 0)(推荐)后端独立 venv;不建也行(setup.sh 会回退系统 python3)
python3 -m venv .venv && .venv/bin/pip install -r server/requirements.txt

# 1) 一次性准备(依赖 + 字体 + BGM + gsap + hyperframes + Chrome [+ nginx])
bash deploy/setup.sh

# 一键启动全部(数字人 + 配音 + 后端)
bash deploy/start-all.sh
bash deploy/start-all.sh --no-avatar      # 只做纯 PPT 视频时,跳过数字人(省 3-6 分钟预热)

# 或分步启动
bash deploy/start-avatar.sh   # 数字人 gRPC 50051(首次 3-6 分钟:加载权重 + torch.compile)
bash deploy/start-tts.sh      # CosyVoice3 8016(多实例见 TTV_TTS_GPUS/PORTS)
bash deploy/start.sh          # 后端 8015
bash deploy/start-tts-qwen.sh # 备用引擎 Qwen3-TTS 8017(默认不启)
```

启动后自检:

```bash
curl -s http://127.0.0.1:8015/health          # 后端
curl -s http://127.0.0.1:8016/health          # 配音(回报钉版版本)
.venv/bin/python server/smoke_test.py         # 冒烟回归(必须用 .venv 的解释器,系统 python3 缺 httpx)
```

停止:`pkill -f "uvicorn main:app"`(后端)、`pkill -f "tts_serve[r]"`(配音)、`bash cyberverse.sh stop`(数字人网页版);`deploy/*.sh` 重复执行会自动先杀旧进程。

## 二、使用流程

1. **上传文章**(txt / md / docx ≤20MB)或**粘贴文字**(≥50 字)
2. **选择风格**:快速套用三套经典预设,或按 **字体 × 配色 × 背景 × 动效** 四个维度自由组合(每个维度多种选项)
3. **选择视频类型与时长**(同一滑杆,切换类型自动换档):
   - **宣传视频**:提炼主旨、归档宣传的政论片,30 秒 - 10 分钟
   - **讲解视频**:老师逐段精讲的授课片,5 - 30 分钟(每 5 分钟一档)
4. **开始分析**:调用 DeepSeek 网关。宣传视频**两阶段分析**——阶段一诊断核心论点/论证链节拍/数据清单(逐字核验)/金句清单(逐字)/帧计划,阶段二按帧计划生成逐帧脚本;讲解视频**两步分析**——先诊断文章类型与讲解方案(备课),再按章节**并行**分段生成逐帧脚本(耗时更长,页面显示阶段进度)
5. **数字人播报视频(可选,分析完成后就能点)**:页面「数字人播报视频」区块一键生成——把逐帧数字人画面按时间轴拼成一条独立视频(**大小可选,默认 300×300**,含完整配音音轨),**不需要先构建、也不需要等成片渲染**。区块按「合成配音 → 生成数字人片段 → 拼接播报视频」三步展示进度、已用时间与预计剩余,完成后就地独立播放与下载
   - **数字人大小**在区块内直接输入数字(默认 300×300;也可从 240/300/400/464/640 里挑,`464` 是数字人服务原生上限,再大只是放大、清晰度不再增加),尺寸按任务记住,重开页面仍是上次那一档;不同尺寸的片段各自缓存,来回切换不重复烧 GPU
   - **数字人出镜**(成片里叠加的那个人像)在创作页是一个下拉:**不出镜 / 左上 / 右上(默认)/ 右下 / 左下**;选角落即出镜,大小手输(默认 300×300)。分析完成后还能在预览页「视频预览」上方随时改 —— **包括切成「不出镜」**(成片随即回到纯 PPT 版,不必重新提交文章、重新分析);改完重新「构建预览」「渲染成片」即生效
   - 数字人念的就是 PPT 的台词(同一份 `frames[].voiceover` 是唯一来源),所以它与「构建预览」**谁先谁后都行**:谁先跑谁合成配音,另一方直接复用,**两条轨道始终是同一版声音**(脚本改动后自动重新合成;需要重掷配音时用 `POST /api/jobs/{id}/build?force_voice=1`)
   - 最省时的路径是「分析 → 构建预览 → 播报视频 → 下载」:此时配音与片段都已就绪,播报视频通常几秒出片
6. **构建预览**:本地 CosyVoice3 **多实例并行合成**配音(自然语速)+ 旁白量不足目标时自动二次拓展内容 + 组装 HyperFrames 项目;预览就绪时 **Studio 编辑器已同步启动**,页面直接进入完整编辑器(时间线、逐帧编辑、实时预览)。**配音默认复用**(同一份脚本+音色+引擎只合成一次),重复构建不再重跑 TTS
7. **渲染成片**:1080p 高清渲染(约 5-20 分钟,视时长;30 分钟讲解片渲染更久),完成后同位置切换为成片播放,在线观看并下载(按钮显示格式 + 文件大小)

**时长靠内容充实度填**(每帧 2-4 句旁白、画面元素填满上限、自然语速 1.0):长文短时自动压缩、短文长时逐层展开。

## 三、视频类型

### 宣传视频(默认)
提炼主旨、归档宣传:把文章改写为庄重的政论宣传片——开场钩子 → 核心论点 → 是什么-为什么-怎么办 → 结尾收束署名。

### 讲解视频
**老师逐段精讲**,像讲作文一样拆解文章(可参考申论讲解视频/政治类文章解读视频),不是把文章念一遍,更不是主旨提炼:

- **两步分析**:① 诊断文章类型(策论文/政论文/综合分析/时政评论等)并设计讲解方案——章节安排、逐段讲解要点(段意/作用/写法/可迁移点)、值得逐句批注的原句、可迁移写法、语言表达分析、答题方法总结;② 按章节分段生成逐帧脚本后合并
- **授课式旁白**:老师口吻(「我们来看」「注意这一句」),先点出这段在干什么、为什么这么写,再带学生看关键句;明确区分「文章认为……」与「目前已知事实是……」
- **讲解专用画面**:
  - 原文段页(textblock):讲义式展示原文段落 + 本段作用标签
  - 逐句批注页(annotation):原句逐字展示 + 论点/论据/分析/对策/过渡/金句 彩色标注 + 老师批注
  - 写法提炼页(method):把这段写法抽象成可迁移的板书卡片
  - 复用宣传视频的 statement/points/process(文章框架图)/contrast(原文观点 vs 已知事实)/quote(金句赏析)/data 等帧型
- **原文引用逐字校验**:textblock/annotation 引用的原句必须逐字摘自原文(允许截断),校验门硬拦截改写与编造
- 时长 5-30 分钟,每 5 分钟一档;渲染复用同一套四维风格系统

## 四、风格系统(四维度)

| 维度 | 选项 |
|---|---|
| 字体 | 宋体标题+黑体正文(庄重)/ 全宋体(学术)/ 全黑体(现代) |
| 配色 | 中国红(政论)/ 黛青墨韵(学术)/ 科技蓝(前沿)/ 藏蓝赭红(编辑部) |
| 背景 | 地球环经纬网格 / 水墨远山竹枝 / 科技网格折线 / 极简留白 |
| 动效 | 庄重缓叙(crossfade 0.7s)/ 明快节奏(支持上推)/ 极简静止 |

预设 = 经典组合:庄重肃穆·中国红 / 清雅学术·墨黛青 / 现代锐意·科技蓝。详细样式脚本见 `styles/` 目录。

## 五、技术栈与目录

- 前端:`web/index.html` 单文件 SPA(上传配置页 + 预览二级页;字体 woff2 子集化 + `unicode-range` 回退系统字体)
- 后端:FastAPI `server/`(任务状态机 `jobs/`、分析 `analyze.py`、配音 `tts.py`、数字人 `avatar.py`、构建器 `builder/`)
- 渲染:hyperframes CLI + chrome-headless-shell(1080p;渲染全局并发 ≤2)
- 任务目录:`jobs/<job_id>/`(原文 → `script.json` → `project/` → `renders/`)
- 日志:`logs/backend.log`、`logs/tts/*.log`、`logs/studio/<job_id>.log`
- 详细结构、状态机与接口清单见 **`ARCHITECTURE.md`**;服务器搭建全过程与踩坑见 **`BUILD.md`**

## 六、运维

```bash
# 重启后端(任务自动恢复,preview 任务自动重建 Studio)
bash deploy/start.sh
# 重启配音服务
bash deploy/start-tts.sh
# 看日志
tail -f logs/backend.log
tail -f logs/tts/tts-8016.log
tail -f logs/studio/<job_id>.log     # 每任务的 Studio(hyperframes preview)输出
```

BGM:把授权曲目放入 `assets/bgm/`(solemn-red.mp3 / academic-ink.mp3 / modern-blue.mp3),缺文件时自动静音占位。

## 七、已知限制

- 短文超长视频有内容天花板:模型单轮扩写约 800 字旁白(≈3 分钟语音),超长时长以「两轮拓展+论证展开+变换表述重述」尽力逼近(实测 300s 目标可达 ~258s),实际时长以真实配音为准
- 讲解视频分析为两步多次 LLM 调用(30 分钟档约 6-8 次),耗时 5-15 分钟属正常;渲染 30 分钟成片耗时更久(超时上限已放宽到 3 小时)
- 讲解视频合并后的整体校验失败时仅警告放行(段落级校验已兜底,属罕见情况;重点段缺帧会打印告警)
- Studio 编辑器经反向代理接入,核心编辑/预览功能可用
- 词级字幕为「帧内按字数均分」估算,如需精确对齐可后续接 whisper
- 预览音频依赖浏览器自动播放策略:Studio 预览点击播放出声,已注入音频看门狗自动恢复被策略拦截的死状态;成片音频不受影响
- **本地 CosyVoice3 必须钉住 `transformers==4.51.3` / `tokenizers==0.21.4`**(2026-09-12 定位):详见 §1.3 ②;已在 `config.PINNED_TTS_DEPS` 钉版、`tts_server` 启动时硬校验(不符即拒启)、`smoke_test` 校验 tts-venv 环境
- TTS 依赖位于独立 `tts-venv`,升级该 venv 里任何包前请先跑 `.venv/bin/python server/smoke_test.py`
- 播报视频是「人像轨道」(与成片里那个人像同源,默认 300×300,大小可在区块内手输),不含 PPT 画面;要带画面的版本请用「渲染成片」
- 成片里那个数字人默认叠在**右上角**(四个角落可选,也可以直接选**不出镜**),大小默认 300×300;换大小/换角落/切不出镜后要重新构建预览再渲染才生效(旧尺寸的片段仍留在缓存里,换回来很快)

## 八、版本

- **v2.5**(2026-09-12):数字人出镜可选可关 —— 「数字人出镜」是一个下拉:**不出镜 / 左上 / 右上(默认)/ 右下 / 左下**,大小**默认 300×300、可手输**(160–1080 偶数,接口校验);创作页建任务时设置,预览页随时可改(`POST /api/jobs/{id}/avatar/geom`,可只改一项),**切「不出镜」后重新渲染即成纯 PPT 版**;「数字人播报视频」的大小也改成手输(默认跟随任务的数字人大小),按任务记住、不同尺寸片段各自缓存,预计耗时随所选尺寸缩放
- **v2.3**(2026-09-12):修复配音乱码根因 —— tts-venv 运行时钉版(`transformers==4.51.3` / `tokenizers==0.21.4`)+ 服务启动硬校验 + 冒烟环境校验(4.52+ 会让语音 LLM 输出乱码,而时长/峰值全正常)
- **v2.2**(2026-09-12):数字人播报视频(分析完成即可单独生成 320×320 人像片,三步进度 + 预计剩余 + 独立预览/下载;配音复用、失败无害、独立 artifact)
- **v2.0**(2026-08-28):宣传两阶段分析、CosyVoice3 三实例并行合成、讲解分段并行生成、并发限流与 httpx 连接池、前端字体子集化与轮询优化(详见 `CHANGELOG.md`)
- **v1.1**(2026-08-27):新增讲解视频(两步分析+三种讲解帧+原文逐字校验,5-30 分钟每 5 分钟一档,与宣传视频共用滑杆与风格系统)
- **v1.0**(2026-08-27):四维度风格系统、时长自适应分析(内容驱动)、CosyVoice3 本地配音、Studio 编辑器为唯一预览入口(构建期同步启动零等待)、预览音频看门狗、健壮性加固(脚本修改守卫/渲染后资源回收/docx 防护/陈旧产物清理)、冒烟回归测试
- 详见 `ARCHITECTURE.md`、`BUILD.md` 与 `CHANGELOG.md`
