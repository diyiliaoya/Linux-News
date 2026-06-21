#!/usr/bin/env python3
"""
Linux新闻抓取+翻译脚本
每天自动从RSS源读取Linux新闻，用DeepSeek API翻译成中文，生成静态网站
"""

import os
import json
import time
import hashlib
import feedparser
from datetime import datetime, timezone
from openai import OpenAI

# ── 配置 ──────────────────────────────────────────────────────────────────────

DEEPSEEK_API_KEY = os.environ["DEEPSEEK_API_KEY"]

# RSS源列表（聚焦发行版、桌面、软件）
RSS_FEEDS = [
    {"name": "OMG! Ubuntu",      "url": "https://www.omgubuntu.co.uk/feed"},
    {"name": "It's FOSS News",   "url": "https://news.itsfoss.com/rss"},
    {"name": "DistroWatch",      "url": "https://distrowatch.com/news/dw.xml"},
    {"name": "Phoronix",         "url": "https://www.phoronix.com/rss.php"},
    {"name": "Linux Today",      "url": "https://www.linuxtoday.com/feed/"},
    {"name": "9to5Linux",        "url": "https://9to5linux.com/feed"},
]

# 每个源最多抓取的文章数
MAX_ARTICLES_PER_FEED = 5

# 输出目录
OUTPUT_DIR = "docs"

# 已处理文章的缓存文件（避免重复翻译）
CACHE_FILE = "scripts/cache.json"

# ── DeepSeek 客户端 ───────────────────────────────────────────────────────────

client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com",
)

# ── 工具函数 ──────────────────────────────────────────────────────────────────

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_cache(cache):
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

def article_id(url):
    return hashlib.md5(url.encode()).hexdigest()

def translate(title, summary):
    """调用 DeepSeek API 翻译标题和摘要"""
    prompt = f"""你是一名专业的Linux技术编辑，负责将英文Linux新闻翻译成简洁、准确的中文。

请翻译以下文章的标题和摘要：
- 保留专有名词（如发行版名称、软件名称等）
- 摘要控制在150字以内
- 输出格式为JSON，字段为 title 和 summary

原文标题：{title}
原文摘要：{summary}

只输出JSON，不要其他内容。"""

    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=400,
        temperature=0.3,
    )
    text = resp.choices[0].message.content.strip()
    # 去掉可能的 markdown 代码块
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    data = json.loads(text)
    return data.get("title", title), data.get("summary", summary)

# ── 主流程 ────────────────────────────────────────────────────────────────────

def fetch_articles():
    """从所有RSS源抓取文章"""
    articles = []
    for feed_info in RSS_FEEDS:
        print(f"  抓取 {feed_info['name']} ...")
        try:
            feed = feedparser.parse(feed_info["url"])
            for entry in feed.entries[:MAX_ARTICLES_PER_FEED]:
                url   = entry.get("link", "")
                title = entry.get("title", "").strip()
                # 优先取 summary，fallback 到 description
                raw_summary = entry.get("summary", entry.get("description", ""))
                # 去掉 HTML 标签（简单处理）
                import re
                summary = re.sub(r"<[^>]+>", "", raw_summary).strip()[:500]
                pub_date = entry.get("published", "")
                if url and title:
                    articles.append({
                        "id":       article_id(url),
                        "source":   feed_info["name"],
                        "url":      url,
                        "title_en": title,
                        "summary_en": summary,
                        "pub_date": pub_date,
                    })
        except Exception as e:
            print(f"    ⚠ 抓取失败: {e}")
    return articles

def translate_new_articles(articles, cache):
    """翻译尚未处理的文章"""
    new_articles = []
    for art in articles:
        aid = art["id"]
        if aid in cache:
            new_articles.append(cache[aid])
            continue
        print(f"  翻译: {art['title_en'][:60]}...")
        try:
            title_zh, summary_zh = translate(art["title_en"], art["summary_en"])
            art["title_zh"]   = title_zh
            art["summary_zh"] = summary_zh
            cache[aid] = art
            new_articles.append(art)
            time.sleep(0.5)   # 避免触发速率限制
        except Exception as e:
            print(f"    ⚠ 翻译失败: {e}")
            art["title_zh"]   = art["title_en"]
            art["summary_zh"] = art["summary_en"]
            new_articles.append(art)
    return new_articles

# ── HTML 生成 ─────────────────────────────────────────────────────────────────

CATEGORY_KEYWORDS = {
    "发行版": ["ubuntu", "debian", "fedora", "arch", "mint", "opensuse", "manjaro",
               "distro", "release", "pop!_os", "elementary", "rocky", "alma"],
    "桌面环境": ["gnome", "kde", "plasma", "xfce", "desktop", "wayland", "x11",
                 "gtk", "qt", "theme", "extension"],
    "软件应用": ["app", "software", "flatpak", "snap", "appimage", "firefox",
                 "libreoffice", "gimp", "vlc", "update", "version"],
}

def categorize(article):
    text = (article["title_en"] + " " + article["summary_en"]).lower()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(k in text for k in keywords):
            return cat
    return "其他"

def build_site(articles):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 分类
    for art in articles:
        art["category"] = categorize(art)

    # 按类别分组
    categories = {}
    for art in articles:
        categories.setdefault(art["category"], []).append(art)

    today = datetime.now(timezone.utc).strftime("%Y年%m月%d日")
    total = len(articles)

    # 生成文章卡片 HTML
    def card(art):
        cat_colors = {
            "发行版":   "#3b82f6",
            "桌面环境": "#8b5cf6",
            "软件应用": "#10b981",
            "其他":     "#6b7280",
        }
        color = cat_colors.get(art["category"], "#6b7280")
        return f"""
        <article class="card">
          <div class="card-meta">
            <span class="tag" style="background:{color}20;color:{color}">{art['category']}</span>
            <span class="source">{art['source']}</span>
          </div>
          <h2 class="card-title">
            <a href="{art['url']}" target="_blank" rel="noopener">{art['title_zh']}</a>
          </h2>
          <p class="card-summary">{art['summary_zh']}</p>
          <a class="read-more" href="{art['url']}" target="_blank" rel="noopener">阅读原文 →</a>
        </article>"""

    # 每个分类的区块
    def section(cat_name, arts):
        cards = "\n".join(card(a) for a in arts)
        return f"""
      <section class="category-section">
        <h2 class="section-title">{cat_name} <span class="count">{len(arts)}</span></h2>
        <div class="grid">{cards}</div>
      </section>"""

    sections_html = "\n".join(
        section(cat, arts)
        for cat, arts in categories.items()
        if arts
    )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Linux 中文速报</title>
<meta name="description" content="每日聚合国外Linux发行版、桌面、软件最新资讯，自动翻译成中文">
<style>
  :root {{
    --bg:       #0f1117;
    --surface:  #1a1d27;
    --border:   #2a2d3a;
    --text:     #e2e8f0;
    --muted:    #8892a4;
    --accent:   #38bdf8;
    --font-mono: 'JetBrains Mono', 'Fira Code', monospace;
    --font-body: 'Inter', system-ui, sans-serif;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: var(--font-body);
    font-size: 15px;
    line-height: 1.7;
  }}

  /* ── Header ── */
  header {{
    border-bottom: 1px solid var(--border);
    padding: 24px 0 20px;
    background: linear-gradient(180deg, #0d1520 0%, var(--bg) 100%);
  }}
  .header-inner {{
    max-width: 1100px;
    margin: 0 auto;
    padding: 0 24px;
    display: flex;
    align-items: baseline;
    gap: 16px;
    flex-wrap: wrap;
  }}
  .logo {{
    font-family: var(--font-mono);
    font-size: 22px;
    font-weight: 700;
    color: var(--accent);
    letter-spacing: -0.5px;
  }}
  .logo span {{ color: var(--muted); font-weight: 400; }}
  .tagline {{
    color: var(--muted);
    font-size: 13px;
    flex: 1;
  }}
  .update-time {{
    font-family: var(--font-mono);
    font-size: 12px;
    color: var(--muted);
    background: var(--surface);
    border: 1px solid var(--border);
    padding: 4px 10px;
    border-radius: 4px;
  }}

  /* ── Stats bar ── */
  .stats-bar {{
    max-width: 1100px;
    margin: 20px auto 0;
    padding: 0 24px;
    display: flex;
    gap: 24px;
    font-size: 13px;
    color: var(--muted);
  }}
  .stats-bar strong {{ color: var(--text); }}

  /* ── Main ── */
  main {{
    max-width: 1100px;
    margin: 0 auto;
    padding: 32px 24px 64px;
  }}

  /* ── Section ── */
  .category-section {{ margin-bottom: 48px; }}
  .section-title {{
    font-family: var(--font-mono);
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--muted);
    border-bottom: 1px solid var(--border);
    padding-bottom: 10px;
    margin-bottom: 20px;
    display: flex;
    align-items: center;
    gap: 10px;
  }}
  .count {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 1px 8px;
    font-size: 11px;
    color: var(--muted);
    text-transform: none;
    letter-spacing: 0;
  }}

  /* ── Grid ── */
  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 16px;
  }}

  /* ── Card ── */
  .card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 18px 20px;
    display: flex;
    flex-direction: column;
    gap: 10px;
    transition: border-color .15s, transform .15s;
  }}
  .card:hover {{
    border-color: #3a4a6a;
    transform: translateY(-2px);
  }}
  .card-meta {{
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 12px;
  }}
  .tag {{
    padding: 2px 8px;
    border-radius: 4px;
    font-weight: 500;
    font-size: 11px;
  }}
  .source {{ color: var(--muted); }}
  .card-title {{
    font-size: 15px;
    font-weight: 600;
    line-height: 1.4;
  }}
  .card-title a {{
    color: var(--text);
    text-decoration: none;
  }}
  .card-title a:hover {{ color: var(--accent); }}
  .card-summary {{
    font-size: 13px;
    color: var(--muted);
    line-height: 1.6;
    flex: 1;
  }}
  .read-more {{
    font-size: 12px;
    color: var(--accent);
    text-decoration: none;
    font-family: var(--font-mono);
    margin-top: 4px;
  }}
  .read-more:hover {{ text-decoration: underline; }}

  /* ── Footer ── */
  footer {{
    border-top: 1px solid var(--border);
    padding: 24px;
    text-align: center;
    font-size: 12px;
    color: var(--muted);
  }}
  footer a {{ color: var(--muted); }}

  @media (max-width: 600px) {{
    .grid {{ grid-template-columns: 1fr; }}
    .header-inner {{ flex-direction: column; gap: 8px; }}
  }}
</style>
</head>
<body>

<header>
  <div class="header-inner">
    <div class="logo">$ linux<span>-news</span></div>
    <div class="tagline">每日聚合国外 Linux 资讯，自动翻译成中文</div>
    <div class="update-time">更新于 {today}</div>
  </div>
  <div class="stats-bar">
    <div>今日收录 <strong>{total}</strong> 篇</div>
    <div>来源 <strong>{len(RSS_FEEDS)}</strong> 个站点</div>
    <div>分类 <strong>{len(categories)}</strong> 个</div>
  </div>
</header>

<main>
{sections_html}
</main>

<footer>
  <p>数据来自 {' · '.join(f['name'] for f in RSS_FEEDS)} · 由 DeepSeek AI 翻译 · 
     <a href="https://github.com" target="_blank">GitHub</a> 开源</p>
</footer>

</body>
</html>"""

    index_path = os.path.join(OUTPUT_DIR, "index.html")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  ✓ 网站已生成 → {index_path}")

# ── 入口 ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("📡 加载缓存...")
    cache = load_cache()

    print("📡 抓取 RSS 源...")
    articles = fetch_articles()
    print(f"  共获取 {len(articles)} 篇文章")

    print("🤖 翻译新文章...")
    articles = translate_new_articles(articles, cache)

    print("💾 保存缓存...")
    save_cache(cache)

    print("🏗  生成网站...")
    build_site(articles)

    print("✅ 完成！")
