# CyberVerse GPU 部署（0 → 运行）

单卡 **RTX 5090** + Ubuntu 22.04 + Python 3.10，用 **uv 隔离环境**，跑本地数字人 **FlashHead** + Go API + 前端。
实测环境：RTX 5090 32GB / 驱动 580.65.06 / CUDA 12.8 / Python 3.10.12。全程 30–60 分钟，下载量约 21GB（权重 15.4GB + wheel 5GB）。

> 命令按顺序敲即可。**第 8 节「踩坑速查」是最省时间的部分**，卡住了先看它。

```bash
# $ROOT 是**本仓库根目录**（本文统一用它；不要写死机器路径）
export ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." 2>/dev/null && pwd || pwd)"
export REPO=$ROOT/CyberVerse-main TOOLS=$ROOT/.tools WHEELS=$ROOT/.wheels
```
> 实测机器上该值是 `/mnt/data/ttv`。若只想用 CyberVerse 的 gRPC 推理服务给本仓库出片，
> 可直接用 `deploy/start-avatar.sh` 启动（它已封装第 3/6 节的环境变量与探活）。

---

## 0. 先拿到 CyberVerse 源码（本文档之外，最容易漏）

**CyberVerse 不在本仓库内**，也不在任何公开模型仓库里；上游是 <https://github.com/Lynpoint/CyberVerse>（公开）。

```bash
cd "$ROOT"
git clone https://gh-proxy.com/https://github.com/Lynpoint/CyberVerse.git CyberVerse-main   # 国内走 gh-proxy；直连慢
# 或：git clone git@github.com:Lynpoint/CyberVerse.git CyberVerse-main
```

落位必须是 `<仓库根>/CyberVerse-main/`——`deploy/start-avatar.sh` 与 `deploy/cyberverse.sh`
都按这个相对位置找它（可用 `TTV_CYBERVERSE_DIR` 覆盖）。

> 实测参考：`main` 分支 HEAD `13a6a95b47e5e6f0809683458767746ad54d7d7f`，解压/克隆后约 667 个文件、**不含** `.git` 之外的权重。
> 仓库**不跟踪** CyberVerse，所以它不会被本仓库的 `git pull` 影响。

---

## 1. 系统依赖（root）

```bash
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends \
  ffmpeg libopus-dev libopusfile-dev libsoxr-dev pkg-config python3.10-dev
```

`libopus/soxr -dev` 给 Go 的 livekit 编译用；**`python3.10-dev` 不能漏**——torch.compile 要编译 C 扩展，缺了 FlashHead 初始化直接失败。

## 2. Go 1.25 + protoc 29.3

`server/go.mod` 要 go 1.25.0；`generate_proto.sh` 硬性要求 `libprotoc 29.3`。

```bash
mkdir -p $TOOLS/dl
curl -fL -o $TOOLS/dl/go.tgz https://dl.google.com/go/go1.25.0.linux-amd64.tar.gz   # 直连可用
mkdir -p $TOOLS/go && tar -C $TOOLS/go --strip-components=1 -xzf $TOOLS/dl/go.tgz
# protoc 在 GitHub releases：国内直连很慢/会断，走 gh-proxy
curl -fL -o $TOOLS/dl/protoc.zip \
  "https://gh-proxy.com/https://github.com/protocolbuffers/protobuf/releases/download/v29.3/protoc-29.3-linux-x86_64.zip"
mkdir -p $TOOLS/protobuf-29.3 && unzip -qo $TOOLS/dl/protoc.zip -d $TOOLS/protobuf-29.3
ln -sf $TOOLS/go/bin/go /usr/local/bin/go
ln -sf $TOOLS/protobuf-29.3/bin/protoc /usr/local/bin/protoc
go version && protoc --version      # go1.25.0 / libprotoc 29.3
```

> [!IMPORTANT]
> **protoc 的查找路径有坑**：`generate_proto.sh` 依次找 `$PROTOC` → `$HOME/.local/cyberverse-tools/protobuf-29.3/bin/protoc` → `command -v protoc`。
> 而 `start-avatar.sh` 会把 `HOME` 改写成 `$ROOT/.home` 并且**不设 `PROTOC`**，于是上面第二条路径会落空。
> 第三条能兜住（前提是 `/usr/local/bin/protoc` 已在 PATH），但为了不依赖 PATH，**建议再多做一个软链**：
> ```bash
> mkdir -p $ROOT/.home/.local/cyberverse-tools/protobuf-29.3/bin
> ln -sf /usr/local/bin/protoc $ROOT/.home/.local/cyberverse-tools/protobuf-29.3/bin/protoc
> ```
> 版本必须**恰好** `libprotoc 29.3`，`generate_proto.sh` 会硬校验并拒绝其他版本（为了 Go 产物可复现）。
> Go 模块记得走国内源：`export GOPROXY=https://goproxy.cn,direct`。

## 3. uv 隔离环境

```bash
export HOME=$ROOT/.home UV_CACHE_DIR=$ROOT/.cache/uv UV_PYTHON_INSTALL_DIR=$TOOLS/pythons
export HF_HOME=$ROOT/.cache/huggingface TORCHINDUCTOR_CACHE_DIR=$ROOT/.cache/torch_inductor
mkdir -p "$HOME"

# uv：astral.sh 的安装脚本在国内可能很慢，用 Python 包更稳（也可用官方脚本）
python3 -m venv "$TOOLS/toolenv"
"$TOOLS/toolenv/bin/pip" install -q -U uv modelscope     # modelscope 后面下权重要用
UV="$TOOLS/toolenv/bin/uv"

cd "$REPO" && "$UV" venv .venv --python 3.10

# ── torch：先单独装（本机做法，确保走清华源）──
# 注意：torch **没有**写在 pyproject.toml 的依赖里，但会被 xformers / accelerate / xfuser
# 等**传递依赖**带进来（仓库自带的 uv.lock 中就有 torch 2.8.0，244 个包）。
# 所以直接跑下面的 `uv pip install -e "..."` 也会装 torch；先单独装只是为了锁定索引、
# 避开不通的 pypi.org，并让失败点更清晰。
# 走清华 PyPI 即可拿到 +cu128；**别用 download.pytorch.org**（常见 403）。
"$UV" pip install --python .venv/bin/python \
  --index-url https://pypi.tuna.tsinghua.edu.cn/simple \
  torch==2.8.0 torchvision==0.23.0 torchaudio==2.8.0

# ── 项目依赖组 ──
"$UV" pip install --python .venv/bin/python \
  --index-url https://pypi.tuna.tsinghua.edu.cn/simple \
  -e ".[dev,inference,flash_head]"
```
> **关于 `uv.lock`（1.6MB）与"是否 uv 隔离环境"**：
> `uv venv` 建出来的 `.venv` **是与系统包隔离的**（`pyvenv.cfg` 里 `uv = 0.12.17`、
> `include-system-site-packages = false`、**不含 pip**），但**不等同于 `uv sync` 的锁文件环境**——
> 上面用的是 `uv pip install`（pip 兼容接口），**绕过了仓库自带的 `uv.lock`**。原因是
> `uv.lock` 的 `source` 记的是 `registry = "https://pypi.org/simple"`，而本机 pypi.org 不通
> （仓库自己的 Makefile/文档也未提 `uv sync`）。
>
> **实测差异**（装完后与 `uv.lock` 逐包比对，232 个锁定包）：**一致 95 个 / 版本不同 51 个 / 未安装 86 个**。
> - 版本漂移例：`diffusers` 0.38.0→**0.39.0**、`accelerate` 1.14.0→1.15.0、`grpcio` 1.81.1→1.84.0、
>   `fastapi` 0.138.0→0.141.1、`llvmlite` 0.47.0→0.49.0、`mediapipe` 0.10.35→**1.0.1**。
> - "未安装"的 86 个基本是**故意没装的组**（`rag`/`milvus`/`omni`/`live_act`，如 `chromadb`、`jsonschema`）。
> - 该环境**已跑通完整出片**（1080p、含数字人叠加），所以漂移是可接受的；但要**严格复现**请到能访问
>   pypi.org 的网络下用 `uv sync --extra dev --extra inference --extra flash_head`，或给 `uv sync` 指定可用索引。
>
> 对比：本仓库 article2video 的 `.venv` 同样隔离（`include-system-site-packages = false`），
> 而 **`tts-venv` 是 `true`（不隔离）**——它刻意复用系统基础包，也正是"transformers 钉版最容易被带坏"的根因。
> `--index-url` 也可以换成 `export UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple` 一次性生效（pip 同理写 `~/.config/pip/pip.conf`）。
> uv 缓存峰值约 8GB，装完可 `"$UV" cache clean` 回收（若大 wheel 已硬链到 venv，回收量可能很小）。

- **HOME 必须指到工作区**：`/root` 可能是只读，且所有缓存默认写 `$HOME`。
- **不要装 `.[all]`**：会拖入 `vllm`/`live_act`/`milvus`/`rag`，单卡 5090 跑不动 LiveAct 也不需要。
- 需要**文本 LLM**（OpenAI 兼容网关、paratera、OpenAI 等）时，再补一组：`openai` SDK 在 `llm`/`tts` 组里，不装的话 `llm.openai`、`tts.openai` 会静默初始化失败：

```bash
uv pip install --python .venv/bin/python -e ".[llm,tts]"
```

验证：

```bash
.venv/bin/python -c "import torch;print(torch.__version__,torch.version.cuda,torch.cuda.is_available(),torch.cuda.get_device_name(0))"
# 期望：2.8.0+cu128 12.8 True NVIDIA GeForce RTX 5090
```

### 3.1 装不上时走离线（本机实测必用）

症状：pip/uv 卡在几十 KB/s，大 wheel 在 60–100MB 处断，但 `curl` 下同一个 URL 有 1.8–11MB/s。

```bash
# 生成锁定清单（uv 只解析元数据，很快）
printf 'torch==2.8.0\ntorchvision==0.23.0\ntorchaudio==2.8.0\n' > torch-in.txt
uv pip compile --python-version 3.10 --python-platform x86_64-unknown-linux-gnu \
  -o torch-reqs.txt torch-in.txt
uv pip compile --python-version 3.10 --python-platform x86_64-unknown-linux-gnu \
  --extra dev --extra inference --extra flash_head -o proj-reqs.txt pyproject.toml

# curl 逐文件断点续传（可反复重跑，已验证 sha256）
python3 $TOOLS/curl_wheels.py $WHEELS torch-reqs.txt proj-reqs.txt

# 离线安装
uv pip install --python .venv/bin/python --no-index --find-links $WHEELS -r torch-reqs.txt
uv pip install --python .venv/bin/python --no-index --find-links $WHEELS -e ".[dev,inference,flash_head]"
```

`curl_wheels.py` 已在 **`$TOOLS/curl_wheels.py`**（锁定清单也在 `$TOOLS/` 下）。逻辑：从 PyPI 的 versioned JSON 取精确 wheel URL（避开慢的 `/simple/` 大索引页），用 `curl -C -` 断点续传，并用 sha256 校验（大小对但内容坏的文件会自动重下）。

## 4. 模型权重（15.4GB，必下）

ModelScope 最快（9–12MB/s，约 21 分钟）：

```bash
uv venv $TOOLS/toolenv --python 3.10
uv pip install --python $TOOLS/toolenv/bin/python modelscope
export MODELSCOPE_CACHE=$ROOT/.cache/modelscope
cd $REPO && mkdir -p checkpoints
$TOOLS/toolenv/bin/modelscope download --model Soul-AILab/SoulX-FlashHead-1_3B \
  --local_dir checkpoints/SoulX-FlashHead-1_3B          # 14GB / 19 files
$TOOLS/toolenv/bin/modelscope download --model facebook/wav2vec2-base-960h \
  --local_dir checkpoints/wav2vec2-base-960h            # 1.1GB / 12 files
find checkpoints -name '*.incomplete' | wc -l           # 必须是 0
```

备选（约 2.2MB/s）：`export HF_ENDPOINT=https://hf-mirror.com` 后用 `hf download ...`
**不要下** LiveAct / chinese-wav2vec2-base。

## 5. 配置 + proto

```bash
cd $REPO
cp -r infra/config config
PYTHON=$REPO/.venv/bin/python ./scripts/generate_proto.sh

# 集成测试读的是仓库根的 cyberverse_config.yaml（README 未提）。必须是真实文件，不能软链
cp config/cyberverse.yaml cyberverse_config.yaml
sed -i 's|model_config_dir: "avatar_models"|model_config_dir: "config/avatar_models"|' cyberverse_config.yaml
```

`config/cyberverse.yaml` 的 GPU 关键项（infra 默认已正确）：

```yaml
inference:
  avatar:
    enabled: true
    default: "flash_head"       # 单卡 5090 用它；live_act 需 RTX PRO 6000
    runtime: { cuda_visible_devices: 0, world_size: 1 }
```

`config/env` 填云端 Key；纯本地数字人可留空，但**完整语音问答**需要其中一个（`DASHSCOPE_API_KEY` 或 `DOUBAO_*`）。

### 5.1 接入 OpenAI 兼容的 LLM 网关（可选）

以 paratera（`https://llmapi.paratera.com/v1`，模型 `DeepSeek-V4-Flash`）为例。

**坑**：`OpenAILLMPlugin` 只在 provider 名恰好是 `llm.openai` 时才读 `OPENAI_BASE_URL`，其他名字走 YAML 里的 `base_url`。所以新建独立 provider 最干净：

```bash
cat > config/llm_models/paratera.yaml <<'YAML'
paratera:
    plugin_class: "inference.plugins.llm.openai_plugin.OpenAILLMPlugin"
    api_key: "${PARATERA_API_KEY}"
    base_url: "https://llmapi.paratera.com/v1"
    model: "DeepSeek-V4-Flash"
    temperature: 0.7
YAML

# Key 写进 config/env（文件名 = provider 名，故插件名为 llm.paratera）
echo 'PARATERA_API_KEY=你的key' >> config/env
```

再把后台 subagent 从 qwen 切过去（Pi runtime 只对 `qwen` 有内置默认，其他 provider 必须显式写全三个字段）：

```yaml
inference:
  persona:
    subagent:
      provider: "paratera"
      model: "DeepSeek-V4-Flash"
      provider_api: "openai-completions"
      provider_base_url: "https://llmapi.paratera.com/v1"
      provider_api_key_env: "PARATERA_API_KEY"
```

重启推理服务后，日志应出现 `Registered plugin: llm.paratera` + `Initialized plugin: llm.paratera`。

> **注意**：LLM provider ≠ 语音对话。`PersonaAgent`（实时对话核心）要求的是 **omni** provider
> （`omni.qwen_omni` / `omni.doubao` / `omni.gemini` / `omni.openai_realtime`），各自需要对应厂商的 Key。
> LLM provider 只服务文本路径（Pi 后台子任务、RAG 回答、LLM 服务）。
> 想一次性打通语音，最省事的是加一个 `DASHSCOPE_API_KEY`（omni + TTS + ASR 三样都覆盖）。

## 6. 启动（3 个终端）

```bash
source $TOOLS/env.sh   # 或手动 export 第 3 节那几个变量
```

**T1 · GPU 推理**（首次 torch.compile + 预热 3–5 分钟）

```bash
cd $REPO && PYTHON=$REPO/.venv/bin/python ./scripts/inference.sh config/cyberverse.yaml
```

**T2 · Go API**（首次先编译）

```bash
export GOPROXY=https://goproxy.cn,direct
cd $REPO && PROTOC=/usr/local/bin/protoc ./scripts/generate_proto.sh
cd server && go build -tags livekit -o ../bin/cyberverse-server ./cmd/cyberverse-server/
cd $REPO; set -a; . ./config/env; set +a
cd server && ../bin/cyberverse-server --config ../config/cyberverse.yaml
```

**T3 · 前端**

```bash
cd $REPO/frontend && npm install && CHOKIDAR_USEPOLLING=true npm run dev
```

## 7. 验收

```bash
curl -s http://localhost:8080/api/v1/health                      # {"inference_connected":true,"status":"ok"}
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:5173/  # 200
ss -ltn | grep -E ':8080|:50051|:5173|:8443'                     # 四个端口都在听
```

真·出视频（唯一权威判据；`examples/` 被 gitignore，包里没有，必须先造两个夹具）：

```bash
cd $REPO && mkdir -p examples
cp frontend/public/liukanshan/persona.png examples/girl.png
ffmpeg -y -loglevel error -i docs/assets/peiyin_clone_25s.mp3 \
  -ac 1 -ar 16000 -c:a pcm_s16le examples/podcast_sichuan_16k.wav
.venv/bin/python -m pytest tests/integration/test_flash_head_generates_real_video.py -m integration -v -s
ffprobe -v error -show_entries stream=codec_name,width,height,nb_frames \
  -of default=noprint_wrappers=1 artifacts/flash_head_smoke.mp4
```

**必须看到 `1 passed`**；`1 skipped` = 夹具缺失，不算通过。

**实时性（RTP）要看数据，别照抄 README 表格。** `RTP = 生成耗时 / (帧数 / fps)`，<1 才有余量，>1 跟不上播放。
本机实测（RTX 5090 单卡、FlashHead Pro、464×464 @ 20fps）：每块 28 帧＝播放 1.400s，实际生成 **1.527s → RTP = 1.09**，
即**约差 9%，按 README 标准不算实时**（README 表格给该行标了 ✅，实测不符，可能是调优/环境差异）。
想达标：`model_type: "lite"`、把 `height/width` 降到 416/384、或把 `tgt_fps` 降到 15。
测法见 `$ROOT/.run/measure_rtp.py`（逐块打印 wall/playback/RTP 与稳态均值）。

### 7.1 只给本仓库（article2video）出片时的验收

如果只需 CyberVerse 的 gRPC 推理服务，**不必起 Go API 与前端**，用 `bash deploy/start-avatar.sh` 即可
（它封装了第 3/6 节的环境变量，并且走**真 gRPC 探活**而不是只看端口——就绪会打印
`← 数字人服务已就绪:avatar.flash_head 512x512 20fps`，首次约 **228 秒**）。

```bash
# 探活（后端自己的客户端）
cd $ROOT && .venv/bin/python -c "import sys;sys.path.insert(0,'server');import avatar;print(avatar.probe())"
# 期望：{'available': True, 'addr': '127.0.0.1:50051', 'model': 'avatar.flash_head',
#        'server_size': '512x512', 'fps': 20, 'frames_per_chunk': 28}
```

**叠加是否真的生效，别只看日志**：勾选数字人的任务会同时产出
`jobs/<id>/project/renders/ppt.mp4`（无数字人）与 `final.mp4`（含数字人），两者时长帧率一致，
逐帧差分即可定位叠加区域（`cutout=false` 时是整块卡片，差异接近 100%；`cutout=true` 只保留人像，约 50%）：

```bash
# 以右上角 300px、cutout=true 为例：全帧平均差应很小，右上角区域平均差应极大
ffmpeg -y -v error -ss 10 -i jobs/<id>/project/renders/ppt.mp4   -frames:v 1 /tmp/a.png
ffmpeg -y -v error -ss 10 -i jobs/<id>/project/renders/final.mp4 -frames:v 1 /tmp/b.png
# 依赖 Pillow 与 numpy(裸机没装先 pip install pillow numpy)
python3 - <<'PY'
from PIL import Image; import numpy as np
a=np.asarray(Image.open('/tmp/a.png').convert('RGB')).astype(int)
b=np.asarray(Image.open('/tmp/b.png').convert('RGB')).astype(int)
d=np.abs(a-b).sum(axis=2); h,w=d.shape
print('全帧平均差', round(d.mean(),2), '| 右上角320x320平均差', round(d[:320, w-320:].mean(),2),
      '| 显著差异像素占比', f'{(d[:320,w-320:]>30).mean()*100:.1f}%')
PY
```
实测参考值：全帧 9.8–10.2，右上角 167–172，占比 46.7–47.5%（`cutout=true`）。

### 7.2 注意力后端：`flash_attn` / `sageattention` 是可选的加速项

启动日志里那句
`Flash Attention library "flash_attn" not found, using pytorch attention implementation`
**不影响功能**，只是没用上更快的注意力实现。FlashHead 的选择顺序（见
`models/flash_head/src/modules/flash_head_model.py` 的 `flash_attention()`）：

1. `compatibility_mode=True` → PyTorch `F.scaled_dot_product_attention`
2. `sageattention` 可用 → `sageattn`
3. **FlashAttention 3**（`flash_attn_interface`）可用 → `flash_attn_func`
4. **FlashAttention 2**（`flash_attn`）可用 → `flash_attn_func`
5. 都没有 → PyTorch `F.scaled_dot_product_attention`

FlashAttention 是 Dao-AILab 的 IO 感知**精确**注意力实现：通过分块 + 在线 softmax 避免把 S×S
注意力矩阵完整写回 HBM，从而省显存、提速度（长序列收益最大）。它是**数值精确**的，不是近似，
所以装不装都不会改变画面正确性，只影响速度与峰值显存。
本机（RTX 5090 / sm_120）没装 `flash_attn`，走的是第 5 条 PyTorch SDPA，出片正常。
想再压榨速度可优先试 `sageattention`（第 2 条，优先级更高且 pip 可装），`flash_attn` 在
Blackwell 上需自行编译、耗时较长。

## 8. 踩坑速查

| 症状 | 原因 | 解决 |
|---|---|---|
| `fatal error: Python.h` → `FlashHead default avatar init failed` / `avatar_ready=False` | 缺 Python 开发头 | `apt-get install -y python3.10-dev` |
| `avatar model config dir not found` | 根目录配置用了软链 | 换真实文件 + `model_config_dir: "config/avatar_models"` |
| pip/uv 几十 KB/s，大文件 60–100MB 断 | 长连接被掐（curl 正常） | 第 3.1 节：`curl_wheels.py` + `uv --no-index` |
| uv 联网永远慢（pip 却正常） | uv 是 Rust 写的，不读 `gai.conf`，选到死 IPv6 | `/etc/gai.conf` 加 `precedence ::ffff:0:0/96  100`；或直接离线 |
| `nvidia-smi: NVML Insufficient Permissions`，`/dev/nvidia*` 不存在 | 受限沙箱只挂最小 `/dev` | GPU 命令必须在非受限 shell 跑（`torch.cuda.is_available()` 会是 False） |
| `proxy.golang.org: i/o timeout` | Go 代理不通 | `export GOPROXY=https://goproxy.cn,direct` |
| 集成测试 skip | 缺 `examples/girl.png` 或 `podcast_sichuan_16k.wav`（≥8s, 16k mono s16），或 CUDA 不可见 | 见第 7 节 |
| `model_config_dir` / conda 路径报错 | Makefile 默认指向 `$HOME/miniconda3/envs/cyberverse` | 不用 conda：直接 `go build`（系统 pkg-config 已够） |
| 磁盘不够 | 权重 15.4GB + wheel 5GB + 缓存数 GB | 预留 40GB+ |
| 不知道 CyberVerse 从哪来 / `找不到 CyberVerse-main` | 它不在本仓库内，且本文档早期版本没写上游 | 见**第 0 节**：<https://github.com/Lynpoint/CyberVerse>，落到 `<仓库根>/CyberVerse-main/` |
| GitHub 下 protoc/release 极慢或 ECONNRESET | 直连 GitHub | 走 `https://gh-proxy.com/<原始URL>`（实测 2MB/s） |
| `uv pip install torch` 失败 / 403 | `download.pytorch.org` 被拒 | 改走清华 PyPI（`torch==2.8.0` 即 `+cu128`），见第 3 节 |
| `ERROR: protoc version mismatch` 或 `protoc not found` | `start-avatar.sh` 把 `HOME` 改成 `$ROOT/.home` 且不设 `PROTOC` | 见第 2 节：补 `$ROOT/.home/.local/cyberverse-tools/protobuf-29.3/bin/protoc` 软链，或显式 `export PROTOC=...` |
| `Flash Attention library "flash_attn" not found` | 可选加速库缺失 | **不影响功能**，回退到 PyTorch SDPA；说明见第 7.2 节 |
| 磁盘被 uv 缓存吃掉几 GB | `UV_CACHE_DIR` 落在工作区 | `"$UV" cache clean`（大 wheel 已硬链时回收量可能很小） |
| 数字人端口对外 | CyberVerse 默认绑 `0.0.0.0:50051`（本仓库后端只连 `127.0.0.1`） | 不需要对外时用防火墙/安全组收紧；它没有鉴权 |

## 9. 国内源速查（本机实测）

| 用途 | 地址 | 实测 |
|---|---|---|
| PyPI | `https://pypi.tuna.tsinghua.edu.cn/simple` | **45 MB/s**（本次实测比早期记录的 2.5–11 快很多，大文件也没断） |
| Go 模块 | `GOPROXY=https://goproxy.cn,direct` | 好 |
| Go 工具链 | `https://dl.google.com/go/` | **17 MB/s**（直连可用） |
| GitHub raw / release / clone | `https://gh-proxy.com/<原始URL>` | **2 MB/s**（直连 `raw.githubusercontent.com` 约 35 KB/s） |
| chrome-headless-shell | `https://cdn.npmmirror.com/binaries/chrome-for-testing/<版本>/linux64/chrome-headless-shell-linux64.zip` | **4.6 MB/s**（Google 存储约 17 KB/s） |
| 模型（首选） | ModelScope CLI | **4–6.5 MB/s**（比早期记录的 9–12 慢，15.4GB 约 40 分钟） |
| 模型（备选） | `HF_ENDPOINT=https://hf-mirror.com` | 2.2 MB/s |
| ❌ 尽量避开 | `pypi.org` / `files.pythonhosted.org`（**直接不通**）、`download.pytorch.org`（**403**，别用来装 torch）、`huggingface.co`（不通）、阿里云 `pytorch-wheels`（只有 ~65 KB/s） | |

## 10. 最短路径

```bash
# 0) 拉源码到 <仓库根>/CyberVerse-main/（第 0 节；最容易漏的一步）
# 1) 系统依赖 + Go/protoc（第 1、2 节；protoc 记得补 $ROOT/.home 下的软链）
# 2) uv venv + torch + 装依赖（第 3 节；卡了就第 3.1 节离线）
# 3) ModelScope 下权重（第 4 节，可与第 2 节并行）
# 4) config + proto + 根目录配置（第 5 节）
# 5) 起服务：只要给本仓库出片 → bash deploy/start-avatar.sh（只起 50051，见第 7.1 节）；
#    要用 CyberVerse 自己的界面 → 三个终端起推理/API/前端（第 6 节）
# 6) health + 集成测试（第 7 节）；本仓库侧用 avatar.probe() + 像素差分验收（第 7.1 节）
```
