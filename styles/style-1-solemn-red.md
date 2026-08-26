# 风格一:庄重肃穆·中国红(政论经典)

> 定位:人民日报「人民要论」式政论片 —— 权威、庄重、有仪式感、大气开阔。
> 适用:时政评论、党报理论文章、重大主题宣传。
> 关键词:**红为点睛,白为底色,金为仪式**。红金占比 ≤20%,白 70%+。

## 一、配色 tokens(构建时逐字写入)

```yaml
colors:
  bg: "#FAFAF8"            # 暖白地面(唯一大底色)
  primary: "#C8161D"       # 主红:眉线 / 数字 / 强调 / 编号 / 分隔
  deep: "#8F1118"          # 深红:大标题 / 章节标题
  gold: "#C9A063"          # 金:五角星 / 标题下分隔线 / 引语出处前缀 / 结尾双线
  card: "#F9E8E9"          # 浅红卡片底
  card-border: "rgba(200,22,29,0.18)"
  accent-ghost: "rgba(200,22,29,0.08)"   # 大号幽灵编号 / 大面积装饰
  text: "#222222"          # 正文深灰(禁纯黑)
  muted: "#666666"         # 次正文
  light: "#969696"         # 弱灰
  divider: "#E5E5E5"
  positive: "#059669"
  negative: "#dc2626"
```

语义映射(换元素时按语义,不按字面 key):
- 大标题(hero/章节)→ 深红 `deep`;眉线/编号/数字 → 主红 `primary`
- 金只用于:开场五角星、标题下分隔线、引语出处短横、结尾署名双线。**金不用于正文文字**。
- 卡片 → 浅红底 + 细红边;正文 `text`;副题/出处/说明 → `muted`。

## 二、字体

| 角色 | family | 文件 |
|---|---|---|
| 标题/大数字 | `Source Han Serif SC Heavy` | `SourceHanSerifSC-Heavy.ttf` |
| 正文 | `Noto Sans SC` | `NotoSansSC-Regular.otf` |
| 强调/标签 | `Noto Sans SC Bold` | `NotoSansSC-Bold.otf` |

每帧 `<style>` 内 `@font-face`(root-relative `url("assets/fonts/…")`)。渲染机无系统 CJK 字体,必须自带。

## 三、背景装饰 SVG(每帧注入,置于背景 clip、内容之前)

### 变体 A —— 开场专用(含五角星 + 红绸带)

```html
<div class="clip hf-deco" data-start="0" data-duration="<帧时长>" data-track-index="1" style="position:absolute;inset:0;">
  <svg width="1920" height="1080" viewBox="0 0 1920 1080" xmlns="http://www.w3.org/2000/svg" style="position:absolute;inset:0;">
    <!-- 经纬网格 -->
    <g fill="none" stroke="#C9C9C9" stroke-width="1" opacity="0.12">
      <path d="M160 0V1080"/><path d="M320 0V1080"/><path d="M480 0V1080"/><path d="M640 0V1080"/><path d="M800 0V1080"/><path d="M960 0V1080"/><path d="M1120 0V1080"/><path d="M1280 0V1080"/><path d="M1440 0V1080"/><path d="M1600 0V1080"/><path d="M1760 0V1080"/>
      <path d="M0 120H1920"/><path d="M0 240H1920"/><path d="M0 360H1920"/><path d="M0 480H1920"/><path d="M0 600H1920"/><path d="M0 720H1920"/><path d="M0 840H1920"/>
    </g>
    <!-- 地球轨道环(右下,主红) -->
    <g fill="none" stroke="#C8161D">
      <circle cx="1540" cy="400" r="360" opacity="0.10"/><circle cx="1540" cy="400" r="290" opacity="0.07"/><circle cx="1540" cy="400" r="225" opacity="0.05"/>
    </g>
    <!-- 左上角红点阵 -->
    <g fill="#C8161D" opacity="0.10">
      <circle cx="90" cy="90" r="3"/><circle cx="126" cy="90" r="3"/><circle cx="162" cy="90" r="3"/><circle cx="198" cy="90" r="3"/><circle cx="234" cy="90" r="3"/><circle cx="270" cy="90" r="3"/>
      <circle cx="90" cy="126" r="3"/><circle cx="126" cy="126" r="3"/><circle cx="162" cy="126" r="3"/><circle cx="198" cy="126" r="3"/><circle cx="234" cy="126" r="3"/><circle cx="270" cy="126" r="3"/>
      <circle cx="90" cy="162" r="3"/><circle cx="126" cy="162" r="3"/><circle cx="162" cy="162" r="3"/><circle cx="198" cy="162" r="3"/><circle cx="234" cy="162" r="3"/><circle cx="270" cy="162" r="3"/>
    </g>
    <!-- 中央金色五角星(开场焦点,40px,0.9 不透明但不刺眼) -->
    <g id="gold-star" transform="translate(960,300)">
      <path d="M0,-40 L11.8,-12.4 L40,-12.4 L19,8.1 L27,35.3 L0,19.4 L-27,35.3 L-19,8.1 L-40,-12.4 L-11.8,-12.4 Z" fill="#C9A063" opacity="0.9"/>
    </g>
    <!-- 底部红绸带双曲线 + 金细线 -->
    <g fill="none">
      <path d="M0 900 Q960 830 1920 900" stroke="#C8161D" stroke-width="3" opacity="0.14"/>
      <path d="M0 960 Q960 890 1920 960" stroke="#C8161D" stroke-width="2" opacity="0.08"/>
      <path d="M0 980 Q960 960 1920 980" stroke="#C9A063" stroke-width="1.5" opacity="0.35"/>
    </g>
    <!-- AI 网络节点连线(跨帧连续元素) -->
    <g stroke="#B9B9B9" stroke-width="2" opacity="0.18" fill="none"><path d="M90 900 L330 760 L610 815 L915 630 L1330 690 L1700 560"/></g>
    <g fill="#B9B9B9" opacity="0.25">
      <circle cx="90" cy="900" r="5"/><circle cx="330" cy="760" r="5"/><circle cx="610" cy="815" r="5"/><circle cx="915" cy="630" r="5"/><circle cx="1330" cy="690" r="5"/><circle cx="1700" cy="560" r="5"/>
    </g>
  </svg>
</div>
```

### 变体 B —— 主体通用(去星、去绸带,保留网格+环+点阵+连线)

变体 A 中删除 `gold-star` 与红绸带组,环位置不变。内容密度高的帧可再降环 opacity 0.02。

### 变体 C —— 结尾署名(网格+环,底部红金双直线)

```html
<g fill="none">
  <line x1="860" y1="1010" x2="1060" y2="1010" stroke="#C8161D" stroke-width="3" opacity="0.5"/>
  <line x1="890" y1="1026" x2="1030" y2="1026" stroke="#C9A063" stroke-width="1.5" opacity="0.7"/>
</g>
```

## 四、帧类型模板(10 种)

### 1. opening —— 开场大标题(6–8s,无旁白或 1 句总起)

```
[金五角星,960,300]
[眉线] 人民要论 · 理论文章        # 主红 28px,字距 0.35em,居中
[主标题] 最多两行,每行 ≤14 字      # 思源宋体 Heavy 88px,深红,居中,行高 1.25
[金色分隔线] 240×2px               # 主标题下方
[副题] 一句话副题(可选)            # 黑体 32px,muted,居中
[底部绸带 SVG]
```

动效(单 paused timeline,时间相对帧起点):
- 星:`from {scale:0.6, autoAlpha:0, y:20} → to 正常,0.9s,power2.out`,起始 0s
- 眉线:fade+字距收紧 0.5s @0.2s;主标题:整块 fade-up 24px 0.7s @0.5s
- 金色分隔线:`scaleX 0→1` 0.5s @0.9s;副题:fade-up 0.5s @1.1s
- 绸带:opacity 0→0.14 1.2s @0.4s

### 2. section —— 章节页(4–5s,旁白 = 章节导语)

```
[左侧竖条] 8×120px,主红,垂直居中左侧 12%      # scaleY 0→1,0.5s,power2.out
[幽灵编号] 一 / 01                             # 宋体 Heavy 150px,accent-ghost,左侧 20%
[章节标题] ≤12 字                              # 宋体 Heavy 64px,深红
[章节副题] 一句话(可选)                        # 黑体 26px,muted
```

动效:竖条 → 编号 fade 0.4s → 标题 fade-up 0.6s → 副题 0.4s,依次错开 0.15s。

### 3. statement —— 论点陈述页(8–12s,主干页)

```
[眉线] 核心观点 / 关键论断           # 主红 26px,左对齐,前有 24px 红短横
[论点] 最多 2 行,每行 ≤18 字        # 宋体 Heavy 56px,#222222,左对齐
[支撑句] 1–2 行,每行 ≤24 字         # 黑体 Regular 30px,muted
[左缘金红竖线] 4×整高,红底金尖       # 装饰
```

动效:眉线 0.3s → 论点逐行 fade-up 0.5s → 支撑句 0.5s(延迟 0.2s)。

### 4. elaboration —— 论证展开页(8–12s,卡片阵)

```
[论点标题] 宋体 Bold 44px,深红,左对齐
[卡片 ×2~3] 横排,每卡:
  [编号] 01/02/03          # 主红,黑体 Bold 28px
  [要点标题] ≤10 字         # 黑体 Bold 30px,text
  [一句说明] ≤20 字         # 黑体 22px,muted
  [底边细线] 卡内底部 2px 红 # 装饰
  卡片:浅红底 #F9E8E9,圆角 12px,内边距 48px,宽 ~520px,高 ~300px
```

动效:标题 0.4s → 卡片依次 fade-up 40px + scale 0.98,每卡 0.45s,stagger 0.18s。

### 5. quote —— 金句/引语页(7–10s)

```
[大引号] 「”」宋体 130px,主红,居中上方        # fade+scale 0.9→1,0.6s
[引语] ≤3 行,每行 ≤14 字                     # 宋体 Bold 48px,text,居中
[出处前缀] —— 金色 40px 短横                  # scaleX 0→1
[出处] 作者/文献,黑体 26px,muted,居中
[背景] 大面积留白 + 右下环(opacity 0.05)
```

动效:引号 → 引语逐行 fade-up → 横线 → 出处,依次 0.15s 错开;引语每行 stagger 0.25s。

### 6. data —— 数据实证页(6–9s)

```
[大数字] 140–180px,宋体 Heavy,主红          # 从 0 滚动计数(GSAP innerText snap),1.2s,power2.out
[单位] 黑体 Bold 32px,text,紧贴数字
[说明] 一行 ≤20 字,黑体 26px,muted
[结论] 黑体 Bold 30px,text(可选)
[背景] 细网格 + 数字后浅红大圆(opacity 0.06)
```

多数据时 2–3 个并排,间距 ≥160px,数字依次入场 stagger 0.3s。

### 7. points —— 分点页(8–12s,3–4 点)

```
[标题] 宋体 Bold 44px,深红
[要点行 ×3~4]:
  [红点] 10px 圆,主红,左侧             # pop 0.3s
  [序号] 01 / 02…黑体 Bold 30px,主红
  [要点] ≤22 字,黑体 30px,text
  行距 96px
```

动效:标题 0.4s → 要点行依次 slide-up 30px + fade,stagger 0.35s(边念边出)。

### 8. process —— 递进流程页(8–12s,「是什么-为什么-怎么办」)

```
[标题] 宋体 Bold 44px,深红
[步骤 ×3~4] 横向链条:
  [圆] 直径 88px,白底,2px 红边,内编号红 32px   # pop scale 0→1,0.35s,back.out(1.4)
  [箭头] 灰色 60px →                            # scaleX 0→1,0.3s
  [步骤名] ≤10 字,黑体 Bold 28px,text
  [一句说明] ≤18 字,黑体 22px,muted
```

动效:圆 → 箭头交替依次入场,stagger 0.3s;说明随各自圆入场。

### 9. contrast —— 对比页(8–10s,「曾经/如今」「挑战/机遇」)

```
[左栏] [标签] 曾经        # 主红 24px,小胶囊描边
       [要点 ×2~3] ≤16 字  # 黑体 28px,muted
[中缝] 金色竖线 2×70%高     # scaleY 0→1,0.6s
[右栏] [标签] 如今 + 要点   # 要点 text,更重
[两栏标题] 宋体 Bold 40px,深红
```

动效:左栏 slide-left 60px 入场 → 中线 → 右栏 slide-right 60px,依次 0.2s 错开。

### 10. closing —— 结尾署名(4–5s,静帧,无旁白)

```
[细红横线] 120×2px,居中                    # scaleX 0→1,0.5s
[署名] 来源:人民日报 / 作者:XXX             # 黑体 28px,muted
[标题再现] 小号 40px,宋体 Heavy,深红,居中
[底部红金双线(变体 C)]
```

动效:横线 → 署名 fade 0.4s → 标题再现 fade-up 0.5s;全部完成后静置 ≥1.5s。

## 五、字幕样式(克制下划线式)

- 胶囊:浅红 `#F9E8E9` 底 + 细红边(`rgba(200,22,29,0.18)`),圆角 10px,无阴影;距底 8%,居中,内边距 16px 24px。
- 词级高亮:未读 `#666666`;已读 `#222222`;**当前词:主红 `#C8161D` + 2px 红下划线**。禁止实心红底块。
- 字号 32px,单行最多 ~22 字,超出换行按 2 行。

## 六、转场与动效总则

- 帧间转场:**crossfade 0.6s**(章节间)、cut(同章小节间)、opening 入场前与 closing 退场后 fade to/from black 0.8s。
- 缓动:一律 power2.out / power3.out,禁 bounce/elastic(数字 pop 的 back.out(1.4) 除外)。
- 位移 ≤48px;每帧只有一个主运动焦点;严禁连续快速推拉、无意义循环摆动。
- 全片同一舞台:主体帧共享同一构图基准(左对齐内容区 x=320–1600)与同一套卡片,让全片像一次连续镜头。

## 七、音轨规范

- 旁白 VO:CosyVoice3-0.5B 零样本克隆「male」音色(云扬新闻男声种子);兜底 edge-tts YunxiNeural。语速默认,每句间 0.35s 停顿。
- BGM:庄严管弦(慢板,弦乐+定音鼓轻击),**必须无版权风险素材**;音量 0.12 bed(VO 1.0),开场前 2s 可抬至 0.2 起势再回落,结尾 2s 淡出。
- 帧时长 = 该帧旁白时长 + 1.2s(静置余量),opening/closing 单独定长。

## 八、文案密度规范(注入 DeepSeek)

- 主标题 ≤28 字(两行);章节标题 ≤12 字;论点 ≤36 字;金句 ≤42 字;卡片要点 ≤10 字。
- 旁白每帧 1–2 句、15–35 字,口语化、庄重、不煽情、不喊口号。
- 全片旁白总字数 ≈ 目标时长(秒) × 4.2 字/秒(2 分钟 ≈ 500 字)。

## 九、HyperFrames 实现要点

- 每帧一个 `<section class="clip" data-start data-duration data-track-index="2">`;装饰 SVG 为独立 clip(`data-track-index="1"`,无动效或轻动效)。
- 根 `data-composition-id` + `data-width="1920" data-height="1080"`,30fps。
- 单一 `gsap.timeline({paused:true})` 注册到 `window.__timelines["<id>"]`;所有 tween 位置基于帧内偏移。
- BGM 一个 `<audio id="bgm">`(volume 0.12),VO 按帧 `<audio>`(或整轨 `data-media-start` 切);音频文件本地 `assets/audio/`。
- 字幕由 TTS 词级时间戳驱动(word-level highlight)。
