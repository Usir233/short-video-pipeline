# 配套仓库

路径都相对工作区根目录。安装和更新步骤见 [setup.md](setup.md)。

**配套仓库一律使用最新版本，不固定版本。** 新环境安装时取最新；已有环境在用户说「更新配套仓库」时更新。

版本变了以后，以各仓库自己的 skill 和文档为准。本目录里唯一依赖具体版本的是 [creatorhub-api.md](creatorhub-api.md)，它是从 CreatorHub 源码整理的，文件开头记着核对时的提交号；提交号对不上时，按它开头写的办法重新核对。

下面每个仓库的「上次核对」只是记录这套流程在哪个版本上验证过，用来在新版本出问题时对照，不是要求安装的版本。

## 需要安装到工作区的三个仓库

### openfilm/openfilm：素材库、剪辑、渲染

- 仓库：https://github.com/openfilm/openfilm
- 版本：npm 包 `openfilm` 的最新版（根目录 `package.json` 里写的是 `latest`）
- 上次核对：0.3.2，2026-11-18
- 安装位置：`node_modules/openfilm/`
- 命令：`node_modules/.bin/openfilm`
- 给 agent 的 skill（必须读）：
  - `node_modules/openfilm/MANUAL.md`：总入口
  - `openfilm skill edit`（文件 `node_modules/openfilm/manual/edit/SKILL.md`）：项目、`film.html`、页面、`openfilm look`
  - `openfilm skill media`（文件 `node_modules/openfilm/manual/media/SKILL.md`）：自带库和生成服务
  - `openfilm skill canvas`（文件 `node_modules/openfilm/manual/canvas/SKILL.md`）：画板，本流程一般用不到
  - `node_modules/openfilm/SPEC.md`：`film.html` 的规范，拿不准写法时查
- 说明：
  - 自带库（音乐、音效、转场、特效、滤镜、贴纸、文字、模板）装好就能用。
  - 配音、出图、出视频、素材搜索要在 OpenFilm 的设置里接服务，连接信息存在 `~/.openfilm`，不随本仓库迁移。`openfilm get` 列出当前能用的种类。

### JuneYaooo/rea-video：拆解参考视频、给出复刻方案

- 仓库：https://github.com/JuneYaooo/rea-video
- 版本：默认分支的最新提交
- 上次核对：提交 `07dd587`，2026-11-18
- 安装位置：`rea-video/`，虚拟环境 `rea-video/.venv`
- 命令：`rea-video/.venv/bin/rea-video`（不在 PATH 里）
- 给 agent 的 skill（必须读）：
  - `rea-video/skills/rea-video/SKILL.md`：拆解、看图复核、交付、复刻的完整流程
  - `rea-video/skills/rea-video/references/`：`review.md`（看图复核）、`taxonomy.md`（画面分类）、`audio.md`、`materials.md`、`remake.md`（各类镜头怎么复刻）、`remake-tools.md`（可选的复刻工具）、`setup.md`、`memory.md`、`output-template.md`
  - `rea-video/AGENTS.md`：仓库对 agent 的说明
- 说明：
  - 虚拟环境用 Python 3.12–3.14。上次核对的版本在 3.11 上 `rea_video/report.py` 有语法错误，拆片包（`VIDEO.md`、`video/`）和报告都生成不出来。
  - 安装时带 `[ocr,asr]`，才有字幕时间轴和台词识别。首次运行会下载模型到 `~/.cache/rea-video/models`。
  - 它提到的复刻执行工具 [JuneYaooo/capsule-cinema](https://github.com/JuneYaooo/capsule-cinema) 和 ChatCut 都要付费，本流程不安装、不使用。

### 3441293738/creatorhub：账号、采集、下载、发布

- 仓库：https://github.com/3441293738/creatorhub
- 版本：默认分支的最新提交
- 上次核对：v0.2.8，提交 `a902546`，2026-11-18
- 安装位置：`creatorhub/`
- 命令：在 `creatorhub/` 里 `python3 creatorhub.py install`、`start --no-open`、`check`
- 本机接口：`http://127.0.0.1:8000`
- 给 agent 的 skill：仓库里没有。接口整理在 [creatorhub-api.md](creatorhub-api.md)，依据是 `creatorhub/app/main.py`。
- 其他文档：`creatorhub/README.md`、`creatorhub/guide/`（给人看的使用说明）、`creatorhub/app/agent/README.md`（它内置的 AI 助手，只读，不能发布，本流程不用）
- 说明：
  - 账号登录态、数据库、浏览器 Profile、上传文件都在 `creatorhub/data/`，不随本仓库迁移，也不得外传。
  - 小红书固定用系统安装的 Google Chrome。

## 不安装、直接调用的公开接口

| 用途 | 仓库 | 接口 |
|---|---|---|
| 抖音、微博热榜 | [vikiboss/60s](https://github.com/vikiboss/60s) | `https://60s.viki.moe/v2/douyin`、`https://60s.viki.moe/v2/weibo` |
| 热榜备用 | [solarhell/hot-search-crawler](https://github.com/solarhell/hot-search-crawler) | `https://solarhell.github.io/hot-search-crawler/latest.json` |

2026-11-18 实测：60s 的抖音返回 49 条、微博 50 条；它的小红书接口 `/v2/rednote` 报 500；备用源的小红书榜被限流。所以小红书热度改用 CreatorHub 关键词采集来查。视频号没有找到免费的热榜来源。

## 可选：指纹浏览器内核

- 仓库：https://github.com/adryfish/fingerprint-chromium
- 用途：给 CreatorHub 的抖音、视频号账号用，按账号的种子生成固定指纹。不装也能用，CreatorHub 自带的浏览器可以发布。
- 版本：有对应系统安装包的最新发行版
- 上次核对：148.0.7778.215（macOS），2026-11-18
- 安装位置：`browsers/`
