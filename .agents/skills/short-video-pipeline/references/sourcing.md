# 热点与素材寻源指南（最优方案）

本文件记录本工作区经过实测对比后选定的**国内外热点寻源**与**分场景素材寻源**方案。所有能力均基于**零新增重型仓库、零常驻额外服务**的原则设计，全部通过两个零外部依赖脚本（复用工作区现有 `playwright-core`、`browsers/ms-playwright/`、`creatorhub/.venv/bin/yt-dlp`、`ffmpeg`）直接调用：

- 热点拉取：`.agents/skills/short-video-pipeline/scripts/fetch_trends.py`
- 素材搜抓：`.agents/skills/short-video-pipeline/scripts/fetch_asset.py`

执行前照例在当前 shell 先 source 环境脚本：`. .agents/skills/short-video-pipeline/scripts/env.sh`。

---

## 一、方案对比与选型结论

### 1. 热点寻源对比

| 候选方案 | 优点 | 缺点 / 淘汰原因 | 结论 |
|---|---|---|---|
| **60s Top-3 公共实例 + NewsNow + 官方直连 RSS + Google/Bing News RSS + 已有 CreatorHub** | 覆盖国内大众 + 国内外科技/AI + 科技大厂一手发布 + 平台内爆款验证；**零常驻服务、零新增仓库**；2026-11-20 实测全部 1.6s–5.9s 连通 | 公共节点偶发抖动（通过多节点自动降级与直连官方源兜底解决） | **选定主力** |
| `imsyy/DailyHotApi` | 国内热榜全 | 需本地另起 Node 服务；海外与科技大厂一手源偏少 | 不引入 |
| `sansan0/TrendRadar` | 热榜 + RSS + 推送机器人 | 本质是包装 NewsNow + RSS + 聊天推送，本流水线由 agent 直接消费 JSON，不需要推送服务 | 吸收其“热榜 + 官方 RSS”架构，不克隆整仓 |
| `DIYgod/RSSHub` | 全网覆盖最广 | 重型服务、反爬维护成本高；科技大厂官网已自带免反爬原生 RSS | 不引入 |
| `MediaCrawler` / `BettaFish` | 社媒深爬与评论区舆情 | 与工作区已有 `CreatorHub` 采集重叠，且维护与风控成本高 | 不引入 |

> 2026-11-20 实测剔除的不可用源：`Reddit JSON`（403）、`blogs.microsoft.com/feed`（403）、`36kr.com/feed`（XML 解析异常）、`60s` 小红书 `/v2/rednote`（全节点 500）、`60s.viki.moe` 主域名（高频并发易 429）。

### 2. 素材寻源对比

| 候选方案 | 优点 | 缺点 / 淘汰原因 | 结论 |
|---|---|---|---|
| **OpenFilm（自带库 + 免费 Pexels/Pixabay + 代码画面） + 工作区已有 `playwright-core` 抓新闻页/截图 + 工作区已有 `yt-dlp` 切官方 Demo + 零 Key 公开库（Wikimedia/NASA/Archive/Openverse）** | 零新增重型依赖；同时解决**科技巨头新闻官方图/网页截图/发布会短切片**与**通用免版权 B-roll**；下载即归档至 `materials/`、`film/assets/`、`.local/openfilm-user/saved/` 并自动记 `credits.json` | 通用高清竖屏 B-roll 在配好免费 Pexels/Pixabay Key 后质感最佳（未配前走 Wikimedia/NASA/代码画面兜底） | **选定主力** |
| `unclecode/crawl4ai` | 动态网页抽取强 | 依赖极重（数十个 Python 包且与工作区 Playwright 重复） | 用工作区已有 `playwright-core` 轻量实现替代 |
| `searxng/searxng` | 多引擎聚合 | 需常驻后端服务（常需 Docker） | 不引入 |
| 通用图库 MCP（`stocky` 等） | 方便单家客户端调用 | 绑定特定 MCP 客户端配置；OpenFilm 本身已内置 Pexels 与 Pixabay 能力 | 优先直接用 OpenFilm 内置能力，保持 agent 无关 |

---

## 二、国内外热点寻源（4 层矩阵）

| 层级 | 覆盖内容 | 实测数据源 | 降级兜底 |
|---|---|---|---|
| **L1 国内大众热榜** | 抖音、微博、B站、知乎、头条、百度 | 60s Top-3 实例按序降级：`api.cczo.cc/60s` → `60s.mizhoubaobei.top` → `60s.okbaike.com` | NewsNow 国内源（`douyin`/`weibo`/`zhihu`/`bilibili-hot-search`/`thepaper`）→ `hot-search-crawler` |
| **L2 国内外科技 / 开发者 / 财经** | IT之家（快讯+热榜）、AI 资讯快报、Hacker News、GitHub Trending、Product Hunt、华尔街见闻、财联社、少数派、Solidot、联合早报 | NewsNow API（9 源全通，~2.4s）+ 60s（`/v2/it-news`、`/v2/it-news/rank`、`/v2/ai-news` 超时 ≥15s） | HN Algolia 官方 JSON（`hn.algolia.com`）+ IT之家/少数派原生 RSS |
| **L3 科技巨头一手官方发布 & 权威外媒** | OpenAI、Google Blog、Google DeepMind、Apple Newsroom、NVIDIA Blog、GitHub Blog、Hugging Face、TechCrunch、The Verge、Ars Technica、Google News 全球科技 | 官网直连 RSS / Atom（1.9s–3.6s，零中间商） | 按主题实时查 Google News RSS（中/英）+ Bing News RSS |
| **L4 平台内爆款交叉验证** | 小红书、抖音近 7 天最高赞 | 工作区 `CreatorHub` `/api/collections`（`search_sort: most_liked`, `publish_time: week`） | 失败则跳过，不阻塞主流程 |

### 常用命令

```bash
. .agents/skills/short-video-pipeline/scripts/env.sh

# 1. 全量国内外热点（L1 + L2 + L3，自动标出跨平台同时上榜的高潜选题）
python3 .agents/skills/short-video-pipeline/scripts/fetch_trends.py --mode all --out runs/<目录>/topic

# 2. 只看国内外科技与 AI 热点（含科技大厂一手官方 RSS）
python3 .agents/skills/short-video-pipeline/scripts/fetch_trends.py --mode tech --out runs/<目录>/topic

# 3. 只看国内大众热榜 / 只看海外科技
python3 .agents/skills/short-video-pipeline/scripts/fetch_trends.py --mode domestic --out runs/<目录>/topic
python3 .agents/skills/short-video-pipeline/scripts/fetch_trends.py --mode global --out runs/<目录>/topic

# 4. 按指定主题或公司名实时搜国内外新闻（用于查事实 & 找官方新闻稿 URL）
python3 .agents/skills/short-video-pipeline/scripts/fetch_trends.py --mode search --query "NVIDIA" --out runs/<目录>/topic
```

脚本会把完整 JSON 存为 `runs/<目录>/topic/hotlist-<mode>.json`，并在终端打印紧凑摘要（含跨平台重合话题提示）。

---

## 三、素材寻源决策树（按 5 类镜头分流）

做分镜（`storyboard.json`）时，先判断每一镜属于下面哪一类，再走对应最优通道，**不要把新闻实事镜头硬塞去图库搜，也不要把参数对比强行用 AI 生图**：

| 镜头类型 | 最优通道（按顺序） | 执行命令 / 工具 |
|---|---|---|
| **A. 音乐、音效、动态贴纸、已有自存** | 1. OpenFilm 本地复用库 `my-media`<br>2. OpenFilm 自带 CC0 免费库（含 **1,587 枚离线动态贴纸**：箭头/强调圈/警示标/徽章）<br>3. Openverse Audio（免 Key 备用） | `openfilm get my-media --prompt "..."`<br>`openfilm get music-search` / `sfx-search` / `sticker --prompt "..." --take <id>`<br>备用：`fetch_asset.py stock --kind audio --source openverse ...` |
| **B. 数据对比、参数表、清单、金句标题、流程动效** | 直接写 **OpenFilm 语义级 SVG / Canvas 定制动画**（`stroke-dashoffset` + `getPointAtLength` 流光 / 流式打字机 / 拓扑图 / 天平 / 阶梯图），单支视频语义 SVG/Canvas 场景占比 `≥ 45%` | 在 `film/scenes/` 下写 1080×1920 动态页面（清晰度最高、最贴合口播、零版权风险、最快） |
| **C. 科技巨头发布新闻 / 产品报道 / 真实事件** | 1. 找一手官方新闻稿/博客链接（`fetch_trends.py --mode search` 或 RSS 原文链接）<br>2. **抽官方高清配图 + 截取干净官网首屏**<br>3. **搜并截取官方发布会/Demo 3–6 秒短片段** | 抽图与截图：`fetch_asset.py news-page --url "<官方URL>" --out materials --screenshot`<br>搜官方视频：`fetch_asset.py video-search --query "Apple keynote official"`<br>精准切片：`fetch_asset.py video-clip --url "<URL>" --start 00:10 --end 00:16 --mute --out materials/demo.mp4` |
| **D. 通用实拍动态 B-roll / 氛围空镜 / 科普插图** | 1. 查 `openfilm get my-media`（`.local/openfilm-user/saved/`）<br>2. **优先补 1–2 段 3–6 秒真实运动视频（`.mp4`）**：已配免费 Key 用 **OpenFilm 内置 Pexels / Pixabay**（2–4 个英文视觉关键词 + `--orientation portrait`）；未配 Key 用 **免 Key 公开免版权库**（Wikimedia Commons / NASA / Internet Archive）搜视频与图 | 配了免费 Key：`openfilm get video-search --prompt "server room neon" --orientation portrait`<br>免 Key 优先视频：`fetch_asset.py stock --query "office team" --kind video --download 2 --out materials --assets film/assets --save-reusable`<br>免 Key 图片兜底：`fetch_asset.py stock --query "microchip silicon wafer" --kind image ...` |
| **E. 抽象概念 / 搜不到的专属场景** | 1. Agent 自带生图能力（9:16 竖屏）或 OpenFilm 已接生图服务——**入片必须叠加与口播绑定的 SVG 矢量前景动效层**（光点/扫光/连线/准星），禁止纯静图死板慢推<br>2. 生成视频（全片 ≤2 镜、每镜 ≤6 秒；付费须先告知用户费用并获同意）<br>3. 失败或不可用则退回 **B 类代码动画** | Agent 生图 / `openfilm get image` / `openfilm get video` |

> **单支视频内视觉素材单次使用铁律（硬约束）**：在同一支成片（单片或入口 E 的任意单槽位）中，每一张 B-roll 图、AI 生图、动态贴纸、预置手册原图或实拍视频 B-roll 片段（品牌固定 Logo 除外）**严格仅允许使用 1 次（`count = 1`）**，禁止跨镜复用或在同一场景中重复挂双层 `<img>`；在入口 E 中，4 个槽位之间也禁止照搬同一批补充 B-roll，须各自独立补足。

### 素材入库与复用命令

筛选好 `materials/` 里的最终素材后，用 `register` 一步复制到 OpenFilm 项目素材区 `film/assets/`（通用空镜/音效可加 `--save-reusable` 同步放进 `.local/openfilm-user/saved/`，后续视频直接用 `openfilm get my-media` 复用），并自动更新 `film/assets/credits.json`：

```bash
python3 .agents/skills/short-video-pipeline/scripts/fetch_asset.py register \
  --file runs/<目录>/materials/apple-img1.jpg \
  --assets runs/<目录>/film/assets \
  --type news_image \
  --source "Apple Newsroom 官方发布" \
  --url "https://www.apple.com/newsroom/..." \
  --license "新闻报道合理引用（画面标注来源）"
```

> **入口 E（[multi-variant.md](multi-variant.md)）多项目路径提醒**：在入口 E 中，母片与 3 条延伸子片各自拥有独立目录，调用 `fetch_asset.py` 时务必将 `--out` 与 `--assets` 分别指向对应片目录（如 `runs/<目录>/master/materials` 与 `runs/<目录>/master/film/assets`，或 `runs/<目录>/variants/v1-<风格>/materials` 与 `.../film/assets`），严禁 4 片混写进同一目录。若在深层子目录执行脚本，先 source `env.sh` 后直接使用 `python3 "$SVP_ROOT/.agents/skills/short-video-pipeline/scripts/fetch_asset.py"`。

---

## 四、版权与画面合规底线

1. **科技新闻/真实事件素材（C 类）**：
   - 中文科技媒体的二次转载图常带站点水印（如右下角角标）且会被压小。**中文报道只用来发现线索，抓官图和截图必须溯源到海外/大厂官方原博或 Newsroom**（如 `techcommunity.microsoft.com`、`openai.com`、`apple.com/newsroom`）拿无水印高清原图，且下载后必须逐张看图确认无水印再入 `film/assets/`。
   - 优先使用**官方新闻室（Newsroom / Press Kit / 官方博客 / 官方频道发布会）**的原图、官网干净截图和 ≤6 秒的官方 Demo 短切片，并在画面角落或说明中清晰标注出处（如“来源：Microsoft USB Blog”）。
   - 新闻中的参数对比、跑分数据优先抽取事实后用 **B 类代码画面**重绘，避免模糊截图。
2. **严禁越界**：
   - 严禁把别人的二次创作短视频成片、搬运片段、带平台/图库水印的图或视频当素材（CreatorHub 下载的参考视频只进 `ref/`）。
   - 严禁伪造新闻画面、伪造聊天/新闻截图、生成真实人物肖像或伪造品牌 Logo。
   - 所有素材原件、截图、切片均留在 `runs/<目录>/materials/` 与 OpenFilm 区，不向工作区外写任何文件。
