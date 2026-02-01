# local_scraper

一个本地/服务器均可运行的“招采信息采集 + 过滤 + 去重 + AI 总结 + 飞书推送 + WebUI + 定时任务”项目。

当前默认采集站点：
- `https://zcpt.zgpmsm.com.cn/jyxx/sec_listjyxx.html`

## 1. 你能用它做什么

- 采集“交易信息/采购公告”等栏目列表，自动翻页
- 按关键词与“最近 N 天”过滤
- SQLite 落库与去重（可选：按 title / url / title+date）
- 详情页抽取正文，调用 AI 生成摘要
- 可选推送到飞书群机器人
- WebUI：公告列表/详情、运行记录、任务管理（cron/interval）
- 任务：新建/启停/立即运行/停止/状态监控/实时日志（SSE）

## 2. 快速开始（本机）

### 2.1 安装依赖

```bash
cd "/Users/ethanyu/Downloads/CLI/n8n招采中心采集/local_scraper"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2.2 配置环境变量

不要把密钥提交到仓库。使用 `.env`：

```bash
cp .env.example .env
```

至少配置：
- `AI_API_KEY`（启用 AI 总结时必需）
- `FEISHU_WEBHOOK_URL`（需要飞书推送时必需）
- `WEBUI_USERNAME` / `WEBUI_PASSWORD`（WebUI Basic Auth）

### 2.3 运行一次采集（命令行）

```bash
source .venv/bin/activate
AI_DISABLED=false python scripts/run.py --days-lookback 7 --keywords "采购" --max-items 10 --loop-delay 1 --log-level info
```

说明：
- `--max-items 0` 表示不限制；建议先小一点验证
- `AI_DISABLED=false` 启用 AI 总结

### 2.4 启动 WebUI

```bash
source .venv/bin/activate
python scripts/webui.py
```

访问：
- `http://127.0.0.1:8000`

## 3. 常用参数与配置

### 3.1 过滤与去重

- 最近 N 天：`DAYS_LOOKBACK=7` 或 `--days-lookback 7`
- 关键词：
  - `--keywords "采购,招标"`（逗号分隔，自动转为 OR 正则）
  - 或 `--keyword-regex "(采购|招标)"`
- 去重策略：`DEDUPE_STRATEGY=title|url|title_date` 或 `--dedupe-strategy ...`

### 3.2 分页上限（建议调小）

新站点分页很多，建议限制：
- `MAX_PAGES_TOTAL=80`（全局最多抓取页数）
- `MAX_PAGES_PER_CATEGORY=50`（单栏目最多翻页数）

### 3.3 大批量自适应节流

当本次采集“翻页次数 > 阈值”时启用节流：每处理一批增加延迟，降低限流风险。

- `ADAPTIVE_DELAY_THRESHOLD_PAGES=10`
- `BATCH_SIZE=50`
- `DELAY_INCREMENT_SECONDS=1`
- `MAX_LOOP_DELAY_SECONDS=10`

日志里会看到：
- `list.collected ... page_turns=...`
- `throttle.enabled ...`
- `throttle.step ...`（每批一次）

### 3.4 飞书通知模式

- `FEISHU_NOTIFY_MODE=digest|per_item`
  - `digest`：单次运行只发一张汇总卡片（首条展开 + 其余列表 + 可选“查看全部”按钮）
  - `per_item`：每条新增都发卡片，最后再发统计卡片
- `FEISHU_CARD_IMAGE_URL`：digest 卡片头图 URL（可选）
- `WEBUI_PUBLIC_URL`：digest 模式下用于“查看全部”按钮跳转到 WebUI 列表

## 4. WebUI 使用说明

### 4.1 公告

- 支持搜索（标题/链接）
- 支持日期范围、状态筛选
- 支持 AI 总结筛选：有总结/失败/为空
- 列表显示 AI 预览，点击进入详情查看全文与 AI 摘要

### 4.2 运行记录

- 查看历史 runs（来自 SQLite）
- WebUI 启动的“立即运行”支持实时日志（SSE）

### 4.3 任务（定时/周期）

- 新建任务：cron（5段）或 interval（秒）
- 启用/停用任务
- 立即运行、停止任务
- 任务详情页可查看实时日志与最近一次运行状态
- 任务详情页显示 `FEISHU_NOTIFY_MODE` 与 `KEYWORDS_LABEL`

说明：任务调度器运行在 WebUI 进程内，因此 WebUI 需要常驻运行。

已存在任务的 KEYWORDS_LABEL 回填：
```bash
python scripts/migrate_keywords_label.py --db-path data/zhaocai.db
```

## 5. 测试

单元测试：
```bash
source .venv/bin/activate
pytest -q
```

AI 集成测试（需要 `AI_API_KEY`，并确保 `AI_DISABLED=false`）：
```bash
source .venv/bin/activate
set -a; source .env; set +a
AI_DISABLED=false pytest -q -m integration
```

## 6. 服务器部署（Ubuntu 22.04 + 1Panel）

推荐 Docker 部署，见：
- `deploy/ubuntu-22.04-1panel.md`

关键点：
- 使用 GHCR 镜像（版本管理）或直接从 Git 项目构建
- 挂载 `data/` 与 `logs/` 以持久化 SQLite 与日志
- 用 1Panel 反代 + HTTPS；WebUI 仍有 Basic Auth

## 7. 版本发布（GitHub + GHCR）

推送 tag（例如 `v0.1.0`）会触发：
- GitHub Release
- GHCR 镜像构建与推送：`ghcr.io/<owner>/local-scraper:v0.1.0` 和 `:latest`

相关 workflow：
- `.github/workflows/release.yml`
- `.github/workflows/docker-ghcr.yml`
