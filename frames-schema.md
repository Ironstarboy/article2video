# DeepSeek 分析输出契约(hyperframes 脚本 JSON Schema)

> 本文件是「DeepSeek 分析 → HyperFrames 构建」的接口契约。DeepSeek 必须严格输出下方 JSON;
> 构建器(builder)按 `style` + `frames[].type` 渲染。注入 DeepSeek prompt 时原样引用。

## 顶层结构

```json
{
  "title": "视频标题(≤28 字,两行内)",
  "subtitle": "副题(可选,≤20 字)",
  "duration_sec": 120,
  "style_recommendation": {
    "style": "solemn-red",
    "reason": "一句话理由"
  },
  "analysis": {
    "core_argument": "一句话核心论点(视频必须传达的那件事)",
    "outline": "文章大纲分析(3-5 行:行文逻辑/层次关系)",
    "structure": "视频结构说明(开场钩子→主体层次→收束,3-5 行)"
  },
  "frames": [ /* 8-16 帧,见下 */ ],
  "voiceover_full": "全部旁白按帧顺序合并(不含开场/结尾静帧)",
  "credits": { "source": "来源名称,如 人民日报", "author": "作者名,可空" }
}
```

- `style` 取值:`solemn-red`(庄重肃穆·中国红)/ `academic-ink`(清雅学术·墨黛青)/ `modern-blue`(现代锐意·科技蓝)
- `duration_sec`:与用户输入的目标时长一致(允许 ±10%)
- `frames[].duration` 之和 ≈ `duration_sec`

## frames[] 公共字段

```json
{
  "index": 1,
  "type": "opening",
  "scene": "一句话画面意图(画面里有什么,写清楚)",
  "voiceover": "本帧旁白文本(开场/结尾静帧为空字符串)",
  "duration": 7,
  "transition_in": "cut",
  "beat": "好奇/笃定/推进/叹服/坚定(目标情绪)",
  "content": { /* type 专属字段 */ }
}
```

- `type` 枚举:`opening | section | statement | elaboration | quote | data | points | process | contrast | closing`
- `transition_in` 枚举:`cut | crossfade | push_up`(同章小节间 cut,章节间 crossfade,push_up 仅 modern-blue)
- 旁白规则:每帧 1–2 句、15–35 字;总旁白字数 ≈ duration_sec × 4.2;帧时长 = 该帧旁白朗读时长 + 1.2s(opening/closing 单独定长)
- 结构铁律:第 1 帧必为 `opening`(开场钩子:设问/反直觉/数字),最后一帧必为 `closing`(署名静帧);
  第 2 帧即落地核心论点;主体 3–6 帧层层递进(是什么-为什么-怎么办 或 问题-分析-对策);章节 ≥2 个时用 `section` 分章

## content 按 type 的专属字段

```jsonc
// opening
{ "eyebrow": "眉线文字,如 人民要论 · 理论文章(≤12 字)", "title": "主标题(≤28 字,可含 \n 分两行)", "subtitle": "副题(可选)" }

// section(章节页)
{ "number": "一/二/三 或 01", "title": "章节标题(≤12 字)", "subtitle": "章节导语(可选,≤18 字)" }

// statement(论点陈述页,主干)
{ "eyebrow": "眉线,如 核心观点/关键论断(≤8 字)", "thesis": "论点(≤36 字,可 \n 分两行)", "support": "支撑句(1-2 句,≤48 字)" }

// elaboration(论证展开页,卡片阵)
{ "title": "论点标题(≤16 字)", "cards": [ { "id": "01", "heading": "要点标题(≤10 字)", "note": "一句说明(≤20 字)" } ] } // cards 2-3 个

// quote(金句/引语页)
{ "quote": "引语(≤42 字,可 \n 分三行)", "source": "出处(作者/文献,≤20 字)", "keyword": "引语内需高亮的一个词(可选,≤4 字)" }

// data(数据实证页)
{ "items": [ { "value": "16.4", "unit": "万亿元", "note": "说明(≤20 字)", "chart": "bar" } ], "conclusion": "结论(可选,≤24 字)" }
// items 1-3 个;chart 取值 bar/line/ring/null;value 必须是文章里真实出现的数字

// points(分点页)
{ "title": "标题(≤16 字)", "points": [ "要点(≤22 字)" ] } // 3-4 个

// process(递进流程页,是什么-为什么-怎么办)
{ "title": "标题(≤16 字)", "steps": [ { "name": "步骤名(≤10 字)", "note": "一句说明(≤18 字)" } ] } // 3-4 步

// contrast(对比页)
{ "left_label": "曾经/传统/挑战(≤6 字)", "left_points": [ "要点(≤16 字)" ], "right_label": "如今/创新/机遇(≤6 字)", "right_points": [ "要点(≤16 字)" ] } // 各 2-3 条

// closing(结尾署名,静帧无旁白)
{ "source": "来源名称", "author": "作者名(可空)", "title": "标题再现(取顶层 title)" }
```

## 校验门(builder 侧硬校验,失败则重试分析)

1. `frames[0].type == "opening"` 且 `frames[-1].type == "closing"`(closing 的 voiceover 为空)
2. 每帧 voiceover 非空(除 opening 可为空、closing 必为空)且 ≤60 字
3. `data` 帧的数字必须能在原文中找到(避免 DeepSeek 编造数据)
4. 所有 content 字段与 type 对应齐全,枚举值合法
5. |Σ duration − duration_sec| ≤ 10% × duration_sec
6. title/quote/thesis 等长度符合各字段上限
