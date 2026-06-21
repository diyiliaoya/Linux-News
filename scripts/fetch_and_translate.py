#!/usr/bin/env python3
"""
Linux新闻抓取+翻译脚本
每天自动从RSS源读取Linux新闻，抓取原文正文，用DeepSeek API翻译成中文，生成静态网站
"""

import os
import re
import json
import time
import hashlib
import feedparser
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from openai import OpenAI

# ── 配置 ──────────────────────────────────────────────────────────────────────

DEEPSEEK_API_KEY = os.environ["DEEPSEEK_API_KEY"]

RSS_FEEDS = [
    {"name": "OMG! Ubuntu",      "url": "https://www.omgubuntu.co.uk/feed"},
    {"name": "It's FOSS News",   "url": "https://news.itsfoss.com/rss"},
    {"name": "DistroWatch",      "url": "https://distrowatch.com/news/dw.xml"},
    {"name": "Phoronix",         "url": "https://www.phoronix.com/rss.php"},
    {"name": "Linux Today",      "url": "https://www.linuxtoday.com/feed/"},
    {"name": "9to5Linux",        "url": "https://9to5linux.com/feed"},
]

MAX_ARTICLES_PER_FEED = 5
OUTPUT_DIR  = "docs"
CACHE_FILE  = "scripts/cache.json"

# 正文抓取超时（秒）
FETCH_TIMEOUT = 10

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

def strip_tags(html):
    """简单去除 HTML 标签"""
    return re.sub(r"<[^>]+>", " ", html)

# ── 正文抓取 ──────────────────────────────────────────────────────────────────

# 需要从页面正文中跳过的常见噪音块（CSS选择器关键词）
NOISE_TAGS = {"script", "style", "nav", "header", "footer", "aside",
              "form", "noscript", "iframe", "button", "select"}

class TextExtractor(HTMLParser):
    """从 HTML 中提取正文文字，跳过噪音标签"""
    def __init__(self):
        super().__init__()
        self.texts = []
        self._skip_depth = 0
        self._skip_tag = None

    def handle_starttag(self, tag, attrs):
        if tag in NOISE_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in NOISE_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0:
            text = data.strip()
            if len(text) > 20:          # 过滤极短碎片
                self.texts.append(text)

    def result(self):
        return "\n".join(self.texts)


def fetch_fulltext(url: str) -> str:
    """抓取原文网页，提取正文（最多 4000 字符送给 AI）"""
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; LinuxNewsBot/1.0)"}
        )
        with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as resp:
            raw = resp.read()
            # 尝试从 Content-Type 推断编码
            ct = resp.headers.get_content_charset() or "utf-8"
            html = raw.decode(ct, errors="replace")

        parser = TextExtractor()
        parser.feed(html)
        text = parser.result()

        # 取前 4000 字符，避免超出 token 限制
        return text[:4000].strip()
    except Exception as e:
        return ""   # 抓取失败时返回空，后续 fallback 到摘要

# ── DeepSeek 翻译 ─────────────────────────────────────────────────────────────

def translate_article(title_en: str, summary_en: str, fulltext_en: str):
    """
    翻译标题、摘要，并把正文翻译成中文。
    返回 (title_zh, summary_zh, fulltext_zh)
    """
    # 正文内容：优先用抓取到的全文，否则用摘要
    body = fulltext_en if fulltext_en else summary_en

    prompt = f"""你是一名专业的Linux技术编辑，将英文Linux新闻翻译成准确、流畅的中文。

请完成以下任务，输出纯JSON，字段为 title、summary、fulltext：
1. title：翻译标题，保留专有名词
2. summary：根据正文内容写一段150字以内的中文摘要
3. fulltext：将正文完整翻译成中文，保留段落结构，保留专有名词（发行版、软件名等）

原文标题：{title_en}

原文正文（可能含噪音，请忽略广告/导航等无关内容）：
{body}

只输出JSON，不要任何其他内容。"""

    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=2000,
        temperature=0.3,
    )
    text = resp.choices[0].message.content.strip()
    text = re.sub(r"^```json|^```|```$", "", text, flags=re.MULTILINE).strip()
    data = json.loads(text)
    return (
        data.get("title",    title_en),
        data.get("summary",  summary_en),
        data.get("fulltext", body),
    )

# ── 主流程 ────────────────────────────────────────────────────────────────────

def fetch_articles():
    articles = []
    for feed_info in RSS_FEEDS:
        print(f"  抓取 {feed_info['name']} ...")
        try:
            feed = feedparser.parse(feed_info["url"])
            for entry in feed.entries[:MAX_ARTICLES_PER_FEED]:
                url  = entry.get("link", "")
                title = entry.get("title", "").strip()
                raw_summary = entry.get("summary", entry.get("description", ""))
                summary = re.sub(r"<[^>]+>", "", raw_summary).strip()[:500]
                pub_date = entry.get("published", "")
                if url and title:
                    articles.append({
                        "id":         article_id(url),
                        "source":     feed_info["name"],
                        "url":        url,
                        "title_en":   title,
                        "summary_en": summary,
                        "pub_date":   pub_date,
                    })
        except Exception as e:
            print(f"    ⚠ 抓取失败: {e}")
    return articles


def process_new_articles(articles, cache):
    result = []
    for art in articles:
        aid = art["id"]
        if aid in cache:
            result.append(cache[aid])
            continue

        print(f"  处理: {art['title_en'][:60]}...")

        # 1. 抓取原文正文
        fulltext_en = fetch_fulltext(art["url"])
        if fulltext_en:
            print(f"    ✓ 正文抓取成功 ({len(fulltext_en)} 字符)")
        else:
            print(f"    ⚠ 正文抓取失败，使用摘要替代")

        # 2. 翻译
        try:
            title_zh, summary_zh, fulltext_zh = translate_article(
                art["title_en"], art["summary_en"], fulltext_en
            )
            art["title_zh"]    = title_zh
            art["summary_zh"]  = summary_zh
            art["fulltext_zh"] = fulltext_zh
            cache[aid] = art
            time.sleep(0.8)
        except Exception as e:
            print(f"    ⚠ 翻译失败: {e}")
            art["title_zh"]    = art["title_en"]
            art["summary_zh"]  = art["summary_en"]
            art["fulltext_zh"] = art["summary_en"]

        result.append(art)
    return result

# ── 分类 ─────────────────────────────────────────────────────────────────────

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

# ── HTML 生成 ─────────────────────────────────────────────────────────────────

def build_site(articles):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for art in articles:
        art["category"] = categorize(art)

    categories = {}
    for art in articles:
        categories.setdefault(art["category"], []).append(art)

    today = datetime.now(timezone.utc).strftime("%Y年%m月%d日")
    total = len(articles)

    cat_colors = {
        "发行版":   "#3b82f6",
        "桌面环境": "#8b5cf6",
        "软件应用": "#10b981",
        "其他":     "#6b7280",
    }

    def escape_html(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    def fulltext_paragraphs(text):
        """把全文按段落转为 <p> 标签"""
        paras = [p.strip() for p in text.split("\n") if p.strip()]
        return "".join(f"<p>{escape_html(p)}</p>" for p in paras)

    def card(art):
        color = cat_colors.get(art["category"], "#6b7280")
        aid   = art["id"]
        full  = fulltext_paragraphs(art.get("fulltext_zh", art.get("summary_zh", "")))
        title_safe   = escape_html(art["title_zh"])
        summary_safe = escape_html(art["summary_zh"])

        return f"""
        <article class="card" id="card-{aid}">
          <div class="card-meta">
            <span class="tag" style="background:{color}20;color:{color}">{art['category']}</span>
            <span class="source">{escape_html(art['source'])}</span>
          </div>
          <h2 class="card-title">
            <button class="title-btn" onclick="toggleFull('{aid}')" aria-expanded="false">
              {title_safe}
            </button>
          </h2>
          <p class="card-summary">{summary_safe}</p>

          <div class="fulltext" id="full-{aid}" hidden>
            <div class="fulltext-body">{full}</div>
          </div>

          <div class="card-actions">
            <button class="btn-expand" onclick="toggleFull('{aid}')" id="btn-{aid}">
              展开全文 ▾
            </button>
            <a class="read-more" href="{art['url']}" target="_blank" rel="noopener">阅读原文 →</a>
          </div>
        </article>"""

    def section(cat_name, arts):
        cards = "\n".join(card(a) for a in arts)
        return f"""
      <section class="category-section">
        <h2 class="section-title">{cat_name} <span class="count">{len(arts)}</span></h2>
        <div class="grid">{cards}</div>
      </section>"""

    sections_html = "\n".join(
        section(cat, arts) for cat, arts in categories.items() if arts
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
    --bg:        #0f1117;
    --surface:   #1a1d27;
    --border:    #2a2d3a;
    --text:      #e2e8f0;
    --muted:     #8892a4;
    --accent:    #38bdf8;
    --full-bg:   #13161f;
    --font-mono: 'JetBrains Mono', 'Fira Code', monospace;
    --font-body: 'Inter', system-ui, sans-serif;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--bg); color: var(--text);
    font-family: var(--font-body); font-size: 15px; line-height: 1.7;
  }}

  /* Header */
  header {{
    border-bottom: 1px solid var(--border);
    padding: 24px 0 20px;
    background: linear-gradient(180deg, #0d1520 0%, var(--bg) 100%);
  }}
  .header-inner {{
    max-width: 1100px; margin: 0 auto; padding: 0 24px;
    display: flex; align-items: baseline; gap: 16px; flex-wrap: wrap;
  }}
  .logo {{
    font-family: var(--font-mono); font-size: 22px; font-weight: 700;
    color: var(--accent); letter-spacing: -0.5px;
  }}
  .logo span {{ color: var(--muted); font-weight: 400; }}
  .tagline {{ color: var(--muted); font-size: 13px; flex: 1; }}
  .update-time {{
    font-family: var(--font-mono); font-size: 12px; color: var(--muted);
    background: var(--surface); border: 1px solid var(--border);
    padding: 4px 10px; border-radius: 4px;
  }}
  .stats-bar {{
    max-width: 1100px; margin: 20px auto 0; padding: 0 24px;
    display: flex; gap: 24px; font-size: 13px; color: var(--muted);
  }}
  .stats-bar strong {{ color: var(--text); }}

  /* Main */
  main {{ max-width: 1100px; margin: 0 auto; padding: 32px 24px 64px; }}

  /* Section */
  .category-section {{ margin-bottom: 48px; }}
  .section-title {{
    font-family: var(--font-mono); font-size: 13px; font-weight: 600;
    letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted);
    border-bottom: 1px solid var(--border); padding-bottom: 10px;
    margin-bottom: 20px; display: flex; align-items: center; gap: 10px;
  }}
  .count {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 10px; padding: 1px 8px; font-size: 11px;
    color: var(--muted); text-transform: none; letter-spacing: 0;
  }}

  /* Grid */
  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 16px;
  }}

  /* Card */
  .card {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 8px; padding: 18px 20px;
    display: flex; flex-direction: column; gap: 10px;
    transition: border-color .15s;
  }}
  .card:hover {{ border-color: #3a4a6a; }}
  .card-meta {{ display: flex; align-items: center; gap: 8px; font-size: 12px; }}
  .tag {{ padding: 2px 8px; border-radius: 4px; font-weight: 500; font-size: 11px; }}
  .source {{ color: var(--muted); }}

  /* Title button */
  .card-title {{ font-size: 15px; font-weight: 600; line-height: 1.4; }}
  .title-btn {{
    background: none; border: none; padding: 0; cursor: pointer;
    color: var(--text); font-size: 15px; font-weight: 600;
    line-height: 1.4; text-align: left; font-family: inherit;
    transition: color .15s;
  }}
  .title-btn:hover {{ color: var(--accent); }}

  /* Summary */
  .card-summary {{ font-size: 13px; color: var(--muted); line-height: 1.6; }}

  /* Full text */
  .fulltext {{
    border-top: 1px solid var(--border);
    background: var(--full-bg);
    border-radius: 6px;
    padding: 16px;
    margin-top: 4px;
  }}
  .fulltext[hidden] {{ display: none; }}
  .fulltext-body {{ font-size: 14px; line-height: 1.8; color: #c8d0dc; }}
  .fulltext-body p {{ margin-bottom: 12px; }}
  .fulltext-body p:last-child {{ margin-bottom: 0; }}

  /* Actions row */
  .card-actions {{
    display: flex; align-items: center; gap: 16px; margin-top: 4px;
  }}
  .btn-expand {{
    background: none; border: 1px solid var(--border); border-radius: 4px;
    padding: 4px 10px; font-size: 12px; color: var(--muted);
    cursor: pointer; font-family: var(--font-mono); transition: all .15s;
  }}
  .btn-expand:hover {{ border-color: var(--accent); color: var(--accent); }}
  .btn-expand.expanded {{ color: var(--accent); border-color: var(--accent); }}
  .read-more {{
    font-size: 12px; color: var(--accent); text-decoration: none;
    font-family: var(--font-mono);
  }}
  .read-more:hover {{ text-decoration: underline; }}

  /* Footer */
  footer {{
    border-top: 1px solid var(--border); padding: 24px;
    text-align: center; font-size: 12px; color: var(--muted);
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

<script>
function toggleFull(id) {{
  const full = document.getElementById('full-' + id);
  const btn  = document.getElementById('btn-'  + id);
  const titleBtn = document.querySelector('#card-' + id + ' .title-btn');
  const expanded = !full.hidden;
  full.hidden = expanded;
  btn.textContent  = expanded ? '展开全文 ▾' : '收起全文 ▴';
  btn.classList.toggle('expanded', !expanded);
  titleBtn.setAttribute('aria-expanded', String(!expanded));
}}
</script>

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

    print("🌐 抓取正文 + 🤖 翻译...")
    articles = process_new_articles(articles, cache)

    print("💾 保存缓存...")
    save_cache(cache)

    print("🏗  生成网站...")
    build_site(articles)

    print("✅ 完成！")

