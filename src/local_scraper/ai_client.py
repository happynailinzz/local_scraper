from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .http_client import HttpClient


@dataclass(frozen=True)
class AiConfig:
    api_key: str
    base_url: str
    model: str
    temperature: float
    timeout_ms: int
    retry_count: int
    retry_interval_ms: int
    fallback_model: str = "llama-3.1-8b-instant"


class AiClient:
    def __init__(self, http: HttpClient, cfg: AiConfig):
        self._http = http
        self._cfg = cfg

    def summarize(self, content: str) -> str:
        clean = " ".join(content.split()).strip()
        clean = clean[:4000]
        return self._summarize_with_model(clean, self._cfg.model)

    def _summarize_with_model(self, clean: str, model: str) -> str:
        messages = [
            {
                "role": "system",
                "content": (
                    "你是一个专业的招投标分析助手，擅长从公告原文中提取项目关键信息，"
                    "输出适合直接发送到飞书机器人的结构化摘要。"
                    "你的目标不是复述原文，而是帮助用户快速判断项目是否值得跟进。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "请总结以下招投标公告内容，并输出结构化提要。\n\n"
                    f"公告原文：{clean}\n\n"
                    "要求：\n"
                    "1. 优先输出你真正关心的决策信息：采购内容/标的、预算/限价、采购单位或招标人、采购方式、报名截止时间、投标截止时间、开标时间、联系人及电话。\n"
                    "2. 如果原文出现应用场景、功能范围、建设内容、系统能力清单，必须优先提炼为‘采购内容’字段，并压缩成一句业务摘要。\n"
                    "3. 如果原文出现项目周期、交付周期、开发周期、质保期，也要优先输出为‘项目周期’或‘交货期/服务期/工期’字段。\n"
                    "4. 在不遗漏关键信息的前提下，再补充：项目编号、代理机构、标段/包号、实施地点、获取文件时间。\n"
                    "5. 如果某项原文未明确提及，不要编造，也不要写‘无’。\n"
                    "6. 输出使用中文，按多行结构化提要展示，每行一个字段。\n"
                    "7. 第一行必须是‘项目概要：’并用一句话概括采购标的，优先写设备/系统/材料/服务名称，不要泛泛写成‘某公司采购项目’。\n"
                    "8. 不要照抄公告原文的章节标题、编号串、表头、长句残片；不要把‘一、二、三、六、’之类章节编号带进结果。\n"
                    "9. 同类信息不要重复，例如已经有‘采购单位/招标人’，就不要再换个字段重复写采购人。\n"
                    "10. 总字数尽量控制在220字以内，但要优先保证重点字段完整。\n"
                    "11. 推荐格式示例：\n"
                    "项目概要：采购矿井人员定位系统升级及配套安装服务\n"
                    "项目编号：XM-2026-001\n"
                    "采购单位/招标人：平煤神马某矿业公司\n"
                    "代理机构：河南某招标代理有限公司\n"
                    "采购方式：公开招标\n"
                    "标段/包号：1标段\n"
                    "项目周期：开发部署8个月，质保2年\n"
                    "交货期/服务期/工期：签约后30日内完成供货安装\n"
                    "采购内容：人员定位系统、配套通信设备、安装调试\n"
                    "预算/限价：120万元\n"
                    "报名开始：2026-04-18 09:00\n"
                    "报名截止：2026-04-22 17:00\n"
                    "获取文件：2026-04-18至2026-04-22\n"
                    "投标截止：2026-04-25 09:30\n"
                    "开标时间：2026-04-25 09:30\n"
                    "实施地点：河南平顶山\n"
                    "联系人：张工 13800000000"
                ),
            },
        ]

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": self._cfg.temperature,
        }

        headers = {
            "Authorization": f"Bearer {self._cfg.api_key}",
            "Content-Type": "application/json",
        }

        url = self._cfg.base_url.rstrip("/") + "/chat/completions"
        try:
            data = self._http.post_json(
                url=url,
                headers=headers,
                payload=payload,
                timeout_ms=self._cfg.timeout_ms,
                retry_count=self._cfg.retry_count,
                retry_interval_ms=self._cfg.retry_interval_ms,
            )
        except Exception as e:  # noqa: BLE001
            if model == self._cfg.model and self._should_try_fallback(e):
                return self._summarize_with_model(clean, self._cfg.fallback_model)
            return "AI 总结失败"

        try:
            choices = data.get("choices") or []
            if not choices:
                return "AI 总结失败"
            msg = choices[0].get("message") or {}
            text = (msg.get("content") or "").strip()
            if not text:
                return "AI 总结失败"
            return _clean_summary_output(text)
        except Exception:  # noqa: BLE001
            return "AI 总结失败"

    def _should_try_fallback(self, error: Exception) -> bool:
        text = str(error).lower()
        return "429" in text or "rate_limit" in text or "rate limit" in text


def _clean_summary_output(text: str) -> str:
    cleaned_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _is_low_value_field_line(line):
            continue
        cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines).strip()
    return cleaned or "AI 总结失败"


def _is_low_value_field_line(line: str) -> bool:
    normalized_line = line.strip()
    if normalized_line.endswith("结构化提要：") or normalized_line.endswith("结构化摘要："):
        return True
    if normalized_line in {"以下是结构化提要：", "以下是结构化摘要：", "总结如下：", "结构化提要如下："}:
        return True
    if "：" not in line:
        return False
    key, value = line.split("：", 1)
    normalized = value.strip().lower()
    if normalized in {"无", "暂无", "未提及", "不详", "未知", "none", "n/a"}:
        return True
    return False
