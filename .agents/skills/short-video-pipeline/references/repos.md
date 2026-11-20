# 配套仓库

路径都相对工作区根目录。安装和更新步骤见 [setup.md](setup.md)。

三个仓库都装在工作区里，不全局安装；它们的设置、模型、缓存、浏览器内核也都在工作区里，由 `.agents/skills/short-video-pipeline/scripts/env.sh` 指定位置。执行下面任何命令之前先执行这个环境脚本。

**配套仓库一律使用最新版本，不固定版本。** 新环境安装时取最新；已有环境在用户说「更新配套仓库」时更新。

版本变了以后，以各仓库自己的 skill 和文档为准。本目录里唯一依赖具体版本的是 [creatorhub-api.md](creatorhub-api.md)，它是从 CreatorHub 源码整理的，文件开头记着核对时的提交号；提交号对不上时，按它开头写的办法重新核对。

下面每个仓库的「上次核对」只是记录这套流程在哪个版本上验证过，用来在新版本出问题时对照，不是要求安装的版本。

## 需要安装到工作区的三个仓库

### openfilm/openfilm：素材库、剪辑、渲染

- 仓库：https://github.com/openfilm/openfilm
- 版本：npm 包 `openfilm` 的最新版（根目录 `package.json` 里写的是 `latest`）
- 上次核对：0.4.1，2026-11-20
- 安装位置：`node_modules/openfilm/`
- 命令：`node_modules/.bin/openfilm`（source `env.sh` 后当前 shell 内直接敲 `openfilm` 也优先指向它）
- 给 agent 的 skill（必须读）：
  - `node_modules/openfilm/SYSTEM_PROMPT.md`（或直接无参运行 `openfilm`）：总入口与 skill 列表
  - `openfilm skill film`（文件 `node_modules/openfilm/manual/film/SKILL.md`，兼容 `openfilm skill edit`）：项目、`film.html`、页面、`openfilm look`
  - `openfilm skill media`（文件 `node_modules/openfilm/manual/media/SKILL.md`）：自带库（`my-media`、`music-search`、`sfx-search`、`sticker`）和生成服务
  - `openfilm skill canvas`：画板，本流程一般用不到
  - `node_modules/openfilm/SPEC.md`：`film.html` 的规范，拿不准写法时查
- 说明：
  - 自带免费离线 CC0 库（音乐、音效、贴纸）和用户自带媒体（`my-media`）装好就能用。
  - 配音、出图、出视频、素材搜索要在 OpenFilm 的设置里接服务，连接信息存在 `.local/openfilm/`（由环境脚本的 `OPENFILM_HOME` 指定），不随本仓库迁移。`openfilm get` 列出当前能用的种类。
  - 渲染用的浏览器内核在 `browsers/ms-playwright/`（`PLAYWRIGHT_BROWSERS_PATH`）。

### JuneYaooo/rea-video：拆解参考视频、给出复刻方案

- 仓库：https://github.com/JuneYaooo/rea-video
- 版本：默认分支的最新提交
- 上次核对：提交 `82d5463`，2026-11-20
- 安装位置：`rea-video/`，虚拟环境 `rea-video/.venv`
- 命令：`rea-video/.venv/bin/rea-video`（不在 PATH 里）
- 给 agent 的 skill（必须读）：
  - `rea-video/skills/rea-video/SKILL.md`：先看后拆（`survey`）、拆解、看图复核、交付、复刻的完整流程
  - `rea-video/skills/rea-video/references/`：`review.md`（看图复核）、`taxonomy.md`（画面分类）、`audio.md`、`materials.md`、`remake.md`（各类镜头怎么复刻）、`remake-tools.md`（可选的复刻工具）、`setup.md`、`memory.md`、`output-template.md`（以及 `chatcut.md`、`capsule-cinema.md`、`hyperframes.md`、`diy.md`）
  - `rea-video/AGENTS.md`：仓库对 agent 的说明
- 说明：
  - 虚拟环境建议使用 Python 3.12–3.14（`82d5463` 已修复 3.11 上 `rea_video/report.py` 的 f-string 语法错误，本工作区 `.venv` 沿用 Python 3.14）。
  - 安装时带 `[ocr,asr]`，才有字幕时间轴和台词识别。首次运行会下载模型到 `.local/rea-video/models/`（`REA_VIDEO_MODELS`）；它的记忆文件在 `.local/rea-video/home/`（`REA_VIDEO_HOME`）。
  - 它提到的复刻执行工具 [JuneYaooo/capsule-cinema](https://github.com/JuneYaooo/capsule-cinema)、ChatCut、HyperFrames 本流程不安装、不使用（一律用 OpenFilm 制作成片）。

### 3441293738/creatorhub：账号、采集、下载、发布

- 仓库：https://github.com/3441293738/creatorhub
- 版本：默认分支的最新提交
- 上次核对：v0.2.9+1，提交 `27b9b8e`，2026-11-20
- 安装位置：`creatorhub/`
- 命令：在 `creatorhub/` 里 `python3 creatorhub.py install`、`start --no-open`、`check`
- 本机接口：`http://127.0.0.1:8000`
- 给 agent 的 skill：仓库里没有。接口整理在 [creatorhub-api.md](creatorhub-api.md)，依据是 `creatorhub/app/main.py`。
- 其他文档：`creatorhub/README.md`、`creatorhub/guide/`（给人看的使用说明）、`creatorhub/app/agent/README.md`（它内置的 AI 助手，只读，不能发布，本流程不用）
- 说明：
  - 账号登录态、数据库、浏览器 Profile、上传文件都在 `creatorhub/data/`，不随本仓库迁移，也不得外传。
  - 小红书固定用系统安装的 Google Chrome。

## 不安装、直接调用的公开接口（封装在 `scripts/` 中）

完整的对比依据、降级链路和命令示例见 [sourcing.md](sourcing.md)。

| 用途 | 来源 / 仓库 | 入口与接口 |
|---|---|---|
| 国内大众热榜 + 科技/AI 资讯 | [vikiboss/60s](https://github.com/vikiboss/60s) | `scripts/fetch_trends.py` 自动按序降级：`https://api.cczo.cc/60s`（首选）→ `https://60s.mizhoubaobei.top` → `https://60s.okbaike.com`；含 `/v2/douyin`、`/v2/weibo`、`/v2/bili`、`/v2/zhihu`、`/v2/toutiao`、`/v2/baidu/realtime`、`/v2/it-news`、`/v2/it-news/rank`、`/v2/ai-news`、`/v2/hacker-news/top` |
| 国内外科技 / 开发者 / 财经热榜 | [ourongxing/newsnow](https://github.com/ourongxing/newsnow) 公共接口 | `https://newsnow.busiyi.world/api/s?id=<源>`（GitHub Trending、Product Hunt、Hacker News、华尔街见闻、财联社、IT之家、少数派、Solidot、联合早报，及国内热榜降级源） |
| 科技巨头一手官方发布 & 权威外媒 | 官方直连 RSS / JSON | OpenAI、Google Blog、DeepMind、Apple Newsroom、NVIDIA Blog、GitHub Blog、Hugging Face、TechCrunch、The Verge、Ars Technica、少数派、HN Algolia API、Google News RSS（中/英）、Bing News RSS |
| 热榜最终兜底 | [solarhell/hot-search-crawler](https://github.com/solarhell/hot-search-crawler) | `https://solarhell.github.io/hot-search-crawler/latest.json` |
| 零 Key 免版权素材库 & 新闻抓图切片 | Wikimedia Commons、NASA Media API、Internet Archive、Openverse + 复用工作区 `playwright-core` & `yt-dlp` | `scripts/fetch_asset.py`（子命令：`news-page`、`stock`、`video-search`、`video-clip`、`register`） |

2026-11-20 实测记录：
- `api.cczo.cc/60s` 与 `60s.mizhoubaobei.top` 上述 10 个 60s 接口全通（`/v2/ai-news` 超时需 ≥15s）；`newsnow` 国内外 15 个常用源全部 ~2.4s 返回；官方 RSS 清单中 11–12 个稳定秒返（已剔除 403/解析异常源）。
- 各 60s 实例的 `/v2/rednote` 均报 500，小红书热度继续用 CreatorHub 关键词采集来查；视频号无免费公开热榜。
- Wikimedia Commons 下载原图需遵守规范 `User-Agent` 并使用 `iiurlwidth=1920`（`fetch_asset.py` 已内置处理）。

## 可选：指纹浏览器内核

- 仓库：https://github.com/adryfish/fingerprint-chromium
- 用途：给 CreatorHub 的抖音、视频号账号用，按账号的种子生成固定指纹。不装也能用，CreatorHub 自带的浏览器可以发布。
- 版本：有对应系统安装包的最新发行版
- 上次核对：148.0.7778.215（macOS），2026-11-18
- 安装位置：`browsers/`
