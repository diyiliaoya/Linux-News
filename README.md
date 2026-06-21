# Linux 中文速报

每日自动抓取国外 Linux 发行版、桌面、软件资讯，用 DeepSeek AI 翻译成中文，发布为静态网站。

## 部署步骤（15分钟完成）

### 第一步：创建 GitHub 仓库

1. 登录 [github.com](https://github.com)，点击右上角 **+** → **New repository**
2. 仓库名填 `linux-news`（或任意名称）
3. 选 **Public**（公开，GitHub Pages 免费版必须公开）
4. 点击 **Create repository**

### 第二步：上传代码

在新建的仓库页面，点击 **uploading an existing file**，把以下文件按目录结构上传：

```
linux-news/
├── .github/
│   └── workflows/
│       └── daily.yml          ← GitHub Actions 自动化脚本
├── scripts/
│   └── fetch_and_translate.py ← 主程序
└── README.md
```

> **提示**：上传时需要先创建文件夹。方法：点击 **Create new file**，文件名输入 `.github/workflows/daily.yml`，GitHub 会自动创建目录层级。

### 第三步：填入 DeepSeek API Key

1. 去 [platform.deepseek.com](https://platform.deepseek.com) 注册并获取 API Key
2. 回到 GitHub 仓库，点击 **Settings** → **Secrets and variables** → **Actions**
3. 点击 **New repository secret**
4. Name 填 `DEEPSEEK_API_KEY`，Value 填你的 API Key
5. 点击 **Add secret**

### 第四步：开启 GitHub Pages

1. 仓库 **Settings** → **Pages**
2. Source 选 **Deploy from a branch**
3. Branch 选 **main**，目录选 **/docs**
4. 点击 **Save**

### 第五步：手动触发第一次运行

1. 点击仓库的 **Actions** 标签
2. 点击左边的 **每日更新Linux新闻**
3. 点击 **Run workflow** → **Run workflow**
4. 等待约 2 分钟运行完成

### 完成！

几分钟后访问：`https://你的用户名.github.io/linux-news`

之后每天北京时间早上 8 点自动更新。

---

## 自定义

**修改更新时间**：编辑 `.github/workflows/daily.yml` 里的 `cron` 表达式  
**增减 RSS 源**：编辑 `scripts/fetch_and_translate.py` 里的 `RSS_FEEDS` 列表  
**修改每源文章数**：修改 `MAX_ARTICLES_PER_FEED`（默认5篇）

## 费用

DeepSeek API 极便宜，每天翻译约30篇文章，每月费用约 **¥1-3**。
