# CyberVerse GPU 部署（0 → 运行）

单卡 **RTX 5090** + Ubuntu 22.04 + Python 3.10，用 **uv 隔离环境**，跑本地数字人 **FlashHead** + Go API + 前端。
实测环境：RTX 5090 32GB / 驱动 595.58.03 / CUDA 12.8 / Python 3.10.12。全程 30–60 分钟，下载量约 21GB（权重 15.4GB + wheel 5GB）。

> 命令按顺序敲即可。**第 8 节「踩坑速查」是最省时间的部分**，卡住了先看它。

```bash
export ROOT=/data/Avatar REPO=$ROOT/CyberVerse-main TOOLS=$ROOT/.tools WHEELS=$ROOT/.wheels
```

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
curl -fL -o $TOOLS/dl/go.tgz https://dl.google.com/go/go1.25.0.linux-amd64.tar.gz
mkdir -p $TOOLS/go && tar -C $TOOLS/go --strip-components=1 -xzf $TOOLS/dl/go.tgz
curl -fL -o $TOOLS/dl/protoc.zip \
  https://github.com/protocolbuffers/protobuf/releases/download/v29.3/protoc-29.3-linux-x86_64.zip
mkdir -p $TOOLS/protobuf-29.3 && unzip -qo $TOOLS/dl/protoc.zip -d $TOOLS/protobuf-29.3
ln -sf $TOOLS/go/bin/go /usr/local/bin/go
ln -sf $TOOLS/protobuf-29.3/bin/protoc /usr/local/bin/protoc
go version && protoc --version      # go1.25.0 / libprotoc 29.3
```

## 3. uv 隔离环境

```bash
export HOME=$ROOT/.home UV_CACHE_DIR=$ROOT/.cache/uv UV_PYTHON_INSTALL_DIR=$TOOLS/pythons
export HF_HOME=$ROOT/.cache/huggingface TORCHINDUCTOR_CACHE_DIR=$ROOT/.cache/torch_inductor
mkdir -p $HOME
curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=$TOOLS/bin UV_NO_MODIFY_PATH=1 sh
export PATH=$TOOLS/bin:$PATH
cd $REPO && uv venv .venv --python 3.10
uv pip install --python .venv/bin/python -e ".[dev,inference,flash_head]"
```

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

## 9. 国内源速查（本机实测）

| 用途 | 地址 | 实测 |
|---|---|---|
| PyPI | `https://pypi.tuna.tsinghua.edu.cn/simple` | 2.5–11 MB/s（大文件会断，配 curl） |
| Go 模块 | `https://goproxy.cn,direct` | 好 |
| 模型（首选） | ModelScope CLI | 9–12 MB/s |
| 模型（备选） | `HF_ENDPOINT=https://hf-mirror.com` | 2.2 MB/s |
| Go 工具链 | `https://dl.google.com/go/` | 好 |
| ❌ 尽量避开 | `files.pythonhosted.org`（18KB/s）、`download.pytorch.org`（1.6MB/s）、`huggingface.co`（不通） | |

## 10. 最短路径

```bash
# 1) 系统依赖 + Go/protoc（第 1、2 节）
# 2) uv venv + 装依赖（第 3 节；卡了就第 3.1 节离线）
# 3) ModelScope 下权重（第 4 节，可与第 3 节并行）
# 4) config + proto + 根目录配置（第 5 节）
# 5) 三个终端起推理/API/前端（第 6 节）
# 6) health + 集成测试（第 7 节）
```
