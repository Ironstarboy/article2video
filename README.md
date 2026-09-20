<!-- prettier-ignore -->
<div align="center">

<img src="assets/logo.svg" alt="" width="80" />

# 理论文章转视频(Theory-to-Video)

*把一篇理论长文,自动变成一条庄重的政论视频 —— PPT 式成片 + 数字人播报视频*

[![Python](https://img.shields.io/badge/Python-%3E%3D3.10-3776AB?style=flat-square&logo=python&logoColor=fff)](https://www.python.org)
[![Node.js](https://img.shields.io/badge/Node.js-22-3c873a?style=flat-square&logo=node.js&logoColor=fff)](https://nodejs.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=fff)](https://fastapi.tiangolo.com)
[![CUDA](https://img.shields.io/badge/CUDA-12.8-76B900?style=flat-square&logo=nvidia&logoColor=fff)](https://developer.nvidia.com/cuda-toolkit)
![Platform](https://img.shields.io/badge/Platform-Linux%20%2B%20NVIDIA%20GPU-333?style=flat-square&logo=linux&logoColor=fff)

[效果展示](#效果展示) • [工作原理](#工作原理) • [快速开始](#快速开始) • [环境要求](#环境要求) • [从零部署](#从零部署) • [启动与自检](#6-启动与自检) • [配置](#配置) • [已知限制](#已知限制) • [相关文档](#相关文档)

</div>

上传一篇人民日报「人民要论」、马院论文这类理论长文,选好风格与时长,系统用大模型生成逐帧解说脚本、本地配音、浏览器渲染,产出一条 1080p 的 PPT 式政论视频;需要时还能叠一个数字人出镜播报。**前端、后端、配音、渲染全部跑在本机**,只有文本分析走 OpenAI 兼容网关。

| 入口 | 地址 |
|---|---|
| 本机默认 | `http://localhost:8015/`(接口文档 `/docs`) |
| nginx 子路径(可选) | `http://<host>:<port>/ttv/`(见[部署到生产](#部署到生产nginx)) |

## 效果展示

同一套流水线,换一张脸就是另一个数字人:

<p align="center">
  <img src="assets/screenshots/avatar-jinli.png" alt="数字人「金立」出镜的 PPT 成片截图" width="100%" />
  <br /><em>内置形象「金立」出镜</em>
</p>

<p align="center">
  <img src="assets/screenshots/avatar-wei-dongyi.png" alt="数字人「韦东奕」出镜的 PPT 成片截图" width="100%" />
  <br /><em>上传形象「韦东奕」出镜 —— 在「数字人形象」页上传并设为默认,重新构建即换人</em>
</p>

## 工作原理

```text
文章(txt / md / docx ≤20MB,或粘贴文字)
  └─ 分析(DeepSeek 兼容网关)
       ├─ 宣传视频:两阶段 —— 论证诊断(论点/论证链/数据/金句/帧计划)→ 按帧计划生成脚本
       └─ 讲解视频:两步 —— 备课方案(章节/逐段要点/待批注句)→ 按章节分段并行生成脚本
  └─ 构建(CosyVoice3 多实例并行配音 → 二次拓展内容 → 组装 HyperFrames 工程 → 同步拉起 Studio 编辑器)
       └─ 渲染成片:1080p PPT 视频 [→ 数字人片段按时间轴叠加到指定角落(可选抠像)]
  └─ 数字人播报视频(支线,不经过 HyperFrames):逐帧片段顺序拼接 + 合流音轨
```

任务是磁盘持久化的状态机:`uploaded → analyzing → analyzed → building → preview → rendering → rendered`;一键出片走同一套状态(不经过 `preview`),播报视频走支线状态 `avatar_building`,**失败不阻塞出片**。完整架构、状态机、接口清单与设计决策见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。

## 功能特性

- **两种视频类型** —— *宣传视频*提炼主旨、归档宣传(30 秒 - 10 分钟);*讲解视频*逐段精讲、拆解写法(5 - 30 分钟)。
- **一条台词驱动全部轨道** —— 每帧的 `voiceover` 既是配音文本、也是底部字幕、还是数字人念的内容。
- **四维度风格系统** —— 字体 × 配色 × 背景 × 动效自由组合,另有三套经典预设。
- **本地配音,零调用成本** —— CosyVoice3 多实例(`TTV_TTS_GPUS` 多卡并行)零样本克隆三种音色,配音按指纹复用。
- **数字人出镜(可选)** —— 四角任选、大小可调,可叠**纯 PPT 版**;默认「只保留人像」—— 每段片段旁生成一条灰度遮罩(MODNet ONNX,Apache-2.0,25MB),叠加时 `alphamerge` 合成;抠像不可用时逐条回退圆角卡片,成片照出。
- **数字人形象库** —— 网页上传/管理多张形象(≤20MB,同图去重),设为默认即换脸:不改代码、不重启,只影响后续构建。
- **网页「设置」页** —— 分析服务地址/密钥、成片另存位置都在页面上改,保存即生效;密钥只回显掩码,落盘 `0600`。
- **质量门 + 「永不失败」管线** —— 引文逐字接地校验、段级确定性修复、脚本疑似问题兜底放行;并发上限(LLM 6 / 渲染 2 / 进行中任务 >4 返回 429)、任务重启恢复、冒烟回归覆盖纯函数与接口契约。

## 快速开始

**已经装好环境的机器**(裸机请先走[从零部署](#从零部署)):

```bash
bash deploy/start-all.sh      # 一键起全栈:后端与网页 8015 · 配音 8016 · 数字人 50051
```

打开 `http://localhost:8015/` → 「＋ 新建视频」→ 上传文章、选风格与时长 → 点「一键出片」。

`start-all.sh` 可以**反复执行**:已在跑的服务自动跳过,只补缺的那个,不打断进行中的任务。其余子命令(`status` / `logs` / `restart` / `stop` / `--no-avatar` / `--no-wait`)见[启动与自检](#6-启动与自检)。

## 环境要求

| 项 | 要求 | 实测组合 |
|---|---|---|
| 系统 | Linux x86_64(Ubuntu 22.04) | Ubuntu 22.04 |
| GPU | NVIDIA,显存 ≥16GB(配音/数字人需要);**新卡要注意算力代次** | RTX 5090 32GB(sm_120) |
| 驱动 / CUDA | 需支持 CUDA 12.8 的 NVIDIA 驱动 | 595.58.03 / CUDA 12.8 |
| Node.js | 22(`hyperframes` CLI 用) | v22.20.0 |
| Python | 主站 3.10+;**配音 venv 按实测用 3.10** | 3.10.12(配音/数字人)/ 3.12.14(主站 venv) |
| 其它 | `ffmpeg` / `ffprobe`、`curl`、`git`、`npm` | ffmpeg 4.4.2 |
| 磁盘 | 仅 PPT 主线 ≥30GB;含数字人 ≥100GB | 实测占用 51GB(其中权重 24.6GB) |
| 网络 | 可访问 DeepSeek 兼容网关、PyPI/npm、ModelScope(或 hf-mirror) | — |

> [!IMPORTANT]
> **torch 必须是 CUDA 12.8 轮子(`2.8.0+cu128`)**。RTX 5090 是 `sm_120`(Blackwell):实测该轮子里**编进了 `sm_120` 内核**(`torch.cuda.get_arch_list()` = `sm_70/75/80/86/90/100/120`);换成 cu121 这类老轮子没有对应内核,典型症状是 `no kernel image is available for execution on the device`(或 cuDNN/cuBLAS 直接起不来)。配音 venv 里这一条最容易漏 —— 它不随依赖树自动进来,必须显式装(见[第 4 步](#4-本地配音cosyvoice3))。

## 从零部署

下面命令按顺序执行即可;`$ROOT` 指仓库根目录(脚本全部按自身位置推导,不写死路径,换机器不用改)。

> [!TIP]
> **国内网络先换源**,否则第 2-5 步会大量卡在下载上(实测数据见 [`docs/cyberverse/DEPLOY-GPU.md`](docs/cyberverse/DEPLOY-GPU.md) 第 9 节):
> - **pip / uv** 换清华源:`export UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple`,或写进 `~/.config/pip/pip.conf`。`pypi.org` 与 `files.pythonhosted.org` 常直接不通。
> - **不要**用 `download.pytorch.org` 装 torch(常见 **403**);清华 PyPI 上的 `torch==2.8.0` 本身就是 `+cu128` 构建(依赖钉死 `nvidia-*-cu12==12.8.*`),已验证 `torch.__version__` 即 `2.8.0+cu128`。
> - **GitHub raw / release / clone** 走代理 `https://gh-proxy.com/<原始URL>`(实测 2MB/s;直连约 35KB/s)。备选 `gitclone.com`,但它**不传子模块**,见第 4.2 步。
> - **chrome-headless-shell** 走 npmmirror:`https://cdn.npmmirror.com/binaries/chrome-for-testing/<版本>/linux64/chrome-headless-shell-linux64.zip`(4.6MB/s;Google 存储约 17KB/s)。
> - **权重**优先 ModelScope CLI(HuggingFace 直连不通,备选 `HF_ENDPOINT=https://hf-mirror.com`)。

### 1. 系统依赖

```bash
sudo apt-get update
sudo apt-get install -y ffmpeg curl git python3-venv python3-pip
# 可选:要走 nginx 子路径再装;不装也能用 http://<host>:8015/
sudo apt-get install -y nginx
```

数字人那条线还需要 `libopus-dev libopusfile-dev libsoxr-dev pkg-config python3.10-dev`、Go 1.25 与 protoc 29.3,见[第 5 步](#5-数字人可选)。

### 2. Node 22 + hyperframes + 无头 Chrome

```bash
# 任选一种装 Node 22:NodeSource / nvm / 官方 tarball
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt-get install -y nodejs
node --version                     # v22.x

# npm 11.19+ 默认禁止依赖跑安装脚本;而 onnxruntime-node 的 postinstall 会去
# GitHub releases 拉 CUDA 包(国内常 ECONNRESET)。跳过它,基础二进制已在包里。
sudo ONNXRUNTIME_NODE_INSTALL_CUDA=skip npm install -g hyperframes@0.8.34
# 上面那条的副作用:bin 落成 644,不补可执行位会报 Permission denied
sudo chmod +x "$(npm prefix -g)"/lib/node_modules/hyperframes/bin/*.mjs

hyperframes browser ensure         # 下载 chrome-headless-shell(落在 ~/.cache/hyperframes)
# 若下载极慢:改用 npmmirror 预放 zip 再重跑 ensure(见上面的「国内网络先换源」)
hyperframes doctor                 # Node / FFmpeg / Chrome 三项应全绿
```

> [!IMPORTANT]
> **无头 Chrome 需要一套系统库**,漏装会报 `libatk-1.0.so.0: cannot open shared object file`
> (此时 `hyperframes doctor` 仍可能显示 Chrome ✓,因为它只查文件存不存在):
> ```bash
> sudo apt-get install -y libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 \
>   libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2 libpango-1.0-0 \
>   libcairo2 libatspi2.0-0 libxshmfence1 fonts-liberation
> ```

> [!NOTE]
> Node 不在 PATH 时(官方 tarball / nvm 安装),导出 `TTV_NODE_BIN=<node 所在 bin 目录>`;后端会把它前置到 PATH 再调用 hyperframes。
> `deploy/setup.sh` 会用同一个版本再装一次(可用 `TTV_HYPERFRAMES_VERSION` 覆盖),两者不会打架;hyperframes 自带自动升级,升级因网络超时失败不影响出片。
> **注意 `setup.sh` 里那次 `npm install` 不带上述 `ONNXRUNTIME_NODE_INSTALL_CUDA=skip`**,在受限网络下会失败;先手动按本节装好,或给 `npm` 配上 `allow-scripts` 与跳过 CUDA 包下载后再跑 `setup.sh`。

### 3. 主站(后端 + 网页)

```bash
git clone git@github.com:Ironstarboy/article2video.git   # 私有库:需 SSH key,或改用 HTTPS + token
cd article2video

# 主站 venv:实测 Python 3.12.14;3.10+ 均可(Ubuntu 22.04 的 python3 就是 3.10)
python3 -m venv .venv
.venv/bin/pip install -r server/requirements.txt

# 一次性资产准备:完整版 OTF 字体(校验 ≥10MB)、前端 UI 字体子集、CC0 占位 BGM、
# GSAP、hyperframes + Chrome、抠像权重 MODNet 25MB [+ 可选安装 nginx 路由]
bash deploy/setup.sh
```

`setup.sh` 还会尽力往 `tts-venv` 里装 `onnxruntime`(抠像 worker 需要)。UI 字体子集若要单独重跑:`.venv/bin/python deploy/make-ui-font.py`。

> [!IMPORTANT]
> `setup.sh` 从 **GitHub raw** 下 4 个 OTF 字体,国内直连会长时间挂住。**建议先预放好** `assets/fonts/`
> 四个文件(每个 ≥10MB;子集版会把生僻字渲染成方框,脚本会校验并报错),`setup.sh` 见到非空文件就跳过下载:
> ```bash
> P="https://gh-proxy.com/https://raw.githubusercontent.com"
> curl -fL -o assets/fonts/SourceHanSerifCN-Heavy.otf   "$P/adobe-fonts/source-han-serif/release/OTF/SimplifiedChinese/SourceHanSerifSC-Heavy.otf"
> curl -fL -o assets/fonts/SourceHanSerifCN-Regular.otf "$P/adobe-fonts/source-han-serif/release/OTF/SimplifiedChinese/SourceHanSerifSC-Regular.otf"
> curl -fL -o assets/fonts/NotoSansSC-Regular.otf       "$P/notofonts/noto-cjk/main/Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf"
> curl -fL -o assets/fonts/NotoSansSC-Bold.otf          "$P/notofonts/noto-cjk/main/Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Bold.otf"
> ```

> [!WARNING]
> `setup.sh` 里的 BGM 源(`freepd.com/music/...`)**三个 URL 均已失效(404)**,脚本会退化成 60 秒**静音占位**,不影响出片。
> 想要配乐请自备授权曲目,按风格覆盖同名文件:`assets/bgm/{solemn-red,academic-ink,modern-blue}.mp3`。
> 另外该兜底逻辑在 `assets/bgm/` 为空时会生成一个名为 `*.mp3` 的无用文件(glob 未匹配),删掉即可。

### 4. 本地配音(CosyVoice3)

```bash
# 4.1 权重(ModelScope;HuggingFace 直连在部分网络下不通)
.venv/bin/pip install modelscope      # 仅用于下载权重,也可用别的解释器
.venv/bin/python -c "from modelscope import snapshot_download; snapshot_download('FunAudioLLM/Fun-CosyVoice3-0.5B-2512', local_dir='models/CosyVoice3-0.5B')"

# 4.2 源码(需 Matcha-TTS 子模块)
git clone --depth 1 https://github.com/FunAudioLLM/CosyVoice.git cosyvoice-src
(cd cosyvoice-src && git submodule update --init)
# 注意:有些代理/镜像(如 gitclone.com)不传子模块,third_party/Matcha-TTS 会是空目录,
# 表现为 ModuleNotFoundError: No module named 'matcha'。此时手动补(commit 与上游钉的一致):
#   rm -rf cosyvoice-src/third_party/Matcha-TTS
#   git clone https://gh-proxy.com/https://github.com/shivammehta25/Matcha-TTS.git cosyvoice-src/third_party/Matcha-TTS
#   git -C cosyvoice-src/third_party/Matcha-TTS checkout dd9105b34bf2be2230f4aa1e4769fb586a3c824e

# 4.3 运行时(系统 python3.10;--system-site-packages 只为复用系统基础包)
#     Ubuntu 24.04 默认没有 python3.10,需自行装(deadsnakes)或改用与实测一致的镜像
python3.10 -m venv --system-site-packages tts-venv

# 先钉死会被依赖树带坏的包(见下方 WARNING),后续每次装包都带 -c
cat > tts-constraints.txt <<'EOF'
transformers==4.51.3
tokenizers==0.21.4
huggingface-hub==0.36.2
diffusers==0.29.0
EOF

# torch:用清华 PyPI 即可(pypi.org 常不通、download.pytorch.org 常 403);
# 清华上的 torch==2.8.0 就是 +cu128 构建,装完 torch.__version__ 应为 2.8.0+cu128
tts-venv/bin/pip install torch==2.8.0 torchaudio==2.8.0 torchvision==0.23.0 \
  --index-url https://pypi.tuna.tsinghua.edu.cn/simple
tts-venv/bin/pip install -c tts-constraints.txt modelscope wetext sentencepiece hydra-core HyperPyYAML \
  omegaconf librosa soundfile inflect pyworld conformer gdown wget lightning openai-whisper
tts-venv/bin/pip install -c tts-constraints.txt onnxruntime
tts-venv/bin/pip install -c tts-constraints.txt "transformers==4.51.3" "tokenizers==0.21.4"
# 上面清单之外,tts_server.py 还实际需要这几个(清单里漏了,漏装会启动即报错):
tts-venv/bin/pip install -c tts-constraints.txt fastapi uvicorn pydantic rich pyarrow \
  diffusers==0.29.0 onnx matplotlib x-transformers
```

> [!WARNING]
> **不要**按 `cosyvoice-src/requirements.txt` 装依赖——那是**上游旧版**(torch 2.3.1),会覆盖掉刚装好的 cu128 栈。本仓库只采用本节这套钉版。
> **另一个大坑**:装 `diffusers` 的最新版会把 `huggingface-hub` 升到 1.x,直接搞坏 `transformers==4.51.3`(报 `huggingface-hub>=0.30.0,<1.0 is required`)。而 CosyVoice 经 matcha 用到 `diffusers.models.lora.LoRACompatibleLinear`,该符号在新版 diffusers 已删,所以必须钉 `diffusers==0.29.0`。**任何往 `tts-venv` 装包的操作都要带 `-c tts-constraints.txt`。**

> [!WARNING]
> `transformers==4.51.3` / `tokenizers==0.21.4` **不能改**。语音 LLM 跑在 Qwen2 backbone 上,4.52+ 会让 speech token 序列乱掉:听感是「读音完全不正常、断断续续」,而**时长与峰值全正常**(时长/静音验收拦不住)。`tts_server` 启动时会硬校验版本,不符即拒启(`TTV_TTS_ALLOW_UNPINNED=1` 仅排障用)。
> 配音 venv 是 `--system-site-packages` 建的,不显式安装就会继承系统里更新的 transformers —— 这一条最容易被漏掉。

**三个零样本种子音色上游不提供**(ModelScope 权重里没有 `asset-v2/`,官方 CosyVoice 仓库只有 `asset/zero_shot_prompt.wav`),而 `tts_server.py` 启动和预热都要读它们。全新机器有两个选择:

**(a) 从已有环境拷贝**(约 1MB,最省事):
```bash
models/CosyVoice3-0.5B/asset-v2/{male,female,male_narrator}.wav
```

**(b) 没有现成的就自己造**——把官方 `zero_shot_prompt.wav` 当音色参考,逐句合成 `tts_server.py` 里 `VOICES` 声明的那三段文本,这样种子音频的逐字内容与其 `prompt_text` 严格一致,**不需要改任何代码**:
```bash
cat > /tmp/make-seed-voices.py <<'PY'
import os, sys, torch, soundfile as sf, torchaudio
ROOT = os.getcwd()
sys.path[:0] = [f"{ROOT}/cosyvoice-src", f"{ROOT}/cosyvoice-src/third_party/Matcha-TTS"]
def _load(p, **k):
    d, sr = sf.read(str(p), dtype="float32", always_2d=True); return torch.from_numpy(d.T), sr
def _save(p, t, sr, **k):
    d = t.detach().cpu().numpy(); sf.write(str(p), d.T if d.ndim == 2 else d, sr)
torchaudio.load, torchaudio.save = _load, _save          # 与 tts_server.py 相同的 shim
from cosyvoice.cli.cosyvoice import AutoModel
MD = f"{ROOT}/models/CosyVoice3-0.5B"; OUT = f"{MD}/asset-v2"; os.makedirs(OUT, exist_ok=True)
REF = f"{ROOT}/cosyvoice-src/asset/zero_shot_prompt.wav"   # 逐字文本见下
SYS = "You are a helpful assistant.<|endofprompt|>"
SEEDS = {  # 文件名 → <|endofprompt|> 之后的逐字文本(与 tts_server.py 的 VOICES 一一对应)
 "male.wav": "各位观众大家好,欢迎收看今天的节目。当前我国经济社会发展稳中有进,高质量发展扎实推进,各项事业取得新的重大成就。",
 "female.wav": "大家好,欢迎来到今天的节目。理论创新每前进一步,理论武装就要跟进一步。让我们共同思考,共同学习。",
 "male_narrator.wav": "新时代赋予新使命,新征程呼唤新作为。让我们坚定信心、真抓实干,在新赛道上跑出加速度。",
}
m = AutoModel(model_dir=MD, fp16=True); sr = int(getattr(m, "sample_rate", 24000))
for name, text in SEEDS.items():
    for r in m.inference_zero_shot(text, SYS + "希望你以后能够做的比我还好呦。", REF, stream=False):
        w = r["tts_speech"].squeeze(0).detach().cpu().numpy()
        sf.write(f"{OUT}/{name}", w, sr); print(f"{name}: {len(w)/sr:.2f}s peak={abs(w).max():.3f}"); break
PY
# 必须在**仓库根目录**执行(脚本用 os.getcwd() 当 $ROOT),且要用 tts-venv 解释器
cd "$ROOT" && tts-venv/bin/python /tmp/make-seed-voices.py
```
实测产物:`male.wav` 10.36s / `female.wav` 10.16s / `male_narrator.wav` 9.60s(24kHz 单声道),时长与峰值正常。
> 代价:三个音色共用同一个参考音色,**听感相同**。要三个不同声音需自备三段参考音频重跑。

> [!TIP]
> 权重目录里 `llm.rl.pt`、`speech_tokenizer_v3.batch.onnx`、`flow.decoder.estimator.fp32.onnx` 共约 **4.1GB 运行时用不到**(分别是备用 LLM、vLLM 在线路径、TRT 路径),新机器可以不下,省 4GB 下载。

### 5. 数字人(可选)

只有勾选「数字人出镜」的任务需要。整条线是独立第三方项目(**CyberVerse** + **SoulX-FlashHead-1_3B** 权重 15.4GB),完整步骤、离线 wheel 方案与踩坑速查见 [`docs/cyberverse/DEPLOY-GPU.md`](docs/cyberverse/DEPLOY-GPU.md),摘要:

0. **先拿到源码**:CyberVerse **不在本仓库内**,上游是 <https://github.com/Lynpoint/CyberVerse>(公开)。落到 `<仓库根>/CyberVerse-main/`:
   ```bash
   git clone https://gh-proxy.com/https://github.com/Lynpoint/CyberVerse.git CyberVerse-main   # 国内走代理
   ```
   `deploy/start-avatar.sh` 与 `deploy/cyberverse.sh` 都按 `<仓库根>/CyberVerse-main` 找它(可用 `TTV_CYBERVERSE_DIR` 改)。
1. `apt-get install -y libopus-dev libopusfile-dev libsoxr-dev pkg-config python3.10-dev`(缺 `python3.10-dev` 时 `torch.compile` 直接失败);
2. Go 1.25 + protoc 29.3(Go API 与 `generate_proto.sh` 需要;protoc 务必是 `libprotoc 29.3`,`generate_proto.sh` 会硬校验版本);
3. `uv venv .venv --python 3.10`;torch 不在 `pyproject.toml` 的依赖列表里,但会被 `xformers` 等**传递依赖**带进来(仓库的 `uv.lock` 里就有 `torch 2.8.0`)。本机做法是**先单独装 torch**(确保走清华源、避开不通的 `pypi.org`),再 `uv pip install --index-url <清华> -e ".[dev,inference,flash_head]"`;权重放 `CyberVerse-main/checkpoints/`;
4. 音频编码器 `wav2vec2-base-960h` 一并下载,与 FlashHead 权重同在 `checkpoints/` 下。

> [!NOTE]
> CyberVerse 钉 `transformers==4.57.3`,与本仓库 `tts-venv` 的 `4.51.3` **不同**——两者是**独立 venv**,互不影响,升级任一侧时别把另一侧带崩。

不装数字人也能跑完 PPT 主线,启动时加 `--no-avatar` 即可(见下节);数字人只需它的**推理服务(gRPC 50051)**,不需要它自带的 Go API(8080)与前端(5173)。

### 6. 启动与自检

```bash
# 配置分析端点(.secrets/llm.env,deploy/start.sh 会自动加载;也可稍后在网页「设置」页填)
mkdir -p .secrets && cat > .secrets/llm.env <<'EOF'
TTV_DEEPSEEK_URL=http://<网关地址>/v1
TTV_DEEPSEEK_MODEL=DeepSeek-V4-Flash
TTV_DEEPSEEK_KEY=sk-...          # 内网无鉴权网关可省略
EOF

bash deploy/start-all.sh               # 一键起全栈:数字人 50051 + 配音 8016 + 后端与网页 8015
bash deploy/start-all.sh --no-avatar   # 只起后端 + 配音(纯 PPT 视频够用,省掉数字人 3-6 分钟预热)
bash deploy/start-all.sh status        # 端口 / 就绪度 / pid / GPU / 任务数
bash deploy/start-all.sh logs          # 跟踪三份日志(Ctrl+C 只退出查看,不停服务)
bash deploy/start-all.sh restart       # 强制全部重启
bash deploy/start-all.sh stop          # 停全栈(终端下问一次;脚本里加 --yes)
```

`start-all.sh` 的 `start` 是**幂等**的:已在跑的服务直接跳过,只补缺的那个,不会打断进行中的任务;要强制重启用 `restart`。就绪判定是真探活 —— 后端/配音走 `/health`,数字人走 gRPC(端口开了 != 模型就绪)。单服务粒度可用 `deploy/start-avatar.sh` / `start-tts.sh` / `start.sh`(这三个会先 `pkill` 旧进程,后端重启会打断进行中的任务)。

**验收清单**:

```bash
curl -s http://127.0.0.1:8015/health          # 后端
curl -s http://127.0.0.1:8016/health          # 配音(回报钉版版本)
.venv/bin/python server/smoke_test.py         # 后端冒烟回归(须用 .venv 解释器,系统 python3 缺 httpx)
node tests/avatar-page.test.js                # 前端页面逻辑回归(无 npm 依赖,仓库根直接跑)

# GPU 栈自检:应打印 2.8.0+cu128 / 12.8 / (12, 0) / 含 'sm_120' 的 arch 列表
tts-venv/bin/python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.get_device_capability(), torch.cuda.get_arch_list())"
```

两份回归在本机均 **全部通过**;跑通后打开 `http://localhost:8015/`,上传仓库自带的示例文章 `tests/fixtures/test-article.md`、选最短时长出一条约 30 秒的片子,即可确认整条链路(分析 → 配音 → 渲染)。

## 配置

所有环境变量都有默认值(见 `server/config.py`),常用项:

| 变量 | 默认 | 说明 |
|---|---|---|
| `TTV_ROOT` | 仓库根 | 部署目录(不改代码换路径) |
| `TTV_PORT` | `8015` | 后端端口 |
| `TTV_NODE_BIN` | 自动探测 | Node 不在 PATH 时指向其 bin 目录 |
| `TTV_DEEPSEEK_URL` / `_MODEL` / `_KEY` | 内网 vLLM / `DeepSeek-V4-Flash` / 空 | 分析端点出厂默认(通常写 `.secrets/llm.env`);网页「设置」页写过后以网页为准 |
| `TTV_TTS_GPUS` / `TTV_TTS_PORTS` | `0` / `8016` | 多卡多实例,如 `"1 2 3"` / `"8016 8018 8019"` |
| `TTV_TTS_VENV` / `TTV_COSYVOICE_SRC` | `<根>/tts-venv` / `<根>/cosyvoice-src` | 配音环境与源码 |
| `TTV_MODELS_DIR` / `TTV_COSYVOICE_DIR` | `<根>/models` / `<根>/models/CosyVoice3-0.5B` | 权重位置 |
| `TTV_AVATAR` / `_ADDR` / `_IMAGE` / `_SIZE` / `_CORNER` | `0` / `127.0.0.1:50051` / 形象库默认 / `300` / `tr` | 数字人开关、服务地址、形象、边长、默认角落 |
| `TTV_AVATAR_CUTOUT` | `1` | 出厂默认是否抠背景(新任务);形象页改过之后以偏好文件为准 |
| `TTV_MATTE_MODEL` / `_PYTHON` | `<根>/models/matte/modnet.onnx` / `<根>/tts-venv/bin/python` | 抠像权重与跑它的解释器(需 `onnxruntime` + `numpy`) |
| `TTV_CYBERVERSE_DIR` | `<根>/CyberVerse-main` | 数字人服务目录 |
| `TTV_EXPORT_DIR` | 空 | 成片的额外另存位置(网页可改);空 = 不另存 |
| `TTV_VO_CHECK_FRAMES` | `2` | 合成后用 whisper 抽检可懂度(`0` = 关) |
| `TTV_SKIP_NGINX` | `0` | `1` = 跳过 nginx 配置 |

完整清单(含抠像参数、偏好/设置文件路径、钉版校验开关等)见 `server/config.py` 与 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。

**端口一览**:8015 后端 · 8016/8018/8019 CosyVoice3 实例池 · 8017 Qwen3-TTS 备用(默认停) · 4150-4153 每任务 Studio 编辑器 · 50051 数字人 gRPC。
**日志**:`logs/backend.log`、`logs/tts/*.log`、`logs/studio/<job_id>.log`;运行时偏好与设置落在 `.run/`。

## 使用流程

0. 打开站点即为**项目历史页**(按最近更新倒序),点「＋ 新建视频」进入创作页;顶栏另有「数字人形象」与「设置」两个二级页。
1. **上传文章**(txt / md / docx ≤20MB)或**粘贴文字**(≥50 字)。
2. **选风格与视频类型**:三套预设或四维自由组合,宣传/讲解共用时长滑杆。
3. **开始分析**:调用大模型网关;讲解视频多轮调用,5-15 分钟属正常;分析完可就地编辑脚本或让 AI 按意见修订。
4. **一键出片(推荐)**:一个按钮跑完「构建 → 渲染」—— 并行配音、组装工程、1080p 渲染(约 5-20 分钟),不拉 Studio、不停在预览态;想先调时间线就改用「构建预览 → 渲染成片」两步。
5. **数字人(可选)**:预览页可改出镜开关 / 角落 / 大小 / 是否抠像,改完需重新构建 + 重新渲染;分析完成后也可单独生成一条**播报视频**。
6. **随时回来**:每一步的结果与失败都记进项目历史,从入口页点某一步即回到对应结果。

逐功能操作手册、BGM 替换、运维与常见问题见 [`docs/使用说明.md`](docs/使用说明.md)。

## 部署到生产(nginx)

`deploy/setup.sh` 会把 [`deploy/nginx-ttv.conf`](deploy/nginx-ttv.conf) 装成 `/etc/nginx/ttv-locations.conf` 并 include 进已有站点:

- `/ttv/` → 前端静态(`web/index.html`,`no-cache`)
- `/ttv/assets/` → 字体/BGM/vendor 等静态资产(immutable 长缓存)
- `/ttv/api/` → `127.0.0.1:8015`(限流 10 请求/秒、突发 20,`client_max_body_size 30M`)

> [!WARNING]
> `deploy/setup.sh` 安装路由时会**按实际仓库根自动替换**模板里的老路径占位(`alias /mnt/workspace/ttv/...` → `$ROOT`),所以照脚本走不会 404;但它假定宿主机已有一个站点配置(`/etc/nginx/sites-enabled/comfyui-20013`)可被 include —— 干净服务器上会打印提示并跳过,需要你自己在 server 块里加一行 `include /etc/nginx/ttv-locations.conf;`,或直接用 `http://<host>:8015/`(`TTV_SKIP_NGINX=1`)。

## 已知限制

- **短文超长视频有内容天花板**:模型单轮扩写约 800 字旁白(≈3 分钟语音),更长时长以「两轮拓展 + 论证展开 + 变换表述重述」逼近,实际时长以真实配音为准。
- **讲解视频耗时更长**:分析多轮调用(30 分钟档约 6-8 次),渲染超时上限已放宽到 3 小时。
- **词级字幕为估算**:帧内按字数均分。
- **数字人几何改动不追溯**:换大小/角落、切「不出镜」、开关抠像后需重新构建 + 重新渲染(片段与遮罩缓存保留,切回来很快)。
- **换默认形象只影响后续构建**:形象在构建时解析,老任务不会自动变脸。
- **运行时状态不入库**:上传的形象、`assets/avatars/library.json`、`.run/*.json`、`.secrets/`、`jobs/` 都不入库;换机器需自行拷贝(`assets/avatars/` 整目录可迁移)。
- **抠像速度与回退**:MODNet 在 CPU 上约 8 帧/秒(300px),遮罩按片段缓存只算一次;解释器或权重缺失时自动回退圆角卡片。
- **历史不保留多次成片版本**:磁盘上只保留最新一份,重新渲染会覆盖。
- **升级配音依赖前先回归**:改 `tts-venv` 后先跑 `server/smoke_test.py`,再跑 `tts-venv/bin/python server/voice_check.py --script jobs/<id>/project/script.json --audio jobs/<id>/project/assets/audio --frames 5 --model-dir models/whisper`(它是唯一能拦住「时长正常、读音是乱码」的检查)。

## 项目结构

```text
.                           仓库根只放 README 与 CHANGELOG,其余文档全在 docs/
├── README.md                 本文件(从零部署 / 快速开始)
├── CHANGELOG.md              版本与变更记录
├── docs/
│   ├── ARCHITECTURE.md       总体架构、状态机、接口清单
│   ├── 使用说明.md           面向使用者的操作手册
│   ├── BUILD.md              从零搭建(⚠️ 老 PPU 机器,历史文档)
│   ├── CONTEXT.md            领域词汇表
│   ├── frames-schema.md      分析输出契约(帧 JSON)
│   ├── cyberverse/           数字人部署与启动手册(DEPLOY-GPU / QUICKSTART / CONTINUE)
│   ├── adr/                  架构决策记录
│   └── 问题修复说明-*.md      方框字、配音乱码等历史事故复盘
├── server/                   FastAPI 后端
│   ├── main.py               任务 API / Studio 代理 / 流水线阶段 / 并发与质量门
│   ├── config.py             路径、端口、模型端点与全部环境变量
│   ├── analyze.py            大模型分析(宣传两阶段 / 讲解两步 + 分段并行 + 二次拓展)
│   ├── tts.py / tts_server.py  配音调度(多实例轮询、词级时间轴)与 CosyVoice3 服务
│   ├── avatar.py / avatar_library.py / matte.py  数字人片段、形象库、MODNet 抠像 worker
│   ├── settings.py / preferences.py  网页设置与全局偏好
│   ├── jobs.py               任务状态机(磁盘持久化,重启恢复)
│   ├── smoke_test.py         冒烟回归(纯函数 + 接口契约)
│   └── builder/              风格注册表 / 帧模板 / script.json → HyperFrames 工程
├── web/index.html            单文件 SPA(历史入口页 + 创作页 + 预览页 + 形象页 + 设置页)
├── tests/
│   ├── avatar-page.test.js   前端页面逻辑回归(node 直跑,无 npm 依赖)
│   └── fixtures/test-article.md  示例文章,可直接上传跑通整条链路
├── deploy/                   setup / 启动脚本(start-all、start-*、cyberverse.sh)/ nginx 路由 / 校验脚本
├── styles/                   三套经典风格设计脚本
├── proto/                    数字人 gRPC 契约
├── assets/                   Logo、成片截图、形象库(内置 jinli.png 入库;上传的形象不入库)、字体/BGM/GSAP(不入库,setup.sh 获取)
├── .run/                     运行时状态(偏好、设置、Studio 端口注册);不入库
└── jobs/<job_id>/            每任务:原文 → script.json → project/ → renders/
```

## 相关文档

| 文档 | 内容 |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 总体架构、状态机、关键设计决策、**完整接口清单**、扩展点 |
| [`docs/使用说明.md`](docs/使用说明.md) | 面向使用者的操作手册:使用流程、风格、换形象、运维与常见问题 |
| [`docs/cyberverse/DEPLOY-GPU.md`](docs/cyberverse/DEPLOY-GPU.md) | **数字人(FlashHead)从 0 到运行的权威步骤**与踩坑速查 |
| [`docs/CONTEXT.md`](docs/CONTEXT.md) | 领域词汇表(帧 / 台词 / 成片 / 播报视频…统一口径) |
| [`docs/frames-schema.md`](docs/frames-schema.md) | 分析输出契约(帧 JSON 结构) |
| [`CHANGELOG.md`](CHANGELOG.md) | 版本与变更记录(当前 v2.15) |
| [`docs/adr/`](docs/adr/) | 架构决策记录(如抠像用独立灰度遮罩) |
| [`docs/BUILD.md`](docs/BUILD.md) | ⚠️ 历史文档:记录的是**老 PPU 机器**(4×PPU-ZW810E / `/mnt/workspace/ttv` / python3.12 / torch 2.10)的搭建过程,仅供排障时对照,新机器请以上面几份为准 |
