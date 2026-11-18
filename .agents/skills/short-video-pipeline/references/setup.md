# 新环境初始化

本仓库只存规则（`AGENTS.md`、`.agents/`）和 OpenFilm 的版本锁定文件。三个配套仓库、账号登录态、运行产物都不在里面，换环境后按本文件装回来。

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
npm install
node_modules/.bin/openfilm doctor
```

版本由 `package-lock.json` 固定。`doctor` 报缺渲染用的浏览器时，按它的提示处理。

### 2. rea-video

```bash
git clone https://github.com/JuneYaooo/rea-video.git
git -C rea-video checkout 07dd587119e884f7c50fbfae92e47840de86bea5
python3.12 -m venv rea-video/.venv          # 换成本机有的 3.12–3.14 解释器
(cd rea-video && .venv/bin/python -m pip install -e ".[ocr,asr]")
rea-video/.venv/bin/rea-video --help
```

不要运行它的 `scripts/install_skill.sh`：那个脚本会往系统 Python 和用户主目录里装东西。

### 3. CreatorHub

```bash
git clone https://github.com/3441293738/creatorhub.git
git -C creatorhub checkout a902546d4df0d15799da339c13d6f09120b93351
(cd creatorhub && python3 creatorhub.py install)
(cd creatorhub && python3 creatorhub.py start --no-open)    # 放后台运行
curl -fsS http://127.0.0.1:8000/health
```

`install` 会建它自己的虚拟环境、下载浏览器组件、生成 `config.yaml`，需要联网，耗时较长。

## 需要用户亲自做的事

这些 agent 做不了，装完后请用户做：

1. 打开 `http://127.0.0.1:8000`，在账号页扫码登录抖音、小红书、视频号。
2. 小红书的号再做一次「创作者登录」，否则不能发布。
3. 想用配音、出图、出视频、素材搜索：在 OpenFilm 的设置里接上对应服务。不接也能跑，画面以自带库和代码画面为主。

## 可选：指纹浏览器内核

不装也能发布。要装的话：

1. 到 https://github.com/adryfish/fingerprint-chromium/releases 下载对应系统的安装包。核对过的版本是 148.0.7778.215（macOS 包名 `ungoogled-chromium_148.0.7778.215-1.1_macos.dmg`）。
2. 解出来放到 `browsers/fingerprint-chromium-148/`。
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
