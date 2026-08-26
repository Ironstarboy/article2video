# 风格二:清雅学术·墨黛青(书香学术)

> 定位:马院论文、学术理论文章 —— 书香、留白、水墨东方美学,学者书斋气。
> 适用:学术论文、理论研讨、思想史类文章。
> 关键词:**墨为骨,黛青为韵,朱砂一点**。大量留白,装饰极克制,色块占比 ≤15%。

## 一、配色 tokens

```yaml
colors:
  bg: "#F6F1E4"            # 宣纸米白(唯一大底色)
  primary: "#1F4E5F"       # 黛青:眉线 / 数字 / 编号 / 章节字
  deep: "#16394A"          # 深黛:大标题 / 章节标题
  ink: "#2A2A2A"           # 墨:正文(禁纯黑)
  ochre: "#8B5E34"         # 赭石:卡片边框 / 次要分隔 / 单位
  cinnabar: "#A63A2B"      # 朱砂:印章 / 对比中线 —— 每帧只允许 1 处,面积 <1%
  card: "#EFE9DA"          # 米色卡片底
  card-border: "rgba(139,94,52,0.35)"
  accent-ghost: "rgba(31,78,95,0.07)"   # 幽灵编号 / 大面积装饰
  text: "#2A2A2A"
  muted: "#5F5A50"         # 次正文(暖灰)
  light: "#9A9384"         # 弱灰
  divider: "#D8D2C2"
```

语义映射:大标题/章节 → 深黛;眉线/编号/数字 → 黛青;卡片 → 米色底 + 赭石细边;正文 → 墨;朱砂只出现在印章与对比中线。

## 二、字体

| 角色 | family | 文件 |
|---|---|---|
| 标题/引语 | `Source Han Serif SC Heavy` | `SourceHanSerifSC-Heavy.ttf` |
| 正文 | `Source Han Serif SC Regular` | `SourceHanSerifSC-Regular.otf` |
| 强调/标签 | `Noto Sans SC Bold` | `NotoSansSC-Bold.otf` |

正文用宋体(学术感),黑体只做小标签。

## 三、背景装饰 SVG

### 变体 A —— 开场专用(水墨山峦 + 竹枝 + 朱砂印章)

```html
<div class="clip hf-deco" data-start="0" data-duration="<帧时长>" data-track-index="1" style="position:absolute;inset:0;">
  <svg width="1920" height="1080" viewBox="0 0 1920 1080" xmlns="http://www.w3.org/2000/svg" style="position:absolute;inset:0;">
    <!-- 水墨远山(淡墨三层,底部) -->
    <g fill="none" stroke="#16394A" stroke-linecap="round">
      <path d="M0 1010 Q240 900 480 975 T960 960 T1440 985 T1920 950" stroke-width="2" opacity="0.22"/>
      <path d="M0 1045 Q280 960 560 1015 T1040 1000 T1520 1020 T1920 990" stroke-width="1.5" opacity="0.14"/>
      <path d="M0 1070 Q320 1010 640 1050 T1280 1035 T1920 1055" stroke-width="1" opacity="0.10"/>
    </g>
    <!-- 竹枝(右上,简笔) -->
    <g stroke="#1F4E5F" fill="none" opacity="0.30">
      <path d="M1720 90 L1720 420" stroke-width="3"/>
      <path d="M1720 140 L1660 120 L1715 150" stroke-width="2"/>
      <path d="M1720 210 L1780 185 L1725 220" stroke-width="2"/>
      <path d="M1720 300 L1655 275 L1712 310" stroke-width="2"/>
    </g>
    <g fill="#1F4E5F" opacity="0.22">
      <ellipse cx="1662" cy="118" rx="34" ry="9" transform="rotate(-18 1662 118)"/>
      <ellipse cx="1778" cy="183" rx="34" ry="9" transform="rotate(16 1778 183)"/>
      <ellipse cx="1657" cy="273" rx="34" ry="9" transform="rotate(-16 1657 273)"/>
    </g>
    <!-- 朱砂印章(开场焦点,白字「论」) -->
    <g id="seal" transform="translate(960,320)">
      <rect x="-44" y="-44" width="88" height="88" rx="8" fill="#A63A2B" opacity="0.92"/>
      <text x="0" y="12" font-family="'Source Han Serif SC Heavy',serif" font-size="52" fill="#F6F1E4" text-anchor="middle">论</text>
    </g>
    <!-- 淡墨网格(更疏,几乎不可见) -->
    <g fill="none" stroke="#8B5E34" stroke-width="1" opacity="0.06">
      <path d="M320 0V1080"/><path d="M640 0V1080"/><path d="M960 0V1080"/><path d="M1280 0V1080"/><path d="M1600 0V1080"/>
      <path d="M0 270H1920"/><path d="M0 540H1920"/><path d="M0 810H1920"/>
    </g>
  </svg>
</div>
```

### 变体 B —— 主体通用(远山最浅一层 + 淡墨网格,无印章无竹)

仅保留远山第一层(opacity 0.10)与网格;右上角保留一枚 40px 小印章(opacity 0.25)作为跨帧连续元素。

### 变体 C —— 结尾署名(远山全三层 + 底部赭石细线)

```html
<line x1="840" y1="1020" x2="1080" y2="1020" stroke="#8B5E34" stroke-width="1.5" opacity="0.5"/>
```

## 四、帧类型模板(10 种)

### 1. opening —— 开场大标题(6–8s)

```
[朱砂印章「论」,960,320]               # scale 0.7→1 + fade,0.8s,power2.out
[眉线] 理论文章 · 学术视角              # 黛青 26px,字距 0.4em,居中
[主标题] 最多两行,每行 ≤14 字          # 宋体 Heavy 84px,深黛,居中,行高 1.3
[副题] 一句话副题(可选)                # 宋体 30px,muted,居中
[底部远山 SVG]
```

动效:印章 → 眉线 0.4s → 标题逐字?否,整块 fade-up 0.7s → 副题 0.5s,错开 0.2s;远山三条依次 draw(stroke-dashoffset)1.2s @0.6s。

### 2. section —— 章节页(4–5s)

```
[中文数字] 壹 / 贰 / 叁               # 宋体 Heavy 140px,accent-ghost,左上 18%
[章节标题] ≤12 字                     # 宋体 Heavy 60px,深黛
[细墨线] 标题下方 160×1px             # scaleX 0→1,0.5s
[章节导语] 一句话(可选)               # 宋体 26px,muted
```

动效:数字 fade 0.4s → 标题 fade-up 0.5s → 墨线 → 导语,错开 0.15s。

### 3. statement —— 论点陈述页(8–12s)

```
[眉线] 核心论点                       # 黛青 26px,左对齐,前有 24px 赭石短横
[论点] 最多 2 行,每行 ≤18 字          # 宋体 Heavy 54px,墨,左对齐
[支撑句] 1–2 行,每行 ≤24 字           # 宋体 Regular 29px,muted
[左缘朱砂细竖线] 3×700px              # scaleY 0→1,0.6s —— 本帧唯一朱砂
```

动效:竖线 → 眉线 → 论点逐行 fade-up → 支撑句,错开 0.15s。

### 4. elaboration —— 论证展开页(8–12s,卡片阵)

```
[论点标题] 宋体 Heavy 42px,深黛
[卡片 ×2~3] 横排,每卡:
  [编号] 壹/贰/叁(或 01)      # 黛青,宋体 30px
  [要点标题] ≤10 字            # 黑体 Bold 29px,墨
  [一句说明] ≤20 字            # 宋体 22px,muted
  卡片:米色底 #EFE9DA,圆角 4px,赭石 1.5px 细边,内边距 44px,宽 ~520px
```

动效:标题 0.4s → 卡片依次 fade-up 32px,每卡 0.5s,stagger 0.2s。

### 5. quote —— 引语页(7–10s)

```
[大引号] 「”」宋体 120px,黛青,居中上方    # fade + scale 0.9→1,0.6s
[引语] ≤3 行,每行 ≤14 字                 # 宋体 Heavy 46px,墨,居中
[出处] 作者/文献,宋体 24px,muted          # 前缀赭石短横 scaleX
[小印章] 右下 36px,opacity 0.5
```

动效:引号 → 引语逐行 fade-up(stagger 0.3s)→ 横线 → 出处。

### 6. data —— 数据实证页(6–9s)

```
[大数字] 130–170px,宋体 Heavy,黛青       # 从 0 滚动计数,1.2s,power2.out
[单位] 宋体 Bold 30px,赭石,紧贴数字
[说明] 一行 ≤20 字,宋体 25px,muted
[背景] 数字后淡墨大圆(opacity 0.05)+ 细网格
```

### 7. points —— 分点页(8–12s,3–4 点)

```
[标题] 宋体 Heavy 42px,深黛
[要点行 ×3~4]:
  [序号] 其一 / 其二 / 其三        # 宋体 30px,黛青,宽 96px
  [要点] ≤22 字,宋体 29px,墨
  [行下细线] 赭石 1px,opacity 0.3   # scaleX 0→1 随行入场
```

动效:标题 0.4s → 行依次入场 + 细线 draw,stagger 0.35s。

### 8. process —— 递进流程页(8–12s)

```
[标题] 宋体 Heavy 42px,深黛
[步骤 ×3~4] 横向链条:
  [圆] 直径 84px,白底,1.5px 黛青边,内中文数字 28px    # pop 0.35s
  [墨线箭头] 60px,赭石,opacity 0.6                    # draw(stroke-dashoffset)0.3s
  [步骤名] ≤10 字,黑体 Bold 27px,墨
  [一句说明] ≤18 字,宋体 21px,muted
```

动效:圆 → 箭头交替,stagger 0.3s。

### 9. contrast —— 对比页(8–10s)

```
[左栏] [标签] 传统/曾经      # 黛青 24px,描边胶囊
       [要点 ×2~3] ≤16 字    # 宋体 27px,muted
[中缝] 朱砂细竖线 2×70%高     # scaleY 0→1,0.6s —— 本帧唯一朱砂
[右栏] [标签] 创新/如今 + 要点 # 要点墨色
```

动效:左栏 slide-left 50px → 中线 → 右栏 slide-right 50px,错开 0.2s。

### 10. closing —— 结尾署名(4–5s,静帧)

```
[朱砂印章] 48px「论」,居中                    # fade 0.5s
[署名] 来源:… / 作者:…                       # 宋体 26px,muted,居中
[标题再现] 小号 38px,宋体 Heavy,深黛,居中
[底部赭石细线(变体 C)]
```

## 五、字幕样式

- 胶囊:米色 `#EFE9DA` 底 + 赭石细边(`rgba(139,94,52,0.35)`),圆角 6px,无阴影;距底 8%。
- 词级:未读 `#9A9384`;已读 `#2A2A2A`;**当前词:黛青 `#1F4E5F` + 2px 下划线**。
- 字号 32px,单行 ~22 字。

## 六、转场与动效总则

- 帧间:crossfade **0.8s**(水墨晕染感);同章小节 cut;首尾 fade to/from black 0.9s。
- 缓动:power2.out / power3.out 为主,全程无弹性;位移 ≤36px;每帧一个主运动焦点。
- 一切「线」入场用 stroke-dashoffset draw,一切「块」入场用 fade-up;禁止大位移推拉。

## 七、音轨规范

- VO:CosyVoice3-0.5B 零样本克隆「female」音色(云霞知性女声种子);兜底 edge-tts XiaoxiaoNeural。
- BGM:古琴/笛箫 + 轻弦乐,慢板;音量 0.10 bed(VO 1.0),结尾 2.5s 淡出。
- 帧时长 = 旁白时长 + 1.3s 静置余量。

## 八、文案密度规范(注入 DeepSeek)

同风格一 §八(字数上限一致),语气改为:平实、学理、克制,可用「其一/其二」「质言之」「究其根本」等书面连接词,禁用口号。

## 九、HyperFrames 实现要点

同风格一 §九;额外:印章与竹枝 SVG 的 `<text>` 必须用已声明 @font-face 的宋体,否则渲染成方块。
