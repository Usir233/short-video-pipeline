---
name: short-video-pipeline
description: 在本工作区按固定流程做竖屏短视频并分发：热点选题或指定主题或复刻参考视频 → 脚本分镜 → 寻找或生成素材 → OpenFilm 剪辑渲染 → CreatorHub 发布到抖音、小红书、视频号。用户说「跑一条」「做一条视频」「按热点做」「主题：xxx」「复刻这条」「二创」「做同款」「发一条」，或给出一条参考视频的链接、分享文案、文件时使用。
---

# 短视频流水线

所有路径都是相对路径，相对工作区根目录，也就是 `AGENTS.md` 所在的目录。命令默认在根目录执行，另有说明的除外。不要在任何文件里写死绝对路径；接口要求绝对路径时，运行时现算（执行环境脚本后用 `$SVP_ROOT`，见下一节）。

本文件面向任何 agent，不依赖某一家的专有工具。只假设你能执行命令、读写文件。其他能力有就用，没有就按「能力不足时的退路」处理。

用户已定：这条流程由 agent 从头跑到发布，中途不逐步请示；素材由 agent 自行寻找或生成。

## 一切留在工作区内

用户已定，任何步骤都适用：

- **安装只装在工作区里**，不全局安装，不往用户主目录里放东西。细则见 [references/setup.md](references/setup.md)。
- **处理和生成的东西只放在工作区里**，并按下面的「归档规范」归档。不往桌面、下载目录、`~/Movies`、用户主目录、系统临时目录里放任何文件。
- 安装、更新、运行配套仓库的任何命令之前，先在同一个 shell 里执行环境脚本，它把各仓库的设置、缓存、模型、浏览器内核的位置都指到工作区里：

  ```bash
  . .agents/skills/short-video-pipeline/scripts/env.sh        # 在根目录
  . ../../../.agents/skills/short-video-pipeline/scripts/env.sh   # 在 runs/<目录>/film/ 里
  ```

  每个新开的 shell 都要重新执行一次。执行后 `$SVP_ROOT` 是工作区根目录的绝对路径，接口要绝对路径时用它。
- 你自带的工具（生成图片、生成视频、下载、截图）把文件存到了工作区之外时，立刻把文件移进本次运行的目录，外面不留。
- 你自己的草稿、脚本、中间文件放本次运行的 `tmp/`，不放系统临时目录。

## 用到的仓库

每一步用哪个仓库、读它的哪个 skill，写在下表。**进入某一步之前，先把该仓库的 skill 整篇读完再动手**，按它的做法做。配套仓库一律用最新版本，不固定版本。命令入口见 [references/repos.md](references/repos.md)，新环境的安装和已有环境的更新见 [references/setup.md](references/setup.md)。用户说「更新配套仓库」时，按 `setup.md` 的「更新已有环境」做。

| 步骤 | 仓库 | 本机位置 | 先读的 skill 或文档 |
|---|---|---|---|
| 选题（热榜） | [vikiboss/60s](https://github.com/vikiboss/60s)，备用 [solarhell/hot-search-crawler](https://github.com/solarhell/hot-search-crawler) | 不安装，直接调它们的公开接口 | 无 |
| 选题（小红书热度）、取参考视频 | [3441293738/creatorhub](https://github.com/3441293738/creatorhub) | `creatorhub/` | [references/creatorhub-api.md](references/creatorhub-api.md) |
| 复刻：拆解参考视频 | [JuneYaooo/rea-video](https://github.com/JuneYaooo/rea-video) | `rea-video/` | `rea-video/skills/rea-video/SKILL.md` 及它指向的 `references/` |
| 素材 | [openfilm/openfilm](https://github.com/openfilm/openfilm) | `node_modules/openfilm/` | `openfilm skill media` |
| 剪辑、渲染 | openfilm/openfilm | `node_modules/openfilm/` | `node_modules/openfilm/MANUAL.md`，`openfilm skill edit` |
| 分发 | 3441293738/creatorhub | `creatorhub/` | [references/creatorhub-api.md](references/creatorhub-api.md) |

CreatorHub 仓库里没有给 agent 的 skill，它的接口整理在 `references/creatorhub-api.md`。

## 三种入口

| 用户说 | 入口 | 走哪些步骤 |
|---|---|---|
| 「跑一条」「按热点做一条」 | A 热点原创 | 1 → 3 → 4 → 5 → 6 → 7 |
| 「主题：xxx」「做一条关于 xxx 的」 | B 指定主题 | 3 → 4 → 5 → 6 → 7 |
| 「复刻这条」「二创」「做同款」，或给了参考视频 | C 复刻 | 2 → 3 → 4 → 5 → 6 → 7。没给新主题时先走步骤 1 选题 |

指令里的附加词：

- 「参考爆款」：A 或 B 里加做步骤 2，参考视频由 agent 用 CreatorHub 采集该题下点赞最高的一条视频。
- 「只发抖音」「不发小红书」等：只发指定平台。
- 「先给我看」「只做不发」：做到步骤 5 停下，给出成片路径，等用户说发再发。

没有附加词时：三个平台都发，做完直接发。

## 归档规范

每次运行建一个目录，这次运行的所有东西都放在里面。下文把它叫「运行目录」。

**目录名**：`runs/<YYYYMMDD-HHMM>-<话题短名>/`

- 时间是开始运行时的本机时间，例如 `20261118-1805`。
- 话题短名 2–12 个字，能让人一眼看出是哪个话题，中文或英文都可以。只用汉字、字母、数字和连字符，不含空格、标点、斜杠。例如 `runs/20261118-1805-立冬养生/`。
- 同一分钟内重名时在末尾加 `-2`、`-3`。
- 入口 A 要先选题才知道话题：先把取到的热榜存到 `runs/tmp-<YYYYMMDD-HHMM>/topic/`，题目定下后把这个目录改成正式名字。

**目录结构**：

```
runs/
├── topics-log.jsonl              总索引，每次运行一行
└── <YYYYMMDD-HHMM>-<话题短名>/
    ├── run.json                  本次运行的索引
    ├── topic/                    选题
    │   ├── topic.json            题目、来源、热度、事实及出处
    │   └── hotlist-<来源>.json    取到的热榜和采集到的热度，原样存一份
    ├── ref/                      参考视频和拆解结果，只用来分析，不得进入成片
    │   ├── <参考视频文件>
    │   └── out/                  rea-video 的拆片包
    ├── script/
    │   └── storyboard.json       脚本和分镜
    ├── materials/                素材原件：生成工具给出的原始文件、裁剪转码前的文件、没被采用的备选
    ├── film/                     OpenFilm 项目
    │   ├── film.html 和各镜页面
    │   └── assets/               成片实际用到的素材，外加 credits.json（每个素材的来源和提示词）
    ├── output/
    │   ├── final.mp4             成片
    │   └── check/                出片自检的记录：看过的帧图、ffprobe 的输出、check.json
    ├── publish/
    │   └── publish.json          各平台的标题、正文、话题、任务 id、结果、作品链接
    └── tmp/                      草稿和中间文件，运行结束时删掉
```

用不到的目录不建（入口 A、B 不带「参考爆款」时没有 `ref/`）。不在运行目录的根上另放文件，也不自创别的子目录。

**`run.json`**：建目录时就写，每做完一步更新一次，中途停下也要留下当时的状态。字段：

- `id`：目录名
- `topic`：完整的话题
- `entry`：`A`、`B` 或 `C`
- `started_at`、`finished_at`：带时区的时间
- `status`：`running`（进行中）、`made`（成片已出、未发布）、`published`（要发的平台都发成功）、`partial`（部分平台成功）、`failed`（失败）、`stopped`（按用户要求或因问题停下）
- `step`：做到第几步
- `platforms`：每个平台的任务 id、状态、作品链接
- `versions`：OpenFilm 的版本号，rea-video 和 CreatorHub 的提交号
- `notes`：跳过了什么、为什么停下、需要用户处理的事

**不属于某一次运行的东西**不放进 `runs/`：配套仓库的设置、模型、缓存在 `.local/`，浏览器内核在 `browsers/`，CreatorHub 的账号数据和上传的成片副本在 `creatorhub/data/`。

## 步骤 0：开始前检查

1. 环境：执行 `. .agents/skills/short-video-pipeline/scripts/env.sh`。
2. 配套仓库：`node_modules/.bin/openfilm`、`rea-video/.venv/bin/rea-video`、`creatorhub/creatorhub.py` 三者都在。缺任何一个，先按 [references/setup.md](references/setup.md) 装好再继续。
3. CreatorHub：`curl -fsS http://127.0.0.1:8000/health`。不通就在执行过环境脚本的 shell 里，进 `creatorhub/` 后台执行 `python3 creatorhub.py start --no-open`，等到通。
4. 账号：按 `references/creatorhub-api.md` 的「查账号」取每个平台可发布的账号。账号 id 每次现查。某平台不可发布时这次跳过它，并在最后告诉用户原因。一个可用账号都没有时（新环境还没登录），请用户打开 `http://127.0.0.1:8000` 登录后再继续。
5. 建运行目录，写 `run.json`，见「归档规范」。
6. 判断这次要不要派子代理，见「子代理」。

## 步骤 1：选题（入口 A）

1. 取热榜（需要联网）：
   - 抖音 `https://60s.viki.moe/v2/douyin`，微博 `https://60s.viki.moe/v2/weibo`。读 `data[]` 的 `title`、`hot_value`、`link`。
   - 不通时用 `https://solarhell.github.io/hot-search-crawler/latest.json`，读 `boards[].items[]`。
   - 小红书没有可用的免费热榜：挑出 2–3 个候选后，用 CreatorHub 关键词采集查它们在小红书的热度（见 `references/creatorhub-api.md` 的「查热度」）。失败就跳过，不阻塞。
   - 视频号没有热榜来源，沿用选出的题。
2. 筛选：
   - 跳过时政、领导人、外交、军事；灾难伤亡；未证实的传闻；针对具体个人的负面事件；医疗和投资建议。
   - 跳过 `runs/topics-log.jsonl` 里近 14 天做过的题。
   - 在剩下的里选热度高、普通人关心、15–30 秒能讲清一个点的题。
3. 筛完没有合适的：把榜单前 10 列给用户，等用户指定，不硬做。
4. 取到的热榜和热度原样存成 `topic/hotlist-<来源>.json`，写 `topic/topic.json`，把运行目录改成正式名字。

## 步骤 2：复刻拆解（入口 C，或带「参考爆款」）

**先整篇读 `rea-video/skills/rea-video/SKILL.md`，按它的流程做。** 本工作区的约定：

- 命令不在 PATH 里，用 `rea-video/.venv/bin/rea-video`。
- 默认不配 VLM。你能看图时，你就是 VLM：必须做它的「看图复核并入」（`review` → 填 `review_answers.json` → `apply-review`）。
- 按 `references/setup.md` 安装时带了字幕识别和语音识别，`decompose` 不要加 `--no-asr`、`--no-packaging`。

做法：

1. 拿到参考视频，放进 `ref/`：
   - 用户给了本地文件：复制进来。
   - 用户给了链接或分享文案：用 CreatorHub 的「下载分享链接」，`output_dir` 填运行目录里 `ref/` 的绝对路径（`$SVP_ROOT/runs/<目录>/ref`）。
   - 「参考爆款」：用 CreatorHub 关键词采集找到该题下点赞最高的视频，再用它的链接下载。
2. 在运行目录里，先执行环境脚本（`. ../../.agents/skills/short-video-pipeline/scripts/env.sh`），再执行 `../../rea-video/.venv/bin/rea-video decompose ref/<文件> -o ref/out --lang zh`，然后 `summary`、`review`、`apply-review`。所有输出都指到 `ref/out`。
3. 按 rea-video skill 说的顺序读拆片包：`ref/out/VIDEO.md` → `video/content.md`（叙事线）→ `video/timeline.md` → `video/packaging.md` → `video/sound.md` → `video/remake.md`。不要读 `breakdown.json`。
4. 写出要保留的东西，记进 `script/storyboard.json` 的 `reference` 字段：
   - 叙事线：每一段在抓注意、交代背景、给证据、转折还是给结论。
   - 节奏：总时长、每镜时长、切点是否卡节拍。
   - 包装：字幕的位置、字号比例、颜色、描边、入场方式，花字和贴纸落在哪句话上。
   - 声音结构：有无人声、配乐的速度和情绪、音效落在哪些画面事件上。

与 rea-video skill 不同的地方，以这里为准：

- 它让你问用户用哪个模型、用哪个工具复刻。这里用户已定：成片一律用 OpenFilm 做（它列的「自己动手」那一路），不停下来问。
- 它的 `remake`、`code-remake`、`assemble` 产物会拿原片占位，只能用来对比和参考，**不得发布，也不得把原片的画面或声音剪进成片**。
- capsule-cinema、ChatCut 没有安装，且要付费，不使用，除非用户明确要求。
- 它的规则「用户确认之前不调用付费生成」继续有效。

复刻的含义是：保留参考视频的结构、节奏和包装方式，内容、文案、画面、声音全部换成自己的。

## 步骤 3：脚本和分镜

1. 查事实：视频里出现的数字、时间、说法都要有出处，查不到的不写。出处记进 `topic/topic.json`。
2. 写 `script/storyboard.json`：每镜包含起止秒、屏幕文字（每屏不超过两行）、画面描述、画面做法（`code` / `image` / `video` / `library`）。
   - 入口 A、B：总长 15–30 秒，5–8 镜；第一镜 3 秒内说出看点，最后一镜给一句总结。
   - 入口 C：镜数、每镜时长、叙事作用按步骤 2 记下的结构来，文案按新主题重写，不照抄原文案。
3. 默认不配音，字幕加音乐。参考视频有人声而本机没有可用的配音服务时，仍按无配音做，并在最后告诉用户。

## 步骤 4：素材

**先整篇读 `openfilm skill media`**（在 `film/` 目录里执行 `../../../node_modules/.bin/openfilm skill media`）。

每一镜按下面顺序取，能用前面的就不用后面的：

1. **OpenFilm 自带库**（免费、离线、CC0）：音乐、音效、转场、特效、滤镜、贴纸、文字动画、模板。先在这里找，再考虑自己写。
2. **代码画面**：标题、数字、清单、对比、图表、动效，直接写成 OpenFilm 页面。
3. **生成图片**：场景、物品、氛围。用你自带的图片生成能力，或 OpenFilm 已接的服务（`openfilm get` 会列出当前能用的）。竖屏 9:16。
4. **生成视频**：一条片子最多 2 镜，每镜不超过 6 秒。来源同上。

素材放哪里：

- 生成工具给出的原始文件、裁剪转码前的文件、没被采用的备选，放运行目录的 `materials/`。生成工具把文件存到了工作区之外时，移进来，外面不留。
- 成片实际用到的那一份放 `film/assets/`。OpenFilm 的 `--take` 会自己把自带库的东西放进这里。按 OpenFilm skill 的要求，`film/assets/` 里只留成片用得上的。

约束：

- 不生成真实人物的肖像、真实品牌的标志、伪造的新闻画面或截图。
- 不把别人的成片或片段当素材。采集和下载到的内容只进 `ref/`。
- 会另外收费的生成（OpenFilm 标了 at a cost 的、外部付费服务）先告诉用户费用并等同意。agent 自带的生成能力不在此列。
- 某一镜的生成失败或不可用时，改用代码画面，流程继续。
- 每个素材的来源和提示词记进 `film/assets/credits.json`，`materials/` 里的原件也记上对应关系。

## 步骤 5：剪辑和渲染

**先读 `node_modules/openfilm/MANUAL.md`，再整篇读 `openfilm skill edit`**，按它的做法建项目、写 `film.html` 和页面、用 `openfilm look` 看画面。

本工作区的约定：

- 每条命令都在运行目录的 `film/` 里执行，先执行环境脚本，命令是 `../../../node_modules/.bin/openfilm`。
- 项目就建在运行目录的 `film/`，不用 OpenFilm 默认的项目位置。
- 画面 1080×1920。
- 没有图形界面或在受限环境里跑时，加环境变量 `OPENFILM_NO_BROWSER=1`。
- 渲染：`openfilm render --fps 30 --loudness=-14 --out ../output/final.mp4`。每次都带 `--out`，不用默认的导出位置。

出片前自检，全部通过才能进入发布：

- 每镜至少用 `openfilm look` 看一帧：文字不出框、不遮挡、没有错字。
- `ffprobe`：1080×1920、时长与分镜一致、有音轨。
- 入口 C：对照 `ref/out/VIDEO.md`，结构和节奏对得上，且成片里没有原片的任何画面和声音。

自检的记录存进 `output/check/`：`openfilm look` 存下的帧图复制一份进来，`ffprobe` 的输出存成 `ffprobe.json`，每项检查的结论写进 `check.json`。

不合格就修到合格。修不好就停下报告，不发布。

## 步骤 6：分发

带「先给我看」「只做不发」时跳过。

**按 [references/creatorhub-api.md](references/creatorhub-api.md) 的「标准发布顺序」做**，那里有接口、参数、状态和各种失败的处理办法。要点：

- 先按它开头写的办法，核对接口文档和当前 CreatorHub 版本是否一致。
- 每个平台各写一份标题、正文、话题，写进 `publish/publish.json`。任务 id、状态、作品链接拿到后也写回这个文件。
- 建立任务就等于提交发布，建之前确认自检已通过。
- 一个账号发完再发下一个。
- 状态是「结果待确认」时不重试、不删除，交给用户去平台核对。

## 步骤 7：记录和汇报

1. 把运行目录的 `run.json` 更新到最终状态，删掉 `tmp/`。
2. 往 `runs/topics-log.jsonl` 追加一行：日期、入口、题目、来源、运行目录、各平台任务 id、状态、作品链接。中途停下或失败的运行也要记一行。
3. 检查归档：运行目录的结构符合「归档规范」，这次产生的文件没有留在工作区之外，也没有散在工作区的其他位置。
4. 汇报只写：做了什么题和原因、运行目录和成片路径、每个平台的结果和链接、需要用户处理的事。

## 子代理

由主 agent 判断要不要派，以及派几个。你没有派子代理的能力时，按步骤顺序自己做完。

适合并行派出去的：

- 步骤 2 的拆解和看图复核，与步骤 3 的查事实同时进行。
- 有多条参考视频时，每条一个子代理做拆解。
- 步骤 1 取各平台热榜和查小红书热度。
- 步骤 4 里互不依赖的各镜素材：每个子代理负责若干镜的图片、视频或页面文件。

必须由主 agent 自己串行做的：

- 写 `film.html`。子代理可以各写各的页面文件和素材，但 `film.html` 只有主 agent 改。
- 渲染和出片自检。
- 步骤 6 的全部发布操作。
- 同一个账号上的 CreatorHub 操作，不要同时发起两个。

派出时的要求：

- 子代理看不到你的上下文。交代清楚：运行目录、要先读的仓库 skill 的路径、输入文件、要产出的文件路径（按「归档规范」指定到运行目录里的具体位置）、执行命令前先执行环境脚本、不许做的事（不发布、不调用付费生成、不改 `film.html`、不在运行目录之外存放文件）。
- 子代理交回的东西，主 agent 要自己打开文件或看图核对后再用，不只看它的汇报。
- 不值得派的：几分钟内能做完的事、各平台文案。

## 能力不足时的退路

| 你做不到 | 怎么办 |
|---|---|
| 联网搜索 | 只做不依赖具体数据的题；需要数据时请用户提供资料 |
| 看图 | rea-video 按它 `references/review.md` 的「看不了图时的规则」做；OpenFilm 画面无法目检，做到步骤 5 停下，不自动发布，并说明画面没有目检 |
| 生成图片或视频 | 用 OpenFilm 已接的服务；也没有就全部用自带库和代码画面 |
| 派子代理 | 自己按顺序做 |

## 不要做的事

- 不外传、不打印 `creatorhub/data/`、`creatorhub/config.yaml`、`.local/openfilm/`、浏览器 Profile、Cookie 的内容。
- 不在工作区之外安装、生成或存放任何东西；不跳过环境脚本。
- 不通过 CreatorHub 发私信、评论、转发别人的作品、删作品、改代理或指纹，除非用户另外明确要求。
- 不为了凑一条视频放宽选题筛选、事实要求或出片自检。
