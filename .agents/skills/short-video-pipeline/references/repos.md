# 配套仓库与文档路径索引

所有路径均相对工作区根目录。安装和更新步骤见 [setup.md](setup.md)。

三个配套仓库全部装在本工作区内，不全局安装；设置、模型、缓存、浏览器内核均由 `.agents/skills/short-video-pipeline/scripts/env.sh` 重定向到工作区内。运行任何命令前先 `source` 该环境脚本。

**设计原则：配套仓库一律使用最新版本，不固定版本，也不在本仓库中手工抄写各工具的用法明细、接口字段或版本号记录。** 无论上游如何升级、重构或新增能力，Agent 均直接读取各配套仓库自带的相对文档 / Skill 路径与实时接口。

## 三个配套仓库

### 1. openfilm/openfilm（素材库、剪辑、渲染）

- 仓库：https://github.com/openfilm/openfilm（根目录 `package.json` 声明 `openfilm: latest`）
- 安装位置：`node_modules/openfilm/`
- 命令入口：`node_modules/.bin/openfilm`（执行 `env.sh` 后当前 shell 直接 `openfilm` 也优先命中它）
- **项目自身文档与 Skill 路径（直接使用，随更新自动生效）**：
  - `node_modules/openfilm/SYSTEM_PROMPT.md`（总入口，或无参运行 `openfilm`）
  - `node_modules/openfilm/manual/`（各子 skill，如 `manual/film/SKILL.md`、`manual/media/SKILL.md`，或用 `openfilm skill <名称>` 查看）
  - `node_modules/openfilm/SPEC.md`（`film.html` 规范）
  - `node_modules/openfilm/README.md`
- **本工作区补充约束**：
  - 设置与服务连接在 `.local/openfilm/`（`OPENFILM_HOME`），公共复用素材区在 `.local/openfilm-user/saved/`（`OPENFILM_SAVED`），项目与导出落在 `runs/`，浏览器内核在 `browsers/ms-playwright/`；均由 `env.sh` 控制，不外泄 `.local/openfilm/`。
  - 当前可用免费库与已连接服务实时运行 `openfilm get` 查看。

### 2. JuneYaooo/rea-video（参考视频拆解与复刻分析）

- 仓库：https://github.com/JuneYaooo/rea-video（默认分支最新提交）
- 安装位置：`rea-video/`，虚拟环境 `rea-video/.venv`（内置 `yt-dlp` 供素材脚本独立复用）
- 命令入口：执行 `env.sh` 后用 `"$SVP_REA_VIDEO"`（Unix 为 `rea-video/.venv/bin/rea-video`，Windows 为 `rea-video/.venv/Scripts/rea-video.exe`，运行 `--help` 查看最新子命令）
- **项目自身文档与 Skill 路径（直接使用，随更新自动生效）**：
  - `rea-video/skills/rea-video/SKILL.md`（主流程与规范）
  - `rea-video/skills/rea-video/references/`（全部细则参考，按 `SKILL.md` 指引按需读取）
  - `rea-video/AGENTS.md`、`rea-video/README.md`、`rea-video/docs/`（架构、CLI 与环境文档）
- **本工作区补充约束**：
  - 依赖与 Python 版本要求以 `rea-video/skills/rea-video/references/setup.md` 为准，必须装在 `rea-video/.venv` 中；**不运行**会往系统目录写入的 `scripts/install_skill.sh`。
  - 模型与记忆目录由 `env.sh` 重定向到 `.local/rea-video/`。
  - 文档中提到的第三方付费/外部复刻执行工具（如 capsule-cinema、ChatCut 及 `code-render` 外部渲染器）本工作区不安装、不使用，成片统一用 OpenFilm 制作。

### 3. 3441293738/creatorhub（可选模块 · 当前默认停用）

- 仓库：https://github.com/3441293738/creatorhub（默认分支最新提交）
- 安装位置：`creatorhub/`（**当前默认停用静置，日常流程不启动 `8000` 服务，仅在用户显式要求启用时按需使用**）
- 命令入口：在 `creatorhub/` 下执行 `python3 creatorhub.py`（`--help` 查看最新子命令）；本机服务地址 `http://127.0.0.1:8000`
- **项目自身文档与接口路径（直接使用，随更新自动生效）**：
  - `creatorhub/README.md`（项目总览与平台能力）
  - `creatorhub/guide/platforms.json`、`creatorhub/guide/index.html`、`creatorhub/guide/README.md`（各平台功能手册与使用限制）
  - 实时全量接口：`http://127.0.0.1:8000/openapi.json`（可视化文档 `http://127.0.0.1:8000/docs`）
  - 按需单文件源码入口：`creatorhub/app/api/__init__.py`、`creatorhub/app/api/`、`creatorhub/app/transport_matrix.py`、`creatorhub/app/platforms/`
- **本工作区补充约束**：
  - 调用顺序、异常排障与安全红线见 [creatorhub-api.md](creatorhub-api.md)。
  - 账号登录态、数据库、浏览器 Profile 在 `creatorhub/data/`，配置在 `creatorhub/config.yaml`，严禁外传、读取或打印；小红书固定依赖本机 Google Chrome。

## 公开热榜与素材寻源脚本（本工作区自带）

不额外安装第三方仓库，统一封装在 `.agents/skills/short-video-pipeline/scripts/`（`fetch_trends.py`、`fetch_asset.py`），源矩阵、降级链路与用法见 [sourcing.md](sourcing.md)。

## 可选：指纹浏览器内核

- 仓库：https://github.com/adryfish/fingerprint-chromium/releases
- 用途：供 CreatorHub 抖音、视频号账号按种子生成固定浏览器指纹（不装也可正常使用自带浏览器发布）。
- 安装位置：`browsers/fingerprint-chromium-<主版本号>/`（按当前系统取最新有对应安装包的发行版，见 [setup.md](setup.md)）。
