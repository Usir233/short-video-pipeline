# CreatorHub 接口（分发相关）

依据：`creatorhub/app/main.py`。**核对时的提交：`a902546`**（v0.2.8，2026-11-18）。

CreatorHub 用的是最新版，本文件可能落后于它。每次发布前执行 `git -C creatorhub rev-parse --short HEAD`，和上面的提交号比较：

- 一致：直接按本文件做。
- 不一致：先对照源码重新核对本次要用的接口，再发布。至少核对 `creatorhub/app/main.py` 里的 `class PublishIn`、`class KeywordCollectionIn`、`class ShareDownloadIn` 的字段，以及 `/api/publish`、`/api/publish/upload`、`/api/publish/{tid}/run-now`、`/api/accounts` 这几个路由是否还在、行为是否变了。有变化就改本文件并把上面的提交号改成当前的；没变化也把提交号改成当前的。

- 地址：`http://127.0.0.1:8000`，只监听本机，默认不需要鉴权。
- 请求体和返回都是 JSON，上传文件除外。
- 平台标识：`douyin` 抖音、`xhs` 小红书、`shipinhao` 视频号、`kuaishou` 快手、`tiktok`。

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
curl -fsS -F "files=@runs/<目录>/final.mp4" http://127.0.0.1:8000/api/publish/upload
```

返回 `{"files":[{"path":"<服务端保存的绝对路径>","name":"final.mp4"}]}`。取 `path`。一个成片上传一次，三个平台共用这个 `path`。

### 2. 建发布任务

`POST /api/publish`，每个账号一个任务。

| 字段 | 必填 | 说明 |
|---|---|---|
| `account_id` | 是 | 来自「查账号」 |
| `media_type` | 是 | 视频填 `video`（默认值是 `images`，不填会错） |
| `media_paths` | 是 | `["<上一步的 path>"]` |
| `title` | 建议 | 视频号最多 16 字，其余最多 20 字，超出会被直接截断 |
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

**任务一建立，状态就是 `pending`。不填 `scheduled_at` 时，引擎会自动把它发出去，不需要再调别的接口。所以这一步就是提交发布。**

会被拒绝的情况：

| 返回 | 原因 |
|---|---|
| 400 请选择一个已登录的账号 | 账号 id 不存在或平台不支持 |
| 400 没有可用的媒体文件 | `media_paths` 里的文件不存在，先上传 |
| 400 该账号不可发布 | 抖音、视频号未登录；小红书没有创作者登录 |
| 422 | 小红书的文件校验没过（视频只能 1 个文件，不超过 1 GiB），或 `scheduled_at` 格式不对 |

### 3. 立即执行

`POST /api/publish/{id}/run-now`

这个请求会一直等到这条发布做完才返回，可能要几分钟，超时设长一些（例如 `curl -m 900`）。返回里有 `ok` 和 `error`。最终结果以下一步查到的 `status` 为准。

一个账号发完再发下一个。引擎本身也是串行发布的。

### 4. 查结果

`GET /api/publish?platform=<平台>`，按 id 倒序返回任务列表。

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

- `output_dir` 必须是绝对路径：相对路径会被当成相对 CreatorHub 的运行目录（`creatorhub/`）。运行时在工作区根目录用 `pwd` 现算，不要写死。
- `download: false` 只解析作品信息，不下载。
- `account_id` 可选，填了会用该账号的登录态去取，取不到时再加。
- 返回 `{ok, links, results[]}`。每个结果有 `ok`，失败时有 `error`。文件落在 `output_dir` 下，到那里找视频文件。

下载到的视频只用于拆解分析，不得再发布。

## 本流程不调用的接口

没有用户另外的明确要求，不要调：

- `POST /api/contents/{id}/repost-xhs`、`repost-douyin`、`repost-shipinhao`：把采集到的别人的作品转发到自己账号。
- 私信、评论、关注相关的接口。
- `DELETE /api/accounts/{id}`，以及改代理、改指纹、改浏览器内核的接口。
- `POST /api/accounts/{id}/clear-write-pause`：解除写暂停。暂停是风控保护，由用户决定。

## 尚未实测

以上接口的参数和行为都是从源码核对的。到 2026-11-18 为止，上传、建任务、执行发布、关键词采集、下载分享链接都还没有真正跑过。第一次跑的时候如果实际返回和这里写的不一样，以实际为准，并回来更新本文件。
