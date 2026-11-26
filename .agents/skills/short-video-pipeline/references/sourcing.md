# 热点与素材寻源指南（最优方案）

本文件记录本工作区经过实测对比后选定的**国内外热点寻源**与**分场景素材寻源**方案。所有能力均基于**零新增重型仓库、零常驻额外服务**的原则设计，全部通过两个零外部依赖脚本（复用工作区现有 `playwright-core`、`browsers/ms-playwright/`、`rea-video/.venv` 内的 `yt-dlp`、`ffmpeg`，不依赖 CreatorHub 运行）直接调用：

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
| **L4 平台内爆款交叉验证（按需可选）** | 小红书、抖音近 7 天最高赞 | 工作区 `CreatorHub` `/api/collections`（`search_sort: most_liked`, `publish_time: week`） | **当前 CreatorHub 默认停用，日常直接跳过，不阻塞主流程** |

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
| **A. 音乐、音效、已有自存素材** | 1. OpenFilm 本地复用库 `my-media`<br>2. OpenFilm 自带 CC0 免费曲库/音效库（严肃商业/电影风 `S01/S03/S04/S05/S06/S07` 禁用彩色扁平卡通贴纸与 `ui-pop/bell` 轻浮音，入库后必跑 `qc_video.py normalize-sfx` 清洗 `<-50 LUFS` 坏件并归一化至 `-3 dBTP`）<br>3. Openverse Audio（免 Key 备用） | `openfilm get my-media --prompt "..."`<br>`openfilm get music-search` / `sfx-search --prompt "..." --take <id>`<br>`"$SVP_PYTHON" "$SVP_ROOT/.agents/skills/short-video-pipeline/scripts/qc_video.py" normalize-sfx film/assets` |
| **B. 数据对比、成本挤压、周期曲线、金句标题、因果推演** | 直接采用 [editing-vfx.md](editing-vfx.md) 的 **无外框高级视觉模组（`KT1–KT8` 动态排印 + `DV1–DV8` 物理挤压/地平线趋势面/手绘划除）**——**严禁画大圆角框套小框、无数值伪进度条或山寨 App UI 多边形** | 在 `film/scenes/` 按 `storyboard.json` 指定的 `KT/DV` 代号编写 `1080×1920` 无容器化页面 |
| **C. 科技巨头发布新闻 / 产品报道 / 政策原文 / 真实界面** | 1. 找一手官方新闻稿/博客链接（`fetch_trends.py --mode search` 或 RSS 原文链接）<br>2. **抽官方高清无水印配图 + 截取干净官网/文件首屏**，入片挂 `PF6` 3D 透视聚光放大（严禁用代码手画假网页框代替真截图！）<br>3. **搜并截取官方发布会/Demo 3–6 秒单一连续短片段** | 抽图与截图：`"$SVP_PYTHON" .agents/.../fetch_asset.py news-page --url "<官方URL>" --out materials --screenshot`<br>搜官方视频：`fetch_asset.py video-search --query "Apple keynote official"`<br>精准切片：`fetch_asset.py video-clip --url "<URL>" --start 00:10 --end 00:16 --mute --out materials/demo.mp4` |
| **D. 通用实拍动态 B-roll / 行业作业实景 / 情绪空镜** | 1. 查 `openfilm get my-media`（但**严禁跨片改文件名重复使用同一视频，严禁拿欧美地标冒充本土城市**）<br>2. **优先补 2–4 段 2.5–5 秒真实运动视频（`.mp4`）**：已配免费 Key 用 OpenFilm 内置 Pexels / Pixabay（`--orientation portrait`）；未配 Key 用 `fetch_asset.py stock --kind video` 查公开免版权库<br>3. **入片前必抽首/中/尾三帧验货**（确保全段 `YAVG ≥ 18` 无黑屏头、`scdet < 16` 无内部二次硬切、零内嵌硬字幕水印）并统一挂载对应 `.cube` LUT | 配了免费 Key：`openfilm get video-search --prompt "warehouse logistics" --orientation portrait`<br>免 Key 优先视频：`"$SVP_PYTHON" .agents/.../fetch_asset.py stock --query "container port" --kind video --download 2 --out materials --assets film/assets` |
| **E. 抽象概念 / 搜不到的专属场景** | 1. Agent 自带生图能力（9:16 竖屏）或 OpenFilm 已接生图服务——入片采用 `PF7` 2.5D 景深视差合成，且**严禁将 9:16 竖图塞进 `>2.2×` 扁框造成截肢盲裁**<br>2. 生成视频（全片 ≤2 镜、每镜 ≤6 秒；付费须先获同意）<br>3. 失败或不可用则退回 **B 类 `KT/DV` 无框视觉模组** | Agent 生图 / `openfilm get image` / `openfilm get video` |

> **单次使用与感知哈希（`64-bit dHash`）去重铁律（硬拦截）**：在同一支成片内及入口 E 的 4 个槽位之间，每一份补充视觉素材（图片与视频 B-roll，品牌固定 Logo 与源口播视频除外）不仅文件名不得重复，且经 `qc_video.py` **中心区域 `64-bit dHash` 感知哈希检测汉明距离必须 `> 10`**——严禁把同一段视频微裁切或改两个名字塞进不同子片！

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
