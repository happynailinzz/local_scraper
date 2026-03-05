# local_scraper v0.3.0

一个本地/服务器均可运行的「招采信息采集 + 过滤 + 去重 + AI 总结 + 飞书多群分发 + WebUI + 定时任务」项目。

当前默认采集站点：
- `https://zcpt.zgpmsm.com.cn/jyxx/sec_listjyxx.html`

## 功能

- 采集交易信息/采购公告列表，自动翻页、多栏目并行发现
- 按关键词（支持正则）与最近 N 天过滤
- SQLite 落库与去重（可选：按 `title` / `url` / `title+date`）
- 详情页抽取正文，调用 AI 生成摘要（支持 OpenAI 兼容接口）
- **多飞书群分发**：全局维护群列表，任务可勾选推送目标，每个群支持独立关键词过滤
- 飞书卡片格式：`digest` 汇总卡片（含可折叠条目）或 `per_item` 逐条卡片
- WebUI：公告列表/详情、运行记录（实时日志 SSE）、任务管理、飞书群管理、设置页
- 海外服务器支持：通过国内中转节点访问 zcpt 站点（定向 Relay）

## 快速开始（本机）

### 1. 安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，至少配置：
#   AI_API_KEY          启用 AI 总结时必需（或设 AI_DISABLED=true 跳过）
#   FEISHU_WEBHOOK_URL  需要飞书推送时必需
#   WEBUI_USERNAME / WEBUI_PASSWORD  WebUI Basic Auth
```

也可在 WebUI 启动后访问 `/settings/init` 通过页面配置。

> **飞书多群分发**：`FEISHU_WEBHOOK_URL` 作为兜底全局 Webhook。如需按群分发，在 WebUI `/settings/feishu` 新建群后，在任务中勾选推送目标即可，无需修改 `.env`。

### 3. 运行一次采集

```bash
source .venv/bin/activate
AI_DISABLED=false python scripts/run.py \
  --days-lookback 7 \
  --keywords "采购,招标" \
  --max-items 10 \
  --loop-delay 1 \
  --log-level info
```

- `--max-items 0`：不限制条数
- `--keywords` 逗号分隔，自动转为 OR 正则；也可用 `--keyword-regex "(采购|招标)"`

### 4. 启动 WebUI

```bash
source .venv/bin/activate
python scripts/webui.py
# 访问 http://127.0.0.1:8000
```

WebUI 包含任务调度器，**需要常驻运行**才能执行定时任务。

## WebUI 功能说明

| 页面 | 功能 |
|------|------|
| **公告** `/announcements` | 搜索标题/链接，按日期范围、状态、AI 总结状态筛选；点击查看全文与摘要 |
| **运行记录** `/runs` | 查看历史 runs；"立即运行"支持实时日志（SSE） |
| **任务** `/tasks` | 新建/启停 cron（5 段）或 interval（秒）任务；新建时可勾选推送目标飞书群 |
| **飞书群管理** `/settings/feishu` | 增删改启停飞书群，每群可配独立关键词过滤 |
| **设置** `/settings/init` | 直接编辑 LIST_URL、AI 模型、飞书全局 Webhook 等核心配置，保存后立即生效 |

## 飞书多群分发

v0.3.0 新增功能，支持一次采集结果分发到多个飞书群。

### 使用方式

1. 打开 `/settings/feishu`，新建飞书群（填写群名、Webhook URL，可选关键词过滤）
2. 新建或编辑任务时，勾选要推送的目标群
3. 任务运行时，每个勾选的群会收到独立推送

### 关键词过滤策略

| 群的关键词配置 | 行为 |
|--------------|------|
| 留空 | 使用任务自身的关键词过滤 |
| 填写正则 | 用该正则替换任务关键词，仅对该群生效 |

**示例**：任务关键词为「采购」，群 A 留空（收到所有采购公告），群 B 填「软件」（只收含「软件」的公告）。

### 兜底行为

任务未勾选任何群时，沿用全局 `FEISHU_WEBHOOK_URL`，与旧版行为完全兼容。

## 配置参考

### 常用环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `AI_API_KEY` | — | 必需（`DRY_RUN=true` 或 `AI_DISABLED=true` 时除外）|
| `AI_BASE_URL` | `https://api.yuweixun.site/v1` | OpenAI 兼容接口 |
| `AI_MODEL` | `llama-3.3-70b-versatile` | 支持预设：`gpt-4o-mini`、`gpt-4.1-mini`、`deepseek-chat`、自定义 |
| `DAYS_LOOKBACK` | `2` | 最近 N 天，最小 1 |
| `KEYWORD_REGEX` | `(系统\|软件\|平台\|大数据\|AI\|采购\|招标)` | Python 正则 |
| `DEDUPE_STRATEGY` | `title` | `title` / `url` / `title_date` |
| `MAX_ITEMS_PER_RUN` | `50` | `0` = 不限制 |
| `MAX_PAGES_TOTAL` | `200` | 全局页数上限 |
| `MAX_PAGES_PER_CATEGORY` | `50` | 单栏目页数上限 |
| `FEISHU_NOTIFY_MODE` | `digest` | `digest`（汇总卡）或 `per_item`（逐条卡） |
| `FEISHU_CARD_IMAGE_URL` | — | digest 卡片头图（可选） |
| `WEBUI_PUBLIC_URL` | — | digest 卡片「查看全部」按钮跳转地址 |
| `KEYWORDS_LABEL` | — | 飞书卡片中显示的关键词标签（不填则显示正则原文） |

### 大批量自适应节流

当翻页次数超过阈值时自动启用，逐批增加请求延迟，降低被限流风险：

| 变量 | 默认值 |
|------|--------|
| `ADAPTIVE_DELAY_THRESHOLD_PAGES` | `10` |
| `BATCH_SIZE` | `50` |
| `DELAY_INCREMENT_SECONDS` | `1` |
| `MAX_LOOP_DELAY_SECONDS` | `10` |

日志关键字：`throttle.enabled`、`throttle.step`

## 海外服务器：ZCPT 中转（Relay）

海外服务器无法直接访问 `zcpt.zgpmsm.com.cn` 时，可用国内节点做定向中转。

**国内服务器（中转端）**——在已有的 WebUI 服务上开启：
```env
RELAY_ENABLED=true
RELAY_TOKEN=<长随机字符串>
```

**海外服务器（调用端）**：
```env
ZCPT_RELAY_BASE_URL=https://<国内WebUI域名>
ZCPT_RELAY_TOKEN=<同一份 RELAY_TOKEN>
```

中转接口 `POST /relay/zcpt/fetch` 仅转发到 `zcpt.zgpmsm.com.cn`，不是通用代理。建议仅对海外服务器 IP 放行该接口。

## 测试

```bash
# 单元测试
source .venv/bin/activate
pytest -q

# 单个测试文件
pytest tests/test_workflow.py -q

# AI 集成测试（需要真实 AI_API_KEY）
set -a; source .env; set +a
AI_DISABLED=false pytest -q -m integration
```

测试 fixtures（HTML 样本）在 `tests/fixtures/`，设置 `USE_TEST_FIXTURES=true` 可绕过真实 HTTP 请求。

## 服务器部署（Docker）

```bash
# 启动
docker-compose up -d

# 停止
docker-compose down
```

挂载 `data/`（SQLite）和 `logs/`（运行日志）以持久化数据。推荐在反向代理（如 1Panel Nginx）后启用 HTTPS，WebUI 本身保留 Basic Auth。

详细部署文档：`deploy/ubuntu-22.04-1panel.md`

## 版本发布

推送 tag 触发 GitHub Actions 自动构建并发布 GHCR 镜像：

```bash
git tag v0.3.0
git push origin v0.3.0
# → ghcr.io/<owner>/local-scraper:v0.3.0
# → ghcr.io/<owner>/local-scraper:latest
```

## 数据迁移

已存在任务补填 `KEYWORDS_LABEL`：

```bash
python scripts/migrate_keywords_label.py --db-path data/zhaocai.db
```
