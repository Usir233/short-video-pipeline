# CreatorHub 使用约定与文档索引

本文件**不再手工抄写和维护** CreatorHub 的具体接口字段、各平台专属参数或版本提交号，避免随上游更新漂移。接口定义和平台能力一律以工作区内的 `creatorhub/` 文档、源码和运行中的实时 OpenAPI 为准。

## 权威文档与接口入口（相对路径，随上游更新自动生效）

- **项目总览与平台能力**：`creatorhub/README.md`
- **完整使用手册与各平台限制**：`creatorhub/guide/platforms.json`、`creatorhub/guide/index.html`、`creatorhub/guide/README.md`
- **实时全量接口与字段 Schema（首选，无需翻源码）**：服务启动后直接查 `http://127.0.0.1:8000/openapi.json`（可视化文档：`http://127.0.0.1:8000/docs`）。按关键字查路径与字段示例：
  ```bash
  curl -fsS http://127.0.0.1:8000/openapi.json | python3 -c "import sys,json; s=json.load(sys.stdin); print('\n'.join(k for k in sorted(s['paths']) if 'publish' in k))"
  ```
- **按需单文件源码入口**（仅在 `/openapi.json` 看不清具体校验逻辑或平台专属支持边界时按明确路径读取，切勿全目录扫描）：
  - 路由总表：`creatorhub/app/api/__init__.py`（及 `creatorhub/app/api/` 下对应单文件，如 `publishing.py`、`accounts.py`、`task_queue.py`、`collections.py`、`share_downloads.py`、`account_works.py`）
  - 传输通道矩阵：`creatorhub/app/transport_matrix.py`（或实时 `GET /api/settings/transport-matrix`）
  - 各平台发布实现：`creatorhub/app/platforms/` 下对应平台目录（如 `douyin/`、`xhs/`、`channels/`）

## Agent 调用方式（默认本机 API，异常时网页排查）

1. **优先调用本机 REST API**：服务监听 `http://127.0.0.1:8000`（默认无鉴权，JSON 交互，上传文件除外）。无论发布抖音、小红书还是视频号，一律优先通过本机 HTTP 接口操作。
2. **区分两层“API”**：工作台传输矩阵里显示的「抖音/视频号 API 不可用、浏览器可用」或小红书默认走浏览器，指的是 **CreatorHub 内部与内容平台的交互通道**，不是本机 REST API 不可用。调本机发布接口后，CreatorHub 会自动拉起账号隔离浏览器完成上传提交（需保持本机有桌面环境，小红书依赖系统 Google Chrome）。
3. **`http://127.0.0.1:8000` 网页端兜底排查**：当本机 API 不可用、报错信息不明确或接口未覆盖某项诊断/界面状态时，**允许并建议 Agent 访问 `http://127.0.0.1:8000` 前端工作台页面查看和点击排查原因**。网页排查仍须遵守下方全部安全红线；遇到扫码登录或人机验证时停下通知用户。

## 本工作区核心流程约定

具体请求参数、字数上限与响应字段，以 `/openapi.json` 和 `creatorhub/app/api/` 为准；这里只规定本流水线必须遵守的执行顺序与注意事项：

### 1. 查账号（发布/采集前必查）
- 调 `GET /api/accounts`（可按 `platform` 过滤）动态获取 `account_id`，不写死。
- 可发布前提：`status=active`、无写暂停/风控冷却；小红书还须具备创作者登录（`has_creator=true`）。不满足则跳过该平台并在汇报中说明，**不得解除写暂停**。

### 2. 标准发布顺序（审核门禁 + 一次上传 + 逐平台串行）
0. **发布前审核（强制门禁）**：调用 `POST /api/publish` 建任务前，**必须先按 [publish-audit.md](publish-audit.md) 完成逐平台发布前审核**（媒体、文本、话题、合规、账号及各平台标题符号/字数等硬性表单校验），并落盘审核结论；未通过硬性项的平台不得建任务。
1. **上传成片**：`POST /api/publish/upload`（multipart 字段 `files`）。一个成片只上传一次，三平台共用返回的 `path`；**原样透传服务端返回的 `path`，不要自行拼接或改写**。
2. **逐平台串行建任务与等待终态**：
   - 调 `POST /api/publish` 建单个平台任务（视频传 `media_type: "video"`，建议带固定请求头 `Idempotency-Key: run-<运行目录名>-<平台>-<账号id>` 防重）。
   - 不填 `scheduled_at` 时任务建立即进入队列并可能被后台引擎自动拉起。**不要一次性建完多个平台任务再批量触发**，应一个平台完成（到达终态）后再建下一个平台。
   - **等待方式二选一**（单平台浏览器上传通常需 2–5 分钟）：
     - 长超时终端：可同步调 `POST /api/publish/{id}/run-now`（如 `curl -m 900`）；
     - 短超时终端（如 Cursor 等 IDE，推荐）：建完任务后不死卡终端，每隔 15–30 秒轮询 `GET /api/publish?platform=<平台>` 检查 `status` 与 `live_stage`，直到进入终态。
3. **结果与异常处理**：
   - `done`：记录 `result_url`（可能为空）。
   - `failed`：读 `error`，能明确修正原因时可重试一次，仍失败则报告。
   - `uncertain`（已点提交但无明确成功回执）：**严禁重试、删除或修改**，立即停下请用户去平台后台核对；只有用户亲自确认并明确告知结果后，才能调 `POST /api/task-queue/publishes/{id}/resolve` 记录结论。
   - 需检查同账号是否被其他任务占用时，查 `GET /api/task-queue`。

### 3. 查热度（关键词采集）与下载参考视频
- **查热度**：通过 `/api/collections` 相关接口发起轻量关键词采集（使用用户登录态，关键词数与条数尽量取小，不要反复跑）。
- **下载分享链接**：通过 `POST /api/share-download` 下载参考视频；`output_dir` 必须传工作区运行目录的绝对路径（执行 `env.sh` 后用 `$SVP_ROOT/runs/<目录>/ref` 现算），不得使用 CreatorHub 默认目录。下载到的视频仅用于拆解分析，不得再发布。
- **发布后查数据**：按需从 `/openapi.json` 查询 `works/sync`、`account-works`、`account-stats` 等接口。

## 本流程禁止调用的操作（红线）

没有用户另外的明确要求，无论通过 API 还是 `8000` 网页端，都不得执行：

- 转发他人采集作品到自己账号（`/api/contents/*/repost-*`）。
- 发私信、评论、点赞、关注/取关等社交互动写操作。
- 删除账号，或修改代理、指纹、浏览器内核设置。
- 解除写暂停（`clear-write-pause`）——暂停是风控保护，由用户决定。
- 读取、打印或外传 `creatorhub/data/`、`creatorhub/config.yaml`、浏览器 Profile 与 Cookie。
