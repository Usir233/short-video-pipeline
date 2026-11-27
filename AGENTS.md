# 短视频流水线工作区

这个工作区只做一件事：按固定流程做竖屏短视频，并分发到抖音、小红书、视频号。本说明面向任何 agent。

所有路径都是相对路径，相对本文件所在的目录。

## 必须先读

用户说「跑一条」「做一条视频」「按热点做」「主题：xxx」「复刻这条」「二创」「做同款」「发一条」「直接发 xxx.mp4」「写三平台文案」「做封面」「做母片和4条子片」「一条变四条」「做母片和3条子片」「一条变三条」「一鱼多吃」「母片裂变」，或给出参考视频/原片素材/待发成片时：

**先读 `.agents/skills/short-video-pipeline/SKILL.md`，严格按它执行。** 不要让用户重复说明流程，也不要自己另起一套做法。

它会指向各配套仓库自带的 skill，进入每一步之前先把对应的 skill 读完。

## 一切留在本工作区内

两条硬规定，任何步骤都适用：

1. **安装只装在本工作区里。** 配套仓库、它们的依赖、模型、浏览器内核、设置和缓存，全部放在本工作区的目录下。不全局安装（不用 `npm -g`、`sudo`、`pip install --user`、系统 Python、系统包管理器），不改 PATH 和 shell 配置文件，不往用户主目录里放东西。
2. **处理和生成的东西只放在本工作区里，并按规范归档。** 每次运行一个目录 `runs/<日期时间>-<话题短名>/`，选题、参考视频、脚本、素材、成片、发布记录都在里面，结构见 `SKILL.md` 的「归档规范」。不往桌面、下载目录、`~/Movies`、用户主目录、系统临时目录里放任何文件。

做法：安装、更新、运行配套仓库的任何命令之前，先在同一个 shell 里执行

```bash
. .agents/skills/short-video-pipeline/scripts/env.sh
```

它把各仓库的设置、缓存、模型、浏览器内核的位置都指到本工作区里。每个新开的 shell 都要重新执行一次。

## 新环境

本仓库只存规则，不含配套仓库。`node_modules/`、`rea-video/` 任何一个不存在时，先按 `.agents/skills/short-video-pipeline/references/setup.md` 安装（`creatorhub/` 当前默认停用，日常做片不安装也不启动，仅在用户显式要求启用时按需处理）。

配套仓库一律用最新版本，不固定版本。用户说「更新配套仓库」时，按同一个文件的「更新已有环境」做。

## 目录

| 位置 | 是否在本仓库里 | 内容 |
|---|---|---|
| `AGENTS.md`、`CLAUDE.md` | 是 | 入口说明 |
| `.ignore`、`.geminiignore`、`.cursorignore`、`.cursorindexingignore`、`.claude/settings.json` | 是 | 面向各 Agent（Antigravity / Codex / Claude Code / Cursor）的工作区忽略与索引提速配置，仅作用于本工作区 |
| `.agents/skills/short-video-pipeline/` | 是 | 流程（`SKILL.md`）、参考规范（`references/`）、5 套离线校准 3D 调色 LUT（`assets/luts/*.cube`）、环境/寻源/候选检视签收/Python GPU 钩子与声画质检脚本（`scripts/env.sh`、`scripts/py_gpu_site/`、`fetch_trends.py`、`fetch_asset.py` 含 `inspect-candidates` 与 `register --shot --fit-reason`、`qc_video.py` 含 `prepare-voice`/`normalize-sfx`/`build-bgm-bed`/`stabilize-broll`/`audit-render`/`audit-matrix`） |
| `assets/brand/` | 是 | 品牌通用静态素材（透明底品牌 Logo `logo.png` 与按系列分类的视觉参考样图 `samples/`；单期/专题标题图属非通用资产，放各自运行目录不入 git） |
| `package.json` | 是 | 声明 OpenFilm 依赖，版本为 `latest` |
| `node_modules/openfilm/` | 否 | [openfilm/openfilm](https://github.com/openfilm/openfilm)：素材库、剪辑、渲染 |
| `rea-video/` | 否 | [JuneYaooo/rea-video](https://github.com/JuneYaooo/rea-video)：拆解参考视频，用于复刻和二创 |
| `creatorhub/` | 否 | [3441293738/creatorhub](https://github.com/3441293738/creatorhub)（**当前默认停用**，不自动启动服务；仅在用户显式要求自动发布或平台采集时按需启用，本机接口 `http://127.0.0.1:8000`） |
| `browsers/` | 否 | 浏览器内核：`ms-playwright/`（OpenFilm 渲染与新闻抓图/封面截图共用；按需启用 CreatorHub 时亦共用），以及可选的指纹浏览器 |
| `.local/` | 否 | 配套仓库的设置、模型、缓存：`openfilm/`、`openfilm-user/`（其中 `saved/` 下按 `broll/`、`music/`、`sfx/`、`series/` 存放跨期复用的公共素材，可被 `openfilm get my-media` 检索）、`rea-video/`、`npm-cache/`、`pip-cache/` |
| `素材投递区/` | 否 | 后续各期视频与配套素材投递区（不进 git，同盘零重复拷贝）：`已粗剪/`（已处理可直接当母素材）、`未处理原片/`（需先粗剪与预处理）、`参考爆款/`（入口 C 复刻参考）、`待直发成片/`（入口 D 已有成片补齐文案/封面与审核交付） |
| `runs/` | 否 | 归档：每次运行一个目录，外加总索引 `topics-log.jsonl` |

参考文件：

- `references/repos.md`：配套仓库及其自带文档/Skill 的相对路径索引（不再手抄上游用法与版本号）
- `references/sourcing.md`：国内外热点矩阵、5 类镜头素材寻源方案与 API 素材「候选暂存 → 六维制作要求核验 → 实名签收」强制门禁
- `references/setup.md`：新环境的安装步骤、已有环境的更新步骤
- `references/copywriting.md`：视频号、小红书、抖音发布文案写法（`content_archetype` 诚实钩子契约、四项文案、反论文腔短标题、禁生造歧义缩略词、三层标签法、辰奕品牌主张融入与多片防雷同）
- `references/cover-design.md`：双轨制三平台口播封面设计规范（Track A「意图电商」专属品牌模版 + Track B 通用口播 5 套商业杂志拓扑 `C1–C5`、20–30 帧 `contact-sheet.jpg` 五维选帧、亮底禁裸抠像与 `≥104px` 巨字视觉锤）
- `references/editing-styles.md`：十大短视频剪辑风格总谱（`S01–S10`）、单片路由与入口 E 五槽位正交选型、8 大类 34 项剪辑蒙太奇刀法（`H1–H6` 黄金 3 秒冷开、`D1–D5` 精剪去口癖、`JL1–JL5` 声画错位与 B-roll 遮切、`C1–C8` 光学运镜、`L1–L7` 版式拓扑、`B1–B8` B-roll 稳像防抖/运镜解耦/六维签收铁律与 `O1–O4` 尾韵）
- `references/editing-vfx.md`：OpenFilm 特效与动态视觉规范（去框化 Boxless 四定律、10 轨标准栈、7 大类 42 项特效原语 `KT1–KT8`/`DV1–DV8`/`PF1–PF7`/`TR1–TR10`/`AT1–AT5`、`SUB1–SUB6` 零胶囊框五槽等距字幕矩阵、`--of-lut` 调色与同源虚化光学抠像、两段式广播级混音管线与声画耦合）
- `references/multi-variant.md`：入口 E 完整规范（原片+素材分流、`prepare-voice` 人声母带、粗剪/马赛克确认闸门、母素材确立、EDL `time_slices` 精剪冷开、强制固定 1 完整特效母片 + 4 正交风格子片、防传混命名与 `delivery/` 统一交付包）
- `references/creatorhub-api.md`：CreatorHub 文档索引、调用约定（含 `v0.6.0` 账号角色隔离、脱敏诊断、封面边界）与安全红线（**当前默认停用，仅在用户显式要求启用时参考**）
- `references/publish-audit.md`：发布前审核门禁（Boxless 动态视觉、调色/光学抠像、声学 `LRA`/闪避床、API 素材六维签收 `asset_fit_signoff`、B-roll `YAVG`/`scdet`/`vidstab` 防抖/`dHash`、零胶囊字幕、双轨封面与诚实钩子全量硬校验、入口 E 跨 5 片反克隆与路径收口门禁）

## 检索范围与提速约定（面向所有 Agent）

本工作区包含大量本地依赖、浏览器内核、模型缓存与视频文件（约 4 GB+）。无论使用 **Antigravity、Codex、Claude Code 还是 Cursor**：

- 不要对整个工作区或 `browsers/`、`.local/`、`**/.venv/`、`creatorhub/data/`、`creatorhub/node_modules/`、`creatorhub/desktop/`、`creatorhub/frontend/`、`node_modules/openfilm/library/` 做全量递归扫描。
- 查询任何配套工具的用法、能力或接口时，直接按 `references/repos.md` 中的相对路径读取该工具自带文档（`node_modules/openfilm/`、`rea-video/`、`creatorhub/`）或运行中的 `http://127.0.0.1:8000/openapi.json`，不要全量扫描其源码目录。
- 仅按明确路径访问所需文件：`素材投递区/<分类>/<期次>/`、`runs/<目录>/`、`rea-video/`（`AGENTS.md`、`README.md`、`skills/`、`docs/`）、`node_modules/openfilm/`（`SYSTEM_PROMPT.md`、`README.md`、`SPEC.md`、`manual/`）、`creatorhub/`（`README.md`、`guide/`、`app/api/`、`app/transport_matrix.py`、`app/platforms/`）。

## 不要做的事

- 不改 `rea-video/`、`creatorhub/`、`node_modules/` 里的源码。
- 不外传、不打印 `creatorhub/data/`、`creatorhub/config.yaml`、`.local/openfilm/`、浏览器 Profile、Cookie 的内容。
- 不把本仓库 `.gitignore` 白名单之外的东西加进 git。
- 不在本工作区之外安装、生成或存放任何东西。
