# 项目结构文档(Theory-to-Video v0.9)

## 一、总体架构

```
浏览器 ──▶ nginx(8.130.213.80:20013 /ttv/)
             ├── /ttv/              静态前端(web/index.html,单文件 SPA)
             ├── /ttv/assets/       网页字体等静态资产
             └── /ttv/api/      ──▶ FastAPI 后端(127.0.0.1:8015)
                                      ├── DeepSeek 分析(本地 vLLM 20001)
                                      ├── CosyVoice3 TTS(127.0.0.1:8016,GPU1)
                                      ├── hyperframes 构建/渲染/check(CLI+Chrome)
                                      ├── /api/player/<job>/  → play 播放器代理
                                      └── /api/studio/<job>/  → Studio 编辑器代理
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
│   ├── main.py              FastAPI:任务 API、播放器/Studio 代理、流水线阶段、check 质量门
│   ├── config.py            路径/端口/模型端点配置
│   ├── extract.py           txt/md/docx 提取(zip 炸弹防护)
│   ├── analyze.py           DeepSeek 分析:时长自适应提示词 + 压缩/拓展策略 + 校验门
│   ├── tts.py               配音:本地 CosyVoice3(重试×3 → 静音占位,无外部 TTS)+ 词级时间轴
│   ├── tts_server.py        CosyVoice3 服务(8016,三音色零样本克隆,GPU1)
│   ├── jobs.py              任务状态机(磁盘持久化,重启恢复)
│   └── builder/
│       ├── styles.py        风格系统:四维度注册表(字体×配色×背景×动效)+ 组合合成 + SVG 装饰
│       ├── templates.py     10 种帧类型 × 维度属性渲染(HTML+GSAP tween 生成)
│       └── assemble.py      script.json → HyperFrames 项目(index.html + assets + BGM)
├── web/index.html           前端单文件 SPA(上传配置页 + 预览二级页)
└── deploy/                  nginx 路由 / 启动脚本 / 一次性补丁
```

## 三、流水线状态机

```
uploaded → analyzing → analyzed → building → preview → rendering → rendered
              │                       │              │
              │ DeepSeek(≈25s)        │ TTS+组装     │ hyperframes render
              └─ 失败可 /analyze 重跑 └─ 自动 check └─ 渲染期保留播放器
```

- 任务持久化:`jobs/<id>/state.json`,重启后自动恢复;进行中任务置 failed 可重触发
- 每任务:`input.<ext>`(原文)→ `input.txt`(提取文本)→ `script.json`(分析)→ `project/`(composition)→ `project/renders/out.mp4`

## 四、关键设计决策

1. **分析 = 1 次 LLM 调用 + 确定性模板管线**(非 agent 现场创作):快(≈25s)、并发友好、输出可预期;风格 skill 规则固化在 builder 中
2. **时长自适应**:按目标时长分四档(≤90 / ≤180 / ≤360 / ≤600s)规定帧数、旁白量、内容策略(压缩/均衡/拓展/深度拓展);旁白量按 CosyVoice3 实测语速(≈1.8-2.6 字/秒)规划
3. **语速恒为 1.0**(自然语速):实测克隆音色 speed<1 非线性恶化(0.8 → 5 倍时长怪音)
4. **帧时长以真实配音为准**:DeepSeek 的 duration 仅是初始估时,构建时按 TTS 实际时长重算
5. **字体完整版**(82MB 全 CJK):子集字体缺生僻字会渲染成方框
6. **播放器/Studio 双预览**:play(轻量)与 preview(完整编辑器)经后端反代接入;HTML/JS 绝对路径窄化重写(/assets/、/api/ 前缀)
7. **安全**:docx zip 炸弹防护(50MB/2000 条目)、文件名净化、路径防穿越、提示词注入隔离声明、前端 textContent 防 XSS

## 五、接口清单

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/styles | 四维度选项 + 预设 |
| POST | /api/jobs | 上传(file/text + style/font/palette/bg/motion/duration) |
| GET | /api/jobs/{id} | 状态 + 分析结果(自愈播放器/Studio) |
| POST | /api/jobs/{id}/analyze | 重新分析 |
| POST | /api/jobs/{id}/build | 构建(配音+组装+自动 check) |
| POST | /api/jobs/{id}/render | 渲染 MP4 |
| GET | /api/jobs/{id}/video | 下载成片 |
| GET | /api/player/{id}/… | play 播放器代理 |
| GET | /api/studio/{id}/… | Studio 编辑器代理 |

## 六、扩展点

- 新帧类型:builder/templates.py 加函数 + analyze.py FRAME_TYPES/CONTENT_REQUIRED + frames-schema.md
- 新配色/背景:builder/styles.py 注册表加条目(前端自动出现)
- 精确字幕对齐:tts.py 词级时间轴换 whisper 对齐
- BGM:assets/bgm/ 放入同名 MP3 即生效
