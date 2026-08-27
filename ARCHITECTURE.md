# 项目结构文档(Theory-to-Video v1.0)

## 一、总体架构

```
浏览器 ──▶ nginx(8.130.213.80:20013 /ttv/)
             ├── /ttv/              静态前端(web/index.html,单文件 SPA)
             ├── /ttv/assets/       网页字体等静态资产
             └── /ttv/api/      ──▶ FastAPI 后端(127.0.0.1:8015)
                                      ├── DeepSeek 分析(本地 vLLM 20001,云 API 备份)
                                      ├── CosyVoice3 TTS(127.0.0.1:8016,GPU1;豆包/Qwen3 可选)
                                      ├── hyperframes 构建/渲染/check(CLI+Chrome)
                                      ├── /api/studio/<job>/  → Studio 编辑器代理(唯一预览入口)
                                      ├── /api/projects/<pid>/ → Studio 项目 API 转发(项目根/子路径/预览)
                                      └── 每任务 Studio 进程:4150-4153(4 槽,--foreground 直管,按需自愈)
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
│   ├── main.py              FastAPI:任务 API、Studio/项目代理、流水线阶段、check 质量门、Studio 槽位管理(串行化+自愈)、预览音频看门狗注入
│   ├── config.py            路径/端口/模型端点配置
│   ├── extract.py           txt/md/docx 提取(zip 炸弹防护)
│   ├── analyze.py           DeepSeek 分析:宣传视频(时长自适应提示词+校验门)+ 讲解视频两步分析(诊断文章类型与讲解方案 → 按章节分段生成逐帧脚本)+ 构建期二次拓展(expand_script)
│   ├── tts.py               配音:本地 CosyVoice3(重试×3 → 静音占位)+ 词级时间轴 + 真实时长向目标靠拢(apply_real_durations)
│   ├── tts_server.py        CosyVoice3 服务(8016,三音色零样本克隆,GPU1)
│   ├── tts_qwen_server.py   Qwen3-TTS 服务(8017,GPU2,可选引擎)
│   ├── smoke_test.py        冒烟回归:纯函数路径(extract/styles/时长靠拢/校验门/讲解校验)
│   ├── jobs.py              任务状态机(磁盘持久化,重启恢复;video_kind 持久化)
│   └── builder/
│       ├── styles.py        风格系统:四维度注册表(字体×配色×背景×动效)+ 组合合成 + SVG 装饰
│       ├── templates.py     13 种帧类型(10 种宣传 + 3 种讲解:textblock/annotation/method)× 维度属性渲染(HTML+GSAP tween 生成)
│       └── assemble.py      script.json → HyperFrames 项目(index.html + assets + BGM,重建前清理陈旧产物)
├── web/index.html           前端单文件 SPA(上传配置页 + 预览二级页,Studio 为唯一预览)
└── deploy/                  nginx 路由 / 启动脚本 / 一次性补丁
```

## 三、流水线状态机

```
uploaded → analyzing → analyzed → building → preview → rendering → rendered
              │                       │              │
              │ DeepSeek              │ TTS+二次拓展  │ hyperframes render
              │ 宣传:1 次调用(≈25-60s)│ +组装+Studio │ (Studio 保留,完成后回收)
              │ 讲解:两步(≈3-10 分钟) │ 同步拉起     │ 讲解片超时放宽到 3h
              └─ 失败可 /analyze 重跑 └─ 自动 check  └─ 成片就绪
```

关键设计(v1.0):
- **构建期 Studio 同步拉起**:组装完成后、置 preview 状态前启动 Studio(`--foreground` 直管进程,绕开 CLI 会话注册表),状态翻转瞬间编辑器即就绪(零等待);Studio 启动串行化 + 槽满回收确认端口释放,进程按需自愈
- **时长靠内容**:分析提示词按实测语速 4.2 字/秒规划旁白量;构建时旁白量不足目标自动二次拓展(两轮,加长旁白+增帧);apply_real_durations 按真实配音重算帧时长并向目标靠拢(留白仅作安全网)

关键设计(v1.1 讲解视频):
- **两步分析**:①一次调用诊断文章类型(策论/政论/综合分析/时政评论等)+ 讲解方案(章节、逐段要点、待批注句、可迁移写法);②按章节分组为 ≤7 分钟的分段,每段一次调用生成逐帧脚本,合并后整体校验。段级校验兜底(引用逐字/类型/旁白/时长),全局失败即报错可重跑
- **引用接地(grounding)+ 段级确定性修复**:模型输出不依赖自觉——textblock/annotation 引用先精确匹配,不中则模糊匹配(相似度 ≥80%、区间不膨胀),命中即用原文真实区间替换;批注类型词归一化到枚举(例证→论据、措施→对策…);data 值归一化为原文真实数字;帧时长向段目标等比缩放。修复后再校验,修不了的才反馈重试(3 次)
- **段级旁白上下限**:下限 1.6×秒数、上限 4.2×秒数(实测语速上限,超了物理上压不回目标时长);帧数按段时长占比分配硬上限(总上限 200,只兜底不硬压——模型按段落要点自然铺开,实测 5 分钟档 13-23 帧)
- **视频类型贯通**:video_kind(promo/lecture)持久化于任务状态;分析/校验/修订/拓展/编辑保存/渲染超时/留白参数全链路按类型分支;讲解 5-30 分钟(5 分钟一档,后端钳位到 300 的整数倍)
- **预览音频看门狗**:预览 HTML 注入脚本,自动恢复「时间线播放而音频静音/暂停」的自动播放策略死状态

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
| POST | /api/jobs | 上传(file/text + style/font/palette/bg/motion/duration/video_kind) |
| GET | /api/jobs/{id} | 状态 + 分析结果(自愈播放器/Studio) |
| POST | /api/jobs/{id}/analyze | 重新分析 |
| POST | /api/jobs/{id}/build | 构建(配音+组装+自动 check) |
| POST | /api/jobs/{id}/render | 渲染 MP4 |
| GET | /api/jobs/{id}/video | 下载成片 |
| GET | /api/player/{id}/… | play 播放器代理 |
| GET | /api/studio/{id}/… | Studio 编辑器代理 |

## 六、扩展点

- 新帧类型:builder/templates.py 加函数 + analyze.py FRAME_TYPES/CONTENT_REQUIRED + frames-schema.md(讲解帧加校验时注意 validate_script 的 check_quotes 分支)
- 新配色/背景:builder/styles.py 注册表加条目(前端自动出现)
- 精确字幕对齐:tts.py 词级时间轴换 whisper 对齐
- BGM:assets/bgm/ 放入同名 MP3 即生效
