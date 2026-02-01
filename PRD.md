# PRD: 招采中心采集（本地脚本 + SQLite）v1

版本: v1.0
日期: 2026-01-31
负责人: TBD

## 01 背景

当前流程在 n8n 中运行, 实现了“招采中心采集 -> 过滤 -> 查重 -> AI 总结 -> 飞书推送 -> 统计/告警”。
希望迁移为本地脚本稳定运行, 并把查重与数据沉淀落到本地 SQLite, 不依赖飞书多维表结构。

## 02 目标与成功标准

目标:
- 用本地脚本实现与 workflow_enhanced_v2.json 等价的核心功能与行为。
- 使用 SQLite 作为唯一数据源: 查重、历史记录、运行审计。
- 支持由系统 cron 定时触发(每天 8/12/16/20 点)。

成功标准(量化):
- 重复公告不重复通知, 不重复调用 AI(基于同一去重键)。
- 单次运行 10 条数据 < 120 秒(默认串行 + 1s 延迟)。
- 连续运行 7 天无人工干预(除网络/接口不可用等外部因素)。
- 致命异常时能发飞书告警(若配置 webhook)。

## 03 非目标(v1 不做)

- 并发抓取/并发 AI。
- 复杂反爬对抗(验证码/JS 渲染/登录态等)。
- Web 管理后台、可视化面板、分布式部署。

## 04 用户画像与使用场景

用户:
- 本地或服务器运维脚本的人(个人或小团队)。

场景:
- 定时跑脚本: 发现新公告 -> 生成摘要 -> 推送飞书群。
- 手动跑脚本: 排查是否漏采、验证配置。
- 出错告警: 收到飞书卡片 -> 快速定位问题。

## 05 业务规则(与 n8n 对齐)

数据源:
- 列表页: http://zpzb.zgpmsm.cn/qiye/index.jhtml
- 详情页: 列表中 href; 相对路径需补全域名 http://zpzb.zgpmsm.cn

解析规则:
- 列表解析:
  - title: ".list li a" text
  - link:  ".list li a" href
  - date:  ".list li span" text, 清理 '[' ']' 并 trim
- 详情正文:
  - content: ".article-content" (trim)

过滤规则:
- 日期过滤: 仅保留北京时间(Asia/Shanghai)最近 N 天的数据(默认 2 天: 今天/昨天), 输出标准化 YYYY-MM-DD
- 关键词过滤: 默认正则 (系统|软件|平台|大数据|AI|采购|招标) 匹配标题

去重规则(SQLite):
- 默认去重策略: title(与 n8n 的“标题 is”查重一致)
- 可配置: url 或 title_date(title+date)

节流与上限:
- 循环延迟: 默认 1 秒(可配置)
- 单次最大处理条数: 默认 50(可配置; 0 表示不限制)

大批量抓取节流:
- 当翻页次数超过阈值(默认 10)时, 每处理 50 条新增/重复记录, 循环延迟增加 1 秒(最大 10 秒), 以降低被限流风险。

AI 总结规则:
- API: https://api.yuweixun.site/v1 (endpoint: /chat/completions)
- model: llama-3.3-70b-versatile; temperature=0.5
- 输入正文: 压缩空白后截断前 4000 字符
- 输出: 200 字以内, 提取项目名称/预算金额/截止日期/关键联系人, 并总结核心需求
- 失败降级: 写入 "AI 总结失败", 不阻断整轮

飞书通知(可选):
- 新公告卡片: 标题、发布日期、AI 总结、原文按钮
- 统计摘要卡片: 执行时间、耗时、处理/新增/重复
- 错误告警卡片: 错误时间、错误信息、错误阶段(若可判定)

## 06 功能需求(FR)

FR-1 单次执行入口:
- 提供脚本命令, 可被 cron 调用
- 正常完成 exit code=0; 致命错误 exit code!=0

FR-2 SQLite 初始化与迁移:
- 首次运行自动建表与索引
- 记录 schema 版本(可选; v1 可简化为“表不存在则创建”)

FR-3 运行审计:
- 每次 run 记录: 开始/结束时间、耗时、processed/new/duplicate、状态、错误摘要

FR-4 dry-run:
- 只做采集/解析/过滤/查重/统计, 不抓详情/不调用 AI/不发飞书

FR-5 测试夹具模式:
- 支持读取 tests/sample_list.html 和 tests/sample_detail.html 离线验证

FR-6 可靠性机制:
- 列表页请求: 重试 3 次, 间隔 2s, 超时 30s
- 详情页请求: 重试 3 次, 间隔 2s, 超时 30s
- AI 请求: 重试 2 次, 间隔 3s, 超时 60s
- 飞书 webhook: 重试 2 次, 间隔 1s(可选)

## 07 数据设计(SQLite)

数据库文件:
- 默认: data/zhaocai.db(可配置)

表: announcements
- id INTEGER PRIMARY KEY
- title TEXT NOT NULL
- url TEXT NOT NULL
- date TEXT NOT NULL (YYYY-MM-DD)
- content TEXT NULL
- ai_summary TEXT NULL
- status TEXT NOT NULL (NEW/PROCESSED/FAILED)
- source TEXT NOT NULL DEFAULT 'zpzb.zgpmsm.cn'
- created_at TEXT NOT NULL (ISO8601)
- updated_at TEXT NOT NULL (ISO8601)

约束/索引:
- UNIQUE(title)
- INDEX(date)
- INDEX(status)

表: runs
- run_id TEXT PRIMARY KEY
- started_at TEXT NOT NULL
- finished_at TEXT NULL
- duration_seconds INTEGER NULL
- total_processed INTEGER NOT NULL
- total_new INTEGER NOT NULL
- total_duplicate INTEGER NOT NULL
- status TEXT NOT NULL (COMPLETED/FAILED)
- error TEXT NULL

## 08 配置设计(env/参数)

必需:
- AI_API_KEY

可选:
- FEISHU_WEBHOOK_URL(不提供则不推送, 仅本地日志)
- DB_PATH(默认 data/zhaocai.db)
- DEDUPE_STRATEGY(title|url|title_date; 默认 title)
- KEYWORD_REGEX(默认 (系统|软件|平台|大数据|AI|采购|招标))
- DAYS_LOOKBACK(最近N天, 默认 2)
- LOOP_DELAY(秒, 默认 1)
- MAX_ITEMS_PER_RUN(默认 50)
- HTTP_TIMEOUT_MS(默认 30000)
- AI_TIMEOUT_MS(默认 60000)
- DRY_RUN(true/false)
- USE_TEST_FIXTURES(true/false)

## 09 可观测性与日志

- 控制台输出关键阶段日志: 抓取、解析、过滤结果、每条处理(新增/重复/失败)、统计报告
- 不打印敏感信息(API Key、Webhook 全量)

## 10 异常与降级策略

- 列表页完全失败(重试后仍失败): run 标记 FAILED; 若配置飞书, 发送错误告警
- 单条详情页失败: 该条 status=FAILED; 继续处理下一条; run 仍可 COMPLETED(错误写入 runs.error)
- AI 失败: ai_summary 固定为 "AI 总结失败"; 不中断
- 飞书推送失败: 记录日志; 不中断(避免“通知失败导致采集失败”)

## 11 验收标准(AC)

- AC-1 空列表页: 正常结束, processed=0, exit 0
- AC-2 日期筛选: 仅 today/yesterday(含 [YYYY-MM-DD] 清理)
- AC-3 关键词过滤: 仅匹配标题进入逐条处理
- AC-4 去重: 同标题二次运行不抓详情/不调 AI/不发新卡片; duplicate 增加
- AC-5 AI 降级: AI 不可用时仍写库并完成 run; ai_summary 为固定失败文案
- AC-6 飞书推送(配置 webhook 时): 新卡片与“有新增才发摘要卡片”均可达
- AC-7 错误告警(配置 webhook 时): 致命错误触发告警卡片

## 12 测试用例(最小集合)

- 正常流程(使用 fixtures)
- 空数据
- 日期筛选(含不同格式)
- 关键词过滤
- 去重(二次运行)
- AI 失败降级(mock/断网)
- 网络超时重试(mock/配置极短 timeout)

## 13 发布与回滚

发布:
- 部署脚本 + 配置 env + 创建 cron

回滚:
- 停 cron; 保留 sqlite 数据用于排查

## 14 风险与开放问题

风险:
- 目标站点结构变更导致 CSS selector 失效
- 频繁请求触发限流/封禁(已用串行+延迟缓解)

开放问题:
- 去重键是否永远以 title 为准(v1 固定 title)
- FAILED 条目是否需要重试队列(v1 先不做)
