# 新环境初始化和更新

本仓库只存规则（`AGENTS.md`、`.agents/`、`package.json`）。三个配套仓库、账号登录态、运行产物都不在里面，换环境后按本文件装回来。

**配套仓库一律装最新版本，不固定版本。**

所有命令在工作区根目录（`AGENTS.md` 所在目录）执行。

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

### 1. OpenFilm

```bash
npm install openfilm@latest
node_modules/.bin/openfilm doctor
```

`doctor` 报缺渲染用的浏览器时，按它的提示处理。

### 2. rea-video

```bash
git clone https://github.com/JuneYaooo/rea-video.git
python3.12 -m venv rea-video/.venv          # 换成本机有的 3.12–3.14 解释器
(cd rea-video && .venv/bin/python -m pip install -e ".[ocr,asr]")
rea-video/.venv/bin/rea-video --help
```

不要运行它的 `scripts/install_skill.sh`：那个脚本会往系统 Python 和用户主目录里装东西。

装之前看一眼 `rea-video/skills/rea-video/references/setup.md`，新版本对 Python 或依赖的要求变了就以它为准。

### 3. CreatorHub

```bash
git clone https://github.com/3441293738/creatorhub.git
(cd creatorhub && python3 creatorhub.py install)
(cd creatorhub && python3 creatorhub.py start --no-open)    # 放后台运行
curl -fsS http://127.0.0.1:8000/health
```

`install` 会建它自己的虚拟环境、下载浏览器组件、生成 `config.yaml`，需要联网，耗时较长。

装完后按 [creatorhub-api.md](creatorhub-api.md) 开头写的办法，核对接口文档和当前版本是否一致。

## 更新已有环境

用户说「更新配套仓库」时做。不要在一次做视频的流程中途自动更新。

```bash
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
2. 重新读各仓库的 skill（`openfilm skill edit`、`openfilm skill media`、`rea-video/skills/rea-video/SKILL.md`），做法变了以新的为准。
3. 按 [creatorhub-api.md](creatorhub-api.md) 开头写的办法重新核对接口。
4. 把 [repos.md](repos.md) 里各仓库的「上次核对」改成当前版本和日期。

## 需要用户亲自做的事

这些 agent 做不了，装完后请用户做：

1. 打开 `http://127.0.0.1:8000`，在账号页扫码登录抖音、小红书、视频号。
2. 小红书的号再做一次「创作者登录」，否则不能发布。
3. 想用配音、出图、出视频、素材搜索：在 OpenFilm 的设置里接上对应服务。不接也能跑，画面以自带库和代码画面为主。

## 可选：指纹浏览器内核

不装也能发布。要装的话：

1. 到 https://github.com/adryfish/fingerprint-chromium/releases 下载最新的、有对应系统安装包的发行版。不是每个版本都有所有系统的包，最新版没有就往前找一个有的。
2. 解出来放到 `browsers/fingerprint-chromium-<主版本号>/`。
3. 请用户在 CreatorHub 的浏览器内核设置里添加它的主程序路径，并设为默认。主程序文件名必须是 `chrome` 或 `chromium`（Windows 带 `.exe`），大小写不限。

## 装完后的验证

```bash
node_modules/.bin/openfilm get                                  # 列出自带库和可用服务
rea-video/.venv/bin/rea-video decompose <任意一个 mp4> -o runs/_check --lang zh
ls runs/_check/VIDEO.md runs/_check/video                       # 两者都在才算装对，看完可删掉 runs/_check
curl -fsS http://127.0.0.1:8000/api/accounts                    # 能看到已登录的账号
```

## 不随仓库迁移的东西

| 内容 | 位置 | 换环境后 |
|---|---|---|
| 账号登录态、数据库、浏览器 Profile | `creatorhub/data/`、`creatorhub/config.yaml` | 重新登录。若要整体搬迁，由用户自己拷贝 `creatorhub/data/`；里面有明文登录态，不要经过网盘、聊天工具或代码仓库 |
| OpenFilm 的服务连接 | `~/.openfilm` | 重新连接 |
| rea-video 的模型缓存 | `~/.cache/rea-video/models` | 首次运行自动重新下载 |
| 运行产物和选题日志 | `runs/` | 需要去重历史时，由用户拷贝 `runs/topics-log.jsonl` |
| 浏览器内核 | `browsers/` | 按上面「可选」一节重装 |
