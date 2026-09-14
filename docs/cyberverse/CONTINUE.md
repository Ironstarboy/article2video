# CyberVerse GPU 部署 · 新对话续接文档

> **用途**：把这个文件（或路径）贴给一个新的对话，即可无缝接着干。
> **最后更新**：北京时间 2026-09-11 17:45 左右，由当前会话写入。
> **配套文档**：`docs/cyberverse/DEPLOY-GPU.md`（从 0 部署手册）
> **交接下载说明**：`/data/Avatar/.wheels/README-DOWNLOAD.md`

---

## 0. 一句话交接

CyberVerse（`/data/Avatar/CyberVerse-main`，从 `CyberVerse-main.zip` 解压）要按 README 部署运行
**GPU 版**（本地 FlashHead 数字人），**用 uv 隔离环境**，目标机是单卡 **RTX 5090**。
**模型权重、Go 服务、前端、配置、夹具都已完成**；**只差 Python wheel 包装进 venv**，然后起 GPU 推理 + 跑集成测试。

---

## 1. 当前状态（实测结论，勿重复劳动）

### ✅ 已完成

| 项 | 证据 / 路径 |
|---|---|
| 宿主机依赖 | `ffmpeg 4.4.2`、`libopus-dev/libopusfile-dev/libsoxr-dev`、`pkg-config`；`pkg-config --cflags --libs opus opusfile soxr` → `-I/usr/include/opus -lopus -lopusfile -lsoxr` |
| Go 1.25.0 | `/data/Avatar/.tools/go`，软链 `/usr/local/bin/go`，`go version` → `go1.25.0 linux/amd64` |
| protoc 29.3 | `/data/Avatar/.tools/protobuf-29.3`，软链 `/usr/local/bin/protoc`，`libprotoc 29.3` |
| uv 0.12.13 | `/data/Avatar/.tools/bin/uv`；规范副本 `/data/Avatar/CyberVerse-main/.tools/uv/bin/uv` |
| venv | `/data/Avatar/CyberVerse-main/.venv`（Python **3.10.12**，**当前 0 个包**） |
| **模型权重** | `checkpoints/SoulX-FlashHead-1_3B` = **14 GB / 19 files**、`checkpoints/wav2vec2-base-960h` = **1.1 GB / 12 files**，经 ModelScope 下载，**无 `.incomplete`** |
| 配置 | `config/` 由 `infra/config` 复制；`avatar.enabled: true`、`default: flash_head`、`cuda_visible_devices: 0`、`world_size: 1` |
| 兼容软链 | `cyberverse_config.yaml -> config/cyberverse.yaml`（集成测试读根目录这个文件名） |
| 测试夹具 | `examples/girl.png`（1344×1554 人像）、`examples/podcast_sichuan_16k.wav`（pcm_s16le / 16 kHz / mono / 25 s） |
| Go 服务二进制 | `/data/Avatar/CyberVerse-main/bin/cyberverse-server`（50.6 MB，`-tags livekit` 编译成功） |
| Go proto 桩 | `server/internal/pb/*.pb.go` 已生成 |
| 运行中的服务 | **Go API 在 8080**（`/api/v1/health` 返回 HTTP 200，`inference_connected:false`）、**前端在 5173**（Vite 8.1.0 HTTP 200） |
| 前端依赖 | `frontend/node_modules` 已装 |
| 依赖锁定清单 | `$WHEELS/torch-reqs.txt`（29 包，PyTorch CUDA 12.8 全套）、`$WHEELS/proj-reqs.txt`（147 包，项目 dev+inference+flash_head） |

其中 `$WHEELS = /data/Avatar/.wheels`。

### ✅ 未完成项——已全部完成（2026-09-12 00:20）

1. ~~Python wheel 未下载/安装~~ → **已装好**：`.venv` **153 个包**，`torch 2.8.0+cu128`（`torch.version.cuda == "12.8"`），
   `import torch, inference, grpc_tools, transformers, xformers` 全部通过；系统 python 无 torch（隔离成立）；
   无 `vllm/milvus/langchain`（GPU-only 范围正确）。
2. ~~GPU 推理服务未启动~~ → **已运行**：监听 `50051`，`avatar.flash_head` 在"已初始化插件"列表中，
   日志 `FlashHead avatar loaded: model_type=pro ... device=cuda world_size=1`，
   `FlashHead warmup done on rank 0: 28 frames @ 20 fps elapsed=174.752s`。
3. ~~GPU 集成测试未运行~~ → **已通过**：`1 passed in 63.80s`，
   产物 `artifacts/flash_head_smoke.mp4`（ffprobe：h264 512×512，112 帧，aac，5.6s，407 KB）。
4. ~~health 是 error~~ → **已变绿**：`{"error":"","inference_connected":true,"sessions":0,"status":"ok"}`。

### 过程中遇到并修掉的 3 个真实缺陷（新机器会同样遇到）

| 缺陷 | 症状 | 修复 |
|---|---|---|
| 缺 Python 开发头 | `cuda_utils.c:5:10: fatal error: Python.h` → `FlashHead pipeline default avatar init failed` → `avatar_ready=False` | `apt-get install -y python3.10-dev` |
| 集成测试读根目录配置 | 测试硬编码 `REPO_ROOT/cyberverse_config.yaml`；软链会导致 `model_config_dir` 解析到仓库根 → `FileNotFoundError: avatar model config dir not found` | 把根目录 `cyberverse_config.yaml` 换成**真实文件**（非软链），并改 `model_config_dir: "config/avatar_models"` |
| 大 wheel 下载中断 | pip/uv 下大文件在 60–100 MB 处卡死（0.3 MB/s） | 用 `curl -C -` 逐文件断点续传（见 `.run/curl_wheels.py`），实测 1.8–2.8 MB/s 稳定 |

### 仍然未验证（需要你提供的东西）

- **完整语音对话**：需要至少一个云端 Key（`DASHSCOPE_API_KEY` 或 `DOUBAO_*`）。当前日志里
  `asr.whisper`（缺 `openai-whisper` 包，属 `asr` 组，未装）、`tts.doubao`/`tts.openai`/`omni.doubao`
  （缺 Key）初始化失败——**不影响 GPU 数字人链路**，但纯语音问答无法端到端走通。
- **浏览器端 WebRTC**：远程访问需要 `8443/TCP` 可达（或用 SSH 隧道 `-L 8443:127.0.0.1:8443`）。

---

## 2. 下一步该做什么（按顺序）

```bash
source /data/Avatar/.tools/env.sh
export ROOT=/data/Avatar REPO=/data/Avatar/CyberVerse-main WHEELS=/data/Avatar/.wheels
```

### 步骤 1 · 把 wheel 补齐（关键，用 --no-deps 绕开卡死的解析器）

```bash
# 已下载的部分在 $WHEELS/torch，命令可重复执行（自动跳过已完成的包）
/data/Avatar/.tools/toolenv/bin/pip download --no-deps -r $WHEELS/torch-reqs.txt \
  -d $WHEELS/torch -i https://pypi.tuna.tsinghua.edu.cn/simple
/data/Avatar/.tools/toolenv/bin/pip download --no-deps -r $WHEELS/proj-reqs.txt \
  -d $WHEELS/torch -i https://pypi.tuna.tsinghua.edu.cn/simple
```
> 若这条也慢，直接走人工交接：按 `$WHEELS/README-DOWNLOAD.md` 在别的电脑下好，把 `.whl`
> 平铺传到 `/data/Avatar/.wheels/torch/`。**不需要重下 15 GB 权重。**

### 步骤 2 · 离线安装

```bash
cd $REPO
uv pip install --python .venv/bin/python --no-index --find-links $WHEELS/torch -r $WHEELS/torch-reqs.txt
uv pip install --python .venv/bin/python --no-index --find-links $WHEELS/torch -e ".[dev,inference,flash_head]"
```
> 若 `proj-reqs.txt` 里有包在 wheelhouse 中缺失，先补下再装。

### 步骤 3 · 非受限 shell 验证 CUDA（**必须**，受限沙箱里一定是 False）

```bash
cd $REPO
.venv/bin/python -c "import torch;print(torch.__version__, torch.version.cuda, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
# 期望：2.8.0 12.8 True NVIDIA GeForce RTX 5090
```

### 步骤 4 · 起 GPU 推理服务（后台任务，加载 + torch.compile 需数分钟）

```bash
cd $REPO
export TORCHINDUCTOR_CACHE_DIR=/data/Avatar/.cache/torch_inductor HF_HOME=/data/Avatar/.cache/huggingface
mkdir -p .run/logs
PYTHON=$REPO/.venv/bin/python ./scripts/inference.sh config/cyberverse.yaml 2>&1 | tee .run/logs/inference.log
```
日志里要看到 flash_head 插件、checkpoint 路径、`cuda:0`，且 `ss -ltn` 能看到 **50051**。

### 步骤 5 · 跑 GPU 集成测试（唯一权威判据）

```bash
cd $REPO
.venv/bin/python -m pytest tests/integration/test_flash_head_generates_real_video.py -m integration -v -s
ffprobe -v error -show_entries stream=codec_name,width,height -show_entries format=duration \
  -of default=noprint_wrappers=1 artifacts/flash_head_smoke.mp4
```
**必须看到 `1 passed`**；`1 skipped` 说明夹具缺失（见第 1 节已完成项，应已存在）。

### 步骤 6 · 复核整体

```bash
curl -s http://localhost:8080/api/v1/health     # 期望 inference_connected: true
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:5173/
```

---

## 3. 这台机器的硬性事实与坑（务必先读）

1. **GPU**：NVIDIA GeForce RTX 5090，32607 MiB，驱动 595.58.03；CUDA 12.8/13.0 在 `/usr/local`。
2. **GPU 只在非受限 shell 可用**。默认 `workspace-write` 沙箱挂的是最小 `/dev`（没有
   `/dev/nvidia*`），`nvidia-smi` 报 NVML 权限错误。DSH 里需要 `danger-full-access` 提权；
   **若该会话审批被禁用，拒绝即终局，不要重试**——改为让能提权的执行者（captain/用户 shell）来跑。
3. **`/root` 是只读文件系统** → 必须 `export HOME=/data/Avatar/.home`。
4. **IPv6 到镜像站是死的**（`curl -6` 直接失败）。`pip` 读 `/etc/gai.conf` 已修
   （已追加 `precedence ::ffff:0:0/96 100`）；**uv 是 Rust 写的、不读 gai.conf**，所以 uv 联网解析
   仍会卡死。→ 用 `pip download --no-deps` + `uv pip install --no-index --find-links` 组合。
5. **网络速度参考**：curl 直连 tuna 11 MB/s；ModelScope 9–12 MB/s；hf-mirror 2.16 MB/s；
   pip/uv 走解析时只有约 200 KB/s；`files.pythonhosted.org` 约 18 KB/s；`download.pytorch.org` 约 1.6 MB/s。
6. **huggingface.co 不可达**，`go.dev` 不可达；`dl.google.com`、`archive.ubuntu.com`、goproxy.cn 可达。
7. **前台命令 10 分钟上限**：长任务要拆段或放后台（后台在这台机器上对 pypi/tuna 会明显变慢，
   这也是为什么 `--no-deps` 方案更适合前台分段跑）。
8. **不要装 `.[all]`**：会拖入 `live_act`/`vllm`/`rag`/`milvus`，单卡 5090 不需要也跑不动。
9. 团队（AgentTeams）已由用户决定**解散归档**，不存在 task id；所有 `agent_teams_*` 调用都会失败，
   不要再尝试重建或给 retired member 发消息。
10. 旧的 `env-engineer` 会话可能还挂着一个**卡死的 uv 进程**并占用 uv cache 锁；
    如果 `uv pip install` 卡在等锁，需要先把它清掉（该进程在别的 PID namespace 里，`ps` 看不到）。

---

## 4. 失败与已排除的方案（别重走）

| 尝试 | 结果 |
|---|---|
| `uv pip install torch...` 直连 | 卡死（Rust 解析器撞死 IPv6），缓存只涨 0.6 MB/s |
| `UV_CONCURRENT_DOWNLOADS=2` | 更慢（28 KB/s），并发不是原因 |
| `pip install --dry-run --report` | 解析阶段超时（爬 `/simple/` 大页） |
| `pip download`（带依赖解析） | 10 分钟一无所获（卡在解析） |
| AgentTeams 分工 | 成员会话同样受限（无 GPU、不能提权），且比单人更慢，用户已决定弃用 |
| **`pip download --no-deps -r <锁定清单>`** | ✅ **有效**，约 3–4 MB/s，已下 552 MB |

---

## 5. LLM provider：paratera（已接入并验证）

- 新增 `config/llm_models/paratera.yaml`（`OpenAILLMPlugin` + `base_url: https://llmapi.paratera.com/v1` + `model: DeepSeek-V4-Flash`）。
  **注意**：该插件只在 provider 名恰好为 `llm.openai` 时才读 `OPENAI_BASE_URL`，其他名字走 YAML 的 `base_url`。
- `config/env` 增加 `PARATERA_API_KEY` / `PARATERA_BASE_URL`。
- `config/cyberverse.yaml` 的 `inference.persona.subagent` 从 `qwen` 切到 `paratera`，并显式写
  `provider_api: openai-completions` / `provider_base_url` / `provider_api_key_env`（Pi runtime 只对 `qwen` 有内置默认）。
- 同步更新了根目录 `cyberverse_config.yaml`（真实文件 + `model_config_dir: "config/avatar_models"`）。
- 顺带修掉一个缺口：**`openai` SDK 原本没装**（在 `llm`/`tts` 可选组里），导致 `llm.openai`、`tts.openai` 一直静默初始化失败。已 `uv pip install -e ".[llm,tts]"`。

**验证（三层）**：HTTP 直连 200；插件层流式返回"接入成功"；**gRPC `LLMService.GenerateStream`（provider=paratera）返回"服务打通"**。
日志：`Registered plugin: llm.paratera` → `Initialized plugin: llm.paratera`。

> **边界**：LLM provider ≠ 语音对话。`PersonaAgent` 要求 **omni** provider
> （`omni.qwen_omni` / `omni.doubao` / `omni.gemini` / `omni.grok` / `omni.openai_realtime`），各有各的 Key。
> 当前仍失败的：`tts.doubao`（缺 Key）、`omni.doubao`（缺 Key）、`asr.whisper`（缺 `.[asr]` 包）。
> 想一次打通实时语音，最省事是加一个 `DASHSCOPE_API_KEY`（omni + TTS + ASR 全覆盖）。

## 6. 豆包语音（omni.doubao）已接入并验证

- `config/env` 填 `DOUBAO_API_KEY`（**新版控制台 API Key，单独提供即可**；插件里 `if not api_key and not token` 才报错，
  所以 `DOUBAO_APP_ID`/`DOUBAO_ACCESS_TOKEN` 那两个 legacy 占位符可以不动）。鉴权走 `X-Api-Key` 头。

**逐资源探测结果（同一个 key，实测）**：

| 资源 | 端点 | 结果 |
|---|---|---|
| 实时语音对话 `volc.speech.dialog` | `wss://openspeech.bytedance.com/api/v3/realtime/dialogue` | ✅ 可连接 |
| 旧版单向 TTS `volc.service_type.10029` | `wss://openspeech.bytedance.com/api/v1/tts/ws_binary` | ✅ 可连接 |
| TTS 2.0 双向 `seed-tts-2.0` / `10029` / `10048` | `wss://openspeech.bytedance.com/api/v3/tts/bidirection` | ❌ HTTP 403 |

**验证层级**：① WS 鉴权握手 → ② 插件初始化（`Initialized plugin: omni.doubao`）→
③ **会话级** `DoubaoRealtimePlugin.check_voice()` 通过（真正 StartConnection → StartSession → SessionStarted → 正常结束）。
探测脚本：`.run/probe_doubao.py`；TTS 实测脚本：`.run/test_doubao_tts.py`。

> **已知限制**：仓库的 `tts.doubao` 走的是 **TTS 2.0 双向端点**，而该 key 未授权 → 运行时合成会 403
> （插件初始化不会连服务，所以不会在启动时报错，属于**延迟暴露的陷阱**）。
> **omni 模式下语音由 omni 直接产出，不经过 TTS**，所以不影响实时对话。
> 若要启用 TTS：在火山控制台为该 key 开通 TTS 2.0，或把 `config/tts_models/doubao.yaml` 改走已授权的旧版单向端点。

## 7. 交付物清单

| 文件 | 说明 |
|---|---|
| `docs/cyberverse/DEPLOY-GPU.md` | 从 0 部署手册（含国内源速查、7 个陷阱） |
| `docs/cyberverse/CONTINUE.md` | 本文件（续接用） |
| `/data/Avatar/.wheels/README-DOWNLOAD.md` | 人工下载交接说明 |
| `/data/Avatar/.wheels/torch-reqs.txt` | PyTorch CUDA 12.8 全套锁定清单（29 包，≈5.3 GB） |
| `/data/Avatar/.wheels/proj-reqs.txt` | 项目依赖锁定清单（147 包） |
| `/data/Avatar/.run/fetch_wheels.py` | 直连下载脚本（可选，最终没走通） |

**最终验收标准**：`.venv` 内 `torch.cuda.is_available()==True` 且设备名为 RTX 5090；
推理服务监听 50051；`pytest ... -m integration` 输出 `1 passed` 且产出非空 `artifacts/flash_head_smoke.mp4`；
`/api/v1/health` 返回 `inference_connected: true`；前端 5173 可访问。
