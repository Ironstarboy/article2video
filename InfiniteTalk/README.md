# InfiniteTalk —— 数字人说话视频生成

音频驱动的数字人视频生成（口型同步 + 头部/身体/表情跟随），支持图生视频和视频生视频，
可生成不限长度的说话视频。

- **上游项目**：https://github.com/MeiGen-AI/InfiniteTalk （Apache-2.0）
- **运行硬件**：T-HEAD PPU-ZW810E × 4（本机）
- **Web 服务**：http://127.0.0.1:8418

---

## 快速启动

```bash
source /usr/local/PPU_SDK/envsetup.sh
cd /mnt/workspace/ttv/InfiniteTalk/code
CUDA_VISIBLE_DEVICES=1 /mnt/workspace/ttv/InfiniteTalk/env/bin/python app.py \
    --ckpt_dir ../weights/Wan2.1-I2V-14B-480P \
    --wav2vec_dir ../weights/chinese-wav2vec2-base \
    --quant fp8 \
    --quant_dir ../weights/InfiniteTalk-fp8/quant_models/infinitetalk_single_fp8.safetensors
```

> ⚠️ `source /usr/local/PPU_SDK/envsetup.sh` **不能漏**，否则 CUDA 不可用。

---

## 目录说明

| 目录 | 大小 | 说明 |
|------|------|------|
| `code/` | 26M | 项目源码（含 `app.py` 网页界面、`generate_infinitetalk.py` 命令行入口） |
| `env/` | 4.0G | uv 隔离的 Python 环境（**勿删**） |
| `weights/` | 93G | 模型权重（**勿删**） |
| `vendor_wheels/` | 451M | PPU 厂商版 torch/torchvision/torchaudio/xformers 轮子（重建环境用） |
| `docs/` | 49K | 文档 |

### weights/ 明细

| 子目录 | 大小 | 说明 |
|--------|------|------|
| `Wan2.1-I2V-14B-480P/` | 67G | 万相基础模型（含 VAE、CLIP、T5 tokenizer） |
| `InfiniteTalk-fp8/` | 25G | InfiniteTalk fp8 量化权重 + t5_fp8 编码器 |
| `chinese-wav2vec2-base/` | 1.8G | 音频特征提取编码器 |

---

## 文档

| 文档 | 用途 |
|------|------|
| [`docs/启动文档.md`](docs/启动文档.md) | **小白版**：怎么启动、网页怎么用、常见报错 |
| [`docs/从0构建指南.md`](docs/从0构建指南.md) | **从零构建**：换机器/重建环境时看这个（含一键脚本） |
| [`docs/部署文档.md`](docs/部署文档.md) | 部署细节与参数说明 |

---

## 技术要点（踩坑总结）

### 1. PPU 必须用厂商版 PyTorch

PPU-ZW810E **不是通用 CUDA 设备**，公版 torch（cu121/cu128/cu130）**全部无法驱动**：

| torch | 结果 |
|-------|------|
| 公版 2.4.1 / 2.5.1 / 2.10.0 | ❌ `cudaGetDeviceCount` 报错 |
| 厂商 `2.10.0+ppu2.1.0` | ✅ 4 卡 / 96GB 每卡 |

厂商源：`https://aiext-pypi.mirrors.aliyuncs.com/pg1-pip/generic/`

### 2. 用 uv 装厂商轮子要加开关

厂商轮子文件名与内部版本号不一致（违反 PEP 427），uv 默认拒绝：

```bash
UV_SKIP_WHEEL_FILENAME_CHECK=1 uv pip install ...
```

### 3. 量化只能用 fp8

仓库只有 `t5_fp8.safetensors`（**没有** `t5_int8`），而代码按
`--quant` 的值拼 T5 权重文件名，所以 `--quant int8` 会直接失败。

### 4. 其他

- 厂商 torch 10.0 只提供 **cp312**，必须用 Python 3.12
- 源码 `wan/multitalk.py` 需删除 `from inspect import ArgSpec`（Python ≥3.11 已移除）
- GPU 0 被 ComfyUI 占用（约 90GB），本服务用 **GPU 1**

---

## 环境版本

| 组件 | 版本 |
|------|------|
| Python | 3.12.3 |
| torch | 2.10.0+ppu2.1.0 |
| torchvision / torchaudio | 0.25.0 / 2.10.0（PPU 版） |
| xformers | 0.0.30（PPU 版） |
| numpy | 1.26.4 |
| transformers | 5.16.1 |
| diffusers | 0.40.0 |
| peft | 0.20.0 |
| librosa | 0.11.0 |

依赖清单：`code/requirements.txt`（官方）+ `code/requirements-ppu.txt`（PPU 补充，含每个包的用途注释）
