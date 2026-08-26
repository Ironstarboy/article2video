# 风格三:现代锐意·科技蓝(时代前沿)

> 定位:改革、科技创新、新质生产力、数字经济类文章 —— 现代、大气、数据感、有锐度。
> 适用:改革发展、科技政策、产业转型、青年话题。
> 关键词:**蓝为骨架,青为电流,琥珀一点**。浅色底 + 高对比蓝,节奏明快。

## 一、配色 tokens

```yaml
colors:
  bg: "#F5F8FC"            # 冷白(唯一大底色)
  primary: "#0A4DA3"       # 科技蓝:眉线 / 数字 / 编号 / 强调
  deep: "#0A2A5E"          # 深藏蓝:大标题 / 章节标题
  cyan: "#00A8CC"          # 亮青:连线 / 箭头 / 数据高亮 / 渐变端点
  amber: "#FFB400"         # 琥珀:关键数字 / 数据页强调 —— 每帧 ≤2 处
  card: "#E8F1FA"          # 浅蓝卡片底
  card-border: "rgba(10,77,163,0.18)"
  accent-ghost: "rgba(10,77,163,0.07)"
  text: "#1A2B3C"          # 正文深蓝灰(禁纯黑)
  muted: "#5A6B7D"         # 次正文
  light: "#8CA0B3"         # 弱灰蓝
  divider: "#E3EAF2"
  positive: "#0E9F6E"
  negative: "#E02424"
  gradient: "linear-gradient(90deg,#0A4DA3 0%,#00A8CC 100%)"  # 光带/芯片专用
```

语义映射:大标题 → 深藏蓝;眉线/编号/数字 → 科技蓝;数据/金句中的关键数字 → 琥珀或亮青;卡片 → 浅蓝底;渐变只用于光带与编号芯片。

## 二、字体(全黑体,现代感)

| 角色 | family | 文件 |
|---|---|---|
| 标题/大数字 | `Noto Sans SC Bold` | `NotoSansSC-Bold.otf` |
| 正文 | `Noto Sans SC` | `NotoSansSC-Regular.otf` |
| 强调 | `Noto Sans SC Bold` | `NotoSansSC-Bold.otf` |

## 三、背景装饰 SVG

### 变体 A —— 开场专用(网格 + 上升折线 + 光晕)

```html
<div class="clip hf-deco" data-start="0" data-duration="<帧时长>" data-track-index="1" style="position:absolute;inset:0;">
  <svg width="1920" height="1080" viewBox="0 0 1920 1080" xmlns="http://www.w3.org/2000/svg" style="position:absolute;inset:0;">
    <!-- 科技网格(细蓝线) -->
    <g fill="none" stroke="#0A4DA3" stroke-width="1" opacity="0.10">
      <path d="M160 0V1080"/><path d="M320 0V1080"/><path d="M480 0V1080"/><path d="M640 0V1080"/><path d="M800 0V1080"/><path d="M960 0V1080"/><path d="M1120 0V1080"/><path d="M1280 0V1080"/><path d="M1440 0V1080"/><path d="M1600 0V1080"/><path d="M1760 0V1080"/>
      <path d="M0 180H1920"/><path d="M0 360H1920"/><path d="M0 540H1920"/><path d="M0 720H1920"/><path d="M0 900H1920"/>
    </g>
    <!-- 右上光晕(蓝→青 radial) -->
    <radialGradient id="glow1" cx="0.5" cy="0.5" r="0.5">
      <stop offset="0%" stop-color="#00A8CC" stop-opacity="0.10"/>
      <stop offset="100%" stop-color="#00A8CC" stop-opacity="0"/>
    </radialGradient>
    <circle cx="1600" cy="260" r="560" fill="url(#glow1)"/>
    <!-- 左下上升折线(琥珀节点,青线) -->
    <g fill="none">
      <path d="M120 940 L420 800 L700 830 L1020 620 L1360 650 L1760 430" stroke="#00A8CC" stroke-width="3" opacity="0.30"/>
    </g>
    <g fill="#FFB400" opacity="0.5">
      <circle cx="120" cy="940" r="6"/><circle cx="420" cy="800" r="6"/><circle cx="700" cy="830" r="6"/><circle cx="1020" cy="620" r="6"/><circle cx="1360" cy="650" r="6"/><circle cx="1760" cy="430" r="6"/>
    </g>
    <!-- 右上角数据芯片装饰(渐变细框 + 圆点) -->
    <g opacity="0.35">
      <rect x="1640" y="60" width="200" height="96" rx="10" fill="none" stroke="#0A4DA3" stroke-width="1.5"/>
      <circle cx="1680" cy="90" r="5" fill="#00A8CC"/><line x1="1700" y1="90" x2="1820" y2="90" stroke="#0A4DA3" stroke-width="2" opacity="0.5"/>
      <line x1="1680" y1="120" x2="1780" y2="120" stroke="#0A4DA3" stroke-width="2" opacity="0.3"/>
    </g>
  </svg>
</div>
```

### 变体 B —— 主体通用(网格 + 光晕 + 折线,去掉数据芯片)

### 变体 C —— 结尾署名(网格 + 底部渐变细条)

```html
<rect x="810" y="1010" width="300" height="3" rx="1.5" fill="url(#gradBar)" opacity="0.8"/>
<!-- #gradBar: linearGradient 0.0 #0A4DA3 → 1.0 #00A8CC,方向 90deg -->
```

## 四、帧类型模板(10 种)

### 1. opening —— 开场大标题(6–8s)

```
[眉线] 时代观察 · 前沿评论            # 科技蓝 26px,字距 0.35em,居中,前有 40px 青短线
[主标题] 最多两行,每行 ≤14 字         # 黑体 Bold 86px,深藏蓝,居中,行高 1.25
[渐变光带] 240×4px,gradient           # scaleX 0→1,0.6s,power3.out
[副题] 一句话(可选)                   # 黑体 30px,muted
[背景:变体 A]
```

动效:眉线 0.3s → 标题 fade-up 28px 0.7s @0.4s → 光带 scaleX @0.9s → 副题 0.4s;折线 draw(stroke-dashoffset)1.4s @0.5s;光晕 opacity 0→1 1.5s。

### 2. section —— 章节页(4–5s)

```
[编号芯片] 01 / 02 / 03               # 88×88px,渐变蓝底,白字 Bold 40px,左上 16%  # pop scale 0.8→1,0.4s,back.out(1.3)
[章节标题] ≤12 字                     # 黑体 Bold 62px,深藏蓝
[青横线] 标题下 120×3px               # scaleX 0→1,0.4s
[章节导语] 一句话(可选)               # 黑体 26px,muted
```

动效:芯片 → 标题 fade-up → 横线 → 导语,错开 0.15s。

### 3. statement —— 论点陈述页(8–12s)

```
[眉线] 核心观点                       # 科技蓝 26px,前有 24px 青短横
[论点] 最多 2 行,每行 ≤18 字          # 黑体 Bold 54px,text,左对齐
  [内联高亮] 关键词 1–2 个             # span,科技蓝 + 浅蓝底 #E8F1FA 圆角 4px(可选)
[支撑句] 1–2 行,每行 ≤24 字           # 黑体 29px,muted
[左缘渐变竖条] 4×700px,gradient       # scaleY 0→1,0.6s
```

动效:竖条 → 眉线 → 论点逐行 fade-up → 高亮底 scaleX(随词) → 支撑句。

### 4. elaboration —— 论证展开页(8–12s,卡片阵)

```
[论点标题] 黑体 Bold 42px,深藏蓝
[卡片 ×2~3] 横排,每卡:
  [顶部细条] 3px 渐变条,卡内顶部      # scaleX 0→1,0.4s
  [编号] 01/02/03                     # 科技蓝,黑体 Bold 26px
  [要点标题] ≤10 字                   # 黑体 Bold 28px,text
  [一句说明] ≤20 字                   # 黑体 21px,muted
  卡片:浅蓝底 #E8F1FA,圆角 16px,内边距 44px,宽 ~520px
```

动效:标题 0.4s → 卡片依次 fade-up 40px + scale 0.98,stagger 0.16s(比风格一略快)。

### 5. quote —— 金句页(7–10s)

```
[大引号] 「”」黑体 120px,亮青,居中     # fade + scale,0.5s
[引语] ≤3 行,每行 ≤14 字              # 黑体 Bold 46px,text,居中
[关键词] 引语内 1 词琥珀高亮           # span 琥珀(可选,≤1 处)
[出处] 黑体 24px,muted,前缀青短横
```

动效:引号 → 引语逐行 fade-up(stagger 0.25s)→ 横线 → 出处。

### 6. data —— 数据实证页(6–9s,数据可视化重点)

```
[大数字] 130–170px,黑体 Bold,科技蓝     # 0 滚动计数 1.1s,power2.out
[单位] 黑体 Bold 30px,text
[迷你图表] 数字旁:柱状 3 根 / 折线 / 环形(二选一)
  [柱状] 3 根渐变蓝柱,高低错落,最高柱琥珀   # scaleY 0→1,stagger 0.15s
  [环形] stroke-dasharray 画弧,青描边      # dashoffset 动画 1.2s
[说明] 一行 ≤20 字,黑体 25px,muted
[结论] 黑体 Bold 29px,text(可选)
```

多数据并排时 2–3 组,间距 ≥160px,stagger 0.25s。

### 7. points —— 分点页(8–12s,3–4 点)

```
[标题] 黑体 Bold 42px,深藏蓝
[要点行 ×3~4]:
  [方块序号] 44×44px,圆角 8px,蓝底白字 22px   # pop 0.3s
  [要点] ≤22 字,黑体 29px,text
  [行下细线] divider 2px                      # scaleX 随行
```

动效:标题 0.4s → 行依次 slide-up 28px,stagger 0.3s。

### 8. process —— 递进流程页(8–12s)

```
[标题] 黑体 Bold 42px,深藏蓝
[步骤 ×3~4] 横向链条:
  [圆] 直径 84px,白底,2px 科技蓝边,内编号蓝 30px   # pop 0.3s,back.out(1.3)
  [青箭头] 60px,亮青,stroke 3px                   # draw 0.3s
  [步骤名] ≤10 字,黑体 Bold 27px,text
  [一句说明] ≤18 字,黑体 21px,muted
```

动效:圆 → 箭头交替,stagger 0.28s。

### 9. contrast —— 对比页(8–10s)

```
[左栏] [标签] 过去       # 灰蓝胶囊描边,muted 字
       [要点 ×2~3] ≤16 字 # 黑体 27px,muted
[中缝] 渐变竖条 4×70%高   # scaleY 0→1,0.5s
[右栏] [标签] 现在       # 蓝底白字胶囊
       [要点] text
```

动效:左栏 slide-left 56px → 中缝 → 右栏 slide-right 56px,错开 0.18s。

### 10. closing —— 结尾署名(4–5s,静帧)

```
[渐变细条(变体 C)]                        # scaleX 0→1,0.5s
[署名] 来源:… / 作者:…                    # 黑体 26px,muted
[标题再现] 小号 38px,黑体 Bold,深藏蓝
```

## 五、字幕样式

- 胶囊:浅蓝 `#E8F1FA` 底 + 细蓝边(`rgba(10,77,163,0.18)`),圆角 10px,无阴影;距底 8%。
- 词级:未读 `#8CA0B3`;已读 `#1A2B3C`;**当前词:科技蓝 `#0A4DA3` + 2px 下划线**。
- 字号 32px,单行 ~22 字。

## 六、转场与动效总则

- 帧间:章节间 crossfade 0.45s;同章小节 **push-slide UP 0.4s**(整体上推,方向一致);首尾 fade to/from black 0.7s。
- 缓动:power3.out 为主;芯片/圆 pop 用 back.out(1.3);位移 ≤56px;每帧一个主运动焦点。
- 节奏比风格一、二快 ~20%:stagger 0.15–0.28s,旁白节奏同步。

## 七、音轨规范

- VO:CosyVoice3-0.5B 零样本克隆「male_narrator」音色(云健解说腔种子);兜底 edge-tts YunxiNeural。
- BGM:现代管弦 + 轻电子脉冲(upbeat orchestral + pulse),音量 0.10 bed,结尾 2s 淡出。

## 八、文案密度规范(注入 DeepSeek)

同风格一 §八;语气:明快、有力、有数据意识,多用具体数字与「加速度」「新赛道」等时代语汇,不喊口号。

## 九、HyperFrames 实现要点

同风格一 §九;额外:SVG 渐变必须定义在每帧自己的 `<svg>` 内(不能跨帧引用 defs);push-slide 转场为整体位移,勿与帧内元素位移冲突。
