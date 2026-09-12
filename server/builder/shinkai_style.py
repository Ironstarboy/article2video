"""
shinkai_style.py — 新海诚风政务宣传视频风格卡片
=============================================
在 ttv 现有 modern-blue 基础上定制为 2D新海诚风商务微动画

使用方法（在仓库根目录下）：
  python3 -c "
    import sys; sys.path.insert(0, 'server')
    from builder.shinkai_style import SHINKAI_GOV_STYLE, generate_shinkai_script
    script = generate_shinkai_script('文章内容', target_duration=900)
    print(script)
  "
"""

from builder.styles import STYLES as BASE_STYLES

# ──────────────────────────────────────────────
# 新海诚风·政务微动画 专用风格卡片
# ──────────────────────────────────────────────

SHINKAI_GOV_STYLE_CARD = {
    "name": "shinkai-gov",
    "label": "2D新海诚风·商务微动画（Modern Cel-shaded Anime & Corporate Flat Art）",

    # 配色 —— 新海诚式通透光感
    "bg": "#F5F8FC",           # 纯白/浅冰蓝底
    "deep": "#1A3A5C",         # 深藏蓝（暗部/标题）
    "primary": "#2B5F8A",      # 商务冷蓝（主色）
    "accent1": "#D4A843",      # 暖金光晕（强调色）
    "accent2": "#C8161D",      # 警示正红（点缀）
    "accent3": "#2E8B57",      # 廉洁翠绿（数据/确认）
    "card": "rgba(43,95,138,0.15)",   # 蓝色半透明卡
    "card_border": "rgba(43,95,138,0.3)",  # 卡片边框
    "card_text": "#1A3A5C",     # 卡片内文字
    "muted": "#6B7B8D",        # 辅助文字
    "accent_text": "#D4A843",  # 金色高亮文字

    # 字体
    "font_title": "SourceHanSerifCN-Heavy, serif",   # 标题衬线
    "font_bold": "NotoSansSC-Bold, sans-serif",       # 粗体非衬线
    "font_body": "NotoSansSC-Regular, sans-serif",    # 正文非衬线
    "title_size": 80,
    "section_number_width": 100,
    "section_line_color": "#D4A843",   # 章节分隔线：金色

    # 装饰风格
    "deco_style": "shinkai",   # 自定义装饰

    # 转场
    "transition": "crossfade 0.6s",

    # 配音
    "voice": "male_news",      # 男声新闻感
    "bgm": "governmental_bgm_01",  # BGM
    "bgm_volume": 0.12,

    # 排版
    "card_radius": 8,
    "card_opacity": 0.30,
    "quote_size": 48,
    "data_number_size": 72,
    "list_item_spacing": 8,
}

# 覆盖到 STYLES 中（供 builder 模块使用）
BASE_STYLES["shinkai-gov"] = SHINKAI_GOV_STYLE_CARD


# ──────────────────────────────────────────────
# 装饰 SVG（新海诚风专用）
# ──────────────────────────────────────────────

def shinkai_deco_opening(style):
    """开场装饰——冷蓝渐变光晕 + 金色光束"""
    return f'''
    <svg width="100%" height="100%" viewBox="0 0 1920 1080"
         style="position:absolute;inset:0;pointer-events:none;">
      <defs>
        <linearGradient id="sk-bg-glow" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stop-color="rgba(43,95,138,0.08)"/>
          <stop offset="50%" stop-color="rgba(212,168,67,0.05)"/>
          <stop offset="100%" stop-color="rgba(43,95,138,0.03)"/>
        </linearGradient>
        <radialGradient id="sk-light-spot" cx="30%" cy="20%" r="60%">
          <stop offset="0%" stop-color="rgba(255,255,255,0.25)"/>
          <stop offset="100%" stop-color="rgba(255,255,255,0)"/>
        </radialGradient>
      </defs>
      <rect width="100%" height="100%" fill="url(#sk-bg-glow)"/>
      <rect width="100%" height="100%" fill="url(#sk-light-spot)"/>
      <!-- 右上金色光束 -->
      <line x1="1920" y1="0" x2="1200" y2="1080"
            stroke="rgba(212,168,67,0.08)" stroke-width="2"/>
      <line x1="1920" y1="-100" x2="1000" y2="1080"
            stroke="rgba(212,168,67,0.04)" stroke-width="1"/>
      <!-- 装饰性网格线 -->
      <line x1="0" y1="540" x2="1920" y2="540"
            stroke="rgba(43,95,138,0.06)" stroke-width="1"/>
      <line x1="960" y1="0" x2="960" y2="1080"
            stroke="rgba(43,95,138,0.04)" stroke-width="1"/>
    </svg>'''


def shinkai_deco_section(style):
    """章节过渡装饰——垂直蓝光柱"""
    return f'''
    <svg width="100%" height="100%" viewBox="0 0 1920 1080"
         style="position:absolute;inset:0;pointer-events:none;">
      <rect width="100%" height="100%" fill="rgba(43,95,138,0.03)"/>
      <!-- 左右冷蓝光柱 -->
      <rect x="160" y="0" width="2" height="1080"
            fill="rgba(43,95,138,0.15)"/>
      <rect x="1758" y="0" width="2" height="1080"
            fill="rgba(43,95,138,0.15)"/>
    </svg>'''


def shinkai_deco_closing(style):
    """片尾装饰——冷蓝金双线"""
    return f'''
    <svg width="100%" height="100%" viewBox="0 0 1920 1080"
         style="position:absolute;inset:0;pointer-events:none;">
      <defs>
        <linearGradient id="closing-top" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stop-color="rgba(212,168,67,0)"/>
          <stop offset="30%" stop-color="rgba(212,168,67,0.12)"/>
          <stop offset="50%" stop-color="rgba(212,168,67,0.08)"/>
          <stop offset="70%" stop-color="rgba(43,95,138,0.12)"/>
          <stop offset="100%" stop-color="rgba(43,95,138,0)"/>
        </linearGradient>
      </defs>
      <rect width="100%" height="100%" fill="url(#sk-bg-glow)"/>
      <rect x="200" y="520" width="1520" height="1" fill="rgba(212,168,67,0.3)"/>
      <rect x="300" y="524" width="1320" height="1" fill="rgba(43,95,138,0.2)"/>
    </svg>'''


# ──────────────────────────────────────────────
# 新海诚风专属 Prompt 模板
# ──────────────────────────────────────────────

SHINKAI_GOV_SYSTEM = """你是政务宣传视频编剧和分镜师。根据输入的政务/政策类文章，输出JSON格式的分镜脚本。

【核心风格：2D新海诚风商务微动画】
美术画风：现代2D赛璐璐日系动漫风格，融合扁平矢量商务插画，线条利落闭合，无写实噪点。
色彩与光影：新海诚式通透光感与大面积漫反射：
  - 主色调：商务冷蓝 #2B5F8A、纯白 #F5F8FC
  - 辅助色：暖金光晕 #D4A843、警示正红 #C8161D、廉洁翠绿 #2E8B57
  - 冷暖反差鲜明，营造严肃而不失温情的政务感
动态特征：低幅度呼吸感微动(Cinemagraph)：
  - 极慢镜头推拉/平移（30秒移动5%）
  - 流体上升（茶汽、旗帜飘动）
  - 水波涟漪、车流、绿植微摇
包装风格：现代扁平化政务宣教风：
  - 蓝色半透明法规卡片(圆角8px, 透明度30%)
  - 弹跳矢量花字动画
  - 数据可视化采用冷蓝+翠绿柱状图

【输出JSON格式】
{
  "title": "视频标题",
  "frames": [
    {
      "id": 0,
      "type": "opening",
      "content": {"title": ["标题行1","标题行2"], "eyebrow": "政策解读", "subtitle": "副标题"},
      "dialogue": "各位观众大家好，今天我们来学习...",
      "duration": 8,
      "transition": "crossfade"
    }
  ]
}

【字段约束】
- frames[]: 约18-24帧，每帧5-7秒，总量约15分钟(900秒)
- type: opening/section/statement/elaboration/quote/data/points/process/contrast/closing
- content: 按帧类型不同包含不同子字段
- dialogue: 旁白文本，按4.2字/秒控制长度
- duration: 时长（秒）
- transition: crossfade（推荐）
"""


def generate_shinkai_frames(articles: list[str], target_duration: int = 900) -> dict:
    """将文章列表转化为新海诚风分镜脚本

    Args:
        articles: 文章段落列表
        target_duration: 目标时长（秒），默认900（15分钟）

    Returns:
        script: 符合 builder/templates.py 要求的 script dict
    """
    from datetime import datetime

    # 合并所有段落
    full_text = "\n\n".join(articles)

    # 按段落数估算帧数
    num_articles = len(articles)
    total_frames = min(max(18, num_articles * 3), 30)
    avg_duration = target_duration / total_frames

    script = {
        "title": "政务政策解读",
        "generated_at": datetime.now().isoformat(),
        "target_duration": target_duration,
        "total_frames": total_frames,
        "style": "shinkai-gov",
        "frames": [],
    }

    # 为每段文章生成帧序列
    idx = 0

    for ai, article_text in enumerate(articles):
        lines = article_text.strip().split("\n")
        title = lines[0] if lines else f"政策要点 {ai+1}"
        body_lines = [l for l in lines[1:] if l.strip()]

        # 开场帧（每段的第一个帧或第一段用 opening）
        if ai == 0:
            # Opening: 完整开场
            script["frames"].append({
                "id": idx,
                "type": "opening",
                "content": {
                    "title": [title[:20], ""],
                    "eyebrow": "政策解读",
                    "subtitle": "国务院办公厅 发布"
                },
                "dialogue": f"各位观众朋友，今天我们来解读{title}相关政策内容。",
                "duration": min(avg_duration * 1.5, 10),
                "transition": "crossfade",
            })
            idx += 1
        else:
            # Section: 章节过渡
            script["frames"].append({
                "id": idx,
                "type": "section",
                "content": {
                    "number": f"第{'一二三四五六七八九十'[ai if ai < 10 else 9]}部分",
                    "title": title[:20],
                },
                "dialogue": f"接下来，我们来看{title}方面。",
                "duration": min(avg_duration * 1.2, 8),
                "transition": "crossfade",
            })
            idx += 1

        # 正文帧
        body_chunks = [body_lines[i:i+3] for i in range(0, len(body_lines), 3)]
        for ci, chunk in enumerate(body_chunks):
            if not chunk:
                continue

            chunk_text = "".join(chunk)[:80]

            # 轮流使用不同帧类型
            if ci % 5 == 0:
                # Statement 帧
                script["frames"].append({
                    "id": idx,
                    "type": "statement",
                    "content": {"thesis": chunk_text},
                    "dialogue": chunk_text[:80],
                    "duration": min(avg_duration, 7),
                    "transition": "crossfade",
                })
            elif ci % 5 == 1:
                # Points 帧
                script["frames"].append({
                    "id": idx,
                    "type": "points",
                    "content": {"points": [l.strip()[:40] for l in chunk if l.strip()]},
                    "dialogue": f"具体包括以下几个方面：{'、'.join([l.strip()[:15] for l in chunk if l.strip()])}。",
                    "duration": min(avg_duration, 6),
                    "transition": "crossfade",
                })
            elif ci % 5 == 2:
                # Elaboration 帧
                script["frames"].append({
                    "id": idx,
                    "type": "elaboration",
                    "content": {"cards": [{"title": l.strip()[:15], "text": l.strip()[:60]}
                                           for l in chunk if l.strip()]},
                    "dialogue": f"详细来说，{chunk_text[:60]}。",
                    "duration": min(avg_duration * 1.2, 7),
                    "transition": "crossfade",
                })
            elif ci % 5 == 3:
                # Quote 帧
                script["frames"].append({
                    "id": idx,
                    "type": "quote",
                    "content": {"quote": chunk_text[:60], "source": title[:15]},
                    "dialogue": f"正如官方指出，{chunk_text[:50]}。",
                    "duration": min(avg_duration, 6),
                    "transition": "crossfade",
                })
            else:
                # Process 帧
                script["frames"].append({
                    "id": idx,
                    "type": "process",
                    "content": {"steps": [{"title": l.strip()[:15], "text": l.strip()[:40]}
                                          for l in chunk if l.strip()]},
                    "dialogue": f"推进过程如下：{chunk_text[:50]}。",
                    "duration": min(avg_duration * 1.3, 8),
                    "transition": "crossfade",
                })
            idx += 1

        # 追加 data 帧（每段结束处加一组数据展示）
        if ai < len(articles) - 1:
            script["frames"].append({
                "id": idx,
                "type": "data",
                "content": {
                    "items": [
                        {"label": "目标完成率", "value": "95%"},
                        {"label": "覆盖范围", "value": "全国"},
                        {"label": "实施周期", "value": "3年"},
                    ]
                },
                "dialogue": "数据显示，各项指标稳步推进中。",
                "duration": min(avg_duration * 1.3, 8),
                "transition": "crossfade",
            })
            idx += 1

    # 尾帧
    script["frames"].append({
        "id": idx,
        "type": "closing",
        "content": {
            "cta": "感谢观看",
            "source": "国务院办公厅",
            "date": "2026年"
        },
        "dialogue": "感谢您的收看，我们下期再见。",
        "duration": 8,
        "transition": "crossfade",
    })

    script["total_frames"] = len(script["frames"])
    return script


# ──────────────────────────────────────────────
# 通过 DeepSeek API 生成分镜
# ──────────────────────────────────────────────

def call_deepseek_for_script(article: str, style: str = "shinkai-gov",
                              target_duration: int = 900) -> dict:
    """调用本地 DeepSeek vLLM 生成新海诚风分镜脚本"""
    import httpx
    import json

    DEEPSEEK_URL = "http://8.130.213.80:20001/v1"

    prompt = (
        f"用户输入的文章是一篇政务/政策类文章。\n"
        f"请将其拆分为约24-30帧的分镜脚本，总时长约{target_duration}秒（15分钟）。\n\n"
        f"严格按照2D新海诚风商务微动画的风格要求输出。\n\n"
        f"【文章内容】\n{article[:12000]}"
    )

    messages = [
        {"role": "system", "content": SHINKAI_GOV_SYSTEM},
        {"role": "user", "content": prompt},
    ]

    resp = httpx.post(
        f"{DEEPSEEK_URL}/chat/completions",
        json={
            "model": "DeepSeek-V4-Flash",
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 32768,
        },
        timeout=600.0,
    )

    if resp.status_code != 200:
        raise RuntimeError(f"DeepSeek API 返回 {resp.status_code}: {resp.text[:200]}")

    import re
    content = resp.json()["choices"][0]["message"]["content"]
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.M)
    m = re.search(r"\{.*\}", content, flags=re.S)
    if not m:
        raise RuntimeError("DeepSeek 输出未包含 JSON")

    return json.loads(m.group(0))


# ──────────────────────────────────────────────
# 快速本地分镜生成（不需要 DeepSeek 调用）
# ──────────────────────────────────────────────

def sample_script() -> dict:
    """生成本地测试用的新海诚风政务视频示例分镜"""
    articles = [
        "2026年国务院印发《关于加强政务信息化建设的指导意见》，提出到2028年建成覆盖全国的政务大数据体系。",
        "规划提出三大核心目标：一网通办率达到95%、建成国家政务大数据中心、推进AI辅助决策系统。",
        "具体措施包括：制定统一数据标准、升级基础设施、强化安全保障、培养数字人才。",
        "预期成效：群众办事材料精简60%，审批时限压缩50%，政务数据共享率达85%以上。",
    ]
    return generate_shinkai_frames(articles, target_duration=900)


if __name__ == "__main__":
    import json
    script = sample_script()
    print(json.dumps(script, ensure_ascii=False, indent=2))
    print(f"\n生成 {script['total_frames']} 帧，预估时长 ~{sum(f.get('duration',5) for f in script['frames'])}秒")
