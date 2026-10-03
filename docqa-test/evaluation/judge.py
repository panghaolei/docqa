"""LLM-as-a-Judge：用大模型给 RAG 回答打分。

RAG 系统输出是自然语言，无法用 `==` 断言。工业界做法是用一个"裁判模型"
按固定维度打分（1~5 分）：
    · faithfulness（忠实度）：回答是否完全基于参考资料，有无编造；
    · relevance（相关性）  ：回答是否切题、是否真正解决了用户问题；
    · completeness（完整性）：是否覆盖了问题涉及的关键要点。

实现要点：
- 复用被测系统同一套 OpenAI 兼容协议（硅基流动），零额外依赖；
- 强制 JSON 输出 + 温度 0，降低判分随机性；
- 判分不可用时返回 None，由用例决定跳过而非失败（避免环境问题导致误报）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from core.logger import get_logger

log = get_logger("judge")

_JUDGE_PROMPT = """你是一名严格的 RAG 系统评测专家。请根据【参考资料】对【模型回答】进行打分。

评分维度（每项 1~5 分，整数）：
- faithfulness 忠实度：回答是否完全基于参考资料？出现参考资料中不存在的关键事实（编造）则不得超过 2 分。
- relevance 相关性：回答是否切中【用户问题】的核心，而非泛泛而谈。
- completeness 完整性：是否覆盖了问题所问的全部要点。

只输出 JSON，不要任何解释文字，格式如下：
{{"faithfulness": 5, "relevance": 5, "completeness": 5, "reason": "一句话依据"}}

【用户问题】
{question}

【参考资料】
{context}

【模型回答】
{answer}
"""


@dataclass
class JudgeScore:
    faithfulness: float
    relevance: float
    completeness: float
    reason: str = ""
    raw: str = ""
    error: Optional[str] = None

    @property
    def average(self) -> float:
        return round((self.faithfulness + self.relevance + self.completeness) / 3.0, 2)

    def __str__(self) -> str:  # pragma: no cover
        return (f"<JudgeScore faithfulness={self.faithfulness} relevance={self.relevance} "
                f"completeness={self.completeness} avg={self.average} reason={self.reason}>")


def _extract_json(text: str) -> Optional[Dict[str, Any]]:
    """从模型输出中稳健地提取 JSON（兼容 ```json 代码块与前后废话）。"""
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        brace = re.search(r"\{.*\}", text, re.S)
        candidate = brace.group(0) if brace else None
    if candidate is None:
        return None
    try:
        return json.loads(candidate)
    except Exception:
        return None


class LLMJudge:
    """基于 OpenAI 兼容接口的回答质量裁判。"""

    def __init__(self, base_url: str, api_key: str, model: str,
                 timeout: float = 60, temperature: float = 0.0):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.temperature = temperature
        self._client = None

    @property
    def available(self) -> bool:
        """判分能力是否可用（缺依赖或缺 Key 时不可用）。"""
        if not self.api_key:
            return False
        try:
            import openai  # noqa: F401
        except ImportError:
            return False
        return True

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(base_url=self.base_url, api_key=self.api_key,
                                  timeout=self.timeout)
        return self._client

    def score(self, question: str, answer: str,
              contexts: Sequence[str]) -> Optional[JudgeScore]:
        """返回评分；不可用或调用失败时返回 None（由调用方决定 skip）。"""
        if not self.available:
            return None
        context_text = "\n---\n".join(contexts) if contexts else "（无参考资料）"
        prompt = _JUDGE_PROMPT.format(question=question, context=context_text[:6000],
                                      answer=answer[:4000])
        try:
            client = self._get_client()
            resp = client.chat.completions.create(
                model=self.model,
                temperature=self.temperature,
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            content = resp.choices[0].message.content or ""
            parsed = _extract_json(content)
            if not parsed:
                return JudgeScore(0, 0, 0, raw=content, error="裁判模型未返回可解析 JSON")
            return JudgeScore(
                faithfulness=float(parsed.get("faithfulness", 0)),
                relevance=float(parsed.get("relevance", 0)),
                completeness=float(parsed.get("completeness", 0)),
                reason=str(parsed.get("reason", ""))[:300],
                raw=content,
            )
        except Exception as exc:  # pragma: no cover - 网络/限流等外部因素
            log.warning("LLM 判分失败：%s", exc)
            return JudgeScore(0, 0, 0, error=str(exc))


def aggregate(scores: List[JudgeScore]) -> Dict[str, float]:
    """把多条评分汇总为各维度均值。"""
    valid = [s for s in scores if s and s.error is None]
    if not valid:
        return {"count": 0, "avg": 0.0, "faithfulness": 0.0,
                "relevance": 0.0, "completeness": 0.0}
    n = len(valid)
    return {
        "count": n,
        "avg": round(sum(s.average for s in valid) / n, 2),
        "faithfulness": round(sum(s.faithfulness for s in valid) / n, 2),
        "relevance": round(sum(s.relevance for s in valid) / n, 2),
        "completeness": round(sum(s.completeness for s in valid) / n, 2),
    }
