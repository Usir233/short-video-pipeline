# 短视频流水线工作区

这个工作区只做一件事：按固定流程做竖屏短视频，并分发到抖音、小红书、视频号。本说明面向任何 agent。

所有路径都是相对路径，相对本文件所在的目录。

## 必须先读

用户说「跑一条」「做一条视频」「按热点做」「主题：xxx」「复刻这条」「二创」「做同款」「发一条」，或给出参考视频时：

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

本仓库只存规则，不含配套仓库。`node_modules/`、`rea-video/`、`creatorhub/` 任何一个不存在时，先按 `.agents/skills/short-video-pipeline/references/setup.md` 安装。

配套仓库一律用最新版本，不固定版本。用户说「更新配套仓库」时，按同一个文件的「更新已有环境」做。

## 目录

| 位置 | 是否在本仓库里 | 内容 |
|---|---|---|
| `AGENTS.md`、`CLAUDE.md` | 是 | 入口说明 |
| `.agents/skills/short-video-pipeline/` | 是 | 流程（`SKILL.md`）、参考文件（`references/`）、环境脚本（`scripts/env.sh`） |
| `package.json` | 是 | 声明 OpenFilm 依赖，版本为 `latest` |
| `node_modules/openfilm/` | 否 | [openfilm/openfilm](https://github.com/openfilm/openfilm)：素材库、剪辑、渲染 |
| `rea-video/` | 否 | [JuneYaooo/rea-video](https://github.com/JuneYaooo/rea-video)：拆解参考视频，用于复刻和二创 |
| `creatorhub/` | 否 | [3441293738/creatorhub](https://github.com/3441293738/creatorhub)：账号、采集、下载、发布，本机接口 `http://127.0.0.1:8000` |
| `browsers/` | 否 | 浏览器内核：`ms-playwright/`（OpenFilm 渲染和 CreatorHub 共用），以及可选的指纹浏览器 |
| `.local/` | 否 | 配套仓库的设置、模型、缓存：`openfilm/`、`openfilm-user/`、`rea-video/`、`npm-cache/`、`pip-cache/` |
| `runs/` | 否 | 归档：每次运行一个目录，外加总索引 `topics-log.jsonl` |

参考文件：

- `references/repos.md`：配套仓库、命令入口、要读的 skill
- `references/setup.md`：新环境的安装步骤、已有环境的更新步骤
- `references/creatorhub-api.md`：分发用到的接口

## 不要做的事

- 不改 `rea-video/`、`creatorhub/`、`node_modules/` 里的源码。
- 不外传、不打印 `creatorhub/data/`、`creatorhub/config.yaml`、`.local/openfilm/`、浏览器 Profile、Cookie 的内容。
- 不把本仓库 `.gitignore` 白名单之外的东西加进 git。
- 不在本工作区之外安装、生成或存放任何东西。
