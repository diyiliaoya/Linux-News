# AGENTS.md

## Project overview

Single-script Python pipeline: fetch Linux RSS feeds → scrape article bodies → translate via DeepSeek API → generate static HTML to `docs/` (GitHub Pages). CI runs daily via GitHub Actions and auto-commits output.

## Commands

```bash
# The only command — set the API key env var, then run:
export DEEPSEEK_API_KEY="sk-..."
python scripts/fetch_and_translate.py
```

No build system, no test suite, no linter, no typechecker. Python 3.11 per CI.

## Dependencies

There is **no `requirements.txt`**. Dependencies are installed inline in CI:
```
pip install feedparser openai
```
Run the same locally. Only two packages; the rest is Python stdlib.

## Architecture

`scripts/fetch_and_translate.py` (600 lines) is the entire app:
1. `fetch_articles()` — parse 6 RSS feeds via `feedparser`, extract top 5 per feed
2. `fetch_fulltext()` — scrape article URL, extract text via `html.parser.HTMLParser` (stdlib, not lxml/BeautifulSoup), truncate to 4000 chars
3. `translate_article()` — send to DeepSeek API (`deepseek-chat` model) via `openai.OpenAI` client pointed at `base_url="https://api.deepseek.com"`
4. `build_site()` — generate `docs/index.html` (homepage) and `docs/articles/{md5_hash}.html` (per-article pages)

## Key gotchas

- **Cache is git-tracked**: `scripts/cache.json` stores translated articles keyed by MD5 of the source URL. Already-translated articles are skipped. CI commits this file alongside `docs/`. If you change the `article_id()` hashing, all cached translations are invalidated and will be re-fetched/re-translated.

- **No retry on API failure**: If translation throws, the English text is used as-is for Chinese fields. No backoff, no retry loop. A 0.8s `time.sleep()` between translations is the only rate-limiting.

- **HTML template escaping**: Python `.format()`-style `{{` and `}}` are used throughout the inline CSS templates. When adding new CSS, double all braces (e.g., `{{ ... }}` instead of `{ ... }`).

- **LLM response cleanup**: The script strips ```json / ``` fences from the DeepSeek response before `json.loads()` (line 133). If the model changes its output format, this regex may need updating.

- **`.nojeky11` file**: Exists at `docs/.nojeky11` but is a typo (should be `.nojekyll`). Not functionally needed — GitHub Pages doesn't Jekyll-process `docs/` by default on newer setups.

- **Ghost directory**: `{scripts,.github/` is a directory created by a mis-expanded shell brace. It is not used by anything and safe to delete.

## CI

Workflow: `.github/workflows/daily.yml`
- Cron: `0 0 * * *` (UTC midnight = 08:00 Beijing)
- Manual trigger: `workflow_dispatch`
- Steps: checkout → setup Python 3.11 → `pip install feedparser openai` → run script with `DEEPSEEK_API_KEY` secret → `git add docs/ scripts/cache.json` → commit & push
- Permissions: `contents: write` (needed for push)
