# CyberVerse 启动手册（小白版）

**这是什么**：本地跑的数字人 + 语音助手。程序装在 `/data/Avatar/CyberVerse-main`。
**你现在要做的事**：只需记住下面两条命令 —— 一条启动，一条看状态。

---

## 一、启动（就一条命令）

```bash
bash deploy/cyberverse.sh start
```

- 第一次启动要等 **3–5 分钟**（加载数字人模型 + 编译加速），终端会停在"等待推理服务加载模型…"，这是正常的。
- 看到 **`推理服务已就绪`** 就成功了。
- 这条命令**可以重复执行**，已经在跑的服务会自动跳过，不会重复启动。
- 关掉终端不影响服务运行（服务在后台）。

## 二、打开页面

浏览器访问：

```
http://localhost:5173
```

## 三、看状态（任何时候想知道"它活着吗"）

```bash
bash deploy/cyberverse.sh status
```

正常的输出长这样：

```
推理服务     端口 50051  监听中
Go API       端口 8080   监听中
前端         端口 5173   监听中
TURN/WebRTC  端口 8443   监听中
健康检查     {"error":"","inference_connected":true,"sessions":0,"status":"ok"}
GPU          8824 MiB, 32607 MiB
```

**四个"监听中" + 健康检查里 `"status":"ok"` 就是一切正常。**

## 四、停止

```bash
bash deploy/cyberverse.sh stop
```

## 五、卡住了看日志

```bash
bash deploy/cyberverse.sh logs        # 实时跟踪三个服务的日志，Ctrl+C 退出（不会停服务）
```

---

## 六、出问题怎么办

| 现象 | 先做什么 |
|---|---|
| 浏览器打不开页面 | 跑 `deploy/cyberverse.sh status`，看"前端"是不是"未监听"；再看 `logs` |
| 健康检查显示 `"status":"error"` 且 `inference_connected:false` | 推理服务没起来或还在加载。`tail -50 /data/Avatar/CyberVerse-main/.run/logs/inference.log` 看最后几行 |
| 启动后过很久 50051 还是"未监听" | 正常情况首次要 3–5 分钟；超过 8 分钟看 inference.log 有没有报错 |
| 说话没反应 / 没声音 | **还缺语音的云端 Key**，见第七节 |
| 提示端口被占用 | 服务是别的方式启动的：`ss -ltnp \| grep -E ':(50051\|8080\|5173)'` 找到进程再 kill |
| 想彻底重启 | `deploy/cyberverse.sh stop && sleep 5 && deploy/cyberverse.sh start` |

---

## 七、云端 Key 现状（已配置，无需你操作）

| 能力 | Provider | 状态 |
|---|---|---|
| **实时语音对话**（说话 → 听懂 → 回答 → 出声） | 豆包 `omni.doubao` | ✅ **已配并验证**：key 可建立真实对话会话（`check_voice` 通过） |
| 文本大模型 | paratera `DeepSeek-V4-Flash` | ✅ 已配并验证（gRPC 层实测返回） |
| 豆包 TTS 2.0 双向合成 | `tts.doubao` | ⚠️ 该 key **未授权**该资源（403）。**omni 模式下语音由 omni 直接产出，不经过 TTS**，所以不影响正常对话 |
| 本地语音识别 Whisper | `asr.whisper` | ⚠️ 未安装对应包（可选，不需要 Key） |

想换别的厂商（阿里百炼 / Gemini / OpenAI 等）：编辑 `/data/Avatar/CyberVerse-main/config/env`，填对应 Key，然后

```bash
bash deploy/cyberverse.sh stop && sleep 5 && bash deploy/cyberverse.sh start
```

> 数字人**出画**完全不需要云端 Key；Key 只影响"语音对话"这一环。

---

## 八、画质与性能（这台 RTX 5090 的实测值）

当前设置：`FlashHead 1.3B Pro`，`464×464 @ 20fps`（官方表格里单卡 5090 的那一档）。

**实测**：每个视频块 28 帧、播放时长 1.400s，实际生成耗时 1.527s →

```
RTP = 1.527 / 1.400 = 1.09
```

按 README 自己的标准（RTP < 1 才算跑得赢播放），**目前约差 9%，严格说达不到 20fps 实时**。

想更流畅，改 `/data/Avatar/CyberVerse-main/config/avatar_models/flash_head.yaml`：

| 改动 | 效果 |
|---|---|
| `model_type: "lite"`（原 `"pro"`） | 画质下降、速度上升（官方说 lite 更快） |
| `height` / `width`: 464 → 416 或 384 | 分辨率和算力同时下降，明显更流畅 |
| `tgt_fps: 20` → `15` | 降低目标帧率，更容易达标（画面不再那么顺滑） |

改完必须重启：`deploy/cyberverse.sh stop && deploy/cyberverse.sh start`

**显存**：FlashHead 单独约占 **8.8 GB / 32 GB**，余量很充足（不是 24G 那种"刚好够用"）。

---

## 九、从别的电脑访问

需要服务器开放 `5173`、`8080`、`8443` 三个端口（`8443` 是 WebRTC 音视频必需）。
如果开不了端口，用 SSH 隧道：

```bash
ssh -L 8443:127.0.0.1:8443 -L 5173:127.0.0.1:5173 -L 8080:127.0.0.1:8080 用户名@服务器地址
```

然后在**你自己的电脑**上打开 `http://localhost:5173`。

---

## 十、文件都在哪

| 用途 | 路径 |
|---|---|
| 一键脚本 | `deploy/cyberverse.sh` |
| 程序本体 | `/data/Avatar/CyberVerse-main` |
| 配置文件 | `CyberVerse-main/config/`（`env` 放 Key，`cyberverse.yaml` 主配置） |
| 数字人参数 | `CyberVerse-main/config/avatar_models/flash_head.yaml` |
| 日志 | `CyberVerse-main/.run/logs/`（inference / server / frontend） |
| 模型权重 | `CyberVerse-main/checkpoints/`（15.4 GB） |
| Python 环境 | `CyberVerse-main/.venv`（uv 管理，勿手动装包） |

部署过程、踩坑记录、从 0 重装 → 见 `DEPLOY-GPU.md`。
