# 理论文章转视频(Theory-to-Video)

> 把人民日报「人民要论」、马院论文等理论长文,自动生成庄重的政论视频。
> 站点地址:**http://8.130.213.80:20013/ttv/**(VideoLab 云服务器)

## 一、使用流程

1. **上传文章**(txt / md / docx ≤20MB)或**粘贴文字**(≥50 字)
2. **选择风格**:快速套用三套经典预设,或按 **字体 × 配色 × 背景 × 动效** 四个维度自由组合(每个维度多种选项)
3. **选择时长**:30 秒 - 10 分钟(滑杆);分析引擎会按目标时长决定内容详略——长文短时自动压缩、短文长时逐层展开
4. **开始分析**:服务器调用本地 DeepSeek-V4-Flash(vLLM @20001)生成大纲、视频结构、逐帧脚本、风格推荐
5. **构建预览**:本地 CosyVoice3 配音 + 组装 HyperFrames 项目;预览页内嵌 **HyperFrames 播放器**与 **Studio 完整编辑器**(时间线、元素编辑等原有功能,经代理接入)
6. **渲染成片**:1080p 高清渲染(约 10-25 分钟,视时长),在线观看并下载 MP4

## 二、风格系统(四维度)

| 维度 | 选项 |
|---|---|
| 字体 | 宋体标题+黑体正文(庄重)/ 全宋体(学术)/ 全黑体(现代) |
| 配色 | 中国红(政论)/ 黛青墨韵(学术)/ 科技蓝(前沿)/ 藏蓝赭红(编辑部) |
| 背景 | 地球环经纬网格 / 水墨远山竹枝 / 科技网格折线 / 极简留白 |
| 动效 | 庄重缓叙(crossfade 0.7s)/ 明快节奏(支持上推)/ 极简静止 |

预设 = 经典组合:庄重肃穆·中国红 / 清雅学术·墨黛青 / 现代锐意·科技蓝。
详细样式脚本见 `styles/` 目录。

## 三、技术栈与部署位置(服务器)

- 站点:`/mnt/workspace/ttv/`(nginx 20013 端口 `/ttv/` 路由)
- 后端:FastAPI @ 127.0.0.1:8015;TTS 服务:CosyVoice3 @ 127.0.0.1:8016(GPU1)
- 分析:本地 vLLM DeepSeek-V4-Flash(`http://8.130.213.80:20001/v1`,零成本)
- 渲染:hyperframes CLI(全局安装)+ Chrome(chrome-headless-shell)
- 任务目录:`/mnt/workspace/ttv/jobs/<job_id>/`

## 四、运维

```bash
# 重启后端(任务自动恢复,preview 任务自动重建播放器/Studio)
ssh videolab "bash /mnt/workspace/ttv/deploy/start.sh"
# 重启 TTS 服务(含 PPU SDK 环境)
ssh videolab "bash /mnt/workspace/ttv/deploy/start-tts.sh"
# 查看日志
tail -f /mnt/workspace/ttv/backend.log /mnt/workspace/ttv/tts.log
```

BGM:把授权曲目放入 `/mnt/workspace/ttv/assets/bgm/`(solemn-red.mp3 / academic-ink.mp3 / modern-blue.mp3),缺文件时自动静音占位。

## 五、已知限制

- 短文超长视频有内容天花板:旁白不逐字朗读原文、不编造观点,超长时长以「论证展开+变换表述重述」尽力逼近,实际时长以真实配音为准
- Studio 编辑器经反向代理接入,WebSocket 类实时推送可能受限,核心编辑/预览功能可用
- 词级字幕为「帧内按字数均分」估算,如需精确对齐可后续接 whisper

## 六、版本

- v0.9:四维度风格系统、时长自适应分析、CosyVoice3 本地配音、Studio 接入、安全加固、完整字体
- 详见 `ARCHITECTURE.md` 与 `BUILD.md`
