# 搭建过程文档(从零到一)

> 记录本项目在 VideoLab 云服务器(阿里云 PAI-DSW,8.130.213.80)上的完整搭建过程,供重建/排障参考。
> 版本:v2.0(2026-08-28)

## 一、环境侦察(踩坑前提)

- 服务器为 PAI-DSW 实例,4× PPU-ZW810E(阿里自研 GPU,EIC SDK 提供 CUDA 兼容栈);`nvidia-smi` 在 `/usr/local/PPU_SDK/CUDA_SDK/bin/`
- **Node 不在默认 PATH**,位于 `/mnt/workspace/node/bin`(v22.23.2);所有 hyperframes 命令需 `export PATH=/mnt/workspace/node/bin:$PATH`
- 外网安全组仅放行 {20001, 20002, 20010, 20012, 20013, 20014, 20085},无空闲端口 → 站点挂在 20013 的 `/ttv/` 子路径(ComfyUI 端口,nginx 加 location + `auth_basic off`)
- 本地 DeepSeek:8.130.213.80:20001(平台网关 → 另一实例 vLLM,DeepSeek-V4-Flash,纯 HTTP 可用;HTTPS 仅外部可达;本机回环 20001 是 postgres,勿混淆)

## 二、基础依赖

```bash
# hyperframes CLI(全局)+ 固定版 Chrome
export PATH=/mnt/workspace/node/bin:$PATH
npm install -g hyperframes@0.8.15
hyperframes browser ensure          # 下载 chrome-headless-shell 152
hyperframes doctor                  # 验证:Node/FFmpeg/Chrome 全绿

# Python 依赖(系统 python3.12 + venv)
pip3 install fastapi uvicorn httpx python-multipart jieba fonttools
# fonttools 已加入 server/requirements.txt(此前漏声明,全新部署构建必崩)
```

## 三、字体(渲染必须完整版 OTF;网页端用子集)

**渲染用(必须完整版)**:子集字体缺生僻字会渲染成方框。`deploy/setup.sh` 已改为完整版下载。本地经 jsdelivr(<20MB 文件)与 ghfast.top 代理(>20MB 文件)下载后 scp 上传:

| 文件(服务器名) | 来源 |
|---|---|
| NotoSansSC-Regular.otf / Bold.otf | noto-cjk Sans/OTF/SimplifiedChinese(16-17MB) |
| SourceHanSerifCN-Heavy.otf / Regular.otf | source-han-serif OTF/SimplifiedChinese(24MB,jsdelivr 有 20MB 上限需走代理) |

放置:`/mnt/workspace/ttv/assets/fonts/`(渲染项目构建时直接引用,不再复制进每任务目录;网页端经 `/ttv/assets/` nginx 路由加载,`Cache-Control: max-age=31536000, immutable`)

**网页端用(子集 woff2)**:构建时用 fonttools 子集化——UI 用字约 3000 常用字 + 页面静态文案,每份 <300KB,配合 `unicode-range` 回退系统字体(修复此前 @font-face 引 /ttv/assets/ 但 nginx 无该路由导致字体 404 从未生效的问题)。

## 四、CosyVoice3 TTS 多实例池

1. **选型**:CosyVoice3-0.5B(中文 CER 0.000、音标控制多音字;Qwen3-TTS 中文需谨慎,仅作备用引擎)
2. **权重**:ModelScope 下载(HuggingFace 文件下载在本服务器网络不通)
   ```bash
   python3 -c "from modelscope import snapshot_download; snapshot_download('FunAudioLLM/Fun-CosyVoice3-0.5B-2512', local_dir='/mnt/models/CosyVoice3-0.5B')"
   ```
3. **运行时**:GitHub 源码克隆(不能用官方 requirements.txt——会把 torch 降到 2.3.1 破坏 PPU 专用 torch 2.10)
   ```bash
   git clone --depth 1 https://github.com/FunAudioLLM/CosyVoice.git cosyvoice-src
   cd cosyvoice-src && git submodule update --init   # third_party/Matcha-TTS(提供 matcha 模块)
   python3 -m venv --system-site-packages /mnt/workspace/ttv/tts-venv
   tts-venv/bin/pip install modelscope wetext sentencepiece hydra-core HyperPyYAML omegaconf librosa soundfile inflect pyworld conformer gdown wget lightning
   # 只挑官方 requirements 里与「模型推理正确性」相关的两项钉版(其余保持本机新 torch):
   tts-venv/bin/pip install "transformers==4.51.3" "tokenizers==0.21.4"
   # funasr 装不上 → 跳过(仅 instruct 模式需要);onnxruntime-gpu 无 PPU 轮子 → 用系统 CPU 版(仅 tokenizer/embedding 小头)
   ```
4. **关键坑**:
   - **必须 `source /usr/local/PPU_SDK/envsetup.sh`**,否则 PPU 内核 JIT 报 `PPU_SDK/PPU_HOME not exist`
   - **`transformers` 必须钉 4.51.3**(2026-09-12 定位,见 CHANGELOG v2.2「配音乱码根因」):语音 LLM 跑在 Qwen2 backbone 上,4.52+ 会让 speech token 序列乱掉 —— 听感「读音完全不正常、断断续续」,而**时长与峰值都正常**(ratio 0.84–0.88、峰值 -2dB),时长/静音验收全都发现不了。`tts-venv` 是 `--system-site-packages` 建的,不显式安装就会继承系统里更新的 transformers,所以这一条最容易被漏掉;`tts_server` 启动时会硬校验(不符即拒启,`TTV_TTS_ALLOW_UNPINNED=1` 可跳过),`python server/smoke_test.py` 也会校验 tts-venv 的实际版本
   - torchaudio 2.10 需要 torchcodec(无轮子)→ 服务内 monkeypatch 成 soundfile
   - v3 构造签名无 load_jit;prompt 文本必须含 `You are a helpful assistant.<|endofprompt|>` 前缀
   - **speed<1 非线性恶化(0.8 → 5 倍时长)**,服务端钳位下限 1.0(只用 1.0);文本 <15 字 vocoder 卷积报错(Qwen3-TTS 服务补 <8 字 400)
   - 三音色:新闻腔(云扬/云霞/云健)种子 wav → CosyVoice3 零样本克隆
5. **服务(三实例)**:`deploy/start-tts.sh` 以三份分别监听 **8016(GPU1)/ 8018(GPU2)/ 8019(GPU3)**,后端按帧轮询分发、并行合成(重启同样由该脚本统一拉起;pkill 模式 `tts_serve[r]`——uvicorn 进程 cmdline 是 `tts_server:app` 不带 .py);Qwen3-TTS 备用引擎 `deploy/start-tts-qwen.sh`(**8017,GPU2,默认停**)

## 五、主服务部署

```bash
mkdir -p /mnt/workspace/ttv/{jobs,assets/{fonts,bgm,vendor}}
# 上传 server/ web/ deploy/ 后:
bash /mnt/workspace/ttv/deploy/setup.sh     # 资产(含完整版字体)+ nginx
bash /mnt/workspace/ttv/deploy/start.sh     # 后端 8015
bash /mnt/workspace/ttv/deploy/start-tts.sh # TTS 三实例 8016/8018/8019
```

nginx:`/etc/nginx/ttv-locations.conf`(由 comfyui-20013 站点 include):
- `/ttv/` → web/ 静态(alias + auth_basic off;index.html 响应加 no-cache)
- `/ttv/assets/` → assets/ 静态(alias `/mnt/workspace/ttv/assets/`,Cache-Control max-age=31536000 immutable;gzip_types 补 text/css application/javascript application/json image/svg+xml,gzip_proxied any)
- `/ttv/api/` → 127.0.0.1:8015/api/(client_max_body_size 30M;limit_req 每秒 10 请求、突发 20)

## 六、流水线打通顺序(经验)

1. 先直连验证 DeepSeek(20001 纯 HTTP)→ 再写 analyze.py
2. 先合成一段音频验证 TTS → 再写服务化
3. 先手工构建一个 project 跑 `hyperframes check` → 修 lint/对比度 → 再渲染
4. hyperframes 构建器坑:对象键要引号(GSAP fromTo 三参会被当 toVars)、clip 上不 tween display/visibility、音频要 id、根设不透明背景防白闪
5. 渲染实测:1 分钟成片约 10 分钟(软件渲染,30+ Chrome worker 并行)

## 七、前端设计(编辑部气质)

- 设计规范来源:taste-skill(design-taste-frontend)+ DeepSeek vision 两轮截图评审
- 深藏蓝 #1E3A5F 结构色 + 赭红 #A61B29 强调色 + 暖白纸感 #F8F6F3 + 思源宋体标题 + 统一 8px 圆角
- 曾踩坑:对象键 `{solemn-red:…}` 未加引号 → 整段 JS 解析失败,所有交互失效(上传/风格/滑杆全挂)

## 八、版本与仓库

- 服务器代码仓:`/mnt/workspace/ttv`(git,标签 v2.0)
- 本地同步:`Labssh/vtt`(Labssh 目录内,含代码/文档/demo 成片)
- **assets 不入库**:.gitignore 已合并运行时产物与数据(jobs/、test-project/、deploy-tmp/、.bak-v11/、demo/)、Python 缓存(__pycache__/、*.pyc)、日志(*.log)、大字体资产(assets/fonts/、assets/bgm/、assets/vendor/)、密钥(.secrets/)与 TTS 环境(tts-venv/、tts-qwen-venv/、cosyvoice-src/),全部从服务器/官方源获取或本地构建,重建流程见本文档与 deploy/
- `deploy/patch-*.py` 一次性补丁脚本已从仓库移除(git 历史留档)
