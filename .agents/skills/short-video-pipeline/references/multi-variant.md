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
| **母素材（Master Assets）** | `master-assets/` | 「已处理输入」直通，或经粗剪与用户确认预处理完成后的**最终干净原片切片（含合规消音脱敏人声母带）+ 配套素材包**。它是下游 1 母片 + 4 子片的共同干净上游源，从源头统一完成平台敏感词「哔」声屏蔽与脱敏，并避免母片烧录特效/花字/配乐污染下游子片换风格。 |
| **母片（Master · 对应 `G0` 号组）** | `master/` | 对位 **`G0` · `跨境AI十亿增长局`**（宏观战略大盘与十亿增长格局）：基于「母素材」+ Agent 按需补充素材制作出的**完整竖版精剪加特效成片（统一固定 `1080×1920`，不制作横版）**，自带**人物头顶水平居中标题 + 印有 `跨境AI十亿增长局` IP 名的目标平台竖版封面 + 目标平台文案**。 |
| **4 条延伸子片（Variants · 对应 `G1–G4` 号组）** | `variants/v1..v4/` | 基于「母素材」与当期母片，按 **`01-v1 ↔ G1 时奕聊AI经营`、`02-v2 ↔ G2 辰奕AI经营实战`、`03-v3 ↔ G3 老郑AI经营实战`、`04-v4 ↔ G4 老郑AI经营论`** 四大账号 IP 人设与内容方向强制固定延伸出的 **4 条风格各异精剪成片**；每条子片**独立补充素材**，并各自拥有**印本槽精确账号 IP 名的目标平台封面 + 目标平台文案**。 |

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
│   │   ├── 00-master-douyin.png                    1080 × 1920（竖版 · 头顶居中标题）
│   │   ├── 00-master-xhs.png                       1242 × 1660（竖版 · 头顶居中标题）
│   │   ├── 00-master-shipinhao.png                 1080 × 1440（竖版 · 头顶居中标题）
│   │   └── cover-spec.json
│   └── publish/
│       └── publish.json                            母片三平台四项文案、三层标签、发布组合、封面路径与 audit
├── variants/                                       【4 条延伸子片 · 对位 G1-G4】目录物理隔离，天然支持 4 子代理并行
│   ├── v1-<风格短名>/                              对位 G1 · 时奕聊AI经营（默认 S02 / C2）
│   │   ├── script/storyboard.json
│   │   ├── materials/                              子片 1 独立补充素材原件；封面过程稿放 materials/covers/
│   │   ├── film/                                   子片 1 独立 OpenFilm 工程 + assets/ + credits.json
│   │   ├── output/
│   │   │   ├── 01-v1-<风格短名>.mp4                 防传混前缀 01-v1
│   │   │   └── check/
│   │   ├── covers/
│   │   │   ├── 01-v1-douyin.png                    1080 × 1920（竖版 · 头顶居中标题）
│   │   │   ├── 01-v1-xhs.png                       1242 × 1660（竖版 · 头顶居中标题）
│   │   │   ├── 01-v1-shipinhao.png                 1080 × 1440（竖版 · 头顶居中标题）
│   │   │   └── cover-spec.json
│   │   └── publish/publish.json
│   ├── v2-<风格短名>/                               编号前缀 02-v2-* · 对位 G2 · 辰奕AI经营实战（默认 S03或S10 / C3）
│   ├── v3-<风格短名>/                               编号前缀 03-v3-* · 对位 G3 · 老郑AI经营实战（默认 S08或S07 / C5）
│   └── v4-<风格短名>/                               编号前缀 04-v4-* · 对位 G4 · 老郑AI经营论（默认 S04 / C4）
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
3. **相对路径铁律**：所有 JSON（`run.json`、`manifest.json`、`topics.json`、`master-plan.json`、`credits.json`、`cover-spec.json`、`publish.json`）与 Markdown（`delivery/INDEX.md`、`copy.md`）中的路径**一律写相对工作区根目录的路径**（如 `runs/20261124-1400-AI经营提效/master/output/00-master-AI经营提效.mp4`），严禁出现本机绝对路径或 `~/`。
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
4. **原片 BGM / 底噪体检、平台政策合规「哔」声屏蔽与广播级人声前置母带（防违规限流、叠音与削波）**：
   - 无论输入「已处理」还是「未处理」，均检查原片音轨是否自带背景音乐（BGM）或明显环境底噪（已处理口播片常混有原 BGM）；
   - 执行 `"$SVP_REA_VIDEO"` 拆解至 `raw/rea-out/`，提取完整口播逐字稿与精确时间戳（若原片自带 BGM 同步保留干净人声轨 `stems/vocals.wav`）；
   - **平台政策合规敏感词全量扫描与「1000Hz 哔声 + 某X 字幕」脱敏（必做，按输入态精准卡位）**：
     - **当输入为「已处理」（跳过步骤 E1 直通母素材）时**：在确立 `master-assets/clips/` 后立即对逐字稿运行 `"$SVP_PYTHON" "$SVP_ROOT/.agents/skills/short-video-pipeline/scripts/qc_video.py" scan-compliance --transcript <逐字稿.json或.srt> --out master-assets/clips/<切片名>-compliance-bleeps.json` 筛出 5 类国内三平台风控词（① 国内跨平台名如 `抖音→某音`、`小红书→某红书`、`视频号→某频号`、`微信/公众号→某信/某公号`、`快手→某手`、`淘宝/拼多多/京东→某宝/某多多/某东` 等，正常保留亚马逊/独立站/领星/GPT/AI 等业务词；② 站外私域导流词；③ 广告法极限/保本暴利承诺词；④ 逃税/刷单/假货等灰黑产词；⑤ 诈骗/传销/死路/破产跑路等高危风控词），并对每个确认切片运行 `qc_video.py prepare-voice --in <源切片或vocals.wav> --out master-assets/clips/<切片名>-voice-treated.m4a --bleeps master-assets/clips/<切片名>-compliance-bleeps.json` 生成等长零偏移 `-18.0 dBFS` `1000Hz` 哔声润色母带（画面若含第三方平台水印/二维码同步打码或裁除）；
     - **当输入为「未处理原片」（需进入步骤 E1 粗剪与合并）时**：本步仅做原片拆解与 BGM 分轨预检，**留待步骤 `E1.5` 用户确认粗剪并完成 `master-assets/clips/` 最终时间轴校准后，再统一对定稿切片运行 `scan-compliance` 与 `prepare-voice --bleeps`**，确保哔声窗口与最终母素材时间轴 100% 严丝合缝！下游 `00-master` 与 `01-v1..04-v4` 的 `<section id="voice-track">` 一律引用该 `*-voice-treated.m4a`（画面 `<video>` 设 `volume="0"`），5 片字幕、花字、封面与文案同步采用脱敏词并在 `delivery/INDEX.md` 附明细。
5. **判定「已处理 / 未处理」（注意：跳过粗剪闸门 ≠ 跳过成片内 EDL 精剪与黄金冷开！）**：
   - 用户明确说了「已处理 / 已粗剪 / 直接当母素材」，或输入位于工作区 `素材投递区/已粗剪/` 下且用户未另行要求粗剪 → `gates.input_state_confirmed = true`、`gates.rough_cut_approved = "skipped_processed"`，跳过步骤 E1 人工闸门：若源片 `>1440p` 或关键帧间隔 `>0.5s`，用显卡一次性转出 `1440p + -g 8` 快解母片放入 `master-assets/clips/`，否则按零重复拷贝原则归档原片切片、生成 `*-voice-treated.m4a` 并写 `manifest.json`。**关键红线：`master-assets/clips/` 保持完整不剪碎是为了统一时间码基准，但下游 `00-master` 与 `v1..v4` 各自制作时，仍必须在各自 `storyboard.json` 中用 `time_slices` 切净片头采访者搭话、推眼镜冷场与口头禅，并设计 `H1–H6` 黄金 3 秒冷开，严禁把前 7 秒冷场原封不动端进成片！**；
   - 用户明确说了「未处理 / 原片 / 先粗剪」，或输入位于工作区 `素材投递区/未处理原片/` 下且用户未声明已处理 → `gates.input_state_confirmed = true`，进入步骤 E1；
   - 用户未明确说明处理状态且输入不在 `素材投递区/已粗剪/` 或 `素材投递区/未处理原片/` 中 → Agent 先结合 `ffprobe` 与轻量试听/静音检测初步判断，将 `run.json` 置 `status: "waiting_approval"`、`gates.pending_gate: "gate_0_input_state"`，**停下用一句话向用户确认是已处理还是未处理**，绝不擅自跳过粗剪。
6. **主讲人人脸水平质心标定（`probe-speaker-focus`）与三态配套视觉资产标准化接入（V3.1 强制前置）**：
   - **人脸居中焦点锁死**：确立 `master-assets/clips/` 后立即运行 `"$SVP_PYTHON" "$SVP_ROOT/.agents/skills/short-video-pipeline/scripts/qc_video.py" probe-speaker-focus --video <母素材切片> --out master-assets/clips/speaker-focus.json`，将测得的 `face_cx_pct`、`head_top_v`、`chin_v`、`span_v` 同步写入 `master/script/master-plan.json` 的 `speaker_focus` 字段；下游全部 5 个槽位切近景放大时必须对齐 `face_cx_pct`，严防人脸偏入右侧 `x > 930px` 点赞禁区；
   - **三态配套视觉资产接入协议（彻底终结剪辑工手搓脱离语境的简陋 SVG）**：
     1. **投递含交互 `.html`（如演示动效网页）**：**严禁薄套壳直挂**！必须派**专职可视化子代理**执行「纯函数确定性重构 + 竖屏安全区重排」——提升闭包私有时间轴变量，剥离全部 CSS `transition`、`setTimeout`、`setInterval`、`requestAnimationFrame`，重写为纯 `window.film.frame(t)` 确定性插值公式，并将横屏排版重排入 `1080×1920` 安全区（`x ≤ 910px, y = 200..1360px`）接入 `00-master`；`v1–v3` 继承其中的真实业务案例与数据，重构为各自异构展现形态；
     2. **投递含时间戳静态 `.png` 组图（如 `028-04-00m02s-xxx.png` 多张课件表）**：`00-master` 按文件名精确秒数以 `PF6` 3D 聚光灯/局部放大动效挂载原图；`v1–v3` 由视觉模型读图提取核心表格/阶梯数据，重绘为各自账号人设的原生 HTML/SVG 动效形态（**严禁 5 条成片同贴一张静态死图**）；
     3. **纯 `.mp4 + .srt` 无配套视觉件**：由专职可视化子代理通读逐字稿，锚定片中最具象的业务案例、数字与前后反差精写母版 `1080×1920` 叙事动效 HTML，并经 `svp_concurrency.py look` 抽检 4 张关键帧（确认静音仅看画面即可秒懂业务含义）后交下游异构裂变。
   - **母片与子片动效异构铁律（同源业务事实，异构展现形式，严禁简单换 CSS 颜色）**：`00-master` 为商业旗舰全景推演（或 `PF6` 原件聚光）；`01-v1` 重构为**双态手机对话追问气泡流 / 高反差刷屏卡片流**；`02-v2` 重构为**`#F2EFE9` 暖棉纸手账因果拆解树 + 荧光笔批注单**；`03-v3` 重构为**上下冷暖双域红笔划除误区 vs 电光青破局动作交锋台**；`04-v4` 保持**`2.39:1` 变形宽银幕纯光学实拍留白（零 UI 卡片与图表）**。

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
   - **时间轴重算与合规消音人声母带生成铁律**：凡经过删句、重切或合并，**必须先按最终 `master-assets/clips/` 的实际成片重新映射或重跑轻量 ASR 校准逐字稿时间戳**（严禁直接沿用原片旧时间戳导致下游字幕与哔声错位），随即对校准后的逐字稿与定稿切片运行 `qc_video.py scan-compliance --transcript ... --out master-assets/clips/<切片名>-compliance-bleeps.json` 及 `qc_video.py prepare-voice --in <切片或vocals.wav> --out master-assets/clips/<切片名>-voice-treated.m4a --bleeps master-assets/clips/<切片名>-compliance-bleeps.json`；
   - 写入完整的 `master-assets/manifest.json`（记录 `source_topics`、确认切片与合并片路径、`aligned_transcript`、`has_original_bgm`、`vocals_track`、`vocals_treated_track`、`compliance_bleeps`、`preprocess_applied` 与 `supplied_assets` 原名→合规名映射），同步更新 `run.json`（`gates.rough_cut_approved = true`、`gates.pending_gate = null`）。

### 步骤 E2：基于母素材制作完整母片（`master/`）

1. **母片默认剪辑风格与视觉基调（默认对应 [editing-styles.md](editing-styles.md) `S01` 商业旗舰深度叙事，用户指定时可换 `S01–S10`）**：
   - **视觉色板与调色 LUT（墨黑铜青 · `master-editorial.cube`）**：主标题配 `Noto Serif SC` + `Noto Sans SC`，底色深墨 `#0D1920` / `#15262F`、主字暖象牙 `#FFF8E6`、次字灰青 `#93AAB2`、主强调铜青 `#2FB8A8` / `#8BE3D6`、对比暖铜 `#D08346`、重点金标 `#FFC21A`；拷入 `.agents/skills/short-video-pipeline/assets/luts/master-editorial.cube` 至 `master/film/looks/`，所有出镜 `<video>` 挂 `--of-lut: url(looks/master-editorial.cube)` 与自然护镜美颜。
   - **精剪、去框化 Boxless 特效与两段式混音**：对照 [editing-styles.md](editing-styles.md) 与 [editing-vfx.md](editing-vfx.md)，先做 `D1–D5` 精剪与 `H1–H6` 黄金 3 秒冷开（切净开头搭话冷场，非连续切点必用 `JL3` B-roll 覆盖或 `TR1–TR6` 转场遮切，严禁句中假跳切）；严守 **Boxless 去框化四定律**（禁仪表盘套娃外框、禁无数字伪进度条、禁空黑框等字、禁字幕复读横幅、禁固定高 `space-between` 漏块塌陷、禁廉价 Emoji 贴纸）；`--of-cutout: 1` 必垫同源虚化视频底且 `width ≥ 1080px`（`span_v > 0.42` 大头原片禁做 `PF4` 人后字）；字幕采用 **`SUB1` 杂志双字重无框排印字幕**（`46px`，`top: 1412px`，**严禁 `.pill` 半透明胶囊框**）；配乐音效经 `normalize-sfx` 与 `build-bgm-bed`（含 1–2 处金句 `Silence Drop` 抽空留白）混出 `bgm-bed.m4a`，确保 `-14 LUFS`、`LRA ≥ 4.0 LU`。
   - **完整收尾硬规则（母片与 4 条子片均必守）**：① **口播语义闭环**（末句须是完整定论句，加 `30–50ms` 微淡出，严禁截断在转折/引子半句上）；② **视觉收尾落版**（`O1–O4` 稳落 `y≤1540px` 且停留可读 ≥ 1.5 秒）；③ **听觉与尾韵缓冲**（末句后留 `0.6–1.2s` 尾韵配合 BGM 自然淡出，片尾最后 `0.35s` 禁 `> -25 LUFS` 截断人声）。
2. **脚本分镜与补素材**：
   - 基于 `master-assets/manifest.json` 判定 `content_archetype`、测定 `speaker_framing`（含 `span_v`）并锁定 `subtitles.html`，编写 `master/script/storyboard.json`（含 `editing_style`、`color_lut`、`cold_open`、`time_slices`、`silence_drops` 及零复读 `cue_sync_map`：单锚点词 `≤5` 字且与底部字幕重合 `<50%`）；
   - 按 [sourcing.md](sourcing.md) 优先走本地 Pixabay 竖屏稳像源补充运动实拍视频 B-roll 与真实界面/无框动效素材（**严禁盲拿 API 第 1 条直塞 `film/assets/`！必须先下载 `2–4` 个候选至 `master/materials/`、看图检查 `candidate-sheet-*.jpg` 通过六维制作要求与五项技术硬检［`YAVG≥18`、`scdet<16`、`hf_jerk≤2.40px`、台词语义与地域影调吻合、`64-bit dHash` 唯一］后，用 `fetch_asset.py register --shot <镜号> --fit-reason "<具体实看说明>"` 签收入 `master/film/assets/credits.json`**），音频必过 `probe-audio` 与 `normalize-sfx`。
3. **母片剪辑特效、自动闪避床构建、3 秒预检与受控渲染自检**：
   - 写好 `film.html` 人声轨（引用 `*-voice-treated.m4a`）后，渲染前先跑 `"$SVP_PYTHON" "$SVP_ROOT/.agents/skills/short-video-pipeline/scripts/qc_video.py" build-bgm-bed --film-dir . --bgm assets/<bgm> --out assets/bgm-bed.m4a --drops "<t1:t2>"`；
   - **渲染统一走本机并发信号量包装器（自动先过 `preflight-film` 3 秒预检）**：`"$SVP_PYTHON" "$SVP_ROOT/.agents/skills/short-video-pipeline/scripts/svp_concurrency.py" render --film-dir . --out ../output/00-master-<话题短名>.mp4`（不合规秒级拦截零显卡损耗；抢占重渲染槽位后自动按并发负载配 `--workers 3` 或独占 `--workers 4`）；
   - 逐镜 `svp_concurrency.py look` + 全片 `ffprobe` + 必跑 `"$SVP_PYTHON" "$SVP_ROOT/.agents/skills/short-video-pipeline/scripts/qc_video.py" audit-render --video ../output/00-master-<话题短名>.mp4 --film-dir . --out-dir ../output/check`，**亲自打开 `safezone-grid.png`、`safezone-tail.png`、`safezone-cuts.png`、`safezone-broll.png`、`safezone-pip.png`（如有）及 `safezone-cutouts.png`（如有）目检**，零 `hard_failures` 后记录写入 `master/output/check/`。
4. **母片（`G0 · 跨境AI十亿增长局`）目标平台诚实文案 + 商业画报封面 + 单条审核**：
   - 按 [copywriting.md](copywriting.md) 对齐 **`G0` · `跨境AI十亿增长局`** 战略大盘定位，依 `content_archetype` 诚实钩子契约写出母片三平台四项文案（禁伪造不存在的清单/破局方案，禁生造歧义缩略词，禁残留未脱敏敏感词），落盘 `master/publish/publish.json`（含 `"account_group": "G0"`、`"account_ip_name": "跨境AI十亿增长局"`）；
   - 若 `covers_enabled` 为 `true`：按 [cover-design.md](cover-design.md) **`C1` 深墨铜青人物画报**出图（**顶部居中刊头微标必须印精确 IP 名 `跨境AI十亿增长局`，且两行主标题统一置于人物头顶上方水平居中**，严禁标题沉底、压额头或串用其它号组名！先生成 20–30 帧 `materials/covers/contact-sheet.jpg` 五维选帧，严格输出竖版尺寸：抖音 `1080×1920`、小红书 `1242×1660`、视频号 `1080×1440`，零小胶囊标签堆砌），落盘 `master/covers/00-master-<平台>.png` 与 `cover-spec.json`；
   - 按 [publish-audit.md](publish-audit.md) 完成母片单条全目标平台审核（含 `--publish-json` 复跑 `audit-render`）并写回 `audit`。

### 步骤 E3：基于当期母片与 `G1–G4` 账号 IP 定位 → 延伸规划 4 条子片（+ 闸门 2）

1. **三档自适应内容切分策略、五号组选题方向对齐与首尾双重护栏**：
   - **超长深访（母片 `> 120` 秒，且具备 `≥ 4` 个独立论点）**：4 条子片按各自绑定的 **`G1–G4` 账号 IP 方向** 从「母素材 + 母片主线」中对位拆出 **4 个互不重复的核心看点切片**（每条 `25–60` 秒，`G1` 取犀利痛点对谈、`G2` 取方法模型算账、`G3` 取操盘破误区复盘、`G4` 取底层经营规律洞察），再各自做正交风格包装；
   - **中长口播（母片 `75–120` 秒，通常含 `2–3` 个自然论点）**：采用 **「按账号人设拆解局部看点 + 跨段重组」混合制**（例如 `v1 [G1]` 切最锋利痛点快问快切，`v2 [G2]` 切方法推演或算账拆解，`v3 [G3]` 跨首尾抽取“多数人以为的旧共识靶子 vs 老郑一线实战真判断”做双视角交锋，`v4 [G4]` 提炼最具穿透力的周期规律与经营论哲思，**严禁为硬凑 4 段将单一完整论点拦腰劈成残缺半句！**）；
   - **短精华片（母片 `≤ 75` 秒）**：4 条子片围绕同一核心主题，严格站在 **`G1–G4` 四个账号不同人设视角**，以 **4 种完全正交的 `H1–H6` 开头钩子、叙事切角、节奏结构与视觉包装** 重构 4 条高度区分的成片；
   - 用户启动时如显式指定「拆四条」或「同内容四风格」，则优先遵照切分方式指令（但子片总数始终强制固定为 4 条，且 `00–04` 与 `G0–G4` 的账号 IP 对应关系不变）；
   - **开篇独立性护栏（严禁残句冷开）**：拆出的每条子片首句前 `0.8s` 内**严禁残留依赖前文的废语或悬空指代**（如「像我刚刚讲的」「反而是」「所以说」「那这个」）；若原段首句缺独立钩子，须精确后移起点裁净废语，或前置 `2–3s` 结论金句冷开，并在 `master-plan.json` 写明 `opening_hook`；
   - **切点语义与声学闭环硬规（严禁无结尾半句截断或切入下句起音）**：规划每条子片（尤其是倒叙或分段切出的切片）的 `time_slices` 尾点时，**必须对照 `aligned_transcript` 逐字确认末段最后一句是完整句意与明确结论落点，严禁把切点卡在转折词、铺垫引子或未说完的破折号半句上**（例如「但是这个经营流程——」「比如……」「接下来我们看……」），并核对尾点不切入下一句起音（末句语音加 `30–50ms` 微淡出）。若某段自然尾点刚好是引子句而非结论句，须采用以下任一方式收口：① 将尾点前收至上一句完整定论，或向后延伸至该观点完整说完（为保证每条子片独立成篇且收尾完整，允许相邻子片在边界处保留 1 句极短核心结论重叠，**独立完片感高于机械零重叠**）；② 末段显式拼入一句回扣核心定论的完整口播句并配独立收尾落版（`outro`）。每条子片均须在 `master-plan.json` 中显式写出 `account_group`、`account_ip_name`、`opening_hook`（开篇首句与钩子设计）、`ending_sentence`（收尾完整末句原文）与 `outro_design`（收尾画面、停留时长与 BGM 淡出方式），供规划审查。
2. **`00–04` ↔ `G0–G4` 五大账号组人设方向、正交剪辑范式、5 套独立 LUT、零胶囊等距字幕与封面 IP 名硬绑定（严禁换色克隆或账号 IP 串台！）**：
   - **灰度盲测反克隆 & 账号对位铁律**：`00–04` 产出的视频内容方向、剪辑语法与封面刊头 IP 名必须严格与 `G0–G4` 五个账号组一一对应（三平台共享同一 IP 名，严禁把任何手机号写入文件！），且全部去色转黑白灰后任意 3 秒内能一眼区分 5 种截然不同的视频类型（完整总谱见 [editing-styles.md](editing-styles.md)）：
     - **`00-master` ↔ `G0` · `跨境AI十亿增长局`（宏观战略大盘与十亿级增长格局 · 默认 `S01` · `master-editorial.cube` · 封面 `C1`）**：
       - **方向与剪辑**：立足行业大盘、跨境 × AI 规模增长格局与组织进化全景；`H1/H2` 冷开 + 三幕章节推进，全屏锁眼缓推口播（`55%`）↔ 紧凑 `4:3`/`16:10` 开放式侧分栏（`L2`，`v2≥75%`）+ 无框排版锚点与 `DV` 数据动效；封面刊头居中印 **`跨境AI十亿增长局`**；
       - **字幕体制（`SUB1`）**：左侧铜青标尺 + 无框黑宋混排双字重字幕（`46px`，**`top: 1412px`**，禁 `.pill`）。
     - **`01-v1` ↔ `G1` · `时奕聊AI经营`（“聊”：犀利对谈破题与经营体感暴击 · 默认 `S02` · `v1-crisp-contrast.cube` · 封面 `C2`）**：
       - **方向与剪辑（禁用顶部矩形讲座 PiP！）**：聚焦“聊”的鲜活交锋感、一线痛点直球发问与高密度反差；`H1` 前置最狠暴论冷开 + 全屏句界三级阶梯跳切（ASL `2.0–3.2s`，非连续切点用 `JL3` B-roll 遮切）+ `KT1/KT4` 巨字重锤砸屏 / `PF6` 3D 视窗 + `TR5/TR9` 冲击转场；封面刊头居中印 **`时奕聊AI经营`**；
       - **字幕体制（`SUB2`）**：无底框 `9px` 重黑边弹簧跳字（`52px`，关键词 `60px` 弹性上跳，**`top: 1320px`**）。
     - **`02-v2` ↔ `G2` · `辰奕AI经营实战`（企业级 AI 经营方法模型与算账推演 · 默认 `S03`［含实操步骤可切 `S10`］· `v2-warm-paper.cube` · 封面 `C3`）**：
       - **方向与剪辑（禁用 `width > 320px` 半屏矩形 PiP 与霓虹故障！）**：聚焦辰奕企业级 AI 经营框架、投入产出算账模型与 SOP 落地推演；`H4/H2` 切入 + 整块画幅释放为 `#F2EFE9` 无框暖纸研究画布（`70%+` 图解主导，说话人仅首尾或角落 `≤180px` 圆形微章 `L5`），配 `DV2/DV3` 面积挤压与纸张马克笔拟音；封面刊头居中印 **`辰奕AI经营实战`**；
       - **字幕体制（`SUB3` / 切 `S10` 时用 `SUB6`）**：亮底深墨无框印刷字幕 + 底部荧光笔实时手绘扫过（`46px`，**`top: 1458px`**）。
     - **`03-v3` ↔ `G3` · `老郑AI经营实战`（老郑一线操盘复盘与认知证伪避坑 · 默认 `S08`［含案例时间线可切 `S07`］· `tech-keynote.cube` · 封面 `C5`）**：
       - **方向与剪辑（禁用讲座大框与 `v1` 重黑边弹簧字！）**：紧扣“老郑实战”人设，抽取行业普遍踩坑的旧共识靶子 vs 老郑一线真刀真枪的实战判断；`H5` 靶子旧共识亮出（`0–4s`）→ `DV4` 珊瑚红双笔疾速划除并配低频打断音 → `L7` 冷暖双域无框斜切/上下交锋分屏拆解真相 + `L1` 近景直视定论（ASL `2.6–4.2s`）；封面采用 **`C5` 误区划除交锋头版画报**，刊头居中印 **`老郑AI经营实战`**；
       - **字幕体制（`SUB5`）**：极简几何无框等宽混排 + 电光青 `#38BDF8` `2px` 刻度下划线（`46px`，**`top: 1366px`**）。
     - **`04-v4` ↔ `G4` · `老郑AI经营论`（“经营论”：商业周期本质与企业家人性独白 · 默认 `S04` · `v3-obsidian-film.cube` · 封面 `C4`）**：
       - **方向与剪辑（禁用圆角信息盒、SVG 图表、`//` 科技胶囊、贴纸与气泡音效！）**：紧扣“经营论”思想高度，沉淀穿越周期的底层商业规律与组织哲思独白；`H6` 时空坐标呼吸冷开 + 同源虚化底 `--of-cutout: 1` 浅景深光学特写 + `L4/L6` `2.39:1` 宽银幕胶片构图 + `KT3` 光学散焦显影金句 + 大提琴低频氛围铺底配重句 `Silence Drop`，终帧真溶黑 `#000000`；封面采用 **`C4` 黑曜石电影剧照海报**，刊头居中印 **`老郑AI经营论`**；
       - **字幕体制（`SUB4`）**：影院级 `+2.5px` 宽字距暖象牙细衬线纯字（`42px`，**`top: 1504px`**）——**五槽字幕 `top` 精准形成 `1320 (v1) / 1366 (v3) / 1412 (master) / 1458 (v2) / 1504 (v4) px` 等距阶梯（相邻互差 `46px ≥ 40px`、总跨度 `184px ≥ 160px`）！**
   - 将 4 条子片的 `account_group`（`G1–G4`）、`account_ip_name`、`editing_style`（`S01–S10`）、`color_lut`、`cold_open`（`H1–H6`）、精剪 `time_slices`、`silence_drops`、`layout_paradigm`、`speaker_mode`、`subtitle_system`（`SUB1–SUB6`）、`cover_topology`（`C2–C5`）与独立补素材清单完整写入 `master/script/master-plan.json`。
3. **【闸门 2】母片确认 vs「一路跑完」零等待扇出协议 + 整夹多原片跑批规范**：
   - **当指令带「一路跑完」时（零等待 5 槽并发扇出，单期目标 `16–22` 分钟）**：`gates.master_approved = "skipped_auto_run"`。在 `E0` 完成母素材、`speaker_focus` 与母版解说动效基准后，**无需傻等 `00-master` 渲染完成才规划子片——直接前置编写锁定 `master/script/master-plan.json`，立即同步并发推进 `00-master` 与 `v1..v4` 共 5 个槽位**（各自在独立目录并行补素材、写异构展现动效、过 `preflight-film` 3 秒预检后经 `svp_concurrency.py render` 双路 GPU 信号量排队渲染）；
   - **当未带「一路跑完」时（默认开启闸门 2）**：先完成 `00-master` 与 `master-plan.json`，更新 `run.json`（`status: "waiting_approval"`、`step: "E3"`、`gates.pending_gate: "gate_2_master_plan"`），停下向用户展示母片与 4 子片差异化规划表；待用户确认后置 `gates.master_approved = true`、`status: "running"`，并发启动 4 个子代理执行步骤 E4；
   - **整夹多原片跑批规范（如一次输入 `027/`、`028/` 含多条原片的目录）**：顶层批次调度器必须遵守**全机同时活跃子代理总数 `≤ 6`** 的硬水位（按「单期组长子代理」隔离上下文，最多允许 `2` 个期次重叠备料，跨期传入共享 `--batch-id` 调用 `fetch_asset.py` 防撞素材，共享 `.local/locks/` 全域渲染/预览锁）；单槽渲染后若未过检仅局部重试该槽（最多 `2` 次）；若某单期耗尽重试预算仍未过硬门禁，将其记为 `status: "needs_attention"` 写入 `runs/batch-<时间>-summary.json` 并立即释放全部锁槽继续跑完其余期次，绝不单点卡死整批队列。

### 步骤 E4：4 条延伸子片独立制作（支持 4 子代理真并行）

- 4 个目录 `variants/v1-<风格>/`、`variants/v2-<风格>/`、`variants/v3-<风格>/`、`variants/v4-<风格>/` 完全物理隔离，主 Agent 默认同时派发 **4 个子代理**分别负责一条子片（不具备派子代理能力时串行完成）。
- **子代理权限边界（与 [../SKILL.md](../SKILL.md) 保持一致）**：4 个子代理仅在各自专属目录 `variants/vN-<风格>/` 内拥有局部完整制作权（可写各自 `film/film.html`、独立渲染与初检、产出本子片封面/文案初稿及单条 `publish.json`），**严禁修改 `raw/`、`master-assets/`、`master/` 及另外三条子片目录，严禁调用任何发布操作或付费生成，严禁在运行目录外存放文件**。
- 每条子片均以 `master-assets/` 为干净底料（需要局部引用母片某段特效时可按需引用，但不直接把焊死旧花字与旧 BGM 的母片当唯一底轨；原片含 BGM 时统一使用 `vocals_track` 配新风格 BGM），完整执行：
  1. **各自按实际情况独立候选筛片、六维核验签收与音效归一化**：先测定 `speaker_framing` 并锁定本子片精剪 `time_slices` 后的 `scenes/subtitles.html` 精确时间戳（凡命中 `compliance-bleeps.json` 敏感词处一律写脱敏词如 `某音`！），在各自 `script/storyboard.json` 写明零复读 `cue_sync_map`（单锚点 `≤5` 字且与字幕重合 `<50%`），按 [sourcing.md](sourcing.md) 优先走 Pixabay 竖屏稳像源将 `2–4` 个候选先下到本子片 `materials/`，**亲自看图检查 `candidate-sheet-*.jpg` 确认台词语义咬合、地域零穿帮、竖屏主体不被字幕压挡、影调契合本子片风格（如 `v4` 电影流禁高饱和亮片与 CG，`v3` 实战交锋流禁廉价卡通）且通过 `YAVG≥18`、`scdet<16`、`hf_jerk≤2.40px`、跨 5 片 `64-bit dHash > 10` 后，必须用 `fetch_asset.py register --shot <镜号> --fit-reason "<≥12字具体实看结论>"` 签收入本子片 `film/assets/credits.json`（严禁子代理盲拿 API 首条水片充数！）**，并对 `film/assets/` 短音效执行 `"$SVP_PYTHON" "$SVP_ROOT/.agents/skills/short-video-pipeline/scripts/qc_video.py" normalize-sfx film/assets`；
  2. **独立异构动效重绘、构建 `bgm-bed.m4a`、3 秒预检与受控并发渲染初检**：拷入本槽位对应 `.cube` LUT 至 `film/looks/`，挂齐 `--of-lut`、对齐 `face_cx_pct` 的人物近景焦点、同源虚化光学抠像（`width≥1080px`）、按本槽人设重构展现形式的具象业务动效（`v1` 气泡问答流 / `v2` 暖纸白板树与批注单 / `v3` 冷暖双域红笔划除交锋台 / `v4` 纯宽银幕电影留白，严禁仅对母片做 CSS 换色！）与对应 `SUB2/SUB3(SUB6)/SUB5/SUB4` 零胶囊等距字幕，人声轨挂已含 `1000Hz` 合规哔声的 `master-assets/clips/*-voice-treated.m4a`；写好 `film.html` 后先跑 `"$SVP_PYTHON" "$SVP_ROOT/.agents/skills/short-video-pipeline/scripts/qc_video.py" build-bgm-bed --film-dir . --bgm assets/<bgm> --out assets/bgm-bed.m4a --drops "<t1:t2>"`，再统一调用 `"$SVP_PYTHON" "$SVP_ROOT/.agents/skills/short-video-pipeline/scripts/svp_concurrency.py" render --film-dir . --out ../output/0N-vN-<风格短名>.mp4`（自动先过 `preflight-film` 3 秒预检，并在 Windows 全域双路渲染池 `2 × --workers 3` 与 `≥3.5GB` 可用内存熔断保护下安全并发硬编），逐镜 `svp_concurrency.py look` + `ffprobe` + 必跑 `"$SVP_PYTHON" "$SVP_ROOT/.agents/skills/short-video-pipeline/scripts/qc_video.py" audit-render --video ../output/0N-vN-<风格短名>.mp4 --film-dir . --out-dir ../output/check`，亲自打开 `safezone-grid/tail/cuts/broll/pip/cutouts.png` 目检零 `hard_failures`（Playwright 截封面统一走 `svp_concurrency.py exec --pool preview -- ...`）；
  3. **独立目标平台诚实文案（对齐本槽账号 IP 人设）**：按 [copywriting.md](copywriting.md) 紧贴本槽账号定位（`v1=时奕聊AI经营`、`v2=辰奕AI经营实战`、`v3=老郑AI经营实战`、`v4=老郑AI经营论`）、本子片 `content_archetype` 与实际剪出的冷开首句、落点撰写四项文案（禁虚假破局清单承诺、禁生造歧义词、禁未脱敏敏感词、禁描述带秒数），落盘 `publish/publish.json`（含 `account_group` 与 `account_ip_name`）；
  4. **独立目标平台竖版杂志封面（若 `covers_enabled` 为 `true`，强制头顶居中标题 & 严禁账号 IP 名串台！）**：按 [cover-design.md](cover-design.md) 各自 `C2 [v1] / C3 [v2] / C5 [v3] / C4 [v4]` 商业画报拓扑出图（**两行封面字幕一律置于人物头顶上方水平居中（`text-align: center`），且顶部居中刊头精确印本槽位绑定的账号 IP 名**［`v1=时奕聊AI经营`、`v2=辰奕AI经营实战`、`v3=老郑AI经营实战`、`v4=老郑AI经营论`］，严禁串用其他号组名或把标题放底部！先基于 20–30 帧 `contact-sheet.jpg` 五维选出互不撞脸神态帧，`C3` 暖白底禁贴裸抠像改用胶片相框实拍裁切，严格输出三平台竖版尺寸：**抖音 `1080×1920`、小红书 `1242×1660`、视频号 `1080×1440`**），产出 `covers/0N-vN-<平台>.png` 与 `cover-spec.json`；
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
  "id": "20261124-1400-企业AI经营提效",
  "topic": "企业AI经营提效（母素材 + 1母片 + 4延伸风格子片）",
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
  "master_assets": "runs/20261124-1400-企业AI经营提效/master-assets/manifest.json",
  "video_orientation": "portrait",
  "master": {
    "prefix": "00-master",
    "account_group": "G0",
    "account_ip_name": "跨境AI十亿增长局",
    "video": "runs/20261124-1400-企业AI经营提效/master/output/00-master-企业AI经营提效.mp4",
    "covers": {
      "douyin": "runs/20261124-1400-企业AI经营提效/master/covers/00-master-douyin.png",
      "shipinhao": "runs/20261124-1400-企业AI经营提效/master/covers/00-master-shipinhao.png",
      "xhs": "runs/20261124-1400-企业AI经营提效/master/covers/00-master-xhs.png"
    },
    "publish_json": "runs/20261124-1400-企业AI经营提效/master/publish/publish.json"
  },
  "variants": [
    {
      "id": "v1",
      "prefix": "01-v1",
      "account_group": "G1",
      "account_ip_name": "时奕聊AI经营",
      "style": "痛点对谈快剪",
      "dir": "runs/20261124-1400-企业AI经营提效/variants/v1-痛点对谈快剪",
      "video": "runs/20261124-1400-企业AI经营提效/variants/v1-痛点对谈快剪/output/01-v1-痛点对谈快剪.mp4",
      "covers": {
        "douyin": "runs/20261124-1400-企业AI经营提效/variants/v1-痛点对谈快剪/covers/01-v1-douyin.png",
        "shipinhao": "runs/20261124-1400-企业AI经营提效/variants/v1-痛点对谈快剪/covers/01-v1-shipinhao.png",
        "xhs": "runs/20261124-1400-企业AI经营提效/variants/v1-痛点对谈快剪/covers/01-v1-xhs.png"
      },
      "publish_json": "runs/20261124-1400-企业AI经营提效/variants/v1-痛点对谈快剪/publish/publish.json"
    }
  ],
  "delivery_dir": "runs/20261124-1400-企业AI经营提效/delivery",
  "delivery_index": "runs/20261124-1400-企业AI经营提效/delivery/INDEX.md",
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
  "source_video": "runs/20261124-1400-企业AI经营提效/raw/interview-raw.mp4",
  "has_original_bgm": true,
  "source_topics": ["topic-01-个人提效痛点", "topic-03-组织流程重构"],
  "preprocess_applied": [
    "00:12-00:18 左上角白板打马赛克（已核验无漏帧）",
    "合并 topic-01 与 topic-03 并重算对齐逐字稿时间戳"
  ],
  "clips": [
    {
      "id": "clip-01",
      "path": "runs/20261124-1400-企业AI经营提效/master-assets/clips/clip-01-组织流程重构.mp4",
      "vocals_track": "runs/20261124-1400-企业AI经营提效/master-assets/clips/clip-01-组织流程重构-vocals.wav",
      "vocals_treated_track": "runs/20261124-1400-企业AI经营提效/master-assets/clips/clip-01-组织流程重构-voice-treated.m4a",
      "compliance_bleeps": "runs/20261124-1400-企业AI经营提效/master-assets/clips/clip-01-组织流程重构-compliance-bleeps.json",
      "duration_sec": 62.4,
      "aligned_transcript": "runs/20261124-1400-企业AI经营提效/master-assets/clips/clip-01-transcript.json"
    }
  ],
  "merged_clip": "runs/20261124-1400-企业AI经营提效/master-assets/clips/clip-merged-企业AI经营提效.mp4",
  "supplied_assets": [
    {
      "original_name": "流程 演示图 (终版).png",
      "normalized_path": "runs/20261124-1400-企业AI经营提效/master-assets/supplied/workflow-demo-final.png"
    }
  ]
}
```

### 3. `master/script/master-plan.json`（4 条子片对位 `G1–G4` 延伸规划表）

```json
{
  "content_archetype": "actionable_method",
  "master_account_group": "G0",
  "master_account_ip_name": "跨境AI十亿增长局",
  "master_editing_style": "S01",
  "master_duration_sec": 108.0,
  "video_orientation": "portrait",
  "split_strategy": "persona_aligned_4_variants_G1_to_G4",
  "target_platforms": ["douyin", "xhs", "shipinhao"],
  "variants": [
    {
      "id": "v1",
      "prefix": "01-v1",
      "account_group": "G1",
      "account_ip_name": "时奕聊AI经营",
      "editing_style": "S02",
      "style_slug": "痛点对谈快剪",
      "color_lut": "v1-crisp-contrast.cube",
      "layout_paradigm": "fullscreen_jumpcut_kinetic",
      "speaker_mode": "fullscreen_step_zoom",
      "subtitle_system": "SUB2_top1320_no_pill",
      "cover_topology": "C2",
      "color_palette": {
        "bg": "#060B14",
        "bg_2": "#0B1628",
        "text": "#FFFFFF",
        "accent": "#00E5FF",
        "warn": "#FF6B35"
      },
      "source_clips": ["runs/20261124-1400-企业AI经营提效/master-assets/clips/clip-01-组织流程重构.mp4"],
      "time_slices": [[54.2, 56.8], [7.2, 31.5], [34.0, 48.6]],
      "silence_drops": [[28.4, 29.1]],
      "cold_open": "H1 前置2.6s最狠结论金句冷开，切净原片前7.2s搭话冷场，删句切点用JL3实拍B-roll遮切",
      "angle": "对位「时奕聊AI经营」：前3秒犀利直球破题，聚焦员工各用各的AI为何公司整体没提效",
      "opening_hook": "前置2.6s结论金句冷开（裁净悬空代词，巨字锚点补全主语冲突）",
      "ending_sentence": "真正的AI提效不是每个人装十个工具，而是把核心业务流跑成标准闭环。",
      "outro_design": "O1定帧印章落版：末句完整落音加40ms微淡出后切出无框金句收束，停留可读1.8s并留0.8s尾韵配合bgm-bed自然淡出",
      "visual_style": "句界阶梯跳切 + Boxless无框巨字重锤 + PF6真实工作流界面3D视窗 + 实拍B-roll穿插",
      "bgm_mood": "电子脉冲自动闪避铺底床 + 金句前Silence Drop",
      "supplement_assets_plan": ["真实协作界面截图", "团队办公协作实拍运动B-roll", "归一化Whoosh+SubHit音效"],
      "cover_spec": "C2",
      "brand_slogan_mode": "chenyi_default"
    },
    {
      "id": "v2",
      "prefix": "02-v2",
      "account_group": "G2",
      "account_ip_name": "辰奕AI经营实战",
      "editing_style": "S03",
      "style_slug": "白板推演算账",
      "color_lut": "v2-warm-paper.cube",
      "layout_paradigm": "warm_paper_canvas_pan_zoom_L5",
      "speaker_mode": "intro_outro_and_corner_badge",
      "subtitle_system": "SUB3_top1458_no_pill",
      "cover_topology": "C3",
      "color_palette": {
        "bg": "#F2EFE9",
        "bg_2": "#E6E1D6",
        "text": "#111C24",
        "accent": "#1B8A6B",
        "warn": "#D96B27"
      },
      "source_clips": ["runs/20261124-1400-企业AI经营提效/master-assets/clips/clip-01-组织流程重构.mp4"],
      "time_slices": [[19.4, 48.6]],
      "silence_drops": [[38.0, 38.7]],
      "cold_open": "H2 直接在暖棉纸画布抛出跨部门返工损耗账本对比，引入方法模型推演",
      "angle": "对位「辰奕AI经营实战」：用全画幅研究画布拆解跨部门输入输出标准与试点复制SOP",
      "opening_hook": "返工损耗算账切入企业级AI经营推演",
      "ending_sentence": "先把单点试点跑出明确输入输出标准，再向全团队复制才能稳住ROI。",
      "outro_design": "O1暖纸墨字核心公式定格：停留可读1.8s并留0.8s木质拨弦尾韵淡出",
      "visual_style": "C6虚拟摄像机平移推拉暖纸画布 + DV2/DV3无框数据挤压与趋势面 + 纸笔拟音",
      "bgm_mood": "原声木质拨弦自动闪避铺底床 + 马克笔划词拟音",
      "supplement_assets_plan": ["运营团队白板复盘稳像B-roll", "流程标准表真实截图", "纸张翻页与马克笔音效"],
      "cover_spec": "C3",
      "brand_slogan_mode": "chenyi_default"
    },
    {
      "id": "v3",
      "prefix": "03-v3",
      "account_group": "G3",
      "account_ip_name": "老郑AI经营实战",
      "editing_style": "S08",
      "style_slug": "操盘交锋破局",
      "color_lut": "tech-keynote.cube",
      "layout_paradigm": "dual_zone_myth_clash_L7",
      "speaker_mode": "split_clash_and_closeup",
      "subtitle_system": "SUB5_top1366_no_pill",
      "cover_topology": "C5",
      "color_palette": {
        "bg": "#0B1117",
        "bg_2": "#16222E",
        "text": "#F4F7FA",
        "accent": "#38BDF8",
        "warn": "#FF4D3A"
      },
      "source_clips": ["runs/20261124-1400-企业AI经营提效/master-assets/clips/clip-01-组织流程重构.mp4"],
      "time_slices": [[8.5, 19.2], [48.8, 62.0]],
      "silence_drops": [[56.2, 56.8]],
      "cold_open": "H5 先亮出老板盲目全员买账号搞一刀切的旧误区，1.6s处DV4珊瑚红双笔疾速划除并配低频打断音切入老郑实战判断",
      "angle": "对位「老郑AI经营实战」：跨段抽取旧共识靶子vs一线操盘新真相，双色温交锋纠偏",
      "opening_hook": "靶子误区打碎冷开（旧经验vs新规则正面碰撞）",
      "ending_sentence": "没有业务流程改造托底，买再多AI账号也只是增加管理噪音。",
      "outro_design": "O1真相定论无框巨字收束：停留可读1.8s并留0.8s尾韵自然淡出",
      "visual_style": "L7冷暖双域无框分屏 + DV4手绘双笔划除旧认知 + 稳像实拍B-roll",
      "bgm_mood": "前抑后扬紧凑脉冲铺底床 + 打断切点重音",
      "supplement_assets_plan": ["会议讨论实拍B-roll", "仓库履约实拍B-roll", "归一化低频打断音效"],
      "cover_spec": "C5",
      "brand_slogan_mode": "chenyi_default"
    },
    {
      "id": "v4",
      "prefix": "04-v4",
      "account_group": "G4",
      "account_ip_name": "老郑AI经营论",
      "editing_style": "S04",
      "style_slug": "商业周期独白",
      "color_lut": "v3-obsidian-film.cube",
      "layout_paradigm": "widescreen_239_cinema_monologue",
      "speaker_mode": "shallow_dof_closeup_and_239_triptych",
      "subtitle_system": "SUB4_top1504_no_pill",
      "cover_topology": "C4",
      "color_palette": {
        "bg": "#050506",
        "bg_2": "#111216",
        "text": "#F5EFE6",
        "accent": "#D4AF37",
        "warn": "#9C7A3C"
      },
      "source_clips": ["runs/20261124-1400-企业AI经营提效/master-assets/clips/clip-01-组织流程重构.mp4"],
      "time_slices": [[22.0, 48.6]],
      "silence_drops": [[41.2, 42.0]],
      "cold_open": "H6 时空坐标静默呼吸冷开，切入组织能力代际跃迁的本质独白",
      "angle": "对位「老郑AI经营论」：抽离术层技巧，沉淀技术变革期企业家认知与组织底层规律",
      "opening_hook": "2.39:1宽银幕低频弦乐切入核心经营哲学判断",
      "ending_sentence": "每一次工具革命，淘汰的从来不是岗位本身，而是拒绝进化的旧组织分工。",
      "outro_design": "O2金句余韵散焦显影+真溶黑#000000，留1.0s低频尾韵自然消散",
      "visual_style": "同源虚化光学浅景深特写 + L6宽银幕胶片视窗 + KT3光学散焦显影金句",
      "bgm_mood": "大提琴低频氛围铺底床 + 核心论断前Silence Drop",
      "supplement_assets_plan": ["深夜城市航拍稳像B-roll", "港口集装箱慢镜头实拍B-roll"],
      "cover_spec": "C4",
      "brand_slogan_mode": "chenyi_default"
    }
  ]
}
```

### 4. `delivery/0N-*/copy.md` 标准交付模板（标明对应账号 IP 名与竖版封面精确尺寸）

```markdown
# 00-master · 跨境AI十亿增长局 · 企业AI经营提效（人工上传可直接复制）

- 对应账号组：`G0` · `跨境AI十亿增长局`（抖音 / 小红书 / 视频号同名 IP）
- 成片：`runs/<目录>/delivery/00-master/00-master-<话题短名>.mp4`（竖版 1080×1920）
- 合规脱敏记录：已通过 `scan-compliance` + `prepare-voice --bleeps` 处理（列出命中的敏感词及哔声时间点；无命中填「零违规词」）
- 审核结论：全平台硬门禁通过（见 `runs/<目录>/master/publish/publish.json`）

## 抖音（douyin）
- 封面图：`runs/<目录>/delivery/00-master/00-master-douyin.png`（1080×1920 · 头顶居中标题）
- 封面标题（两行）：第一行 / 第二行
- 表单标题（≤30字）：...
- 视频描述：...
- 三层标签候选：赛道（...）｜垂直（...）｜精准（...）
- 本条发布组合（3-5个，整行复制）：`#词1 #词2 #词3 #词4 #词5`

## 小红书（xhs）
- 封面图：`runs/<目录>/delivery/00-master/00-master-xhs.png`（1242×1660 · 头顶居中标题）
- 封面标题（两行）：第一行 / 第二行
- 笔记标题（≤18字，上限20字）：...
- 视频描述：...
- 三层标签候选：赛道（...）｜垂直（...）｜精准（...）
- 本条发布组合（3-8个，整行复制）：`#词1 #词2 #词3 #词4 #词5`

## 视频号（shipinhao）
- 封面图：`runs/<目录>/delivery/00-master/00-master-shipinhao.png`（1080×1440 · 头顶居中标题）
- 封面标题（仅封面图用，勿填短标题框）：第一行 / 第二行
- 短标题（6-16字，无空格无禁用标点）：`...`
- 视频描述：...
- 三层标签候选：赛道（...）｜垂直（...）｜精准（...）
- 本条发布组合（整行复制）：`#词1 #词2 #词3 #词4`
```
