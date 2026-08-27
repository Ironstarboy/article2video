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
  "frames": [ /* 宣传 6-20 帧,见下 */ ],
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
- 旁白规则:每帧 ≥8 字(静帧除外)、1–2 句;单帧旁白上限 vo_cap 按档:≤90s 40 字 / ≤180s 90 字 / ≤360s 110 字 / >360s 130 字;总旁白字数 ≈ duration_sec × 4.2(宣传档位按 3.0/3.8/3.9/4.0 字/秒规划,余量由构建期留白分摊);帧时长 = 该帧旁白朗读时长 + 1.2s(opening/closing 单独定长)
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

1. 帧数 6-20(宣传档)
2. `frames[0].type == "opening"` 且 `frames[-1].type == "closing"`(closing 的 voiceover 为空)
3. 每帧 voiceover ≥8 字且非空(除 opening 可为空、closing 必为空);单帧上限 vo_cap 按档:≤90s 40 字 / ≤180s 90 字 / ≤360s 110 字 / >360s 130 字
4. `data` 帧的数字必须能在原文中找到(避免 DeepSeek 编造数据);`quote` 帧引语逐字接地到原文(精确→模糊匹配替换为原文区间),无法接地保留但写 `_meta.warning`
5. 所有 content 字段与 type 对应齐全,枚举值合法
6. |Σ duration − duration_sec| ≤ 10% × duration_sec
7. title/quote/thesis 等长度符合各字段上限

重试仍不合规时走**永不失败兜底**:带校验反馈重试 3 次,仍失败则对最近一次成功解析的脚本做确定性修复(丢最短旁白次要帧 + 时长缩放)后接受,`_meta.warning` 记录。

---

# 讲解视频(lecture)契约(v1.1)

讲解视频与宣传视频共用顶层结构与 10 种宣传帧,另增 3 种讲解帧与备课方案。整体生成分两步:
①诊断文章类型与讲解方案(lecture_plan)→ ②按章节分段生成 frames 后合并。

## lecture_plan(第一步产出,随脚本保存)

```jsonc
{
  "article_type": "申论策论文/申论政论文/申论综合分析题/时政评论/理论文章…(≤12字)",
  "type_reason": "判定依据",
  "central_task": "中心任务(像老师点题)",
  "audience": "讲解对象与深度定位",
  "chapters": [ { "number": "壹", "title": "章节标题(≤12字)", "minutes": 3.0,
                  "para_range": [1, 2], "content_plan": "本章教学安排" } ],
  "paragraph_notes": [ { "para": 1, "role": "开头引入/中心论点/分论点/论据/分析论证/对策/过渡/结尾升华(≤8字)",
                         "key_idea": "段意", "why_here": "为什么放在这里",
                         "teach_points": ["讲解要点×2-4"], "transferable": "可迁移写法(可空)",
                         "line_analysis": true,
                         "quote_sentences": ["值得逐句批注的原句×0-3,必须逐字摘自原文"] } ],
  "methods": ["全篇可迁移写作方法×3-6"],
  "language_points": ["语言表达分析×2-4"],
  "background_notes": ["需补充的公开背景×0-3"],
  "fact_vs_opinion": ["原文观点 vs 已知事实×1-3"],
  "exam_method_summary": "答题方法总结"
}
```

## 讲解专用帧(content 契约)

```jsonc
// textblock(原文段页:讲义式展示原文 + 本段作用标签)
{ "para": 3, "role": "本段作用(≤8字)", "text": "原文逐字摘录(100-200字,可截断,截断处……)", "focus": "一句话点出最值得注意的地方(≤40字,可选)" }

// annotation(逐句批注页:原句逐字 + 类型彩色标注 + 老师批注)
{ "para": 3, "sentences": [ { "text": "原句逐字(≤80字,可截断)", "kind": "论点|论据|分析|对策|过渡|金句",
                              "note": "老师批注(≤50字):这句为什么这么写/好在哪/怎么学" } ] }
// sentences 2-3 句

// method(写法提炼页:可迁移板书卡片)
{ "title": "标题(≤16字,如 可迁移写法)", "cards": [ { "id": "01", "heading": "写法名(≤14字)", "note": "怎么用/适用场景(≤40字)" } ] }
// cards 2-4 张
```

## 讲解校验门(validate_script kind="lecture")

1. 帧数 8-200;旁白每帧 8-240 字且 ≥2 句(老师口吻,严禁一句话带过;章节页 section 允许无旁白/短旁白——纯标题卡)
2. **原文引用逐字硬校验**:textblock.text 与 annotation.sentences[].text 规范化(去空白/引号/省略号、统一全半角标点)后必须是原文子串;textblock ≥8 字;para 为整数
3. annotation 的 kind 必须在枚举内(段级修复会把 例证/措施 等自由词归一化)、note ≤60 字、1-3 句;method 卡片 2-4 张
4. 宣传脚本不允许出现 textblock/annotation/method(反之亦然)
5. 其余与宣传校验门一致(data 数字真实、content 字段齐全)

## 段级确定性修复(analyze 阶段,校验前就地执行)

1. **引用接地**:精确不中 → 模糊匹配(锚点定位 + 匹配块覆盖度 ≥80%、区间不膨胀) → 用原文真实区间替换(保证逐字忠实)
2. **批注类型归一化**:例证→论据、措施→对策、承上启下→过渡、金句类词→金句,未知→分析
3. **data 值归一化**:「超过3.3万亿元」→ 提取数字 3.3(数字必须在原文中,否则保留让校验拦截编造)
4. **帧时长缩放**:非 opening/closing 帧 duration 等比缩放到段目标(构建期仍按真实配音重算)

修复后仍不达标的错误反馈回 LLM 重试(每段 3 次);段级旁白上限 = 4.2×段秒数(实测语速,超限物理上压不回目标时长)。
