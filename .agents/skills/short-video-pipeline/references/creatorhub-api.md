# CreatorHub 接口（分发相关）

依据：`creatorhub/app/api/`（`publishing.py`、`accounts.py`、`collections.py`、`share_downloads.py`、`task_queue.py`、`account_works.py`、`published_notes.py`）及 `creatorhub/app/services/collections.py`（v0.3.2 起由原 `app/main.py` 按领域拆分）。**核对时的提交：`4f0ec85`**（v0.3.2+1，2026-11-22）。

CreatorHub 用的是最新版，本文件可能落后于它。每次发布前执行 `git -C creatorhub rev-parse --short HEAD`，和上面的提交号比较：

- 一致：直接按本文件做。
- 不一致：先对照源码重新核对本次要用的接口，再发布。至少核对 `creatorhub/app/api/publishing.py` 里的 `class PublishIn`、`creatorhub/app/services/collections.py` 里的 `class KeywordCollectionIn`、`creatorhub/app/api/share_downloads.py` 里的 `class ShareDownloadIn` 的字段，以及 `/api/publish`、`/api/publish/upload`、`/api/publish/{tid}/run-now`、`/api/accounts` 这几个路由是否还在、行为是否变了。有变化就改本文件并把上面的提交号改成当前的；没变化也把提交号改成当前的。

- 地址：`http://127.0.0.1:8000`，只监听本机，默认不需要鉴权。
- 全量实时接口文档：本文件只整理短视频分发最常用的核心接口；服务启动后，全部接口（v0.3.2 共 228 个路由）的实时 OpenAPI 规范位于 `http://127.0.0.1:8000/openapi.json`，可视化文档位于 `http://127.0.0.1:8000/docs`。需要查询本文件未列出的接口或精确字段时，直接按关键字检索 OpenAPI（无需通读源码）：
  ```bash
  curl -fsS http://127.0.0.1:8000/openapi.json | python3 -c "import sys,json; p=json.load(sys.stdin)['paths']; print('\n'.join(k for k in sorted(p) if 'publish' in k))"
  ```
- 请求体和返回都是 JSON，上传文件除外。
- 平台标识：`douyin` 抖音、`xhs` 小红书、`rednote` 海外小红书、`shipinhao` 视频号、`kuaishou` 快手、`tiktok`、`bilibili` 哔哩哔哩、`instagram`、`twitter`。

## Agent 调用方式（默认本机 API，异常时网页排查）

区分上下两层“API”，避免误判：

1. **Agent → CreatorHub（本机 REST API）**：正常流程下，无论发布抖音、小红书还是视频号，**一律优先调用本机 HTTP 接口**（`http://127.0.0.1:8000/api/...`），不要默认去操作前端页面。
2. **CreatorHub → 内容平台（内部传输通道）**：工作台「通道传输矩阵」（`/api/settings/transport-matrix`）里显示抖音、视频号发布「API 不可用 / 浏览器可用」、小红书默认走浏览器（原生身份账号亦强制走浏览器），指的是 **CreatorHub 内部与平台交互的方式**，不是本机 REST API 不可用。Agent 调用本机 `/api/publish` 和 `run-now` 后，CreatorHub 会自动在后台拉起账号隔离浏览器完成上传与发布（因此本机须保持有桌面环境，且小红书依赖系统 Google Chrome）。
3. **`http://127.0.0.1:8000` 网页端作为排查与兜底**：由于部分工作台诊断信息或交互状态未必完整暴露在 REST API 中，**当本机 API 不可用、报错信息不明、状态异常或接口能力不足时，允许并建议 Agent 打开 `http://127.0.0.1:8000` 前端工作台页面查看和点击排查原因**。通过网页端排查时仍须遵守相同红线：不删除账号、不改代理/指纹/浏览器内核、不强行解除写暂停、不重试或删除 `uncertain` 任务、不打印或外传敏感配置与 Cookie；遇到扫码登录或人机验证时停下请用户处理。

## 查账号

`GET /api/accounts?platform=<平台>`，不带参数返回全部。

用到的字段：

| 字段 | 含义 |
|---|---|
| `id` | 账号 id，建任务时用 |
| `platform`、`nickname` | 平台、昵称 |
| `status` | `active` 才可用；`invalid` 表示登录失效，需要用户重新登录 |
| `has_creator` | 小红书必须为 true 才能发布；为 false 时请用户在账号页做「创作者登录」 |
| `has_read_login` | 有浏览登录，采集和查热度要用 |
| `write_paused_until`、`write_pause_reason` | 写操作被暂停到什么时候、原因 |
| `risk_level`、`risk_cooldown_until`、`next_write_at` | 风控等级、冷却到什么时候、下次允许写的时间 |

可发布的条件：`status=active`，没有处在写暂停或风控冷却中；小红书还要 `has_creator=true`。不满足就跳过该平台并告诉用户，不要去调解除暂停的接口。

## 标准发布顺序

### 1. 上传成片

`POST /api/publish/upload`，multipart，字段名 `files`。

```bash
curl -fsS -F "files=@runs/<目录>/output/final.mp4" http://127.0.0.1:8000/api/publish/upload
```

返回 `{"files":[{"path":"<服务端保存路径>","name":"final.mp4"}]}`（实测通常为相对 `creatorhub/` 的路径，如 `data/uploads/xxx.mp4`）。**原样取 `path` 传给下一步的 `media_paths`，不要自行拼接或改写。**一个成片上传一次，三个平台共用这个 `path`。CreatorHub 把上传的副本存在 `creatorhub/data/uploads/`，也在工作区里。

### 2. 建发布任务

`POST /api/publish`，每个账号一个任务。

| 字段 | 必填 | 说明 |
|---|---|---|
| `account_id` | 是 | 来自「查账号」 |
| `media_type` | 是 | 视频填 `video`（默认值是 `images`，不填会错） |
| `media_paths` | 是 | `["<上一步的 path>"]` |
| `title` | 建议 | 抖音最多 30 字，视频号最多 16 字，哔哩哔哩最多 80 字，其余（小红书等）最多 20 字，超出会被直接截断 |
| `desc` | 建议 | 正文 |
| `topics` | 建议 | 话题，英文逗号分隔，不带 `#`，例如 `"生活常识,科普"` |
| `visibility` | 否 | `public`（默认）、`friends`、`private`，抖音有效 |
| `allow_save` | 否 | 抖音是否允许他人保存，默认 true |
| `location` | 否 | 视频号位置，最多 60 字 |
| `scheduled_at` | 否 | 定时发布，ISO 时间并带时区偏移，例如 `2026-11-19T20:00:00+08:00`。不填表示尽快发 |

可选请求头 `Idempotency-Key`：16–128 位，只含字母、数字和 `. _ : -`。同一个 key 加同样的内容再次提交，会返回原任务而不是新建。每个「成片 + 账号」用一个固定的 key，例如 `run-20261118-topic-douyin-1`，这样请求超时后重发不会建出两个任务。

```bash
curl -fsS -X POST http://127.0.0.1:8000/api/publish \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: run-<运行目录名>-<平台>-<账号id>' \
  -d '{"account_id":<账号id>,"media_type":"video","title":"…","desc":"…","topics":"a,b,c","media_paths":["<path>"]}'
```

返回任务对象，含 `id`、`status`、`platform`、`title`（已截断后的）、`scheduled_at` 等。

**任务一建立，状态就是 `pending`。不填 `scheduled_at` 时，后台引擎也会自动拉起执行，所以建任务就等于正式提交发布。**

为避免与后台调度器并发抢跑，**不要一次性把三个平台的任务都建完再逐个执行**，应按「逐平台串行」执行：完成步骤 1 一次上传后，对每个平台依次执行「建任务（步骤 2）→ 执行并等待终态（步骤 3，支持同步 `run-now` 或非阻塞轮询）→ 查最终状态（步骤 4）」，确认当前平台结束（或停在 `uncertain` / `failed`）后再建下一个平台的任务。

会被拒绝的情况：

| 返回 | 原因 |
|---|---|
| 400 请选择一个已登录的账号 | 账号 id 不存在或平台不支持 |
| 400 没有可用的媒体文件 | `media_paths` 里的文件不存在，先上传 |
| 400 该账号不可发布 | 抖音、视频号未登录；小红书没有创作者登录 |
| 422 | 小红书的文件校验没过（视频只能 1 个文件，不超过 1 GiB）、非小红书平台的媒体文件为空，或 `scheduled_at` 格式不对 |

### 3. 执行并等待完成（支持同步或非阻塞轮询）

单平台浏览器上传大视频并等待平台转码/回执，通常需要 2–5 分钟。按当前终端工具的超时特性二选一：

- **方式 A（支持长超时的终端）**：直接同步调用 `POST /api/publish/{id}/run-now`，超时设长一些（例如 `curl -m 900`），返回里有 `ok` 和 `error`。
- **方式 B（终端容易超时，如 Cursor 等 IDE，推荐）**：建完该平台任务后（不填 `scheduled_at` 时后台引擎会自动拉起；或用后台命令触发 `run-now`），**不要长时间阻塞终端**，每隔 15–30 秒调用 `GET /api/publish?platform=<平台>` 查看该任务的 `status` 与 `live_stage`（实时执行阶段），直到变为终态（`done` / `failed` / `uncertain` / `canceled`）。如果建完任务后引擎已自动进入 `publishing`，直接轮询等待即可，不要重复提交或重复建任务。

无论哪种方式，最终结果都以下一步查到的 `status` 为准。一个平台结束后再建、再执行下一个平台；引擎本身也是串行发布的。发布期间 CreatorHub 会自动拉起对应账号的隔离浏览器窗口，如遇滑块/扫码二次验证或 API 异常报错不明确，可访问 `http://127.0.0.1:8000` 工作台页面进一步排查原因，需要人工验证时通知用户处理。

### 4. 查结果

`GET /api/publish?platform=<平台>`，按 id 倒序返回任务列表。除下表状态外，任务对象还带 `live_stage`（实时执行阶段）、`error`、`result_url`、`blocked_reason`、`next_allowed_at`。

| `status` | 含义 | 怎么办 |
|---|---|---|
| `pending` | 在队列里 | 等。看 `blocked_reason` 和 `next_allowed_at`：有值说明被风控、代理、非活跃时段等原因推迟了，照实报告，任务留在队列里 |
| `publishing` | 正在发 | 等 |
| `done` | 成功 | `result_url` 是作品链接，可能为空 |
| `failed` | 确定没发出去 | 读 `error`。能判断原因并修正的，重试一次；仍失败就报告 |
| `uncertain` | 已经点了提交，但没拿到成功的证据 | **不要重试，不要删除，不要改**。告诉用户去平台后台核对 |
| `draft` | 旧的定时任务缺时区，需人工确认 | 本流程不会产生 |
| `canceled` | 已取消 | — |

### 5. 重试和修改

- 重试 `failed`：再调一次 `run-now`。
- 改文案后重发：`PUT /api/publish/{id}`，可改 `title`、`desc`、`topics`、`location`、`visibility`、`allow_save`、`scheduled_at`、`account_id`。只有 `draft`、`pending`、`failed`、`canceled` 状态能改。**改完状态会变回 `pending`，也就是会重新进入发布队列。**
- 删除任务：`DELETE /api/publish/{id}`。`publishing` 和 `uncertain` 状态会返回 409，不能删。

### 6. 人工核对结果待确认的任务

`POST /api/task-queue/publishes/{id}/resolve`，请求体 `{"outcome":"done" 或 "canceled","note":"核对说明"}`。

只有用户亲自去平台看过、并明确告诉你结果之后才能调。它只是记录核对结论，不会重发。

## 查队列

`GET /api/task-queue?queue_type=publishes&state=<状态>&platform=<平台>`

- `queue_type`：`publishes`、`collections`、`comments`、`actions`、`monitor_downloads`、`collection_downloads`
- `state`：`active`（默认）、`pending`、`running`、`blocked`、`failed`、`completed`、`all`

想看有没有别的任务正占着某个账号时用。

## 发布后查数据

| 接口 | 作用 |
|---|---|
| `POST /api/accounts/{账号id}/works/sync` | 打开账号主页，把已发布的作品同步进本地库 |
| `GET /api/account-works?account_id=<id>&limit=200` | 读已同步的作品和互动数据 |
| `GET /api/account-stats/{账号id}?days=30` | 账号每日粉丝、作品数、点赞、评论、播放的趋势 |
| `GET /api/publish/published?account_id=<id>` | 小红书已发布笔记列表，仅小红书 |

## 查热度（关键词采集）

用于步骤 1 查某个题在小红书的热度，和「参考爆款」时找点赞最高的视频。

`POST /api/collections`

```json
{
  "platform": "xhs",
  "account_id": <小红书账号id>,
  "keywords": ["关键词1", "关键词2"],
  "max_contents_per_keyword": 10,
  "search_sort": "most_liked",
  "publish_time": "week",
  "content_type": "video",
  "max_comments_per_content": 0,
  "download_media": false
}
```

- `platform`：`douyin`、`xhs`、`kuaishou`、`tiktok`。视频号的关键词搜索当前不可用。
- `account_id`：该平台一个有浏览登录的账号。
- `keywords`：最多 20 个，每个不超过 80 字。
- `search_sort`：`general`、`latest`、`most_liked`。`publish_time`：`all`、`day`、`week`、`half_year`。`content_type`：`all`、`video`、`images`。
- `max_contents_per_keyword` 1–100，`max_comments_per_content` 0–200。

然后：

- `GET /api/collections/{任务id}`：看 `status`（`pending`、`running`、`done`、`partial`、`failed`、`canceled`）和 `progress_percent`。
- `GET /api/collections/{任务id}/contents?page=1&page_size=20`：返回 `{items, total, pages}`，每条有 `desc`、`author_name`、`like_count`、`comment_count`、`media_type`、`url`。
- `POST /api/collections/{任务id}/cancel`：取消。

这是在用用户的账号搜索，关键词和条数都取小，不要反复跑。

## 下载分享链接（取参考视频）

`POST /api/share-download`

```json
{
  "share_text": "<链接或整段分享文案>",
  "download": true,
  "quality": "highest",
  "output_dir": "<工作区绝对路径>/runs/<目录>/ref",
  "save_metadata": true,
  "save_thumbnail": false,
  "account_id": <账号id>
}
```

- `output_dir` 必须是绝对路径：相对路径会被当成相对 CreatorHub 的运行目录（`creatorhub/`）。执行环境脚本后用 `$SVP_ROOT/runs/<目录>/ref` 现算，不要写死。必须指到本次运行目录的 `ref/`，不要用 CreatorHub 的默认下载位置。
- `download: false` 只解析作品信息，不下载。
- `account_id` 可选，填了会用该账号的登录态去取，取不到时再加。
- 返回 `{ok, links, results[]}`。每个结果有 `ok`，失败时有 `error`。文件落在 `output_dir` 下，到那里找视频文件。

下载到的视频只用于拆解分析，不得再发布。

## 本流程不调用的接口

没有用户另外的明确要求，不要调：

- `POST /api/contents/{id}/repost-xhs`、`repost-douyin`、`repost-shipinhao`、`repost-kuaishou`、`repost-tiktok`、`repost-bilibili`、`repost-rednote`、`repost-instagram`、`repost-twitter`：把采集到的别人的作品转发到自己账号。
- 私信、评论、关注相关的接口。
- `DELETE /api/accounts/{id}`，以及改代理、改指纹、改浏览器内核的接口。
- `POST /api/accounts/{id}/clear-write-pause`：解除写暂停。暂停是风控保护，由用户决定。

## 实测记录

- **已实测通过（2026-11-21）**：`GET /api/accounts`、`POST /api/publish/upload`、抖音发布（`POST /api/publish` + `run-now` 成功并拿到作品链接）、视频号发布提交（成功触发浏览器提交；遇结果未回执时按规范进入 `uncertain` 等待人工核对）。
- **待补充实测**：小红书实际视频发布（账号已具备 `has_creator=true`）、关键词采集（`/api/collections`）、下载分享链接（`/api/share-download`）。实际运行时如接口字段或返回行为与本文件有差异，以实际返回和 `creatorhub/app/api/` 源码为准，并同步更新本文件；若 API 报错不明或接口覆盖不全，可打开 `http://127.0.0.1:8000` 工作台页面辅助排查。
