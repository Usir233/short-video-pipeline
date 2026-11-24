# 母素材确立 → 1 完整母片 + 3 风格子片矩阵流程规范（入口 E）

本文件定义本工作区 **入口 E（单组输入 → 确立母素材 → 1 条完整特效母片 + 3 条基于当前母片延伸的差异风格子片）** 的完整作业标准、人工确认闸门、全链路路径与防传混命名规范以及统一交付包结构。

所有路径均相对工作区根目录，严禁在任何文件或 JSON 中写死本机绝对路径；运行命令前先在当前 shell 执行环境脚本（**推荐先在根目录 `. .agents/skills/short-video-pipeline/scripts/env.sh` 再 `cd` 进目标目录**；若在深层目录直接 source：`master/film/` 为 4 层 `. ../../../../.agents/skills/short-video-pipeline/scripts/env.sh`，`variants/vN-<风格>/film/` 为 5 层 `. ../../../../../.agents/skills/short-video-pipeline/scripts/env.sh`）。source 后在任意深层目录统一直接调用 `openfilm`、`"$SVP_ROOT/rea-video/.venv/bin/rea-video"` 与 `python3 "$SVP_ROOT/.agents/skills/short-video-pipeline/scripts/fetch_asset.py"`，切勿硬写 `../../../`。

---

## 一、核心概念与总产出

本流程严格区分以下五个层级，绝不混用：

| 概念 | 归档位置 | 精确定义 |
|---|---|---|
| **原始输入** | `raw/` | 用户输入的「原片 + 配套素材」，分为「已处理」与「未处理」两种初始状态。原片只读不动（工作区外源文件只读复制进来，绝不移动或删除用户原文件）。 |
| **粗剪与预处理** | `rough-cut/` | 仅当输入为「未处理」时执行：先按视频中的**话题分段切割**，同步**去除口气词/废话/冗余停顿**；完成后强制停下汇报用户（**闸门 1**），按用户指示确认通过或追加预处理（如指定时段/区域**打马赛克**、删改/合并段、裁切/降噪）。 |
| **母素材（Master Assets）** | `master-assets/` | 「已处理输入」直通，或经粗剪与用户确认预处理完成后的**最终干净原片切片（含按需人声分轨）+ 配套素材包**。它是下游 1 母片 + 3 子片的共同干净上游源，从源头避免母片烧录特效/花字/配乐污染下游子片换风格。 |
| **母片（Master）** | `master/` | 基于「母素材」+ Agent 按需补充素材，按工作区既有规范制作出的**完整精剪加特效成片**，自带**母片专属的目标平台封面 + 目标平台文案**。 |
| **3 条延伸子片（Variants）** | `variants/v1..v3/` | 基于「母素材」与当期母片及工作区既有规范，向外延伸出的 **3 条风格各不相同的精剪特效成片**；每条子片根据自身实际情况**独立补充素材**，并各自拥有**目标平台封面 + 目标平台文案**。 |

**单次运行标准总产出**：
- **默认全三平台（`M = 3`）**：**4 条精剪成片（1 母片 + 3 延伸子片）+ 12 张定制封面（4 × 3）+ 12 套过审三平台文案（4 × 3）+ 规范化的 `delivery/` 统一交付包**；
- **指定部分平台 / 免封面弹性**：若用户附加「只发抖音」「不发小红书」等（`M < 3`），则按实际 `target_platforms` 产出 **`4 × M` 张封面 + `4 × M` 套文案**；若显式附加「不做封面」「免封面」，则跳过封面生成与封面校验，在 `run.json` 记 `covers_enabled: false`。
- **交付模式**：默认审核通过后停下交付 `delivery/` 给用户手动发布（即使免封面，因 4 片矩阵通常分发至多账号或错峰排期，仍默认手动交付；仅当用户显式要求 CreatorHub 自动发布并确认账号分配与错峰排期后，才由主 Agent 逐条串行调用 CreatorHub，严禁 4 片并发抢跑同一账号）。

---

## 二、全链路路径与防上传传混命名规范（硬规定）

入口 E 产物数量大，必须从建目录到收尾全链路执行路径与命名规范，确保人工上传 4 条视频、12 张封面、12 套文案时零混淆、零工作区外残留。

### 1. 标准目录树（相对工作区根目录）

```text
runs/<YYYYMMDD-HHMM>-<话题短名>/
├── run.json                                        总控索引（entry: "E"、输入态、两道闸门状态、4片与交付索引）
├── raw/                                            原始输入登记（只读不动原片）
│   ├── input.json                                  原片相对路径、ffprobe 规格、是否含原 BGM 等登记信息
│   ├── supplied/                                   用户原始配套素材副本或登记清单
│   └── rea-out/                                    rea-video 拆解/ASR 逐字稿与可选人声分轨 stems/vocals.wav（按需建）
├── rough-cut/                                      粗剪与预处理区（仅输入未处理时建）
│   ├── topics.json                                 话题分段清单（序号、话题、起止秒、精简口气词摘要、预览路径）
│   ├── cuts/                                       按话题切割并去口气词后的粗剪预览切片
│   │   ├── topic-01-<话题短名>.mp4
│   │   └── topic-02-<话题短名>.mp4
│   └── preprocess.json                             用户确认意见与多轮追加预处理记录（马赛克时段/坐标、核验帧路径、删改/合并）
├── master-assets/                                  【母素材】经确认的最终干净上游底料
│   ├── manifest.json                               母素材清单（确认切片/合并片、对齐后逐字稿时间戳、人声分轨、配套素材映射）
│   ├── clips/                                      已确认的干净原片/预处理切片（支持单段 clip-01-*.mp4、合并片 clip-merged-*.mp4 与 *-vocals.wav）
│   │   └── clip-01-<话题短名>.mp4
│   └── supplied/                                   用户随片提供的配套素材（规范重命名，去除空格与非法符号）
├── master/                                         【母片】完整精剪加特效成片 + 3 平台封面与文案
│   ├── script/
│   │   ├── storyboard.json                         母片分镜与特效/动画脚本
│   │   └── master-plan.json                        基于当期母片延伸的 3 条差异风格子片总规划书
│   ├── materials/                                  母片 Agent 补充素材原件；封面截帧与抠像过程稿放 materials/covers/
│   ├── film/                                       母片 OpenFilm 工程 + assets/ + credits.json
│   ├── output/
│   │   ├── 00-master-<话题短名>.mp4                 母片完整特效成片（防传混前缀 00-master）
│   │   └── check/                                  逐镜帧图、ffprobe.json、check.json
│   ├── covers/
│   │   ├── 00-master-douyin.png                    1080 × 1920
│   │   ├── 00-master-shipinhao.png                 1080 × 1920
│   │   ├── 00-master-xhs.png                       1080 × 1440
│   │   └── cover-spec.json
│   └── publish/
│       └── publish.json                            母片三平台四项文案、三层标签、发布组合、封面路径与 audit
├── variants/                                       【3 条延伸子片】目录物理隔离，天然支持 3 子代理并行
│   ├── v1-<风格短名>/
│   │   ├── script/storyboard.json
│   │   ├── materials/                              子片 1 独立补充素材原件；封面过程稿放 materials/covers/
│   │   ├── film/                                   子片 1 独立 OpenFilm 工程 + assets/ + credits.json
│   │   ├── output/
│   │   │   ├── 01-v1-<风格短名>.mp4                 防传混前缀 01-v1
│   │   │   └── check/
│   │   ├── covers/
│   │   │   ├── 01-v1-douyin.png                    1080 × 1920
│   │   │   ├── 01-v1-shipinhao.png                 1080 × 1920
│   │   │   ├── 01-v1-xhs.png                       1080 × 1440
│   │   │   └── cover-spec.json
│   │   └── publish/publish.json
│   ├── v2-<风格短名>/                               编号前缀 02-v2-*（内部结构与 v1 完全同构）
│   └── v3-<风格短名>/                               编号前缀 03-v3-*（内部结构与 v1 完全同构）
├── delivery/                                       【统一交付包】面向人工上传的一站式出口
│   ├── INDEX.md                                    一页式总交付表（母素材摘要 + 4 成片/12 封面路径 + 审核状态）
│   ├── 00-master/                                  00-master-<话题短名>.mp4 + 3 张封面 PNG + copy.md
│   ├── 01-v1-<风格短名>/                            01-v1-<风格短名>.mp4 + 3 张封面 PNG + copy.md
│   ├── 02-v2-<风格短名>/                            02-v2-<风格短名>.mp4 + 3 张封面 PNG + copy.md
│   └── 03-v3-<风格短名>/                            03-v3-<风格短名>.mp4 + 3 张封面 PNG + copy.md
└── tmp/                                            临时中间文件，收尾时必须删除
```

用不到的目录不建（例如输入已处理跳过粗剪时不建 `rough-cut/`）。不在运行目录根上随意散落其他文件。

### 2. 文件名与路径硬规范

1. **字符白名单**：运行目录名、子目录名及全部自生成文件名仅允许**汉字、英文字母、数字、连字符 `-`、下划线 `_` 与扩展名点号 `.`**；禁止包含空格、全角标点、斜杠、问号、星号与 Emoji。用户提供的原始素材如含空格或怪异符号，原样登记于 `raw/`，复制到 `master-assets/supplied/` 时自动转为合规短名并在 `manifest.json` 记录映射关系。
2. **防上传传混编号前缀**：
   - 母片统一使用 `00-master-` 前缀；
   - 三条延伸子片按序统一使用 `01-v1-`、`02-v2-`、`03-v3-` 前缀；
   - 三平台封面后缀固定为 `-douyin.png`、`-shipinhao.png`、`-xhs.png`；
   - 粗剪话题切片固定为 `topic-01-<话题短名>.mp4`、`topic-02-...`。
3. **相对路径铁律**：所有 JSON（`run.json`、`manifest.json`、`topics.json`、`master-plan.json`、`credits.json`、`cover-spec.json`、`publish.json`）与 Markdown（`delivery/INDEX.md`、`copy.md`）中的路径**一律写相对工作区根目录的路径**（如 `runs/20261124-1400-意图电商/master/output/00-master-意图电商.mp4`），严禁出现本机绝对路径或 `~/`。
4. **`delivery/` 零浪费归集与防陈旧铁律**：
   - 往 `delivery/00-master/`、`delivery/01-v1-*/` 等交付目录汇总成片与封面时，跨平台降级链为：先删旧目标 → 同文件系统优先硬链接（`ln`，Linux/macOS 通用）→ macOS APFS 硬链接受限时用写时复制（`cp -c`）→ 其余降级普通复制（`cp`），避免无谓倍增磁盘占用且确保用户在 Finder 或浏览器上传框里打开单个交付目录即可直接拖拽。
   - **返工强制整包重建铁律（防旧 inode / 副本陈旧大坑）**：OpenFilm 渲染、Playwright/PIL 重出图或 `ffmpeg` 输出往往通过替换生成新 inode；若已有 `delivery/`，后续任何一片（视频、封面或文案）发生返工修改后，**必须先整包清空重建 `delivery/`（如 `rm -rf runs/<目录>/delivery` 后全量重新链接成片/封面并重新生成 `copy.md` 与 `INDEX.md`）**，并核验 `delivery/` 内每个成片/封面与源目录产物的文件大小及哈希（或同 inode）100% 一致，绝不留陈旧文件！
   - **大原片零重复拷贝约定**：从 `raw/` 到 `master-assets/clips/`（已处理直通且无需重编码时）以及从 `master-assets/clips/` 到各片 `film/assets/`（整段复用且无需重编码时），同文件系统同样优先 `ln` 或 `cp -c`（或仅把实际截出的短切片放入 `film/assets/`），严禁对硬链接指向的上游只读文件执行原地覆写（`ffmpeg` 等工具输出必须写新文件名）。
5. **工作区外零残留收口**：Agent 自带工具、浏览器下载或生图工具产出到工作区外的文件，必须立即移入本次运行目录对应的规范子目录，外部不留副本；用户原本放在工作区外的原始输入文件则只读复制进 `raw/`，绝不移动或删除用户原文件；整单到达终态收尾前清空 `tmp/`。

---

## 三、端到端执行步骤（E0 → E6）与暂停/续跑协议

### 暂停状态机与用户回复续跑协议（贯穿 E0 / E1 / E3 / 人工目检）

入口 E 涉及多轮人机确认，必须严格执行以下状态机，避免续跑时重复建目录或污染索引：

- **暂停落盘规则**：每次停下等待用户决定（E0 判定输入态、E1 闸门 1 粗剪/预处理确认、E3 闸门 2 母片与 3 子片方案确认、或无看图能力等待人工目检）时：
  1. 立即更新 `run.json`：`status: "waiting_approval"`、`step` 记当前步骤、`gates.pending_gate` 记 `"gate_0_input_state"` / `"gate_1_rough_cut"` / `"gate_2_master_plan"` / `"visual_review"`、`finished_at: null`、`notes` 写清等待用户拍板的事项；
  2. **不删除**续跑仍需读取的中间文件，**不提前**向 `runs/topics-log.jsonl` 追加记录（避免一次运行写多行污染 14 天去重索引）。
- **用户回复后续跑规则**：用户回复确认、补充预处理指令或「OK 继续」后：
  1. **必须复用原运行目录**（严禁新建 `runs/<新时间>-<话题>/` 目录）；
  2. 先读取原目录 `run.json` 及对应阶段文件（`raw/input.json`、`rough-cut/topics.json`、`rough-cut/preprocess.json`、`master-assets/manifest.json`、`master/script/master-plan.json`）恢复上下文；
  3. 将 `run.json` 恢复为 `status: "running"`，推进对应 `gates.*` 标志并清空 `gates.pending_gate: null`，从断点继续执行。

### 步骤 E0：环境检查、输入态判定与原片音频体检

1. 在工作区根目录执行 `. .agents/skills/short-video-pipeline/scripts/env.sh`，核验 `openfilm`、`ffmpeg`、`ffprobe` 就绪（未处理输入或需人声分轨/ASR 时另核验 `"$SVP_ROOT/rea-video/.venv/bin/rea-video"`；入口 E 默认交付手动发布，不阻塞于 CreatorHub 服务启动或登录态）。
2. 建立运行目录 `runs/<YYYYMMDD-HHMM>-<话题短名>/` 并初始化 `run.json`（`entry: "E"`、`target_platforms` 默认 `["douyin", "xhs", "shipinhao"]`、`covers_enabled: true`、`status: "running"`）。
3. 登记原始输入到 `raw/`：
   - **工作区内原片**：已在工作区内且体积较大时，直接在 `raw/input.json` 记录其相对路径（不强制多拷贝一份大原片）；
   - **工作区外原片**：若用户提供了工作区外的本机文件路径，**只读复制**进 `raw/`（**严禁 `mv` 移动或删除用户本机源文件**）；若是下载链接，则用工作区工具下载进 `raw/`；
   - 用户附带的配套素材只读复制或登记进 `raw/supplied/`；
   - 用 `ffprobe` 检查原片分辨率、帧率、时长、编码与音轨状态，写入 `raw/input.json`。
4. **原片 BGM / 底噪体检与人声分轨预案（防换风格叠音打架）**：
   - 无论输入「已处理」还是「未处理」，均检查原片音轨是否自带背景音乐（BGM）或明显环境底噪（已处理口播片常混有原 BGM）；
   - 若原片**自带 BGM 或需精准口播时间轴**：执行 `"$SVP_ROOT/rea-video/.venv/bin/rea-video"` 拆解至 `raw/rea-out/`，提取完整口播逐字稿与干净人声轨 `stems/vocals.wav`；在确立母素材时同步裁切对齐后的干净人声轨放入 `master-assets/clips/<切片名>-vocals.wav`（或混出无 BGM 的干净口播切片），并在 `master-assets/manifest.json` 记 `has_original_bgm: true` 与 `vocals_track`。下游母片与 3 条子片一律以干净人声轨为底再铺各自风格 BGM，彻底杜绝双 BGM 叠音打架！
5. **判定「已处理 / 未处理」**：
   - 用户明确说了「已处理 / 已粗剪 / 直接当母素材」→ `gates.input_state_confirmed = true`、`gates.rough_cut_approved = "skipped_processed"`，跳过步骤 E1，按零重复拷贝原则（同卷硬链接/`cp -c` 或规范引用）将原片切片（及可选 `*-vocals.wav`）与规范化重命名后的配套素材归档进 `master-assets/` 并写 `manifest.json`；
   - 用户明确说了「未处理 / 原片 / 先粗剪」→ `gates.input_state_confirmed = true`，进入步骤 E1；
   - 用户未明确说明处理状态时 → Agent 先结合 `ffprobe` 与轻量试听/静音检测初步判断，将 `run.json` 置 `status: "waiting_approval"`、`gates.pending_gate: "gate_0_input_state"`，**停下用一句话向用户确认是已处理还是未处理**，绝不擅自跳过粗剪。

### 步骤 E1：粗剪与强制人工确认（闸门 1，仅未处理输入触发）

1. **语音与话题解析**：
   - 使用工作区 `"$SVP_ROOT/rea-video/.venv/bin/rea-video"` 输出到 `raw/rea-out/`（带 ASR 字幕时间轴，若原片带 BGM 同步保留 `stems/vocals.wav`）获取完整口播逐字稿与精确时间戳；
   - 按内容语义与论述转折，将原片切分为若干独立**话题段（Topics）**。
2. **同步去口气词与冗余停顿精简**：
   - 在每个话题段内定位明显非表意口气词（「嗯」「呃」「啊」「那个」「然后就是」等口癖）、口误重说段与冗长冷场气口；
   - 用 `ffmpeg` 按精准切点裁剪并做短交叉淡化（避免音频爆音，保护正常语速与呼吸感，不把有效字头字尾切碎）；
   - 输出每段粗剪预览文件到 `rough-cut/cuts/topic-01-<话题短名>.mp4`…，并将完整切分与精简清单写入 `rough-cut/topics.json`。
3. **【闸门 1】强制停下汇报，由用户拍板**：
   - 更新 `run.json`（`status: "waiting_approval"`、`step: "E1"`、`gates.pending_gate: "gate_1_rough_cut"`），**必须停下**向用户清晰展示：
     - 话题分段总表（序号 / 话题概要 / 原片时段 / 精简后时长 / 剔除的口气词与重说摘要 / 粗剪预览文件相对路径）；
     - 明确请用户判断并告知：
       1. **本次保留哪些话题段**，以及是否需要**将多段按顺序合并**进入「母素材」；
       2. **是否直接通过**，还是需要**追加其它前置处理**（例如：指定时间段与画面区域**打马赛克/模糊隐私**、删除某句话、画面裁切构图、人声降噪/去原 BGM、增补外部素材等）。
4. **执行用户指定的合并与追加预处理（如有，支持多轮修订）**：
   - 收到用户回复后复用原目录续跑（`status: "running"`），按指令执行处理：
     - 多段合并时产出合并片（如 `clip-merged-<话题短名>.mp4`），同时可按需保留独立单段切片供下游子片选用；
     - 打马赛克通过 `ffmpeg` 滤镜精准作用于指定起止秒和坐标区域，处理完抽取起/中/末对应时间帧看图确认遮挡准确且不漏帧（若当前 Agent 无看图能力，则将核验帧路径直接交用户目检确认，不得私自标通过）；
   - 将本轮用户意见、操作参数、核验帧路径与结论按轮次追加记录到 `rough-cut/preprocess.json` 的 `revisions` 数组，回传预览图/片段请用户再次确认，直至用户明确「通过」。
5. **时间轴校准并正式确立「母素材（Master Assets）」**：
   - 只有获得用户明确「通过」指令后，才将最终确认的干净原片切片/合并片（及同步裁切对齐后的干净人声轨 `*-vocals.wav`，如有）放入 `master-assets/clips/`，用户配套素材规范化命名后放入 `master-assets/supplied/`；
   - **时间轴重算铁律**：凡经过删句、重切或合并，**必须按最终 `master-assets/clips/` 的实际成片重新映射或重跑轻量 ASR 校准逐字稿时间戳**（严禁直接沿用原片旧时间戳导致下游字幕与花字错位）；
   - 写入完整的 `master-assets/manifest.json`（记录 `source_topics`、确认切片与合并片路径、`aligned_transcript`、`has_original_bgm`、`vocals_track`、`preprocess_applied` 与 `supplied_assets` 原名→合规名映射），同步更新 `run.json`（`gates.rough_cut_approved = true`、`gates.pending_gate = null`）。

### 步骤 E2：基于母素材制作完整母片（`master/`）

1. **脚本分镜与补素材**：
   - 基于 `master-assets/manifest.json` 提炼母片的一句话核心问题与支撑观点，编写 `master/script/storyboard.json`；
   - 在用户配套素材之外，按 [sourcing.md](sourcing.md) 的 5 类通道自主补充母片所需素材（OpenFilm 复用库/CC0、代码动画、官方无水印图/≤6s 切片、免版权 B-roll、按需生图），原件入 `master/materials/`，实采素材入 `master/film/assets/` 并登记 `credits.json`（调用 `fetch_asset.py` 时明确指定 `--out runs/<目录>/master/materials --assets runs/<目录>/master/film/assets`）。
2. **母片剪辑特效与出片自检**：
   - 先在根目录 source `env.sh` 再 `cd runs/<目录>/master/film`（或在 `master/film/` 执行 `. ../../../../.agents/skills/short-video-pipeline/scripts/env.sh`），按 OpenFilm 规范完成精剪、特效、动画、字幕、花字与配乐包装（`1080×1920` 安全区、`OPENFILM_NO_BROWSER=1`；若 `manifest.json` 标有 `vocals_track` 则用干净人声轨配新 BGM 防叠音）；
   - 渲染命令：`OPENFILM_NO_BROWSER=1 openfilm render --fps 30 --loudness=-14 --out ../output/00-master-<话题短名>.mp4`；
   - 逐镜 `openfilm look` 看图 + 全片 `openfilm look --full` & `ffprobe` 自检，记录写入 `master/output/check/`。
3. **母片目标平台文案 + 封面 + 单条审核**：
   - 按 [copywriting.md](copywriting.md) 写出母片所有目标平台的四项文案、三层标签候选与空格版发布组合，落盘 `master/publish/publish.json`；
   - 若 `covers_enabled` 为 `true`：按对应系列规范制作母片目标平台封面（若当期属于「意图电商」系列则严格按 [cover-design.md](cover-design.md) 出图；否则按当期母片视觉风格独立设计对应尺寸 `1080×1920` / `1080×1440` 封面；**人物抽帧优先从 `master-assets/clips/` 干净源片抽取**，避开母片花字/字幕遮挡抠像），落盘 `master/covers/00-master-<平台>.png` 与 `cover-spec.json`，并亲自看图逐项核对；
   - 按 [publish-audit.md](publish-audit.md) 完成母片单条全目标平台审核并写回 `master/publish/publish.json` 的 `audit`。

### 步骤 E3：基于当期母片与既有规范 → 延伸规划 3 条子片（+ 闸门 2）

1. **内容关系自适应策略**：
   - **母片 > 90 秒（完整长口播/访谈）**：3 条子片优先从「母素材 + 母片主线」中拆出 **3 个互不重复的核心看点/独立金句切片**（如每条 20–60 秒），再各自做不同风格包装；
   - **母片 ≤ 90 秒（单观点精华片）**：3 条子片围绕同一核心主题，从 **3 种不同开头钩子、叙事视角、节奏结构与视觉包装** 重构 3 条高度区分的成片；
   - 用户启动时如显式指定「拆三条」或「同内容三风格」，则优先遵照指令。
2. **基于当前已有规范与当期母片的 3 路延伸框架**：
   - 每条子片必须在 **6 个维度** 与母片及另外两条子片形成清晰差异：**开头钩子结构、剪辑节奏/切镜频率、字幕与花字样式、特效/动画与主辅画面占比、BGM 情绪/BPM、独立补充素材类型**；
   - 参考延伸方向槽位（每期结合当期母片实际风格与受众灵活定名；后续不同账号组沉淀专属封面/品牌规范后可直接挂入对应槽位）：
     - **`v1`（延伸方向 1 · 高节奏网感 B-roll 实证风）**：前 3 秒强冲突/结果前置钩子，高频跳切与重点词弹窗，重点补充实拍空镜、官方产品演示/新闻截图等具象画面，轻快强节奏 BGM；
     - **`v2`（延伸方向 2 · 结构化干货清单/图解风）**：用编号进度条、对比表、流程拆解或白板/信息卡片组织逻辑，重点用 OpenFilm 代码图解与步骤清单画面补充，知性稳健 BGM；
     - **`v3`（延伸方向 3 · 金句反差/轻对话沉浸风）**：强化情绪张力与对话代入感（如买家 vs 卖家视角对切、灵魂追问式花字、留白呼吸节奏），重点补充场景氛围镜头或隐喻视觉元素，克制氛围感 BGM。
   - 将 3 条子片的切分点/视角、风格定义、独立补素材清单、封面规范分配（明确哪条套用既有系列模板如 `cover-design.md`，哪条按各自子片风格独立设计）与品牌主张配置完整写入 `master/script/master-plan.json`（所有路径一律相对工作区根目录）。
3. **【闸门 2】母片与 3 子片方案确认（默认开启，指令带「一路跑完」可跳过）**：
   - 若带「一路跑完」：`gates.master_approved = "skipped_auto_run"`，直接进入步骤 E4；
   - 否则更新 `run.json`（`status: "waiting_approval"`、`step: "E3"`、`gates.pending_gate: "gate_2_master_plan"`），停下向用户展示：① 母片成片、目标平台封面路径与文案摘要；② `master-plan.json` 中的 3 条延伸子片差异化规划表；
   - 待用户回复「OK 继续」（或调整某条风格/切分点）后复用原运行目录续跑，置 `gates.master_approved = true`、`gates.pending_gate = null`、`status: "running"`，启动步骤 E4，避免 3 条子片方向跑偏造成 3 倍返工。

### 步骤 E4：3 条延伸子片独立制作（支持 3 子代理真并行）

- 3 个目录 `variants/v1-<风格>/`、`variants/v2-<风格>/`、`variants/v3-<风格>/` 完全物理隔离，主 Agent 可同时派发 **3 个子代理**分别负责一条子片（不具备派子代理能力时串行完成）。
- **子代理权限边界（与 [../SKILL.md](../SKILL.md) 保持一致）**：3 个子代理仅在各自专属目录 `variants/vN-<风格>/` 内拥有局部完整制作权（可写各自 `film/film.html`、独立渲染与初检、产出本子片封面/文案初稿及单条 `publish.json`），**严禁修改 `raw/`、`master-assets/`、`master/` 及另外两条子片目录，严禁调用任何发布操作或付费生成，严禁在运行目录外存放文件**。
- 每条子片均以 `master-assets/` 为干净底料（需要局部引用母片某段特效时可按需引用，但不直接把焊死旧花字与旧 BGM 的母片当唯一底轨；原片含 BGM 时统一使用 `vocals_track` 配新风格 BGM），完整执行：
  1. **各自按实际情况独立补充素材**：按 [sourcing.md](sourcing.md) 5 类通道独立寻源并落盘各自 `materials/` 与 `film/assets/`，记录 `credits.json`（严禁 4 条片照搬同一批补充素材；通用素材同步一份进 `.local/openfilm-user/saved/`）；
  2. **独立 OpenFilm 剪辑与出片初检**：先在根目录 source `env.sh` 再 `cd runs/<目录>/variants/vN-<风格>/film`（或在 5 层目录执行 `. ../../../../../.agents/skills/short-video-pipeline/scripts/env.sh`），执行 `OPENFILM_NO_BROWSER=1 openfilm render --fps 30 --loudness=-14 --out ../output/0N-vN-<风格短名>.mp4`，逐镜 `openfilm look` + 全片 `openfilm look --full` & `ffprobe` 写入 `output/check/`；
  3. **独立目标平台文案**：按 [copywriting.md](copywriting.md) 紧贴本子片实际剪出的第一句话、案例与落点撰写四项文案、三层标签候选与空格版发布组合，落盘 `publish/publish.json`；
  4. **独立目标平台封面（若 `covers_enabled` 为 `true`）**：按规划槽位优先从 `master-assets/clips/` 干净源片抽帧（同片内各平台取不同截帧），产出 `covers/0N-vN-<平台>.png`（抖音 `1080×1920`、视频号 `1080×1920`、小红书 `1080×1440`）与 `cover-spec.json`（非「意图电商」系列严禁混套「意图电商」标题图）；
  5. **子片单条审核**：按 [publish-audit.md](publish-audit.md) 完成本子片所有目标平台审核并写回 `publish/publish.json` 的 `audit`。

### 步骤 E5：主 Agent 统一复核、跨 4 片矩阵门禁与路径收口

此步必须由**主 Agent 亲自串行执行**，不外包给子代理：
1. **逐片视觉复核**：亲自打开并核验全部 4 条成片的关键帧自检结果，并**亲自打开全部定制封面 PNG（默认 12 张，或 `4 × M` 张）目视复核**；
   - **无看图能力退路**：若当前 Agent 不具备看图能力，严禁伪造目检通过；须将各 `check.json` / `cover-spec.json` 视觉项记为 `"pending_human_visual_review"`、`run.json` 置 `status: "waiting_approval"`、`gates.pending_gate: "visual_review"`、`cross_audit_passed: false`（但仍须完成全部机械项审核并在下一步组装预览包列出全部待目检路径供用户肉眼签收）。
2. **跨 4 片矩阵审核**：按 [publish-audit.md](publish-audit.md) 第五节逐项执行跨片审核（母素材确认态、4 片风格实质差异、各片独立补素材合规、目标平台封面防撞帧/防撞标题/尺寸与视觉门禁、目标平台文案跨片防雷同及表单硬校验）；任一不通过即定向返工对应子片并复审；
3. **路径与命名收口检查**：核验所有 JSON/MD 无绝对路径、文件名全符合字符白名单、无工作区外残留文件、`tmp/` 已清空。

### 步骤 E6：组装 `delivery/` 统一交付包与归档收尾

1. 生成（或返工后**彻底重建**）`runs/<目录>/delivery/` 统一交付包：
   - 若 `delivery/` 已存在，**必须先整包清空重建**（`rm -rf runs/<目录>/delivery`），防止任一片返工重渲后硬链接仍指向旧 inode 或副本陈旧；
   - 建立 `00-master/`、`01-v1-<风格>/`、`02-v2-<风格>/`、`03-v3-<风格>/` 四个交付子目录；
   - 每个子目录放入对应防传混命名的成片（按 `ln` → macOS `cp -c` → `cp` 降级链归集）、全部目标平台封面 PNG（如启用封面），以及按下方模板生成的 `copy.md`；
   - **同步一致性校验**：核验 `delivery/` 内每个成片和封面文件均非空且与源目录（`master/`、`variants/vN-*/`）对应文件大小/哈希一致；
   - 生成 `delivery/INDEX.md` 一页式总交付表（汇总母素材摘要、目标平台、4 片成片路径/时长/风格、全部封面路径、审核结论与手动发布提醒）。
2. 终态归档：
   - 若全部审核（含视觉复核）通过：更新 `run.json`（`status: "made"`、`publish_mode: "manual_with_covers"` 或免封面时的 `"manual_delivery"`、`cross_audit_passed: true`、`finished_at` 填入当前带时区时间），删除 `tmp/`，向 `runs/topics-log.jsonl` 追加一行 JSONL 记录（含 `date`、`entry: "E"`、`topic`、`run_dir`、`target_platforms`、`publish_mode`、`delivery_dir`、`variant_count: 4`、`status: "made"`）；
   - 若因无看图能力停在 `waiting_approval`：暂不向 `topics-log.jsonl` 写终态，明确列出需用户目检的关键帧与封面 PNG 路径待确认。
3. 向用户汇报：母素材摘要、`delivery/` 总交付路径、`delivery/INDEX.md` 核心总览与可直接手动上传的 4 组交付清单。

---

## 四、关键索引 JSON 与交付模板示例

> 以下所有 JSON 与 Markdown 中的路径均严格遵循「相对工作区根目录」铁律。

### 1. `run.json`（入口 E 扩展结构）

```json
{
  "id": "20261124-1400-意图电商专题",
  "topic": "意图电商专题（母素材 + 1母片 + 3延伸风格子片）",
  "entry": "E",
  "input_processed": false,
  "target_platforms": ["douyin", "xhs", "shipinhao"],
  "covers_enabled": true,
  "publish_mode": "manual_with_covers",
  "started_at": "2026-11-24T14:00:00+08:00",
  "finished_at": "2026-11-24T15:30:00+08:00",
  "status": "made",
  "step": "E6",
  "gates": {
    "input_state_confirmed": true,
    "rough_cut_approved": true,
    "master_approved": true,
    "pending_gate": null
  },
  "master_assets": "runs/20261124-1400-意图电商专题/master-assets/manifest.json",
  "master": {
    "prefix": "00-master",
    "video": "runs/20261124-1400-意图电商专题/master/output/00-master-意图电商专题.mp4",
    "covers": {
      "douyin": "runs/20261124-1400-意图电商专题/master/covers/00-master-douyin.png",
      "shipinhao": "runs/20261124-1400-意图电商专题/master/covers/00-master-shipinhao.png",
      "xhs": "runs/20261124-1400-意图电商专题/master/covers/00-master-xhs.png"
    },
    "publish_json": "runs/20261124-1400-意图电商专题/master/publish/publish.json"
  },
  "variants": [
    {
      "id": "v1",
      "prefix": "01-v1",
      "style": "高节奏实证风",
      "dir": "runs/20261124-1400-意图电商专题/variants/v1-高节奏实证风",
      "video": "runs/20261124-1400-意图电商专题/variants/v1-高节奏实证风/output/01-v1-高节奏实证风.mp4",
      "covers": {
        "douyin": "runs/20261124-1400-意图电商专题/variants/v1-高节奏实证风/covers/01-v1-douyin.png",
        "shipinhao": "runs/20261124-1400-意图电商专题/variants/v1-高节奏实证风/covers/01-v1-shipinhao.png",
        "xhs": "runs/20261124-1400-意图电商专题/variants/v1-高节奏实证风/covers/01-v1-xhs.png"
      },
      "publish_json": "runs/20261124-1400-意图电商专题/variants/v1-高节奏实证风/publish/publish.json"
    }
  ],
  "delivery_dir": "runs/20261124-1400-意图电商专题/delivery",
  "delivery_index": "runs/20261124-1400-意图电商专题/delivery/INDEX.md",
  "cross_audit_passed": true,
  "notes": "已完成母素材确认、1母片+3延伸子片制作、目标平台封面与文案过审，交付手动发布"
}
```

> `gates` 取值约定：`rough_cut_approved` 为 `true` / `false` / `"skipped_processed"`；`master_approved` 为 `true` / `false` / `"skipped_auto_run"`；`pending_gate` 为 `null` 或 `"gate_0_input_state"` / `"gate_1_rough_cut"` / `"gate_2_master_plan"` / `"visual_review"`。

### 2. `master-assets/manifest.json`（母素材清单）

```json
{
  "confirmed_at": "2026-11-24T14:25:00+08:00",
  "input_processed": false,
  "source_video": "runs/20261124-1400-意图电商专题/raw/interview-raw.mp4",
  "has_original_bgm": true,
  "source_topics": ["topic-01-买家问AI", "topic-03-商品页改写"],
  "preprocess_applied": [
    "00:12-00:18 左上角白板打马赛克（已核验无漏帧）",
    "合并 topic-01 与 topic-03 并重算对齐逐字稿时间戳"
  ],
  "clips": [
    {
      "id": "clip-01",
      "path": "runs/20261124-1400-意图电商专题/master-assets/clips/clip-01-买家问AI.mp4",
      "vocals_track": "runs/20261124-1400-意图电商专题/master-assets/clips/clip-01-买家问AI-vocals.wav",
      "duration_sec": 62.4,
      "aligned_transcript": "runs/20261124-1400-意图电商专题/master-assets/clips/clip-01-transcript.json"
    }
  ],
  "merged_clip": "runs/20261124-1400-意图电商专题/master-assets/clips/clip-merged-意图电商专题.mp4",
  "supplied_assets": [
    {
      "original_name": "产品 演示图 (终版).png",
      "normalized_path": "runs/20261124-1400-意图电商专题/master-assets/supplied/product-demo-final.png"
    }
  ]
}
```

### 3. `master/script/master-plan.json`（3 条子片延伸规划表）

```json
{
  "master_duration_sec": 135.0,
  "split_strategy": "long_split_3_angles",
  "target_platforms": ["douyin", "xhs", "shipinhao"],
  "variants": [
    {
      "id": "v1",
      "prefix": "01-v1",
      "style_slug": "高节奏实证风",
      "source_clips": ["runs/20261124-1400-意图电商专题/master-assets/clips/clip-01-买家问AI.mp4"],
      "angle": "前3秒抛反差结果，用真实搜索对比画面实证意图匹配",
      "visual_style": "高频跳切 + 弹窗关键词 + 实拍/官图B-roll穿插",
      "bgm_mood": "轻快脉冲节奏",
      "supplement_assets_plan": ["官方案例截图", "实拍购物场景空镜", "过渡音效"],
      "cover_spec": "variant_custom",
      "brand_slogan_mode": "chenyi_default"
    }
  ]
}
```

### 4. `delivery/0N-*/copy.md` 标准交付模板（仅输出目标平台块）

```markdown
# 00-master · 意图电商专题（人工上传可直接复制）

- 成片：`runs/<目录>/delivery/00-master/00-master-<话题短名>.mp4`
- 审核结论：全平台硬门禁通过（见 `runs/<目录>/master/publish/publish.json`）

## 抖音（douyin）
- 封面图：`runs/<目录>/delivery/00-master/00-master-douyin.png`（1080×1920）
- 封面标题（两行）：第一行 / 第二行
- 表单标题（≤30字）：...
- 视频描述：...
- 三层标签候选：赛道（...）｜垂直（...）｜精准（...）
- 本条发布组合（3-5个，整行复制）：`#词1 #词2 #词3 #词4 #词5`

## 小红书（xhs）
- 封面图：`runs/<目录>/delivery/00-master/00-master-xhs.png`（1080×1440）
- 封面标题（两行）：第一行 / 第二行
- 笔记标题（≤18字，上限20字）：...
- 视频描述：...
- 三层标签候选：赛道（...）｜垂直（...）｜精准（...）
- 本条发布组合（3-8个，整行复制）：`#词1 #词2 #词3 #词4 #词5`

## 视频号（shipinhao）
- 封面图：`runs/<目录>/delivery/00-master/00-master-shipinhao.png`（1080×1920）
- 封面标题（仅封面图用，勿填短标题框）：第一行 / 第二行
- 短标题（6-16字，无空格无禁用标点）：`...`
- 视频描述：...
- 三层标签候选：赛道（...）｜垂直（...）｜精准（...）
- 本条发布组合（整行复制）：`#词1 #词2 #词3 #词4`
```
