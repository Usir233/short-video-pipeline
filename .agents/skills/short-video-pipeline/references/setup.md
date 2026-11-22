# 新环境初始化和更新

本仓库只存规则（`AGENTS.md`、`.agents/`、`package.json`）。三个配套仓库、账号登录态、运行产物都不在里面，换环境后按本文件装回来。

**配套仓库一律装最新版本，不固定版本。**

所有命令在工作区根目录（`AGENTS.md` 所在目录）执行。

## 一律装在工作区里

用户已定：配套仓库和它们带来的一切，都装在本工作区的目录下。

- 不全局安装：不用 `npm install -g`、`sudo`、`pip install --user`，不往系统 Python 里装包，不用系统包管理器装东西。
- 不改全局 shell 配置文件、不建全局命令。命令优先用工作区里的路径调用（`node_modules/.bin/openfilm`、`rea-video/.venv/bin/rea-video`）；执行 `env.sh` 时仅在当前 shell 会话中把 `$SVP_ROOT/node_modules/.bin` 置顶到 `PATH`，避免直接敲 `openfilm` 误命中工作区外的全局版本。
- 不运行各仓库里往工作区之外安装的脚本（例如 rea-video 的 `scripts/install_skill.sh`）。
- **每个 shell 里先执行环境脚本，再执行下面任何命令：**

  ```bash
  . .agents/skills/short-video-pipeline/scripts/env.sh
  ```

  它设置的变量和对应的位置：

  | 变量 | 位置 | 内容 | 不设时会落到 |
  |---|---|---|---|
  | `OPENFILM_HOME` | `.local/openfilm/` | OpenFilm 的设置、服务连接、日志、库缓存 | `~/.openfilm` |
  | `OPENFILM_LIBRARY`、`OPENFILM_EXPORTS` | `runs/` | 没指定位置时的项目目录和导出目录 | `~/Movies/OpenFilm`、桌面 |
  | `OPENFILM_SAVED`、`OPENFILM_SKILLS` | `.local/openfilm-user/` | OpenFilm 公共素材区（`saved/`，可跨视频通过 `openfilm get my-media` 复用）、用户自己的 skill | `~/Movies/OpenFilm` |
  | `REA_VIDEO_MODELS` | `.local/rea-video/models/` | rea-video 的模型 | `~/.cache/rea-video/models` |
  | `REA_VIDEO_HOME` | `.local/rea-video/home/` | rea-video 的记忆文件 | `~/.rea-video` |
  | `PLAYWRIGHT_BROWSERS_PATH` | `browsers/ms-playwright/` | OpenFilm 渲染和 CreatorHub 用的浏览器内核 | 用户缓存目录下的 `ms-playwright` |
  | `npm_config_cache`、`PIP_CACHE_DIR` | `.local/npm-cache/`、`.local/pip-cache/` | 包管理器的下载缓存 | `~/.npm`、用户缓存目录 |
  | `SVP_ROOT` | 工作区根目录的绝对路径 | 给需要绝对路径的接口用 | — |
  | `PATH`（仅当前 shell） | 前置 `$SVP_ROOT/node_modules/.bin` | 确保当前 shell 中直接运行 `openfilm` 也命中工作区局部版 | 命中工作区外全局 `openfilm` |

  启动 CreatorHub 的那个 shell 也必须先执行它，否则 CreatorHub 会到用户缓存目录里找浏览器内核。

做不到放进工作区的，只有两类：

- 下面「机器上要先有」的系统级软件，由用户安装。
- 各工具运行时自己用的系统临时目录，文件是短暂的，用完即删。agent 自己的临时文件不放那里，放运行目录的 `tmp/`。

## 机器上要先有

| 需要 | 要求 | 检查 |
|---|---|---|
| git | — | `git --version` |
| Node.js 和 npm | Node 22.2 以上（OpenFilm 的要求） | `node --version` |
| Python | 3.12–3.14 中的任意一个（rea-video 需要；CreatorHub 只要 3.10 以上） | `python3.12 --version` 等 |
| ffmpeg、ffprobe | — | `ffmpeg -version` |
| Google Chrome | 发小红书时 CreatorHub 固定用它 | — |
| 桌面环境 | CreatorHub 发布时要打开有界面的浏览器 | — |

缺哪个就告诉用户，由用户安装，不要自己用包管理器往系统里装。

## 安装三个配套仓库

先执行环境脚本（见上一节），再往下做。

### 1. OpenFilm

```bash
npm install openfilm@latest          # 不带 -g，装到 node_modules/
node_modules/.bin/openfilm doctor
```

`doctor` 报缺渲染用的浏览器时，按它的提示处理；执行过环境脚本后，浏览器会下载到 `browsers/ms-playwright/`。`doctor` 的 `Data` 一行应当是工作区里的 `.local/openfilm`，`Projects` 一行应当是工作区里的 `runs`；不是的话说明环境脚本没生效，先解决再继续。

### 2. rea-video

```bash
git clone https://github.com/JuneYaooo/rea-video.git
python3.12 -m venv rea-video/.venv          # 换成本机有的 3.12–3.14 解释器
(cd rea-video && .venv/bin/python -m pip install -e ".[ocr,asr]")
rea-video/.venv/bin/rea-video --help
```

依赖装进 `rea-video/.venv`，不进系统 Python。不要运行它的 `scripts/install_skill.sh`：那个脚本会往系统 Python 和用户主目录里装东西。

装之前看一眼 `rea-video/skills/rea-video/references/setup.md`，新版本对 Python 或依赖的要求变了就以它为准。

### 3. CreatorHub

```bash
git clone https://github.com/3441293738/creatorhub.git
(cd creatorhub && python3 creatorhub.py install)
(cd creatorhub && python3 creatorhub.py start --no-open)    # 放后台运行
curl -fsS http://127.0.0.1:8000/health
```

`install` 会建它自己的虚拟环境（`creatorhub/.venv`）、下载浏览器组件（执行过环境脚本后下载到 `browsers/ms-playwright/`）、生成 `config.yaml`，需要联网，耗时较长。`start` 也要在执行过环境脚本的 shell 里运行。

装完后确认 `http://127.0.0.1:8000/health` 与 `http://127.0.0.1:8000/openapi.json` 均可正常返回；具体平台能力与接口定义直接参考 `creatorhub/README.md`、`creatorhub/guide/platforms.json` 和实时 `/openapi.json`（见 [creatorhub-api.md](creatorhub-api.md)）。

## 更新已有环境

用户说「更新配套仓库」时做。不要在一次做视频的流程中途自动更新。

```bash
. .agents/skills/short-video-pipeline/scripts/env.sh

# OpenFilm
npm install openfilm@latest

# rea-video
git -C rea-video pull --ff-only
(cd rea-video && .venv/bin/python -m pip install -e ".[ocr,asr]")

# CreatorHub：先确认没有正在执行的任务，再停服务、更新、重装依赖、重启
curl -fsS "http://127.0.0.1:8000/api/task-queue?state=running"
# 停服务：它没有 stop 命令，结束当初 `creatorhub.py start` 启动的那个进程
git -C creatorhub pull --ff-only
(cd creatorhub && python3 creatorhub.py install)
(cd creatorhub && python3 creatorhub.py start --no-open)    # 放后台运行
```

更新 CreatorHub 的注意事项：

- 有任务在执行，或有发布任务处在 `publishing`、`uncertain` 状态时，不要更新，告诉用户原因。
- 停服务前告诉用户一声。更新不会动 `creatorhub/data/`，但更新前仍建议用户自己备份这个目录。
- `git pull --ff-only` 失败（本地有改动或分叉）时停下报告，不要强行覆盖。

更新后必须做：

1. 跑一遍下面的「装完后的验证」。
2. 确认各配套仓库的最新文档与接口入口可读（`node_modules/openfilm/SYSTEM_PROMPT.md`、`rea-video/skills/rea-video/SKILL.md`、`creatorhub/guide/platforms.json` 以及 `http://127.0.0.1:8000/openapi.json`）。后续执行任务时直接以各仓库最新自带文档和实时接口为准，无需手工修改本工作区的参考文档。

## 需要用户亲自做的事

这些 agent 做不了，装完后请用户做：

1. 打开 `http://127.0.0.1:8000`，在账号页扫码登录抖音、小红书、视频号。
2. 小红书的号再做一次「创作者登录」，否则不能发布。
3. **强烈推荐（免费）**：到 Pexels（https://www.pexels.com/api/）和 Pixabay（https://pixabay.com/api/docs/）申请免费 API Key，在 `env.sh` 环境下打开局部 OpenFilm Studio 的 Settings → Services 填入，即可直接用 `openfilm get image-search` / `video-search --orientation portrait` 搜高清竖屏无版权 B-roll。不填也能跑（内置脚本 `scripts/fetch_asset.py` 会用免 Key 的官方新闻抓图/截图、Wikimedia/NASA/Archive 与代码画面兜底）。
4. 想用配音、AI 出图、AI 出视频：同样在 OpenFilm 的设置里接对应服务；不接也能跑。

## 可选：指纹浏览器内核

不装也能发布。要装的话：

1. 到 https://github.com/adryfish/fingerprint-chromium/releases 下载最新的、有对应系统安装包的发行版。不是每个版本都有所有系统的包，最新版没有就往前找一个有的。
2. 解出来放到 `browsers/fingerprint-chromium-<主版本号>/`。
3. 请用户在 CreatorHub 的浏览器内核设置里添加它的主程序路径，并设为默认。主程序文件名必须是 `chrome` 或 `chromium`（Windows 带 `.exe`），大小写不限。

## 装完后的验证

```bash
. .agents/skills/short-video-pipeline/scripts/env.sh
node_modules/.bin/openfilm doctor                               # Data、Projects 两行都在工作区里，Browser 一行正常
node_modules/.bin/openfilm get                                  # 列出自带库和可用服务
rea-video/.venv/bin/rea-video decompose <任意一个 mp4> -o runs/_check --lang zh
ls runs/_check/VIDEO.md runs/_check/video                       # 两者都在才算装对，看完删掉 runs/_check
curl -fsS http://127.0.0.1:8000/api/accounts                    # 能看到已登录的账号
```

## 以前装在工作区之外的环境

机器上已有旧的设置或缓存（见上面表格的「不设时会落到」一列）时：

- 执行环境脚本后，各工具只认工作区里的位置，旧位置不再使用。
- 想省掉重新下载，可以把旧位置里的模型和浏览器内核**复制**进工作区对应的目录。
- 旧位置的东西不要删：其他项目可能也在用。告诉用户有哪些、各占多大，由用户决定。
- CreatorHub 若是在执行环境脚本之前启动的，它仍在用旧位置的浏览器内核；下次由用户同意重启后才切换过来。

## 不随仓库迁移的东西

这些都在工作区里，但不进 git。换机器时整个工作区目录一起拷走就都带上了；只克隆仓库的话按下表处理。

| 内容 | 位置 | 只克隆仓库时 |
|---|---|---|
| 账号登录态、数据库、浏览器 Profile | `creatorhub/data/`、`creatorhub/config.yaml` | 重新登录。若要整体搬迁，由用户自己拷贝 `creatorhub/data/`；里面有明文登录态，不要经过网盘、聊天工具或代码仓库 |
| OpenFilm 的设置和服务连接 | `.local/openfilm/` | 重新连接。里面有密钥，同样不要外传 |
| rea-video 的模型 | `.local/rea-video/models/` | 首次运行自动重新下载 |
| 浏览器内核 | `browsers/` | 安装时重新下载；指纹浏览器按上面「可选」一节重装 |
| 归档的运行产物和总索引 | `runs/` | 需要去重历史时，由用户拷贝 `runs/topics-log.jsonl` |
