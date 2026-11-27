# 母素材确立 → 强制固定 1 完整母片 + 4 风格子片矩阵流程规范（入口 E）

本文件定义本工作区 **入口 E（单组输入 → 确立母素材 → 强制固定 1 条完整特效母片 + 4 条基于当前母片延伸的差异风格子片，不保留旧 3 子片分支）** 的完整作业标准、人工确认闸门、全链路路径与防传混命名规范以及统一交付包结构。

所有路径均相对工作区根目录，严禁在任何文件或 JSON 中写死本机绝对路径；运行命令前先在当前 shell 执行环境脚本（**推荐先在根目录 `. .agents/skills/short-video-pipeline/scripts/env.sh` 再 `cd` 进目标目录**；若在深层目录直接 source：`master/film/` 为 4 层 `. ../../../../.agents/skills/short-video-pipeline/scripts/env.sh`，`variants/vN-<风格>/film/` 为 5 层 `. ../../../../../.agents/skills/short-video-pipeline/scripts/env.sh`）。source 后在任意深层目录统一直接调用 `openfilm`、`"$SVP_REA_VIDEO"`（自动适配 Unix `bin/rea-video` 与 Windows `Scripts/rea-video.exe`）与 `"$SVP_PYTHON" "$SVP_ROOT/.agents/skills/short-video-pipeline/scripts/fetch_asset.py"`，切勿硬写 `../../../`。

---

## 一、核心概念与总产出

本流程严格区分以下五个层级，绝不混用：

| 概念 | 归档位置 | 精确定义 |
|---|---|---|
| **原始输入** | `raw/` | 用户输入的「原片 + 配套素材」，分为「已处理」与「未处理」两种初始状态。原片只读不动（工作区外源文件只读复制进来，绝不移动或删除用户原文件）。 |
| **粗剪与预处理** | `rough-cut/` | 仅当输入为「未处理」时执行：先按视频中的**话题分段切割**，同步**去除口气词/废话/冗余停顿**；完成后强制停下汇报用户（**闸门 1**），按用户指示确认通过或追加预处理（如指定时段/区域**打马赛克**、删改/合并段、裁切/降噪）。 |
| **母素材（Master Assets）** | `master-assets/` | 「已处理输入」直通，或经粗剪与用户确认预处理完成后的**最终干净原片切片（含按需人声分轨）+ 配套素材包**。它是下游 1 母片 + 4 子片的共同干净上游源，从源头避免母片烧录特效/花字/配乐污染下游子片换风格。 |
| **母片（Master）** | `master/` | 基于「母素材」+ Agent 按需补充素材，按工作区既有规范制作出的**完整精剪加特效成片**，自带**母片专属的目标平台封面 + 目标平台文案**。 |
| **4 条延伸子片（Variants）** | `variants/v1..v4/` | 基于「母素材」与当期母片及工作区既有规范，向外强制固定延伸出的 **4 条风格各不相同的精剪特效成片（`v1–v4`）**；每条子片根据自身实际情况**独立补充素材**，并各自拥有**目标平台封面 + 目标平台文案**。 |

**单次运行标准总产出（强制固定规模，不保留 3 子片分支）**：
- **默认全三平台（`M = 3`）**：**5 条精剪成片（1 母片 + 4 延伸子片）+ 15 张定制封面（5 × 3）+ 15 套过审三平台文案（5 × 3）+ 规范化的 `delivery/` 统一交付包**；
- **指定部分平台 / 免封面弹性**：若用户附加「只发抖音」「不发小红书」等（`M < 3`），则按实际 `target_platforms` 产出 **`5 × M` 张封面 + `5 × M` 套文案**；若显式附加「不做封面」「免封面」，则跳过封面生成与封面校验，在 `run.json` 记 `covers_enabled: false`。
- **交付模式**：默认审核通过后停下交付 `delivery/` 给用户手动发布（即使免封面，因 5 片矩阵通常分发至多账号或错峰排期，仍默认手动交付；仅当用户显式要求 CreatorHub 自动发布并确认账号分配与错峰排期后，才由主 Agent 逐条串行调用 CreatorHub，严禁 5 片并发抢跑同一账号）。

---

## 二、全链路路径与防上传传混命名规范（硬规定）

入口 E 产物数量大，必须从建目录到收尾全链路执行路径与命名规范，确保人工上传 5 条视频、15 张封面、15 套文案时零混淆、零工作区外残留。

### 1. 标准目录树（相对工作区根目录）

```text
runs/<YYYYMMDD-HHMM>-<话题短名>/
├── run.json                                        总控索引（entry: "E"、输入态、两道闸门状态、5片与交付索引）
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
│   │   └── master-plan.json                        基于当期母片延伸的 4 条差异风格子片总规划书
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
├── variants/                                       【4 条延伸子片】目录物理隔离，天然支持 4 子代理并行
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
│   ├── v3-<风格短名>/                               编号前缀 03-v3-*（内部结构与 v1 完全同构）
│   └── v4-<风格短名>/                               编号前缀 04-v4-*（内部结构与 v1 完全同构）
├── delivery/                                       【统一交付包】面向人工上传的一站式出口
│   ├── INDEX.md                                    一页式总交付表（母素材摘要 + 5 成片/15 封面路径 + 审核状态）
│   ├── 00-master/                                  00-master-<话题短名>.mp4 + 3 张封面 PNG + copy.md
│   ├── 01-v1-<风格短名>/                            01-v1-<风格短名>.mp4 + 3 张封面 PNG + copy.md
│   ├── 02-v2-<风格短名>/                            02-v2-<风格短名>.mp4 + 3 张封面 PNG + copy.md
│   ├── 03-v3-<风格短名>/                            03-v3-<风格短名>.mp4 + 3 张封面 PNG + copy.md
│   └── 04-v4-<风格短名>/                            04-v4-<风格短名>.mp4 + 3 张封面 PNG + copy.md
└── tmp/                                            临时中间文件，收尾时必须删除
```

用不到的目录不建（例如输入已处理跳过粗剪时不建 `rough-cut/`）。不在运行目录根上随意散落其他文件。

### 2. 文件名与路径硬规范

1. **字符白名单**：运行目录名、子目录名及全部自生成文件名仅允许**汉字、英文字母、数字、连字符 `-`、下划线 `_` 与扩展名点号 `.`**；禁止包含空格、全角标点、斜杠、问号、星号与 Emoji。用户提供的原始素材如含空格或怪异符号，原样登记于 `raw/`，复制到 `master-assets/supplied/` 时自动转为合规短名并在 `manifest.json` 记录映射关系。
2. **防上传传混编号前缀**：
   - 母片统一使用 `00-master-` 前缀；
   - 四条延伸子片按序统一使用 `01-v1-`、`02-v2-`、`03-v3-`、`04-v4-` 前缀；
   - 三平台封面后缀固定为 `-douyin.png`、`-shipinhao.png`、`-xhs.png`；
   - 粗剪话题切片固定为 `topic-01-<话题短名>.mp4`、`topic-02-...`。
3. **相对路径铁律**：所有 JSON（`run.json`、`manifest.json`、`topics.json`、`master-plan.json`、`credits.json`、`cover-spec.json`、`publish.json`）与 Markdown（`delivery/INDEX.md`、`copy.md`）中的路径**一律写相对工作区根目录的路径**（如 `runs/20261124-1400-意图电商/master/output/00-master-意图电商.mp4`），严禁出现本机绝对路径或 `~/`。
4. **`delivery/` 零浪费归集与防陈旧铁律**：
   - 往 `delivery/00-master/`、`delivery/01-v1-*/`..`delivery/04-v4-*/` 等交付目录汇总成片与封面时，跨平台降级链为：先删旧目标 → 同文件系统优先硬链接（`ln`，Linux/macOS 通用）→ macOS APFS 硬链接受限时用写时复制（`cp -c`）→ 其余降级普通复制（`cp`），避免无谓倍增磁盘占用且确保用户在 Finder 或浏览器上传框里打开单个交付目录即可直接拖拽。
   - **返工强制整包重建铁律（防旧 inode / 副本陈旧大坑）**：OpenFilm 渲染、Playwright/PIL 重出图或 `ffmpeg` 输出往往通过替换生成新 inode；若已有 `delivery/`，后续任何一片（视频、封面或文案）发生返工修改后，**必须先整包清空重建 `delivery/`（如 `rm -rf runs/<目录>/delivery` 后全量重新链接成片/封面并重新生成 `copy.md` 与 `INDEX.md`）**，并核验 `delivery/` 内每个成片/封面与源目录产物的文件大小及哈希（或同 inode）100% 一致，绝不留陈旧文件！
   - **工作母版 GPU 快解转码与零重复拷贝约定**：若原始口播片高于 `1440p`（如 4K `3840×2160`）或关键帧间隔 `> 0.5s`，确立 `master-assets/clips/` 时优先调用 NVIDIA 显卡一次性转出 **`1440p + 8帧短关键帧` 快解工作母片**（`ffmpeg -hwaccel cuda -i <源片> -vf "scale=-2:1440" -c:v h264_nvenc -preset p5 -cq 18 -g 8 -c:a copy <master-clip.mp4>`；无 N 卡环境降级 `-c:v libx264 -preset superfast -crf 16 -g 8`），只需数秒转码 1 次，即可让下游 `master` + `v1/v2/v3/v4` 五片跳帧解码提速并全部免除 `.film/cache/seek/` 重复预转缓存；已满足 `≤1440p` 且短关键帧（`≤0.5s`）的源片从 `raw/` 到 `master-assets/clips/`，以及从 `master-assets/clips/` 到各片 `film/assets/` 整段复用时，同文件系统优先 `ln` 或 `cp -c`，严禁对硬链接指向的上游只读文件执行原地覆写（`ffmpeg` 等工具输出必须写新文件名）。
5. **工作区外零残留收口**：Agent 自带工具、浏览器下载或生图工具产出到工作区外的文件，必须立即移入本次运行目录对应的规范子目录，外部不留副本；用户原本放在工作区外的原始输入文件则只读复制进 `raw/`，绝不移动或删除用户原文件；整单到达终态收尾前清空 `tmp/`。

---

## 三、端到端执行步骤（E0 → E6）与暂停/续跑协议

### 暂停状态机与用户回复续跑协议（贯穿 E0 / E1 / E3 / 人工目检）

入口 E 涉及多轮人机确认，必须严格执行以下状态机，避免续跑时重复建目录或污染索引：

- **暂停落盘规则**：每次停下等待用户决定（E0 判定输入态、E1 闸门 1 粗剪/预处理确认、E3 闸门 2 母片与 4 子片方案确认、或无看图能力等待人工目检）时：
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
4. **原片 BGM / 底噪体检、人声分轨与广播级人声前置母带（防叠音与砖墙削波）**：
   - 无论输入「已处理」还是「未处理」，均检查原片音轨是否自带背景音乐（BGM）或明显环境底噪（已处理口播片常混有原 BGM）；
   - 执行 `"$SVP_REA_VIDEO"` 拆解至 `raw/rea-out/`，提取完整口播逐字稿与精确时间戳（若原片自带 BGM 同步保留干净人声轨 `stems/vocals.wav`）；
   - **广播级人声前置润色必做（`prepare-voice`）**：确立母素材时，对每个确认切片（或 `*-vocals.wav`）运行 `"$SVP_PYTHON" "$SVP_ROOT/.agents/skills/short-video-pipeline/scripts/qc_video.py" prepare-voice --in <源切片或vocals.wav> --out master-assets/clips/<切片名>-voice-treated.m4a`，产出**与源片等长零时间偏移**的压缩润色人声母带，记入 `master-assets/manifest.json` 的 `vocals_treated_track`（若原片带 BGM 同时记 `has_original_bgm: true`）。下游母片与 4 条子片的 `<section id="voice-track">` 一律引用该 `*-voice-treated.m4a`（画面 `<video>` 设 `volume="0"`），彻底杜绝双 BGM 叠音与渲染时 `-14 LUFS` 砖墙削波！
5. **判定「已处理 / 未处理」（注意：跳过粗剪闸门 ≠ 跳过成片内 EDL 精剪与黄金冷开！）**：
   - 用户明确说了「已处理 / 已粗剪 / 直接当母素材」，或输入位于工作区 `素材投递区/已粗剪/` 下且用户未另行要求粗剪 → `gates.input_state_confirmed = true`、`gates.rough_cut_approved = "skipped_processed"`，跳过步骤 E1 人工闸门：若源片 `>1440p` 或关键帧间隔 `>0.5s`，用显卡一次性转出 `1440p + -g 8` 快解母片放入 `master-assets/clips/`，否则按零重复拷贝原则归档原片切片、生成 `*-voice-treated.m4a` 并写 `manifest.json`。**关键红线：`master-assets/clips/` 保持完整不剪碎是为了统一时间码基准，但下游 `00-master` 与 `v1..v4` 各自制作时，仍必须在各自 `storyboard.json` 中用 `time_slices` 切净片头采访者搭话、推眼镜冷场与口头禅，并设计 `H1–H6` 黄金 3 秒冷开，严禁把前 7 秒冷场原封不动端进成片！**；
   - 用户明确说了「未处理 / 原片 / 先粗剪」，或输入位于工作区 `素材投递区/未处理原片/` 下且用户未声明已处理 → `gates.input_state_confirmed = true`，进入步骤 E1；
   - 用户未明确说明处理状态且输入不在 `素材投递区/已粗剪/` 或 `素材投递区/未处理原片/` 中 → Agent 先结合 `ffprobe` 与轻量试听/静音检测初步判断，将 `run.json` 置 `status: "waiting_approval"`、`gates.pending_gate: "gate_0_input_state"`，**停下用一句话向用户确认是已处理还是未处理**，绝不擅自跳过粗剪。

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
   - 只有获得用户明确「通过」指令后，才将最终确认的干净原片切片/合并片（若 `>1440p` 或 `GOP > 0.5s` 则统一以 `h264_nvenc -vf "scale=-2:1440" -preset p5 -cq 18 -g 8` 输出快解工作母片，及同步裁切对齐后的干净人声轨 `*-vocals.wav`，如有）放入 `master-assets/clips/`，用户配套素材规范化命名后放入 `master-assets/supplied/`；
   - **时间轴重算铁律**：凡经过删句、重切或合并，**必须按最终 `master-assets/clips/` 的实际成片重新映射或重跑轻量 ASR 校准逐字稿时间戳**（严禁直接沿用原片旧时间戳导致下游字幕与花字错位）；
   - 写入完整的 `master-assets/manifest.json`（记录 `source_topics`、确认切片与合并片路径、`aligned_transcript`、`has_original_bgm`、`vocals_track`、`preprocess_applied` 与 `supplied_assets` 原名→合规名映射），同步更新 `run.json`（`gates.rough_cut_approved = true`、`gates.pending_gate = null`）。

### 步骤 E2：基于母素材制作完整母片（`master/`）

1. **母片默认剪辑风格与视觉基调（默认对应 [editing-styles.md](editing-styles.md) `S01` 商业旗舰深度叙事，用户指定时可换 `S01–S10`）**：
   - **视觉色板与调色 LUT（墨黑铜青 · `master-editorial.cube`）**：主标题配 `Noto Serif SC` + `Noto Sans SC`，底色深墨 `#0D1920` / `#15262F`、主字暖象牙 `#FFF8E6`、次字灰青 `#93AAB2`、主强调铜青 `#2FB8A8` / `#8BE3D6`、对比暖铜 `#D08346`、重点金标 `#FFC21A`；拷入 `.agents/skills/short-video-pipeline/assets/luts/master-editorial.cube` 至 `master/film/looks/`，所有出镜 `<video>` 挂 `--of-lut: url(looks/master-editorial.cube)` 与自然护镜美颜。
   - **精剪、去框化 Boxless 特效与两段式混音**：对照 [editing-styles.md](editing-styles.md) 与 [editing-vfx.md](editing-vfx.md)，先做 `D1–D5` 精剪与 `H1–H6` 黄金 3 秒冷开（切净开头搭话冷场，非连续切点必用 `JL3` B-roll 覆盖或 `TR1–TR6` 转场遮切，严禁句中假跳切）；严守 **Boxless 去框化四定律**（禁仪表盘套娃外框、禁无数字伪进度条、禁空黑框等字、禁字幕复读横幅、禁固定高 `space-between` 漏块塌陷、禁廉价 Emoji 贴纸）；`--of-cutout: 1` 必垫同源虚化视频底且 `width ≥ 1080px`（`span_v > 0.42` 大头原片禁做 `PF4` 人后字）；字幕采用 **`SUB1` 杂志双字重无框排印字幕**（`46px`，`top: 1412px`，**严禁 `.pill` 半透明胶囊框**）；配乐音效经 `normalize-sfx` 与 `build-bgm-bed`（含 1–2 处金句 `Silence Drop` 抽空留白）混出 `bgm-bed.m4a`，确保 `-14 LUFS`、`LRA ≥ 4.0 LU`。
   - **完整收尾硬规则（母片与 4 条子片均必守）**：① **口播语义闭环**（末句须是完整定论句，加 `30–50ms` 微淡出，严禁截断在转折/引子半句上）；② **视觉收尾落版**（`O1–O4` 稳落 `y≤1540px` 且停留可读 ≥ 1.5 秒）；③ **听觉与尾韵缓冲**（末句后留 `0.6–1.2s` 尾韵配合 BGM 自然淡出，片尾最后 `0.35s` 禁 `> -25 LUFS` 截断人声）。
2. **脚本分镜与补素材**：
   - 基于 `master-assets/manifest.json` 判定 `content_archetype`、测定 `speaker_framing`（含 `span_v`）并锁定 `subtitles.html`，编写 `master/script/storyboard.json`（含 `editing_style`、`color_lut`、`cold_open`、`time_slices`、`silence_drops` 及零复读 `cue_sync_map`：单锚点词 `≤5` 字且与底部字幕重合 `<50%`）；
   - 按 [sourcing.md](sourcing.md) 优先走本地 Pixabay 竖屏稳像源补充运动实拍视频 B-roll 与真实界面/无框动效素材（**严禁盲拿 API 第 1 条直塞 `film/assets/`！必须先下载 `2–4` 个候选至 `master/materials/`、看图检查 `candidate-sheet-*.jpg` 通过六维制作要求与五项技术硬检［`YAVG≥18`、`scdet<16`、`hf_jerk≤2.40px`、台词语义与地域影调吻合、`64-bit dHash` 唯一］后，用 `fetch_asset.py register --shot <镜号> --fit-reason "<具体实看说明>"` 签收入 `master/film/assets/credits.json`**），音频必过 `probe-audio` 与 `normalize-sfx`。
3. **母片剪辑特效、自动闪避床构建与出片自检**：
   - 写好 `film.html` 人声轨（引用 `*-voice-treated.m4a`）后，渲染前先跑 `"$SVP_PYTHON" "$SVP_ROOT/.agents/skills/short-video-pipeline/scripts/qc_video.py" build-bgm-bed --film-dir . --bgm assets/<bgm> --out assets/bgm-bed.m4a --drops "<t1:t2>"`；
   - 渲染命令：`OPENFILM_NO_BROWSER=1 openfilm render --fps 30 --loudness=-14 --workers 6 --out ../output/00-master-<话题短名>.mp4`；
   - 逐镜 `openfilm look` + 全片 `openfilm look --full` & `ffprobe` + 必跑 `"$SVP_PYTHON" "$SVP_ROOT/.agents/skills/short-video-pipeline/scripts/qc_video.py" audit-render --video ../output/00-master-<话题短名>.mp4 --film-dir . --out-dir ../output/check`，**亲自打开 `safezone-grid.png`、`safezone-tail.png`、`safezone-cuts.png`、`safezone-broll.png`、`safezone-pip.png`（如有）及 `safezone-cutouts.png`（如有）目检**，零 `hard_failures` 后记录写入 `master/output/check/`。
4. **母片目标平台诚实文案 + 双轨封面 + 单条审核**：
   - 按 [copywriting.md](copywriting.md) 依 `content_archetype` 诚实钩子契约写出母片三平台四项文案（禁伪造不存在的清单/破局方案，禁生造歧义缩略词），落盘 `master/publish/publish.json`；
   - 若 `covers_enabled` 为 `true`：按 [cover-design.md](cover-design.md) 出图（「意图电商」系列走 Track A；其他主题走 **Track B `C1` 深墨左切光杂志人物拓扑**：先生成 20–30 帧 `materials/covers/contact-sheet.jpg` 五维选帧，主标题 `≥104px`/`≥100px`，零小胶囊标签堆砌），落盘 `master/covers/00-master-<平台>.png` 与 `cover-spec.json`；
   - 按 [publish-audit.md](publish-audit.md) 完成母片单条全目标平台审核（含 `--publish-json` 复跑 `audit-render`）并写回 `audit`。

### 步骤 E3：基于当期母片与既有规范 → 延伸规划 4 条子片（+ 闸门 2）

1. **三档自适应内容切分策略与首尾双重护栏（开篇独立性 + 结尾闭环）**：
   - **超长深访（母片 `> 120` 秒，且具备 `≥ 4` 个独立论点）**：4 条子片优先从「母素材 + 母片主线」中拆出 **4 个互不重复的核心看点/独立金句切片**（每条 `25–60` 秒），再各自做正交风格包装；
   - **中长口播（母片 `75–120` 秒，通常含 `2–3` 个自然论点）**：采用 **「局部独立切片 + `v4` 跨段抽取旧误区 vs 真相定论重组」混合制**（例如 `v1/v2/v3` 各聚焦一段局部犀利看点，`v4` 横跨首尾抽取“多数人以为的旧共识靶子 vs 真实经营真相定论”做双视角交锋精粹，**严禁为硬凑 4 段将单一完整论点拦腰劈成残缺半句！**）；
   - **短精华片（母片 `≤ 75` 秒）**：4 条子片围绕同一核心主题，从 **4 种完全正交的 `H1–H6` 开头钩子、叙事视角、节奏结构与视觉包装** 重构 4 条高度区分的成片；
   - 用户启动时如显式指定「拆四条」或「同内容四风格」，则优先遵照切分方式指令（但子片总数始终强制固定为 4 条）；
   - **开篇独立性护栏（严禁残句冷开）**：拆出的每条子片首句前 `0.8s` 内**严禁残留依赖前文的废语或悬空指代**（如「像我刚刚讲的」「反而是」「所以说」「那这个」）；若原段首句缺独立钩子，须精确后移起点裁净废语，或前置 `2–3s` 结论金句冷开，并在 `master-plan.json` 写明 `opening_hook`；
   - **切点语义与声学闭环硬规（严禁无结尾半句截断或切入下句起音）**：规划每条子片（尤其是倒叙或分段切出的切片）的 `time_slices` 尾点时，**必须对照 `aligned_transcript` 逐字确认末段最后一句是完整句意与明确结论落点，严禁把切点卡在转折词、铺垫引子或未说完的破折号半句上**（例如「但是这个意图电商——」「比如……」「接下来我们看……」），并核对尾点不切入下一句起音（末句语音加 `30–50ms` 微淡出）。若某段自然尾点刚好是引子句而非结论句，须采用以下任一方式收口：① 将尾点前收至上一句完整定论，或向后延伸至该观点完整说完（为保证每条子片独立成篇且收尾完整，允许相邻子片在边界处保留 1 句极短核心结论重叠，**独立完片感高于机械零重叠**）；② 末段显式拼入一句回扣核心定论的完整口播句并配独立收尾落版（`outro`）。每条子片均须在 `master-plan.json` 中显式写出 `opening_hook`（开篇首句与钩子设计）、`ending_sentence`（收尾完整末句原文）与 `outro_design`（收尾画面、停留时长与 BGM 淡出方式），供规划审查。
2. **五槽位正交剪辑范式、5 套独立调色 LUT、零胶囊等距字幕阶梯与 `C1–C5` 封面拓扑（严禁“同一布局换 5 套颜色”！）**：
   - **灰度盲测反克隆铁律**：将 `00-master`、`01-v1`、`02-v2`、`03-v3`、`04-v4` 全部去色转为黑白灰后，任意 3 秒内必须能仅凭**画幅架构、人物出镜形态、零胶囊字幕排版体制、剪辑蒙太奇语法**一眼区分出 5 种截然不同的视频类型！完整风格库与选型矩阵见 [editing-styles.md](editing-styles.md)（商业访谈默认推荐 **`S01 + S02 + S03 + S04 + S08`** 五槽组合）：
     - **`00-master`（默认 `S01` 商业旗舰深度叙事 · `master-editorial.cube` · 封面 `C1` 深墨左切光杂志风）**：
       - **剪辑与人物**：`H1/H2` 冷开 + 三幕章节推进，全屏锁眼缓推口播（`55%`）↔ 紧凑 `4:3`/`16:10` 开放式侧分栏（`L2`，`v2≥75%`）+ 无框排版锚点与 `DV` 数据动效；
       - **字幕体制（`SUB1`）**：**严禁 `.pill` 半透明胶囊底盒！**采用左侧铜青标尺 + 无框黑宋混排双字重字幕（`46px`，**`top: 1412px`**）。
     - **`v1`（默认 `S02` 高冲网感快剪冲击流 · `v1-crisp-contrast.cube` · 封面 `C2` 高对比双截战报风）**：
       - **剪辑与人物（禁用顶部矩形讲座 PiP！）**：`H1` 前置最狠暴论冷开 + 全屏句界三级阶梯跳切（严禁句中假跳切！非连续删句切点用 `JL3` B-roll 遮切，ASL `2.0–3.2s`）+ `KT1/KT4` 巨字重锤砸屏 / `PF6` 3D 视窗 + `TR5/TR9` 甩切/RGB 冲击转场，前 3 秒必配重音冲击音效；
       - **字幕体制（`SUB2`）**：无底框 `9px` 重黑边弹簧跳字（`52px`，关键词 `60px` 弹性上跳，**`top: 1320px`**）。
     - **`v2`（默认 `S03` 全画幅动态白板图解流 · `v2-warm-paper.cube` · 封面 `C3` 暖白报纸社论胶片框风）**：
       - **剪辑与人物（禁用 `width > 320px` 半屏矩形 PiP 与一切霓虹/故障！）**：`H4/H2` 痛点切入 + 整块 `1080×1920` 释放为可平移推拉（`C6` Camera Pan & Zoom）的 `#F2EFE9` 无框暖纸研究画布（`70%+` 图解主导，说话人仅首尾出镜或角落 `≤180px` 圆形讲者微章 `L5`），配 `DV2/DV3` 面积挤压/趋势面与纸张马克笔拟音；
       - **字幕体制（`SUB3`）**：亮底深墨无框印刷字幕 + 关键词底部暖橙/翡翠荧光笔实时手绘扫过（`46px`，**`top: 1458px`**）。
     - **`v3`（默认 `S04` 宽银幕电影独白留白流 · `v3-obsidian-film.cube` · 封面 `C4` 黑曜石宽银幕剧照风）**：
       - **剪辑与人物（禁用一切圆角信息盒、SVG 图表、`//` 科技胶囊、贴纸与轻快/气泡音效！）**：`H6` 时空坐标呼吸冷开 + 同源虚化底 `--of-cutout: 1` 浅景深光学特写 + `L4/L6` `2.39:1` 宽银幕胶片三联画并置 + `KT3` 光学散焦收拢显影金句 + 大提琴低频氛围铺底配重句 `Silence Drop`，终帧真溶黑 `#000000`；
       - **字幕体制（`SUB4`）**：影院级 `+2.5px` 宽字距暖象牙细衬线纯字（`42px`，**`top: 1504px`**）。
     - **`v4`（默认 `S08` 双视角交锋/认知证伪流 · `tech-keynote.cube` · 封面 `C5` 头版倒置·误区划除交锋画报）**：
       - **剪辑与人物（禁用讲座大框与 `v1` 重黑边弹簧字；原片含明确实操步骤时可弹性换 `S10` 实操笔记流，含完整故事脉络可换 `S07` 时间线故事流，但仍独占第 5 槽 LUT）**：`H5` 靶子旧共识亮出（`0–4s`）→ `DV4` 手绘珊瑚红双笔疾速划除并配低频打断音 → `L7` 冷暖双域无框斜切/上下交锋分屏拆解真相 + `L1` 近景直视定论（ASL `2.6–4.2s`）；
       - **字幕体制（`SUB5` / 切 `S10` 时用 `SUB6`）**：极简几何无框等宽混排 + 电光青 `#38BDF8` `2px` 刻度下划线（`46px`，**`top: 1366px`**）——**五槽字幕 `top` 精准形成 `1320 / 1366 / 1412 / 1458 / 1504px` 等距阶梯（相邻互差 `46px ≥ 40px`、总跨度 `184px ≥ 160px`）！**
   - 将 4 条子片的 `editing_style`（`S01–S10`）、`color_lut`、`cold_open`（`H1–H6`）、精剪 `time_slices`、`silence_drops`、`layout_paradigm`、`speaker_mode`、`subtitle_system`（`SUB1–SUB6`）、`cover_topology`（`C2–C5`）与独立补素材清单完整写入 `master/script/master-plan.json`。
3. **【闸门 2】母片与 4 子片方案确认（默认开启，指令带「一路跑完」可跳过）**：
   - 若带「一路跑完」：`gates.master_approved = "skipped_auto_run"`，直接进入步骤 E4；
   - 否则更新 `run.json`（`status: "waiting_approval"`、`step: "E3"`、`gates.pending_gate: "gate_2_master_plan"`），停下向用户展示：① 母片成片、目标平台封面路径与文案摘要；② `master-plan.json` 中的 4 条延伸子片差异化规划表；
   - 待用户回复「OK 继续」（或调整某条风格/切分点）后复用原运行目录续跑，置 `gates.master_approved = true`、`gates.pending_gate = null`、`status: "running"`，启动步骤 E4，避免 4 条子片方向跑偏造成 4 倍返工。

### 步骤 E4：4 条延伸子片独立制作（支持 4 子代理真并行）

- 4 个目录 `variants/v1-<风格>/`、`variants/v2-<风格>/`、`variants/v3-<风格>/`、`variants/v4-<风格>/` 完全物理隔离，主 Agent 默认同时派发 **4 个子代理**分别负责一条子片（不具备派子代理能力时串行完成）。
- **子代理权限边界（与 [../SKILL.md](../SKILL.md) 保持一致）**：4 个子代理仅在各自专属目录 `variants/vN-<风格>/` 内拥有局部完整制作权（可写各自 `film/film.html`、独立渲染与初检、产出本子片封面/文案初稿及单条 `publish.json`），**严禁修改 `raw/`、`master-assets/`、`master/` 及另外三条子片目录，严禁调用任何发布操作或付费生成，严禁在运行目录外存放文件**。
- 每条子片均以 `master-assets/` 为干净底料（需要局部引用母片某段特效时可按需引用，但不直接把焊死旧花字与旧 BGM 的母片当唯一底轨；原片含 BGM 时统一使用 `vocals_track` 配新风格 BGM），完整执行：
  1. **各自按实际情况独立候选筛片、六维核验签收与音效归一化**：先测定 `speaker_framing` 并锁定本子片精剪 `time_slices` 后的 `scenes/subtitles.html` 精确时间戳，在各自 `script/storyboard.json` 写明零复读 `cue_sync_map`（单锚点 `≤5` 字且与字幕重合 `<50%`），按 [sourcing.md](sourcing.md) 优先走 Pixabay 竖屏稳像源将 `2–4` 个候选先下到本子片 `materials/`，**亲自看图检查 `candidate-sheet-*.jpg` 确认台词语义咬合、地域零穿帮、竖屏主体不被字幕压挡、影调契合本子片风格（如 `v3` 电影流禁高饱和亮片与 CG，`v4` 交锋流禁廉价卡通）且通过 `YAVG≥18`、`scdet<16`、`hf_jerk≤2.40px`、跨 5 片 `64-bit dHash > 10` 后，必须用 `fetch_asset.py register --shot <镜号> --fit-reason "<≥12字具体实看结论>"` 签收入本子片 `film/assets/credits.json`（严禁子代理盲拿 API 首条水片充数！）**，并对 `film/assets/` 短音效执行 `"$SVP_PYTHON" "$SVP_ROOT/.agents/skills/short-video-pipeline/scripts/qc_video.py" normalize-sfx film/assets`；
  2. **独立 OpenFilm 剪辑、构建 `bgm-bed.m4a` 与出片初检**：拷入本槽位对应 `.cube` LUT 至 `film/looks/`，挂齐 `--of-lut`、同源虚化光学抠像（`width≥1080px`）、Boxless 去框化特效与对应 `SUB2/SUB3/SUB4/SUB5(SUB6)` 零胶囊等距字幕，人声轨挂 `master-assets/clips/*-voice-treated.m4a`；写好 `film.html` 后先跑 `"$SVP_PYTHON" "$SVP_ROOT/.agents/skills/short-video-pipeline/scripts/qc_video.py" build-bgm-bed --film-dir . --bgm assets/<bgm> --out assets/bgm-bed.m4a --drops "<t1:t2>"` 生成自动闪避与抽空留白铺底床，再执行 `OPENFILM_NO_BROWSER=1 openfilm render --fps 30 --loudness=-14 --workers <N> --out ../output/0N-vN-<风格短名>.mp4`（单子片独立跑配 `--workers 6`；2 子片同跑各配 `--workers 4`；**4 子片全并行同时渲染时统一各配 `--workers 2`**，`4 × 2 = 8` 路刚好跑满 NVIDIA `h264_nvenc` 硬编上限；`<24GB` 内存机器自动降为 `2 + 2` 分两波各配 `--workers 4`），逐镜 `openfilm look` + 全片 `openfilm look --full` & `ffprobe` + 必跑 `"$SVP_PYTHON" "$SVP_ROOT/.agents/skills/short-video-pipeline/scripts/qc_video.py" audit-render --video ../output/0N-vN-<风格短名>.mp4 --film-dir . --out-dir ../output/check`，亲自打开 `safezone-grid/tail/cuts/broll/pip/cutouts.png` 目检零 `hard_failures`；
  3. **独立目标平台诚实文案**：按 [copywriting.md](copywriting.md) 紧贴本子片 `content_archetype` 与实际剪出的冷开首句、落点撰写四项文案（禁虚假破局清单承诺、禁生造歧义词、禁描述带秒数），落盘 `publish/publish.json`；
  4. **独立目标平台杂志封面（若 `covers_enabled` 为 `true`）**：按 [cover-design.md](cover-design.md)（非「意图电商」系列按各自 `C2/C3/C4/C5` 杂志拓扑：先共用或各自基于 20–30 帧 `contact-sheet.jpg` 五维选出互不撞脸神态帧，`C3` 暖白底禁贴裸抠像改用胶片相框实拍裁切，`C5` 采用头版倒置·误区划除交锋构图，主标题 `≥104px`/`≥100px`，零小胶囊标签堆砌），产出 `covers/0N-vN-<平台>.png` 与 `cover-spec.json`；
  5. **子片单条审核**：按 [publish-audit.md](publish-audit.md)（含 `--publish-json` 复跑 `audit-render`）完成本子片全目标平台审核并写回 `publish/publish.json` 的 `audit`。

### 步骤 E5：主 Agent 统一复核、跨 5 片矩阵门禁与路径收口

此步必须由**主 Agent 亲自串行执行**，不外包给子代理：
1. **逐片视觉与自动化质检复核**：亲自核验全部 **5** 份 `output/check/qc-report.json`（连同 `--publish-json` 复查全部零 `hard_failures`），**亲自打开全部 5 组 `safezone-grid.png`、`safezone-tail.png`、`safezone-cuts.png`、`safezone-broll.png`（如有）、`safezone-pip.png`（如有）及 `safezone-cutouts.png`（如有）核查四向安全区、Boxless 去框化视觉、同源虚化光学抠像、B-roll 无黑头/稳像/无地标穿帮、`speaker-pip` 五官完整、零复读音画同步与切点无穿帮**，并**亲自打开选片表 `contact-sheet.jpg` 与全部定制封面 PNG（默认 15 张，或 `5 × M` 张）目视复核**；
   - **无看图能力退路**：若当前 Agent 不具备看图能力，严禁伪造目检通过；须将各 `check.json` / `cover-spec.json` 视觉项记为 `"pending_human_visual_review"`、`run.json` 置 `status: "waiting_approval"`、`gates.pending_gate: "visual_review"`、`cross_audit_passed: false`（但仍须完成全部机械项审核并在下一步组装预览包列出全部待目检路径供用户肉眼签收）。
2. **跨 5 片矩阵反克隆与差异门禁（必跑 `qc_video.py audit-matrix`）**：执行 `"$SVP_PYTHON" "$SVP_ROOT/.agents/skills/short-video-pipeline/scripts/qc_video.py" audit-matrix --run-dir runs/<目录> --out runs/<目录>/master/output/check/matrix-qc.json` 确认零 `hard_failures`，并按 [publish-audit.md](publish-audit.md) 第五节逐项执行跨片审核（母素材与 `*-voice-treated.m4a` 就绪、5 片齐全且通过正交架构与 5 套零胶囊等距字幕指纹互斥、跨 5 片 B-roll `64-bit dHash` 零改名克隆、`C1–C5` 杂志封面拓扑与五维选帧过关、`content_archetype` 诚实文案防雷同及表单硬校验）；任一不通过即定向返工对应子片并复审；
3. **路径与命名收口检查**：核验所有 JSON/MD 无绝对路径、文件名全符合字符白名单、无工作区外残留文件、`tmp/` 已清空。

### 步骤 E6：组装 `delivery/` 统一交付包与归档收尾

1. 生成（或返工后**彻底重建**）`runs/<目录>/delivery/` 统一交付包：
   - 若 `delivery/` 已存在，**必须先整包清空重建**（`rm -rf runs/<目录>/delivery`），防止任一片返工重渲后硬链接仍指向旧 inode 或副本陈旧；
   - 建立 `00-master/`、`01-v1-<风格>/`、`02-v2-<风格>/`、`03-v3-<风格>/`、`04-v4-<风格>/` **五个**交付子目录；
   - 每个子目录放入对应防传混命名的成片（按 `ln` → macOS `cp -c` → `cp` 降级链归集）、全部目标平台封面 PNG（如启用封面），以及按下方模板生成的 `copy.md`；
   - **同步一致性校验**：核验 `delivery/` 内每个成片和封面文件均非空且与源目录（`master/`、`variants/vN-*/`）对应文件大小/哈希一致；
   - 生成 `delivery/INDEX.md` 一页式总交付表（汇总母素材摘要、目标平台、5 片成片路径/时长/风格、全部封面路径、审核结论与手动发布提醒）。
2. 终态归档：
   - 若全部审核（含视觉复核）通过：更新 `run.json`（`status: "made"`、`publish_mode: "manual_with_covers"` 或免封面时的 `"manual_delivery"`、`cross_audit_passed: true`、`finished_at` 填入当前带时区时间），删除 `tmp/`，向 `runs/topics-log.jsonl` 追加一行 JSONL 记录（含 `date`、`entry: "E"`、`topic`、`run_dir`、`target_platforms`、`publish_mode`、`delivery_dir`、`variant_count: 5`、`status: "made"`）；
   - 若因无看图能力停在 `waiting_approval`：暂不向 `topics-log.jsonl` 写终态，明确列出需用户目检的关键帧与封面 PNG 路径待确认。
3. 向用户汇报：母素材摘要、`delivery/` 总交付路径、`delivery/INDEX.md` 核心总览与可直接手动上传的 5 组交付清单。

---

## 四、关键索引 JSON 与交付模板示例

> 以下所有 JSON 与 Markdown 中的路径均严格遵循「相对工作区根目录」铁律。

### 1. `run.json`（入口 E 扩展结构）

```json
{
  "id": "20261124-1400-意图电商专题",
  "topic": "意图电商专题（母素材 + 1母片 + 4延伸风格子片）",
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
  "notes": "已完成母素材确认、1母片+4延伸子片制作、目标平台封面与文案过审，交付手动发布"
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
      "vocals_treated_track": "runs/20261124-1400-意图电商专题/master-assets/clips/clip-01-买家问AI-voice-treated.m4a",
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

### 3. `master/script/master-plan.json`（4 条子片延伸规划表）

```json
{
  "content_archetype": "actionable_method",
  "master_editing_style": "S01",
  "master_duration_sec": 108.0,
  "split_strategy": "hybrid_split_and_myth_clash_4_variants",
  "target_platforms": ["douyin", "xhs", "shipinhao"],
  "variants": [
    {
      "id": "v1",
      "prefix": "01-v1",
      "editing_style": "S02",
      "style_slug": "高冲痛点快剪",
      "color_lut": "v1-crisp-contrast.cube",
      "layout_paradigm": "fullscreen_jumpcut_kinetic",
      "speaker_mode": "fullscreen_step_zoom",
      "subtitle_system": "SUB2_top1320_no_pill",
      "cover_topology": "C2_split_contrast",
      "color_palette": {
        "bg": "#060B14",
        "bg_2": "#0B1628",
        "text": "#FFFFFF",
        "accent": "#00E5FF",
        "warn": "#FF6B35"
      },
      "source_clips": ["runs/20261124-1400-意图电商专题/master-assets/clips/clip-01-买家问AI.mp4"],
      "time_slices": [[54.2, 56.8], [7.2, 31.5], [34.0, 48.6]],
      "silence_drops": [[28.4, 29.1]],
      "cold_open": "H1 前置2.6s最狠结论金句冷开，切净原片前7.2s搭话冷场，删句切点用JL3实拍B-roll遮切",
      "angle": "前3秒抛反差结果，用真实搜索对比界面视窗实证意图匹配",
      "opening_hook": "前置2.6s结论金句冷开（裁净悬空代词，巨字锚点补全主语冲突）",
      "ending_sentence": "意图电商不是追着你推旧词，而是真正读懂你的上下文需求。",
      "outro_design": "O1定帧印章落版：末句完整落音加40ms微淡出后切出无框金句收束，停留可读1.8s并留0.8s尾韵配合bgm-bed自然淡出",
      "visual_style": "句界阶梯跳切 + Boxless无框巨字重锤 + PF6真实搜索界面3D视窗 + 实拍B-roll穿插",
      "bgm_mood": "电子脉冲自动闪避铺底床 + 金句前Silence Drop",
      "supplement_assets_plan": ["真实搜索界面截图", "实拍购物场景运动视频B-roll", "归一化Whoosh+SubHit音效"],
      "cover_spec": "track_b_C2",
      "brand_slogan_mode": "chenyi_default"
    },
    {
      "id": "v4",
      "prefix": "04-v4",
      "editing_style": "S08",
      "style_slug": "双域交锋证伪",
      "color_lut": "tech-keynote.cube",
      "layout_paradigm": "dual_zone_myth_clash_L7",
      "speaker_mode": "split_clash_and_closeup",
      "subtitle_system": "SUB5_top1366_no_pill",
      "cover_topology": "C5_top_heavy_myth_strike",
      "color_palette": {
        "bg": "#0B1117",
        "bg_2": "#16222E",
        "text": "#F4F7FA",
        "accent": "#38BDF8",
        "warn": "#FF4D3A"
      },
      "source_clips": ["runs/20261124-1400-意图电商专题/master-assets/clips/clip-01-买家问AI.mp4"],
      "time_slices": [[8.5, 19.2], [48.8, 62.0]],
      "silence_drops": [[56.2, 56.8]],
      "cold_open": "H5 先亮出卖家普遍死磕关键词出价的旧误区，1.6s处DV4珊瑚红双笔疾速划除并配低频打断音切入真相",
      "angle": "跨段抽取旧共识靶子vs意图匹配新真相，双色温交锋纠偏",
      "opening_hook": "靶子误区打碎冷开（旧经验vs新规则正面碰撞）",
      "ending_sentence": "谁先把商品语境写给AI看懂，谁才接得住下一代自然流量。",
      "outro_design": "O1真相定论无框巨字收束：停留可读1.8s并留0.8s尾韵自然淡出",
      "visual_style": "L7冷暖双域无框分屏 + DV4手绘双笔划除旧认知 + 稳像实拍B-roll",
      "bgm_mood": "前抑后扬紧凑脉冲铺底床 + 打断切点重音",
      "supplement_assets_plan": ["买家手机语音提问实拍B-roll", "仓库出货实拍B-roll", "归一化低频打断音效"],
      "cover_spec": "track_b_C5",
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
