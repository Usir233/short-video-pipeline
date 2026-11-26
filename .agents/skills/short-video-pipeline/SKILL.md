---
name: short-video-pipeline
description: 在本工作区按固定流程做竖屏短视频并分发：支持单条视频（热点/指定主题/复刻/已有成片直发）与多风格矩阵裂变（入口 E：原片+素材 → 粗剪确认确立母素材 → 1 完整特效母片 + 3 条不同风格子片，各自独立补素材、3 平台封面与文案，路径规范化打包交付手动发布或 CreatorHub 自动发布）。用户说「跑一条」「做一条视频」「按热点做」「主题：xxx」「复刻这条」「二创」「做同款」「发一条」「写三平台文案」「做封面」「做母片和3条子片」「一条变三条」「一鱼多吃」「母片裂变」，或给出参考视频/原片素材/待发成片时使用。
---

# 短视频流水线

所有路径都是相对路径，相对工作区根目录，也就是 `AGENTS.md` 所在的目录。命令默认在根目录执行，另有说明的除外。不要在任何文件里写死绝对路径；接口要求绝对路径时，运行时现算（执行环境脚本后用 `$SVP_ROOT`，见下一节）。

本文件面向任何 agent，不依赖某一家的专有工具。只假设你能执行命令、读写文件。其他能力有就用，没有就按「能力不足时的退路」处理。

用户已定：单条流程默认由 agent 从头跑到完，中途不逐步请示；素材由 agent 自行寻找或生成。**两类强制分流/暂停例外**：
1. **入口 E（母素材 + 1 母片 + 3 子片）的人工确认闸门**：未处理原片完成粗剪（话题分段切割 + 去口气词）后**必须停下向用户汇报确认或追加预处理（如打马赛克）**，确认后才确立「母素材」；母片完整成片与 3 子片规划完成后默认**再次停下确认**（指令带「一路跑完」可跳过第二次暂停）。停在确认闸门时 `run.json` 置 `status: "waiting_approval"`，用户回复后复用原运行目录续跑。
2. **带定制封面交付手动发布**：凡本次任务制作了定制封面（含入口 E 全部 4 片 × 目标平台定制封面，默认三平台共 12 张），因 CreatorHub 暂不支持上传自定义封面，做到成片、封面与文案全部过审并完成路径规范归集后即停下交付用户手动连同封面发布（不做定制封面时单片仍自动发布；入口 E 默认仍交付 `delivery/` 手动发布，除非用户显式要求自动发布并确认账号排期）。

## 一切留在工作区内

用户已定，任何步骤都适用：

- **安装只装在工作区里**，不全局安装，不往用户主目录里放东西。细则见 [references/setup.md](references/setup.md)。
- **处理和生成的东西只放在工作区里**，并按下面的「归档规范」归档。不往桌面、下载目录、`~/Movies`、用户主目录、系统临时目录里放任何文件。
- 安装、更新、运行配套仓库的任何命令之前，先在同一个 shell 里执行环境脚本，它把各仓库的设置、缓存、模型、浏览器内核的位置都指到工作区里，并在当前 shell 置顶 `$SVP_ROOT/node_modules/.bin` 到 `PATH`：

  ```bash
  # 推荐防错写法：每个新 shell 先在工作区根目录执行一次，再 cd 进任意深层目录
  . .agents/skills/short-video-pipeline/scripts/env.sh

  # 若已在深层目录直接 source，须按实际深度对应层级：
  . ../../../.agents/skills/short-video-pipeline/scripts/env.sh        # 单片 runs/<目录>/film/（3层）
  . ../../../../.agents/skills/short-video-pipeline/scripts/env.sh     # 入口 E runs/<目录>/master/film/（4层）
  . ../../../../../.agents/skills/short-video-pipeline/scripts/env.sh  # 入口 E runs/<目录>/variants/vN-<风格>/film/（5层）
  ```

  每个新开的 shell 都要重新执行一次。执行后 `$SVP_ROOT` 是工作区根目录的绝对路径，在任意深层目录均直接用 `openfilm`（即 `"$SVP_ROOT/node_modules/.bin/openfilm"`）、`"$SVP_ROOT/rea-video/.venv/bin/rea-video"` 与 `"$SVP_ROOT/.agents/skills/short-video-pipeline/scripts/..."`，无需手数 `../` 层级。
- 你自带的工具（生成图片、生成视频、下载、截图）把文件存到了工作区之外时，立刻把文件移进本次运行的目录，外面不留。
- 你自己的草稿、脚本、中间文件放本次运行的 `tmp/`，不放系统临时目录。

## 用到的仓库

每一步用哪个仓库、读它自带的哪个文档/skill，写在下表。**进入某一步之前，直接按相对路径读取该工具最新的自带文档或实时接口**，做法随上游更新自动生效，不依赖手抄缓存。完整文档路径索引见 [references/repos.md](references/repos.md)，安装和更新见 [references/setup.md](references/setup.md)。

| 步骤 | 仓库 | 本机位置 | 直接读取的相对文档 / Skill 路径 |
|---|---|---|---|
| 选题（国内外热榜、科技大厂 RSS） | 本工作区脚本 `scripts/fetch_trends.py` | `.agents/skills/short-video-pipeline/scripts/` | [references/sourcing.md](references/sourcing.md) |
| 选题（小红书/抖音热度）、取参考视频 | [3441293738/creatorhub](https://github.com/3441293738/creatorhub) | `creatorhub/` | `creatorhub/README.md`、`creatorhub/guide/platforms.json`、`/openapi.json` + [references/creatorhub-api.md](references/creatorhub-api.md) |
| 复刻：拆解参考视频 | [JuneYaooo/rea-video](https://github.com/JuneYaooo/rea-video) | `rea-video/` | `rea-video/skills/rea-video/SKILL.md`、`rea-video/skills/rea-video/references/`、`rea-video/docs/` |
| 素材（自带库 + 网络新闻/官图/视频切片 + 免版权图库） | [openfilm/openfilm](https://github.com/openfilm/openfilm) + `scripts/fetch_asset.py` | `node_modules/openfilm/`、`.agents/.../scripts/` | `node_modules/openfilm/SYSTEM_PROMPT.md`、`node_modules/openfilm/manual/`（`openfilm skill media`）+ [references/sourcing.md](references/sourcing.md) |
| 剪辑、渲染与特效工艺 | openfilm/openfilm + 本工作区规范 | `node_modules/openfilm/`、`.agents/.../references/` | `node_modules/openfilm/SYSTEM_PROMPT.md`、`node_modules/openfilm/manual/`（`openfilm skill film`）、`node_modules/openfilm/SPEC.md` + [references/editing-vfx.md](references/editing-vfx.md) |
| 三平台文案撰写（默认全部视频适用） | 本工作区规范 | `.agents/skills/short-video-pipeline/references/` | [references/copywriting.md](references/copywriting.md)（四项文案、三层标签、辰奕品牌主张与字段映射） |
| 三平台定制封面（按需，多号组可扩展） | 本工作区规范 + 品牌固定图 | `.agents/skills/short-video-pipeline/references/`、`assets/brand/` | [references/cover-design.md](references/cover-design.md)（「意图电商」口播系列规范；其他号组按需新增独立模板规范） |
| 母素材与 1 母片 + 3 风格子片裂变（入口 E） | 本工作区规范 | `.agents/skills/short-video-pipeline/references/` | [references/multi-variant.md](references/multi-variant.md)（粗剪/马赛克闸门、母素材确立、1 母片 + 3 延伸子片、防传混命名与 `delivery/` 交付包） |
| 审核与分发 | 3441293738/creatorhub | `creatorhub/` | [references/publish-audit.md](references/publish-audit.md)（强制审核门禁）、[references/creatorhub-api.md](references/creatorhub-api.md)、`creatorhub/guide/platforms.json`、`/openapi.json` |

各配套仓库的具体命令、参数和能力边界一律以上述相对路径里的项目自身文档为准；本文件及 `references/` 只保留本工作区的目录规范、串联顺序、文案/封面/矩阵裂变规范与安全红线，不再单独手抄维护上游工具明细。

## 五种入口

| 用户说 | 入口 | 走哪些步骤 |
|---|---|---|
| 「跑一条」「按热点做一条」 | A 热点原创 | 0 → 1 → 3 → 4 → 5 → 6 → 7 |
| 「主题：xxx」「做一条关于 xxx 的」 | B 指定主题 | 0 → 3 → 4 → 5 → 6 → 7 |
| 「复刻这条」「二创」「做同款」，或给出参考视频要求照着做 | C 复刻 | 0 → 2 → 3 → 4 → 5 → 6 → 7。没给新主题时先走步骤 1 选题 |
| 「发这条成片」「直接发 xxx.mp4」「帮我分发这个视频」（给出待发成片而非参考视频） | D 已有成片直发 | 0 → 6 → 7（跳过制作；用 `ffprobe` 核对分辨率/时长/音轨，工作区内原成片无需再复制一份到 `output/final.mp4`，直接记录其相对路径；若原成片在工作区外则**只读复制**进 `output/final.mp4`，严禁移动/删除用户源文件；按成片内容/轻量抽帧直接按步骤 6 完成三平台文案、按需封面与审核分发，不必跑全量拆片） |
| 「做母片和3条子片」「一条变三条」「一鱼多吃」「母片裂变」，或给出「原片 + 配套素材」要求做 1 母片 + 3 条不同风格子片 | E 母素材裂变矩阵 | 按 [references/multi-variant.md](references/multi-variant.md) 执行 `E0 → E1(未处理先粗剪+闸门1) → 母素材确立 → E2(完整特效母片+3封面+3文案) → E3(3子片延伸规划+闸门2) → E4(3子片各自独立补素材/剪辑/3封面/3文案) → E5(单条+跨4片审核与路径收口) → E6(生成 delivery/ 交付包与归档)` |

指令里的附加词：

- 「参考爆款」：A 或 B 里加做步骤 2，参考视频由 agent 用 CreatorHub 采集该题下点赞最高的一条视频。
- 「只发抖音」「不发小红书」等：只产出/发布指定平台。
- 「带封面」「做意图电商封面」：启用对应系列的封面设计规范（当前为 [references/cover-design.md](references/cover-design.md)），完成后默认停下交付用户手动连同封面发布。
- 「不做封面」「免封面」：跳过定制封面制作；无其他暂停词时走 CreatorHub 自动发布。
- 「直接自动发（封面后补）」：即使制作了定制封面，也继续调用 CreatorHub 自动发布视频，由用户事后去各平台后台补换封面。
- 「不带品牌口号」：跳过 [references/copywriting.md](references/copywriting.md) 中的辰奕品牌主张原句与品牌标签。
- 「先给我看」「只做不发」：做到成片（及按需封面、文案过审）停下，给出产物路径，不自动提交发布。
- 入口 E 专用附加词：「已处理素材 / 直接当母素材」（跳过粗剪）、「未处理原片 / 先粗剪」（先做话题切割与去口气词并过闸门 1）、「一路跑完」（母素材确认后跳过闸门 2 直接跑完 1 母片 + 3 子片）、「拆三条」或「同内容三风格」（覆盖 3 子片自适应切分策略）。

没有附加词时：三个平台都做；仅当视频明确命中已登记的系列封面规范（例如「意图电商」系列命中 [references/cover-design.md](references/cover-design.md)）或用户要求做定制封面时，才制作三张封面并停下交付手动发布；未命中专属封面系列（其他主题/其他号组无对应封面规范，或无出镜纯资讯视频）时不强行套用「意图电商」模板，默认不做定制封面、直接走 CreatorHub 自动发布。

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
    ├── materials/                素材原件：搜索下载或生成工具给出的原始文件、裁剪转码前的文件、没被采用的备选；做封面时的原截帧与抠像过程稿放 materials/covers/
    ├── film/                     OpenFilm 项目
    │   ├── film.html 和各镜页面
    │   └── assets/               成片实际用到的素材，外加 credits.json（每个素材的来源和提示词）
    ├── output/
    │   ├── final.mp4             成片
    │   └── check/                出片自检的记录：看过的帧图、ffprobe 的输出、check.json
    ├── covers/                   三平台定制封面（仅做封面时建）：douyin.png、shipinhao.png、xhs.png、cover-spec.json
    ├── publish/
    │   └── publish.json          各平台的四项文案、三层标签候选、发布组合、封面路径、发布前审核结论（audit）、任务 id、结果、作品链接
    └── tmp/                      草稿和中间文件，运行结束时删掉
```

用不到的目录不建（入口 A、B 不带「参考爆款」时没有 `ref/`；不做定制封面时没有 `covers/`）。不在运行目录的根上另放文件，也不自创别的子目录。

**入口 E（母素材 + 1 母片 + 3 风格子片）扩展目录结构**（完整细则与防传混前缀命名见 [references/multi-variant.md](references/multi-variant.md)）：

```text
runs/<YYYYMMDD-HHMM>-<话题短名>/
├── run.json                总控索引（entry: "E"、闸门状态、母素材/4片/交付包路径）
├── raw/                    原始输入（原片 + 配套素材登记，原片只读）
├── rough-cut/              粗剪话题切片与用户预处理区（仅未处理输入时建）
├── master-assets/          【母素材】经确认的最终干净原片切片 + 配套素材 + manifest.json
├── master/                 【母片】script/、materials/、film/、output/00-master-*.mp4、covers/00-master-*.png、publish/publish.json
├── variants/               【3 条延伸子片】v1-<风格>/、v2-<风格>/、v3-<风格>/（同构独立目录，防传混前缀 01-v1 / 02-v2 / 03-v3）
├── delivery/               【统一交付包】INDEX.md + 00-master/ + 01-v1-*/ + 02-v2-*/ + 03-v3-*/（含成片、3封面、copy.md）
└── tmp/                    草稿和中间文件，运行结束时删掉
```

**`run.json`**：建目录时就写，每做完一步更新一次，中途停下也要留下当时的状态。字段：

- `id`：目录名
- `topic`：完整的话题
- `entry`：`A`、`B`、`C`、`D` 或 `E`（兼容旧记录 `publish-existing`）
- `started_at`、`finished_at`：带时区的时间
- `status`：`running`（进行中）、`waiting_approval`（暂候用户人工确认，如入口 E 输入态判定 / 闸门 1 / 闸门 2 或无看图能力等待人工目检；此态不删续跑中间态、不提前写入 `topics-log.jsonl`，用户回复后复用原运行目录恢复为 `running` 续跑）、`made`（成片及按需封面/过审文案已出、待人工或指令发布）、`published`（要发的平台都发成功）、`partial`（部分平台成功）、`failed`（失败）、`stopped`（用户取消或因问题终止停下）
- `step`：做到第几步
- `platforms`：每个平台的任务 id、状态、作品链接
- `versions`：OpenFilm 的版本号，rea-video 和 CreatorHub 的提交号
- `notes`：跳过了什么、为什么停下、需要用户处理的事

**不属于某一次运行的东西**不放进 `runs/`：配套仓库的设置、模型、缓存在 `.local/`，浏览器内核在 `browsers/`，CreatorHub 的账号数据和上传的成片副本在 `creatorhub/data/`。

## 步骤 0：开始前检查

1. 环境：执行 `. .agents/skills/short-video-pipeline/scripts/env.sh`。
2. 配套仓库：`node_modules/.bin/openfilm`、`rea-video/.venv/bin/rea-video`、`creatorhub/creatorhub.py` 三者都在。缺任何一个，先按 [references/setup.md](references/setup.md) 装好再继续。（入口 D 已有成片直发仅需 `creatorhub/creatorhub.py` 和 `ffprobe`；入口 E 默认交付手动发布，核心仅需 `openfilm`、`ffmpeg`、`ffprobe`，未处理输入或需人声分轨/ASR 时另需 `rea-video`，不阻塞于 CreatorHub。）
3. CreatorHub：`curl -fsS http://127.0.0.1:8000/health`。不通就在执行过环境脚本的 shell 里，进 `creatorhub/` 后台执行 `python3 creatorhub.py start --no-open`，等到通。（仅当本次不调用 CreatorHub 采集/下载且走「带定制封面交付手动发布」或「先给我看」时，CreatorHub 未启动不阻塞制作。）
4. 账号：需要调用 CreatorHub 采集或自动发布时，按 `references/creatorhub-api.md` 的「查账号」取每个平台可发布的账号（`status=active` 且 `account_role != "crawler"`；小红书另须 `has_creator=true`）。账号 id 每次现查。某平台不可发布时这次跳过它，并在最后告诉用户原因。需要自动发布但一个可用账号都没有时，请用户打开 `http://127.0.0.1:8000` 登录后再继续。带定制封面改走手动发布交付时，不因某平台登录态失效阻塞制作与交付，但在最终汇报中顺带提示异常账号。
5. 建运行目录，写 `run.json`，见「归档规范」。
6. 判断这次要不要派子代理，见「子代理」。

## 步骤 1：选题（入口 A）

完整的热点矩阵、降级顺序与脚本命令见 [references/sourcing.md](references/sourcing.md)。

1. 取国内外热榜与科技资讯（需要联网）：
   - 优先直接运行工作区脚本（先执行 `env.sh`）：
     ```bash
     python3 .agents/skills/short-video-pipeline/scripts/fetch_trends.py --mode all --out runs/<目录>/topic
     ```
     按用户诉求可换 `--mode domestic`（国内大众）、`tech`（国内外科技/AI + 大厂一手 RSS）、`global`（海外科技）、`search --query "<关键词>"`（按主题实时搜国内外新闻）。
   - 脚本内置 4 层源并自动降级，原样存成 `topic/hotlist-<mode>.json`：
     - **L1 国内大众热榜**：60s 前三可用实例依次降级（`https://api.cczo.cc/60s` 首选 → `https://60s.mizhoubaobei.top` → `https://60s.okbaike.com`），取抖音 `/v2/douyin`、微博 `/v2/weibo`、B站 `/v2/bili`、知乎 `/v2/zhihu`、头条 `/v2/toutiao`、百度 `/v2/baidu/realtime`；全不通时自动降级到 NewsNow 国内源和 `https://solarhell.github.io/hot-search-crawler/latest.json`。
     - **L2 国内外科技 / 开发者 / 财经**：NewsNow（GitHub Trending、Product Hunt、Hacker News、华尔街见闻、财联社、IT之家、少数派、Solidot、联合早报）+ 60s（`/v2/it-news`、`/v2/it-news/rank`、`/v2/ai-news` 超时 ≥15s）+ HN Algolia 官方 API。
     - **L3 科技巨头一手官方发布 & 权威外媒**：OpenAI、Google、DeepMind、Apple Newsroom、NVIDIA、GitHub、Hugging Face、TechCrunch、The Verge、Ars Technica 官方直连 RSS，以及 Google News / Bing News RSS。
   - **L4 平台内爆款交叉验证**：小红书没有可用的免费热榜；挑出 2–3 个候选后，用 CreatorHub 关键词采集（`search_sort: most_liked`, `publish_time: week`）查它们在小红书/抖音的实际互动热度（见 `references/creatorhub-api.md` 的「查热度」）。失败就跳过，不阻塞。
   - 视频号没有热榜来源，沿用选出的题。
2. 筛选：
   - 跳过时政、领导人、外交、军事；灾难伤亡；未证实的传闻；针对具体个人的负面事件；医疗和投资建议。
   - 跳过 `runs/topics-log.jsonl` 里近 14 天做过的题。
   - 在剩下的里优先选**跨平台同时上榜**或**海外/科技巨头刚发布、普通人关心、15–30 秒能讲清一个核心变化**的题。
3. 筛完没有合适的：把榜单前 10 列给用户，等用户指定，不硬做。
4. 热榜与热度结果存进 `topic/hotlist-<来源>.json`，写 `topic/topic.json`（附事实出处与官方原文链接），把运行目录改成正式名字。

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
2. 在运行目录里（或先在根目录 source `env.sh` 再 `cd` 进运行目录），执行环境脚本后，按 `rea-video` skill 执行 `survey`（能看图且未开 VLM 时先看后拆）和 `"$SVP_ROOT/rea-video/.venv/bin/rea-video" decompose ref/<文件> -o ref/out --lang zh`，然后 `summary`、`review`、`apply-review`。所有输出都指到 `ref/out`。
3. 按 rea-video skill 说的顺序读拆片包：`ref/out/VIDEO.md` → `video/content.md`（叙事线）→ `video/timeline.md` / `video/rhythm.md` → `video/packaging.md` → `video/sound.md` → `video/remake.md`。不要读 `breakdown.json`。
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

1. 查事实与定主旨：视频里出现的数字、时间、说法都要有出处，查不到的不写，出处记进 `topic/topic.json`；同时先用一句话写清全片要回答的核心问题与主要支撑观点，提前对齐后续三平台封面承诺（确保封面答应给观众的东西能在成片里找到）。
2. 写 `script/storyboard.json`：每镜包含起止秒、屏幕文字（每屏不超过两行）、画面描述、画面做法（`code` / `image` / `video` / `library`），以及两项强制前置标定：
   - **① 口播源片人物坐标标定 `speaker_framing`（有出镜口播必做）**：先对源口播片抽 1 帧加 10% 坐标网格，实测并写入源片归一化坐标（头顶 `head_top_v`、眉眼 `eyes_v`、嘴唇 `mouth_v`、下巴 `chin_v`、领麦 `collar_v` 及背景净区右界 `clean_bg_right_u`），禁止后续盲填 `top/height/clip-path` 导致切嘴或漏杂墙；
   - **② 逐镜「真实台词时间戳 → `local_t` → 原词精炼动效」同步表 `cue_sync_map`（先锁 `subtitles.html` 再写分镜，杜绝音画两张皮）**：列出落在本镜 `[clip_at, clip_end]` 内的每条字幕 `cue_start`、换算后的镜内精确触发秒数 **`local_t = round(cue_start - clip_at, 2)`**、100% 提炼自本镜口播原话的 `2–7` 字屏显关键词（整屏总字数 `≤ 35` 字）与对应 SVG/Canvas 渐进动画动作。**严禁跨镜借用上一镜或下一镜才说的台词，严禁生造原话没提过的脑补长词组，严禁拍脑袋填 `0.2 + i*0.8` 等差延迟！**
   - 入口 A、B：总长 15–30 秒，5–8 镜；第一镜 3 秒内说出看点，最后一镜给一句总结。
   - 入口 C：镜数、每镜时长、叙事作用按步骤 2 记下的结构来，文案按新主题重写，不照抄原文案。
3. 默认不配音，字幕加音乐。参考视频有人声而本机没有可用的配音服务时，仍按无配音做，并在最后告诉用户。

## 步骤 4：素材

**先整篇读 `openfilm skill media`**（先 source `env.sh`，再在目标 `film/` 目录里执行 `openfilm skill media`）及 [references/sourcing.md](references/sourcing.md)。

> **前置动作**：OpenFilm 执行 `openfilm get --take` 前若要求目录已是项目（否则报 `is not in a project`），先在运行目录 `film/` 里放一个最小骨架 `film.html`（声明 `1080×1920` viewport），再调用 `openfilm get --take`，全程带 `OPENFILM_NO_BROWSER=1`。具体命令写法以 `node_modules/openfilm/manual/` 为准。

按每镜的内容类型分流取素材，选最匹配的通道，不要硬套单一路径：

- **A. 音乐、音效、动态贴纸、已有自存素材**：先查 OpenFilm 本地复用库（`openfilm get my-media`），再查自带免费 CC0 库（`music-search`、`sfx-search`、离线 1,587 枚动态贴纸 `sticker`）；缺音效/配乐时可用 `fetch_asset.py stock --kind audio --source openverse` 兜底。
- **B. 数据对比、参数表、清单、金句标题、流程动效**：直接写成 **OpenFilm 语义级 SVG / Canvas 定制动画**（1080×1920，优先 `stroke-dashoffset`、`getPointAtLength` 流光、流式打字机与动态图解，最清晰、最贴口播、零版权风险）。
- **C. 科技巨头发布新闻 / 产品报道 / 真实事件画面**：先用 `fetch_trends.py --mode search` 或官方 RSS 定位一手官方新闻稿/博客链接，再由当前 agent 调用 `scripts/fetch_asset.py` 主动抓取并落盘到 OpenFilm 素材区：
  - `news-page`：用工作区 Playwright 抽取正文事实、下载官方高清配图、按需截 1080px 干净官网首屏；
  - `video-search` / `video-clip`：用工作区已有 `yt-dlp` 搜官方发布会/Demo 并按起止秒精准截取 ≤6 秒短片段。
- **D. 通用实拍动态 B-roll / 氛围空镜 / 科普插图**：先查 `openfilm get my-media` → **优先补充 1–2 段 3–6 秒真实运动视频（`.mp4`）**：已配免费 Key 时用 OpenFilm 内置 **Pexels / Pixabay**（用 2–4 个英文视觉关键词，视频加 `--orientation portrait`）→ 未配 Key 时用 `fetch_asset.py stock --kind video`（或 `--kind image` 兜底）查免 Key 公开免版权库（Wikimedia Commons、NASA、Internet Archive、Openverse）。
- **E. 抽象概念 / 搜不到的专属场景**：用 agent 自带生图能力（9:16 竖屏）或 OpenFilm 已接生成服务——**静态生图入片必须叠加与口播绑定的 SVG 矢量前景动效层**，禁止仅做 5% 死板慢推；生成视频一条片子最多 2 镜、每镜不超过 6 秒；生成失败或不可用时退回 B 类代码动画。
- **单支视频内视觉素材单次使用铁律**：同一支成片内，每一份视觉素材（B-roll `.jpg`/`.mp4`、动态贴纸、用户配套原图，品牌固定 Logo 与源口播视频除外）**严格仅允许使用 1 次（`count = 1`）**，严禁跨镜复用或同镜双层 `<img>` 复用。

素材放哪里：

- 搜索下载的原始文件、新闻网页截图原图、生成工具给出的原始文件、裁剪转码前的文件、没被采用的备选，放运行目录的 `materials/`。工具或浏览器把文件存到了工作区之外时，立刻移进来，外面不留。
- **本次成片实际用到的那一份放进 OpenFilm 项目素材区 `film/assets/`**（供 `film.html` 直接引用）。OpenFilm 的 `--take` 会自己把自带库的东西放进这里；其他素材可用 `fetch_asset.py register` 一键落盘并登记。按 OpenFilm skill 的要求，`film/assets/` 里只留成片用得上的。
- **可跨视频复用的通用素材**（如通用空镜、配乐、音效、纹理、贴纸/图标），同步复制一份放进 OpenFilm 公共素材区 **`.local/openfilm-user/saved/`**（环境变量 `$OPENFILM_SAVED`，`fetch_asset.py` 加 `--save-reusable`），方便后续视频直接通过 `openfilm get my-media` 检索复用。

约束：

- 不生成真实人物的肖像、真实品牌的标志、伪造的新闻画面或截图。
- 新闻/科技发布类素材只取**官方新闻室、官方博客、官方频道发布/Demo（≤6 秒）或权威媒体原文的无水印真实配图与截图**，并在画面角落或说明中清晰标注来源（如“来源：Microsoft USB Blog”）。中文二次报道配图常带媒体水印且分辨率偏低，遇到海外科技大厂发布时须溯源到官方原博抓无水印高清图。
- 不把别人的二次创作短视频成片、搬运片段或带平台/图库水印的画面当素材。CreatorHub 采集和下载到的参考视频只进 `ref/`；通用图库素材只取无水印、允许免费使用的公开源。
- 会另外收费的生成或付费素材（OpenFilm 标了 at a cost 的、外部付费服务）先告诉用户费用并等同意。agent 自带的搜索和生成能力不在此列。
- 某一镜的搜索或生成失败、不可用时，改用代码画面，流程继续。
- 每个素材的来源（原文/搜索链接与许可说明，或生成提示词）记进 `film/assets/credits.json`，`materials/` 里的原件和同步进 `.local/openfilm-user/saved/` 的复用件也记上对应关系（使用相对路径，不写死绝对路径）。

## 步骤 5：剪辑和渲染

**先读 `node_modules/openfilm/SYSTEM_PROMPT.md`（或无参运行 `openfilm`）、整篇读 `openfilm skill film`（兼容 `edit`）以及 [references/editing-vfx.md](references/editing-vfx.md)**，按 OpenFilm 做法与本工作区剪辑/特效工艺规范建项目、写 `film.html` 和页面、用 `openfilm look` 看画面。

本工作区的约定：

- 每条命令都在目标 `film/` 里执行（单片为 `runs/<目录>/film/`，入口 E 为 `master/film/` 或 `variants/vN-<风格>/film/`），先在根目录或按对应层级 source `env.sh`，直接调用 `openfilm`（即 `"$SVP_ROOT/node_modules/.bin/openfilm"`，避免硬写 `../../../` 在入口 E 深层目录失效）。
- 项目就建在运行目录的 `film/`（入口 E 建在各自 `master/film/` 或 `variants/vN-<风格>/film/`），不用 OpenFilm 默认的项目位置。
- 画面 1080×1920；**竖屏三平台四向安全区（硬红线）**：顶部留 `≥180px`（避开状态栏/灵动岛/顶部导航）、底部留 `≥360px`（`y ≤ 1560px`，严禁任何底卡、落款或字幕掉入 `y > 1560px` 遮挡死区）、**右侧留 `≥150px`（`x = 930..1080, y = 850..1500` 为点赞/评论/收藏按钮禁区，中下半屏卡片的可读文字、勾选框、徽章与出处必须稳控在 `x ≤ 920px`）**；主视觉和标题控制在 2 行以内，单行字幕严控 `≤14–15` 汉字，不遮挡、不折出第 3 行。
- **人脸构图、PiP 分屏与防 PPT 感约定**：
  - 全屏 16:9 裁 9:16 口播叠加底部浮卡时，必须通过上提构图（如 `scale(1.08–1.10) translateY(-5%)`）让人物下巴稳在 `y ≤ 1120px` 以上，浮卡置于下巴以下且 `y ≤ 1540px`，**严禁卡片切嘴或糊住下巴**；
  - **`speaker-pip` 画中画五官完整保留与去杂墙硬规（严禁扁框切嘴/切下巴）**：画中画 `<video>` 在计入 `object-fit: cover` 与稳态 `clip-path: inset(T R B L)` 后，源片纵向保留区间必须满足 **上界 `v1 ≤ 0.22`（推荐 `≤0.16` 不削发顶）且下界 `v2 ≥ 0.72`（推荐 `≥0.75` 直至领麦，即 `inset_bottom / height ≤ 0.26`，严禁切在嘴唇或下巴以上！）**，可见净高 `≥ 340px`，且分镜内装饰框 `.pip-frame` 必须与稳态裁切可见框像素对齐（误差 `≤ 6px`）；若源片右侧有杂墙需裁除，**严禁把人物放大硬塞进 `>2:1` 扁长条窗（必切嘴）**，须改用居中紧凑 `4:3` / `16:10` 人像窗（如 `490×376px`）或左人像窗 + 右侧实时关键词看板；
  - **音画字逐句 `local_t` 卡点同步硬规（严禁 `t=0` 满屏摊牌、等差抢跑死镜与生造词）**：编写 `scenes/*.html` 前必须先锁定 `scenes/subtitles.html` 精确时间戳，按 `local_t = cue_start - clip_at` 驱动每个标题、SVG 节点框与结论条从 `opacity: 0` 随口播字头（`-0.05s..+0.15s`）渐进入场；**严禁在 `t=0` 把全镜 `≥5` 个文本块一次性静态亮出提前剧透，严禁拍脑袋写 `0.2 + i*0.8` 导致动画在前 40% 播完而后半程死镜，`overlays` 单条信息卡严控 `≤ 6.5s`，严禁跨镜借用下一镜台词或编造口播未提的虚构长词组（单节点 `2–7` 字、整屏 `≤ 35` 字）**；
  - 严禁对未出场信息卡使用 `opacity: 0.18–0.40` 灰暗幽灵预显（未讲到前保持 `opacity: 0`，命中瞬间干脆入场）；卡片正文最小字号 `≥24px`，禁止 `overflow: hidden` 容器内容溢底裁切；尽量用动态实拍 B-roll 或交互式代码动效替代呆板静图；
  - **剪辑节奏、视觉信息密度、前后景防遮挡与特效工艺硬规（细则与原语代码见 [references/editing-vfx.md](references/editing-vfx.md)）**：严格执行分风格 ASL 上限与反死镜红线（4K 源片口播 `>4.5–6s` 须用 4K 无损阶梯跳切或锁眼推镜 `--fx-ax/--fx-ay`，全屏 B-roll/图形夺权 `≥15%`）；**严格压降静态 PPT 感（纯文字圆角卡 `≤25%`、语义级 SVG/Canvas 动效 `≥45%`、静态 B-roll 必叠 SVG 矢量前景动效层、单支视频内每份视觉素材严格仅用 1 次 `count = 1`）**；**严格区分前景与人后层级（需要读清的文字、SVG 图解与核心动效严禁塞进 `--of-cutout: 1` 人物背后被头肩遮挡，须全屏切出、PiP 分屏或前景避让叠加；人后巨字仅限人物缩小下沉头顶 `y≥640px` 后的 2–4 字超短单行词，发梢压字 `≤15%`；动态贴纸锚定视觉载体并避开全屏人物头肩禁区 `x=220..860, y=280..1020`）**；跨 `<section>` 切换同主体时上轨须比下轨提前 `≥0.034s`（防浮点 1 帧双人头叠影），连续同机位严禁切碎复用同套 `scale` 动画（防缩放回弹）；严禁“空放 `whoosh` + 1 帧硬切”，大亮度/景别跳变必加 `0.3–0.5s` 视觉桥接（`clip-path` 空间形变、`--fx-blur` 甩切、跨轨 `fade` 叠化、5 帧 RGB 故障或沉黑屏息）；优先调用 OpenFilm 原生 `--of-cutout: 1`（单段控 `≤4.2s`）、`--of-lut`、离线动态贴纸 `openfilm get sticker`、SVG `stroke-dashoffset`/`getPointAtLength` 与 `motion-kit` 四类物理缓动，告别单一 `cubic-out` PPT 卡片与伪监视器 `REC` 套壳。
- 横屏官图或带文字的演示图放进竖屏卡片时，优先 `object-fit: contain` 配和谐底色，避免 `cover` 裁断左右文字；每个含图片的页面在 `window.film.ready` 里等待 `document.fonts.ready` 和全部 `<img>` 解码完成。
- 同轨首尾相接的 `<iframe>` 不要给切入镜加 `opacity: 0 → 1` 的 `fadeIn`（切点首帧会露黑底并触发 `openfilm look --full` 黑帧告警）；让页面内部由 `frame(t)` 驱动元素入场即可，若确实需要叠化转场须分放上下两轨并重叠。
- **无延迟标准字幕写法**：`subtitles.html` 禁止在正序 `for` 循环中用 `t <= c[1] + 0.12/0.14` 直接 `break`（相邻紧密台词会被前句拖尾卡住 3–4 帧并吞掉入场动画）；统一按 `Math.min(c[1] + 0.12, nextStart - 0.001)` 截断尾延或逆序匹配，并确保跨镜切点字幕不串台。
- **音频先测再配（严禁盲填 `volume`）**：BGM 与 SFX 写入 `film.html` 之前，先执行 `python3 "$SVP_ROOT/.agents/skills/short-video-pipeline/scripts/qc_video.py" probe-audio <assets目录>` 实测每条素材原生 `LUFS / True Peak / LRA / 前6秒均值 / 峰点偏移`，再据此反算 `volume` 与入点：
  - 慢热高动态 BGM（前 6 秒比全曲低 `≥10 dB` 或 `LRA > 12 LU`）禁止直接从 `#t=0` 铺底，须从起势段切入或轻压缩；多段 BGM 拼接须对齐 BPM 小节线并配 `1.5–2.0s` 交叉淡化，**严禁零 `fade` 硬切**；
  - 峰值极热/削波音效（如 `-7 LUFS`）须大幅压低（如 `0.06–0.08`），避免气口刺耳；短音效（`<audio>`）尽量不手写 `#t=0,x` 截尾，转场 whoosh 优先选有效长 `≤0.45s` 防拖尾压字，不同类型音效分放不同 `<section>` 防重叠，点缀 SFX 密度控制在 **`≤ 1 次/5s`**；长片（`>60s`）母带动态保持 `LRA ≥ 4.0 LU` 避免过度砖墙限幅疲劳。
- **首尾气口与完整收尾硬约定（杜绝残句开篇、半句截断与无结尾感）**：独立成片与切片首句前 `0.8s` 内严禁残留无前文废语（「像我刚刚讲的」「反而是」「那这个」等）；末句必须落在**完整语义句号/明确结论点**上（严禁截断在转折词/引子/破折号半句上或切入下句起音，末句人声加 `30–50ms` 微淡出）；末段须具备清晰视觉收尾落版（最后核心信息停留可读 `≥1.5s`），并在末句落音后留约 `0.6–1.2s` 视觉余韵配合 BGM 自然淡出（片尾最后 `0.35s` 不得存在 `> -25 LUFS` 的未落音截断人声）。
- 无头或批处理跑命令时统一加环境变量 `OPENFILM_NO_BROWSER=1`，且不要调用 `openfilm open`，避免拉起多余窗口或干扰机器上其他会话正在使用的全局 OpenFilm。
- 渲染与满血硬件加速：
  - 若源口播视频高于 `1440p`（如 4K `3840×2160`）或关键帧间隔 `> 0.5s`，送入 `film/assets/`（或入口 E 的 `master-assets/clips/`）前先用显卡硬解硬编一次性转出 **快解工作母版**：`ffmpeg -hwaccel cuda -i <源片> -vf "scale=-2:1440" -c:v h264_nvenc -preset p5 -cq 18 -g 8 -c:a copy <目标母片.mp4>`（无 NVIDIA 独显时降级 `-c:v libx264 -preset superfast -crf 16 -g 8`）。`2560×1440` 对竖屏 `1080×1920`（含跳切推镜）无损，且 `-g 8`（`0.26s` 关键帧）可直接命中 OpenFilm `≤0.5s` 快解免检线，省去浏览器硬啃 4K 与各片重复生成 `.film/cache/seek/` 缓存的开销。
  - `--of-cutout: 1`（AI 实时人物抠像）仅在需要「人后立大字 / 电影浅景深虚化」的高潮短镜头（单段控 `≤4.2s`）按需开启，普通全屏口播与顶部常规 PiP 小窗严禁全程常驻挂 `--of-cutout: 1`。
  - 渲染命令：`openfilm render --fps 30 --loudness=-14 --workers 6 --out ../output/final.mp4`（入口 E 按 [references/multi-variant.md](references/multi-variant.md) 分别渲染至 `../output/00-master-<话题短名>.mp4` 与 `../output/0N-vN-<风格短名>.mp4`：**单条独立渲染统一用 `--workers 6`**；2 条子片同跑各配 `--workers 4`；3 条子片同时并行渲染按 `3 / 3 / 2` 分配 `--workers`，确保全机并发 `h264_nvenc` 硬编会话总数 `≤ 8 路` 吃满显卡且不超限回退软编；仅无独显或内存 `<16GB` 机器降回 `--workers 2`）。每次都带 `--out`，不用默认的导出位置。

出片前自检，全部通过才能进入发布：

- 每镜至少用 `openfilm look` 看一帧：文字不出框、不折超 2 行、不遮挡、没有错字、无媒体水印、无音频告警。
- **自动化声画、五官防截断、音画同步与安全区红框门禁（必跑）**：执行 `python3 "$SVP_ROOT/.agents/skills/short-video-pipeline/scripts/qc_video.py" audit-render --video ../output/<成片>.mp4 --film-dir . --out-dir ../output/check`，确认 `qc-report.json` 零 `hard_failures`（校验 1080×1920、真峰值 `≤ -1.0 dBTP`、末尾 `0.35s` 无截断人声、BGM 无零淡化硬切、单支视频内视觉素材严格单次使用、无跨轨浮点双人头叠影、无连续镜缩放回弹、**`speaker-pip` 纵向 `v1≤22%` 且 `v2≥72%` 未切嘴/切下巴且 `.pip-frame` 无错位、分镜无 `t=0` 满屏静态文字提前摊牌、无前半程抢跑播完导致后半程死镜、无 `>7.5s` 超长未分段挂屏 Overlay、无跨镜超前剧透下一镜台词**、无未下沉人物抠像遮挡人后文字/信息特效、无动态贴纸压头压脸或侵右侧按钮禁区、字幕无延迟 Bug、末句无悬空半句、无底卡掉入 `y≥1540px`）并核查视觉信息密度告警（纯文字卡 `≤25%`、语义 SVG/Canvas 动效 `≥45%`、静图 B-roll 叠 SVG 前景）；**并亲自打开带三平台安全区红框的 `output/check/safezone-grid.png`、`output/check/safezone-tail.png`、切点逐帧图 `output/check/safezone-cuts.png`、画中画 1:1 特写图 `output/check/safezone-pip.png`（如有 PiP）与抠像/贴纸专检图 `output/check/safezone-cutouts.png`（如有）目检**，逐项确认：右侧按钮禁区（橙框 `x=930..1080, y=850..1500`）无压字/无遮徽章、底部红区（`y>1560`）与顶部红区（`y<180`）干净、全屏浮卡未切嘴挡下巴、**`safezone-pip.png` 中人物头顶—眼—鼻—嘴—下巴完整无截断且无背景杂墙漏出**、人后文字/特效未被人物头肩遮挡且动态贴纸未落入头肩禁区、卡片容器无 `overflow: hidden` 切底溢出、切点无闭眼/双头/亮度暴跌穿帮、结尾收束停留与 BGM 淡出自然。
- 渲染完成后对成片执行 `openfilm look --full` / `ffprobe`：1080×1920、时长与分镜一致、有音轨、无黑帧/闪屏。
- 入口 C：对照 `ref/out/VIDEO.md`，结构和节奏对得上，且成片里没有原片的任何画面和声音。

自检的记录存进 `output/check/`：`openfilm look` 存下的帧图复制一份进来，`qc_video.py` 产出的 `safezone-grid.png`、`safezone-tail.png`、`safezone-cuts.png`、`safezone-cutouts.png`（如有）、`qc-report.json` 与 `ffprobe` 输出 `ffprobe.json` 一并保留，每项检查的结论写进 `check.json`。

不合格就修到合格。修不好就停下报告，不发布。

## 步骤 6：文案、封面与分发

本步骤按 **6.1 文案 → 6.2 封面（按需）→ 6.3 强制审核门禁 → 6.4 交付手动发布或 CreatorHub 自动发布** 依次执行。

### 6.1 撰写三平台文案（默认全部视频必做）

- **先读 [references/copywriting.md](references/copywriting.md)**，结合成片第一句话、最有说服力的例子和最后落点，先提炼一句核心问题与支撑观点，再为每个目标平台产出四项文案（封面标题、视频描述、视频标签三层候选 + 单行空格分隔发布组合、短标题）。**视频描述中严禁提及任何具体秒数、时间点或片长数字**（如「第24秒」「36秒起」「1分35秒」「最后30秒」「这支48秒短片」等），一律改用自然的内容环节指代。
- 属于辰奕系列账号（如「老郑AI经营实战」，除非用户显式附加「不带品牌口号」或切换至非辰奕号组）时，在三平台描述中完整融入原句 **「用AI重构经营，让企业持续增长」**，并按规范合理配置 `#辰奕`、`#用AI重构经营`、`#让企业持续增长`。
- 按 `copywriting.md` 的字段映射表落盘至 `publish/publish.json`（保留 `cover_title`、`short_title`、`tag_candidates`、`topics_display`、`title`、`desc`、`topics`）；视频号 `title` 强制对应无空格、无禁用符号的短标题。

### 6.2 制作与自检三平台封面（按需，按系列匹配模板）

- **触发条件**：仅当视频明确属于已沉淀封面规范的系列（当前为「意图电商」系列 → [references/cover-design.md](references/cover-design.md)），或用户显式附加「带封面」「做意图电商封面」时执行；其他主题、其他系列或其他账号组的视频**不得强行套用「意图电商」模板或图片**（有对应系列规范时按该规范走；用户要求做封面但尚无对应模板时先确认系列名与视觉风格；未命中且无附加词时跳过）。
- **先读对应系列的封面规范**（如「意图电商」系列读 [references/cover-design.md](references/cover-design.md)，并看一眼标杆样图 `assets/brand/samples/yitu-cover-ref-shipinhao.jpg` 对齐质感）：
  - 直接承接 `6.1` 产出的三平台两行 `cover_title`，并用 `字号 × 字数 ≤ 980px` 校验行宽（如有微调同步回写 `publish/publish.json`）；
  - 若命中专属系列规范（如「意图电商」系列），其专题顶部标题图按 [cover-design.md](references/cover-design.md) 第 14.2 节存放在当次运行目录 `materials/covers/`（非全站通用资产，不提交入 git，禁止跨系列混用）；
  - 用工作区工具为每个目标平台抽取互不重复的人物清晰帧并抠像、做「头顶暗、肩部亮 + 靠平面侧暖橙」边缘光晕（**有干净无字幕母素材/原片时优先从源片抽帧**，兼容 `1920×1080` 横屏与 `1080×1920` 竖屏原帧，避免成片花字/字幕遮挡人物；无干净源片时再从成片挑选无文字遮挡的清晰帧），过程素材放 `materials/covers/`；
  - 渲染三平台封面落盘至 `covers/douyin.png`（`1080×1920`）、`covers/shipinhao.png`（`1080×1920`）、`covers/xhs.png`（`1080×1440`），并写 `covers/cover-spec.json`；
  - **Agent 必须亲自打开全部 3 张 PNG 看图逐项核对规范第 12 节 8 项检查**，未全部通过不得进入下一步。

### 6.3 发布前强制审核门禁

> **强制门禁**：无论是交付用户手动发布，还是调用 CreatorHub 的 `POST /api/publish` 建任务，**都必须先按 [references/publish-audit.md](references/publish-audit.md) 完成逐平台发布前审核**（先以 `qc_video.py audit-render --video <成片> --film-dir <film/> --publish-json <publish.json> --out-dir <output/check>` 过一遍自动化硬校验，再核验媒体规格与安全区红框图、文本洁净度、文案规范去秒数与品牌一致性、封面规格与视觉 8 项自检、话题总长、合规、账号状态与 `account_role != "crawler"` 以及分平台表单硬校验），并将结论写入 `publish/publish.json` 的 `audit` 字段。可无损自动修正的格式问题（如视频号短标题去空格、描述去秒数）须修正并复审通过；存在未通过的硬阻断项时**严禁建任务或放行交付**。

### 6.4 交付手动发布或 CreatorHub 自动发布

- **情况 A：带定制封面，或带「先给我看」「只做不发」→ 停下交付手动发布（不调用 CreatorHub 建任务）**
  - 经复核，CreatorHub（截至 `v0.4.0`）暂不支持为抖音、小红书、视频号上传自定义封面图。凡本次制作了定制封面（且用户未显式指令「直接自动发（封面后补）」），过审后即停下：`run.json` 记 `status: "made"`、`publish/publish.json` 记 `publish_mode: "manual_with_covers"`，把成片、三张封面图与三套可直接复制的四项文案完整交付用户手动连同封面一并发布。
- **情况 B：不做定制封面（或用户显式要求「直接自动发（封面后补）」）→ CreatorHub 串行自动发布**
  - **按 [references/creatorhub-api.md](references/creatorhub-api.md) 的文档索引与调用约定做**；具体字段和各平台能力以运行中的 `http://127.0.0.1:8000/openapi.json`、`creatorhub/guide/platforms.json` 和 `creatorhub/app/api/publishing.py` 为准。
  - **优先走本机 REST API**（`http://127.0.0.1:8000/api/...`）；API 异常或报错不明确时，可先只读调 `GET /api/diagnostics/summary` 与 `GET /api/diagnostics/logs` 排查，必要时打开 `http://127.0.0.1:8000` 前端工作台排查（严守不删账号、不改账号角色/代理/指纹/浏览器内核、不强行解除写暂停、不重试 `uncertain`、不外泄敏感信息的红线；需要扫码或人机验证时停下通知用户）。
  - **逐平台串行（IDE 终端优先非阻塞轮询）**：成片上传一次后，对每个通过审核的平台依次走 `POST /api/publish`「建任务 → 执行并等待终态」（仅明确要求多号定时错峰群发时考虑 `POST /api/matrix/publish-batch`），一个平台结束后再建下一个平台；在易超时的终端环境里，建完任务后间隔轮询 `GET /api/publish` 的 `status` 与 `live_stage` 等待结束（`v0.4.0` 拟人交互引擎单平台耗时通常 2–6 分钟）。
  - 状态是「结果待确认（`uncertain`）」时不重试、不删除、不修改，交给用户去平台核对；若排查发现新的平台表单校验规则，须同步沉淀到 [references/publish-audit.md](references/publish-audit.md) 的「实测踩坑补充」。

## 步骤 7：记录和汇报

1. 把运行目录的 `run.json` 更新到最终状态，删掉 `tmp/`。（注意：处于 `waiting_approval` 暂候用户确认阶段时，不删续跑所需中间态，也不提前执行第 2 步写 `topics-log.jsonl`，待整单到达终态 `made`/`published`/`partial`/`failed`/`stopped` 时再统一收口。）
2. 往 `runs/topics-log.jsonl` 追加一行：日期、入口、题目、来源、运行目录、各平台任务 id、状态、作品链接（入口 E 同行附 `publish_mode`、`delivery_dir`、`target_platforms` 与成片数）。整单终止停下、待手动发布或失败的运行也要记一行。
3. 检查归档与路径规范：运行目录的结构符合「归档规范」，文件名无空格/非法符号，JSON/MD 全部使用相对路径无绝对路径硬编码，这次产生的文件没有留在工作区之外，也没有散在工作区的其他位置（入口 E 另须核对 `delivery/INDEX.md` 及 4 个 `delivery/0N-*/` 子目录内成片、目标平台封面与 `copy.md` 全部齐全非空且与源产物同步一致）。
4. 汇报内容：
   - 做了什么题和原因、运行目录和成片路径（入口 E 给出母素材摘要、`delivery/` 总交付路径与 `delivery/INDEX.md` 索引）；
   - 目标平台定制封面路径（如有；入口 E 按目标平台列出 4 片防传混命名封面路径，默认三平台共 12 张，指定部分平台时为 `4 × M` 张；免封面时省略）；
   - 按目标平台整理好的可直接复制四项文案（封面标题、表单标题/视频号短标题、视频描述、三层标签候选与空格分隔「本条发布组合」；入口 E 同步指向各交付子目录的 `copy.md`）；
   - 自动发布模式列出每个平台结果和链接；带封面手动发布模式明确提示「已按规范产出并过审，请连同封面在各平台后台手动发布」；以及需要用户处理的其他事项（如账号掉线需补登）。

## 子代理

由主 agent 判断要不要派，以及派几个。你没有派子代理的能力时，按步骤顺序自己做完。

适合并行派出去的：

- 步骤 2 的拆解和看图复核，与步骤 3 的查事实同时进行。
- 有多条参考视频时，每条一个子代理做拆解。
- 步骤 1 取各平台热榜和查小红书热度。
- 步骤 4 里互不依赖的各镜素材：每个子代理负责若干镜的图片、视频或页面文件。
- 入口 E（`E4`）：在母片与 `master-plan.json` 通过闸门 2 后，并行派 3 个子代理分别负责 `variants/v1-*/`、`variants/v2-*/`、`variants/v3-*/` 三个物理隔离目录的独立补素材、独立 OpenFilm 剪辑/渲染/初检与本子片目标平台封面/文案初稿及单条 `publish.json`。

必须由主 agent 自己串行做的：

- 单片流程（入口 A/B/C）写 `film.html`（子代理只写各自页面文件与素材）、单片渲染和出片自检。
- 入口 E 的粗剪汇报与母素材确立（闸门 1）、母片定调与 3 子片规划（闸门 2）、全部 4 条成片与全部定制封面的最终看图复核、跨 4 片矩阵审核（`E5`）与 `delivery/` 统一交付包组装（`E6`）。
- 步骤 6 的全部发布操作。
- 同一个账号上的 CreatorHub 操作，不要同时发起两个。

派出时的要求：

- 子代理看不到你的上下文。交代清楚：运行目录、要先读的仓库 skill 的路径、输入文件、要产出的文件路径（按「归档规范」指定到运行目录里的具体位置）、执行命令前先在根目录或按正确层级执行环境脚本 `env.sh`、以及明确权限边界：
  - **公共红线（所有入口子代理严禁）**：不发布、不调用付费生成、不在运行目录之外存放文件、不删改用户的外部源文件；
  - **单片流程子代理额外禁止**：不改主项目的 `film.html`、不做整片渲染与最终文案；
  - **入口 E（`E4`）子代理隔离授权**：允许在自身专属目录 `variants/vN-<风格>/` 内写该子片的 `film/film.html`、渲染 `output/0N-vN-*.mp4` 并产出本子片封面/文案初稿，但**严禁修改 `raw/`、`master-assets/`、`master/` 及另外两条子片目录**。
- 子代理交回的东西，主 agent 要自己打开文件或看图核对后再用，不只看它的汇报。
- 不值得派的：单片流程中几分钟内能做完的事、单条视频的各平台文案（入口 E 3 子片因各有独立成片，其初稿随各自子代理在隔离目录产出，回收后由主 agent 在 `E5` 亲自核查与跨片去重）。

## 能力不足时的退路

| 你做不到 | 怎么办 |
|---|---|
| 联网搜索 | 只要本机有外网，仍可用 `scripts/fetch_trends.py --mode search` 和 `scripts/fetch_asset.py` 查新闻与抓素材；完全离线时只做不依赖具体数据的题或请用户提供资料 |
| 看图 | rea-video 按它 `references/review.md` 的「看不了图时的规则」做；OpenFilm 画面、入口 E 马赛克核验帧或定制封面无法目检时，在 `check.json` / `cover-spec.json` 记为 `pending_human_visual_review`（严禁伪造通过），将 `run.json` 置 `waiting_approval` 停下交用户人工目检（入口 E 可整理预览并列出全部待目检路径，但不自动发布也不标记 `cross_audit_passed: true`） |
| 生成图片或视频 | 按 [references/sourcing.md](references/sourcing.md) 走 `scripts/fetch_asset.py`（官方新闻配图/截图/短切片、免版权公开图库）和 OpenFilm 内置 Pexels/Pixabay；仍无素材再退回自带库和代码画面 |
| 派子代理 | 自己按顺序做 |

## 不要做的事

- 不外传、不打印 `creatorhub/data/`、`creatorhub/config.yaml`、`.local/openfilm/`、浏览器 Profile、Cookie 的内容。
- 不在工作区之外安装、生成或存放任何东西；不跳过环境脚本。
- 不通过 CreatorHub 发私信、评论、转发别人的作品、删作品、改代理或指纹，除非用户另外明确要求。
- 不为了凑一条视频放宽选题筛选、事实要求或出片自检。
