# 短视频流水线工作区

这个工作区只做一件事：按固定流程做竖屏短视频，并分发到抖音、小红书、视频号。本说明面向任何 agent。

所有路径都是相对路径，相对本文件所在的目录。

## 必须先读

用户说「跑一条」「做一条视频」「按热点做」「主题：xxx」「复刻这条」「二创」「做同款」「发一条」，或给出参考视频时：

**先读 `.agents/skills/short-video-pipeline/SKILL.md`，严格按它执行。** 不要让用户重复说明流程，也不要自己另起一套做法。

它会指向各配套仓库自带的 skill，进入每一步之前先把对应的 skill 读完。

## 新环境

本仓库只存规则，不含配套仓库。`node_modules/`、`rea-video/`、`creatorhub/` 任何一个不存在时，先按 `.agents/skills/short-video-pipeline/references/setup.md` 安装。

## 目录

| 位置 | 是否在本仓库里 | 内容 |
|---|---|---|
| `AGENTS.md`、`CLAUDE.md` | 是 | 入口说明 |
| `.agents/skills/short-video-pipeline/` | 是 | 流程（`SKILL.md`）和参考文件（`references/`） |
| `package.json`、`package-lock.json` | 是 | 固定 OpenFilm 的版本 |
| `node_modules/openfilm/` | 否 | [openfilm/openfilm](https://github.com/openfilm/openfilm)：素材库、剪辑、渲染 |
| `rea-video/` | 否 | [JuneYaooo/rea-video](https://github.com/JuneYaooo/rea-video)：拆解参考视频，用于复刻和二创 |
| `creatorhub/` | 否 | [3441293738/creatorhub](https://github.com/3441293738/creatorhub)：账号、采集、下载、发布，本机接口 `http://127.0.0.1:8000` |
| `browsers/` | 否 | CreatorHub 用的浏览器内核，可选 |
| `runs/` | 否 | 每次运行的产物和选题日志 |

参考文件：

- `references/repos.md`：配套仓库的固定版本、命令入口、要读的 skill
- `references/setup.md`：新环境的安装步骤
- `references/creatorhub-api.md`：分发用到的接口

## 不要做的事

- 不改 `rea-video/`、`creatorhub/`、`node_modules/` 里的源码。
- 不外传、不打印 `creatorhub/data/`、`creatorhub/config.yaml`、浏览器 Profile、Cookie 的内容。
- 不把本仓库 `.gitignore` 白名单之外的东西加进 git。
