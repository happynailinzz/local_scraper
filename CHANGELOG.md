# Changelog

All notable changes to this project will be documented in this file.

## v0.3.0 - 2026-03-04

### 新增
- **多飞书群分发**：新增 `feishu_targets` 全局群列表管理，支持为每个群配置独立名称、Webhook URL 和关键词过滤正则
- **任务-群多选关联**：新建/编辑任务时可勾选推送目标群（多对多），不勾选则沿用全局 `FEISHU_WEBHOOK_URL`
- **按群独立关键词过滤**：群的 `keyword_regex` 非空时替换任务关键词，仅对该群生效；留空则接收全部匹配结果
- **WebUI 飞书群管理页** `/settings/feishu`：增删改启停，支持内联新建
- **调度器多目标分发**：每个关联群 fork 独立子进程，日志按群名前缀区分，整体状态汇总

### 数据库
- 新增 `feishu_targets` 表（target_id / name / webhook_url / keyword_regex / enabled）
- 新增 `task_feishu_targets` 关联表（task_id / target_id，多对多）

## v0.2.3

- Bump version, sync docker deployment config

## v0.2.x

- WebUI settings page: edit `.env` and AI model presets in browser
- Feishu digest card: collapsible items, chunked dispatch (10 items/card)
- Adaptive throttling for large scraping runs
- Task detail page: show FEISHU_NOTIFY_MODE and KEYWORDS_LABEL

## v0.1.2 - 2026-02-02

- Add China relay endpoint `POST /relay/zcpt/fetch` with Bearer auth
- Add overseas support to fetch `zcpt.zgpmsm.com.cn` via `ZCPT_RELAY_BASE_URL` / `ZCPT_RELAY_TOKEN`
- Document relay configuration and env vars

## v0.1.1

- Fix GHCR build context

## v0.1.0

- Initial local scraper implementation
- WebUI with Basic Auth
- Task scheduler (cron/interval)
