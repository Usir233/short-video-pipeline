---
name: short-video-pipeline
description: 在本工作区按固定流程做竖屏短视频并分发：热点选题或指定主题或复刻参考视频 → 脚本分镜 → 寻找或生成素材 → OpenFilm 剪辑渲染 → CreatorHub 发布到抖音、小红书、视频号。用户说「跑一条」「做一条视频」「按热点做」「主题：xxx」「复刻这条」「二创」「做同款」「发一条」，或给出一条参考视频的链接、分享文案、文件时使用。
---

# 短视频流水线

所有路径都是相对路径，相对工作区根目录，也就是 `AGENTS.md` 所在的目录。命令默认在根目录执行，另有说明的除外。不要在任何文件里写死绝对路径；接口要求绝对路径时，运行时用 `pwd` 现算。

本文件面向任何 agent，不依赖某一家的专有工具。只假设你能执行命令、读写文件。其他能力有就用，没有就按「能力不足时的退路」处理。

用户已定：这条流程由 agent 从头跑到发布，中途不逐步请示；素材由 agent 自行寻找或生成。

## 用到的仓库

每一步用哪个仓库、读它的哪个 skill，写在下表。**进入某一步之前，先把该仓库的 skill 整篇读完再动手**，按它的做法做。固定的版本和命令入口见 [references/repos.md](references/repos.md)，新环境的安装步骤见 [references/setup.md](references/setup.md)。

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

## 每次运行的目录

`runs/<YYYYMMDD>-<英文短名>/`：

- `topic.json`：题目、来源、热度、事实出处
- `storyboard.json`：分镜
- `ref/`：参考视频和 rea-video 的拆解结果。**这里的文件只用来分析，不得进入成片**
- `film/`：OpenFilm 项目（`film.html`、各镜页面、`assets/`）
- `final.mp4`：成片
- `publish.json`：各平台文案、任务 id、结果

## 步骤 0：开始前检查

1. 配套仓库：`node_modules/.bin/openfilm`、`rea-video/.venv/bin/rea-video`、`creatorhub/creatorhub.py` 三者都在。缺任何一个，先按 [references/setup.md](references/setup.md) 装好再继续。
2. CreatorHub：`curl -fsS http://127.0.0.1:8000/health`。不通就在 `creatorhub/` 里后台执行 `python3 creatorhub.py start --no-open`，等到通。
3. 账号：按 `references/creatorhub-api.md` 的「查账号」取每个平台可发布的账号。账号 id 每次现查。某平台不可发布时这次跳过它，并在最后告诉用户原因。一个可用账号都没有时（新环境还没登录），请用户打开 `http://127.0.0.1:8000` 登录后再继续。
4. 判断这次要不要派子代理，见「子代理」。

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
4. 写 `topic.json`。

## 步骤 2：复刻拆解（入口 C，或带「参考爆款」）

**先整篇读 `rea-video/skills/rea-video/SKILL.md`，按它的流程做。** 本工作区的约定：

- 命令不在 PATH 里，用 `rea-video/.venv/bin/rea-video`。
- 默认不配 VLM。你能看图时，你就是 VLM：必须做它的「看图复核并入」（`review` → 填 `review_answers.json` → `apply-review`）。
- 按 `references/setup.md` 安装时带了字幕识别和语音识别，`decompose` 不要加 `--no-asr`、`--no-packaging`。

做法：

1. 拿到参考视频，放进 `ref/`：
   - 用户给了本地文件：复制进来。
   - 用户给了链接或分享文案：用 CreatorHub 的「下载分享链接」，`output_dir` 填 `ref/` 的绝对路径（运行时用 `pwd` 现算）。
   - 「参考爆款」：用 CreatorHub 关键词采集找到该题下点赞最高的视频，再用它的链接下载。
2. 在运行目录里执行 `../../rea-video/.venv/bin/rea-video decompose ref/<文件> -o ref/out --lang zh`，然后 `summary`、`review`、`apply-review`。
3. 按 rea-video skill 说的顺序读拆片包：`ref/out/VIDEO.md` → `video/content.md`（叙事线）→ `video/timeline.md` → `video/packaging.md` → `video/sound.md` → `video/remake.md`。不要读 `breakdown.json`。
4. 写出要保留的东西，记进 `storyboard.json` 的 `reference` 字段：
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

1. 查事实：视频里出现的数字、时间、说法都要有出处，查不到的不写。出处记进 `topic.json`。
2. 写 `storyboard.json`：每镜包含起止秒、屏幕文字（每屏不超过两行）、画面描述、画面做法（`code` / `image` / `video` / `library`）。
   - 入口 A、B：总长 15–30 秒，5–8 镜；第一镜 3 秒内说出看点，最后一镜给一句总结。
   - 入口 C：镜数、每镜时长、叙事作用按步骤 2 记下的结构来，文案按新主题重写，不照抄原文案。
3. 默认不配音，字幕加音乐。参考视频有人声而本机没有可用的配音服务时，仍按无配音做，并在最后告诉用户。

## 步骤 4：素材

**先整篇读 `openfilm skill media`**（在 `film/` 目录里执行 `../../../node_modules/.bin/openfilm skill media`）。

每一镜按下面顺序取，能用前面的就不用后面的：

1. **OpenFilm 自带库**（免费、离线、CC0）：音乐、音效、转场、特效、滤镜、贴纸、文字动画、模板。先在这里找，再考虑自己写。
2. **代码画面**：标题、数字、清单、对比、图表、动效，直接写成 OpenFilm 页面。
3. **生成图片**：场景、物品、氛围。用你自带的图片生成能力，或 OpenFilm 已接的服务（`openfilm get` 会列出当前能用的）。竖屏 9:16，存到 `film/assets/`。
4. **生成视频**：一条片子最多 2 镜，每镜不超过 6 秒。来源同上。

约束：

- 不生成真实人物的肖像、真实品牌的标志、伪造的新闻画面或截图。
- 不把别人的成片或片段当素材。采集和下载到的内容只进 `ref/`。
- 会另外收费的生成（OpenFilm 标了 at a cost 的、外部付费服务）先告诉用户费用并等同意。agent 自带的生成能力不在此列。
- 某一镜的生成失败或不可用时，改用代码画面，流程继续。
- 每个素材的来源和提示词记进 `film/assets/credits.json`。

## 步骤 5：剪辑和渲染

**先读 `node_modules/openfilm/MANUAL.md`，再整篇读 `openfilm skill edit`**，按它的做法建项目、写 `film.html` 和页面、用 `openfilm look` 看画面。

本工作区的约定：

- 每条命令都在 `film/` 目录里执行，命令是 `../../../node_modules/.bin/openfilm`。
- 画面 1080×1920。
- 没有图形界面或在受限环境里跑时，加环境变量 `OPENFILM_NO_BROWSER=1`。OpenFilm 要写 `~/.openfilm`。
- 渲染：`openfilm render --fps 30 --loudness=-14 --out ../final.mp4`。

出片前自检，全部通过才能进入发布：

- 每镜至少用 `openfilm look` 看一帧：文字不出框、不遮挡、没有错字。
- `ffprobe`：1080×1920、时长与分镜一致、有音轨。
- 入口 C：对照 `ref/out/VIDEO.md`，结构和节奏对得上，且成片里没有原片的任何画面和声音。

不合格就修到合格。修不好就停下报告，不发布。

## 步骤 6：分发

带「先给我看」「只做不发」时跳过。

**按 [references/creatorhub-api.md](references/creatorhub-api.md) 的「标准发布顺序」做**，那里有接口、参数、状态和各种失败的处理办法。要点：

- 每个平台各写一份标题、正文、话题，写进 `publish.json`。
- 建立任务就等于提交发布，建之前确认自检已通过。
- 一个账号发完再发下一个。
- 状态是「结果待确认」时不重试、不删除，交给用户去平台核对。

## 步骤 7：记录和汇报

1. 往 `runs/topics-log.jsonl` 追加一行：日期、入口、题目、来源、运行目录、各平台任务 id、状态、作品链接。
2. 汇报只写：做了什么题和原因、成片路径、每个平台的结果和链接、需要用户处理的事。

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

- 子代理看不到你的上下文。交代清楚：运行目录、要先读的仓库 skill 的路径、输入文件、要产出的文件路径、不许做的事（不发布、不调用付费生成、不改 `film.html`）。
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

- 不外传、不打印 `creatorhub/data/`、`creatorhub/config.yaml`、浏览器 Profile、Cookie 的内容。
- 不通过 CreatorHub 发私信、评论、转发别人的作品、删作品、改代理或指纹，除非用户另外明确要求。
- 不为了凑一条视频放宽选题筛选、事实要求或出片自检。
