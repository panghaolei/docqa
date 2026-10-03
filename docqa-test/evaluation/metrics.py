"""RAG 评测指标（纯函数实现，无外部依赖，便于单元自测）。

分为三类：
1. 检索指标：引用来源是否命中期望文档（citation_accuracy）；
2. 生成指标：关键词命中率、答案可信度代理指标（faithfulness_proxy）；
3. 性能指标：延迟分位数统计（latency_stats）。

注：faithfulness_proxy 是"低成本近似"，用于日常回归；
真实可信度由 LLM-as-a-Judge（evaluation/judge.py）给出，两者互补。
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, Iterable, List, Sequence

_PUNCT = re.compile(r"[\s\u3000，。、；：？！,.;:?!\"'“”‘’()（）【】\[\]<>《》\-—_*#`|]+")


def squash(text: str) -> str:
    """去掉所有空白与标点，用于宽松匹配（"10 天" 与 "10天" 视为等价）。"""
    return _PUNCT.sub("", text or "").lower()


def percentile(values: Sequence[float], p: float) -> float:
    """线性插值分位数（p 取 0~100）。"""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (p / 100.0) * (len(ordered) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return float(ordered[low])
    return float(ordered[low] + (ordered[high] - ordered[low]) * (rank - low))


def latency_stats(values: Iterable[float]) -> Dict[str, float]:
    """延迟统计：均值 / P50 / P90 / P95 / P99 / 最大最小。"""
    data = [float(v) for v in values if v is not None]
    if not data:
        return {"count": 0, "avg": 0.0, "p50": 0.0, "p90": 0.0,
                "p95": 0.0, "p99": 0.0, "min": 0.0, "max": 0.0}
    return {
        "count": len(data),
        "avg": round(sum(data) / len(data), 1),
        "p50": round(percentile(data, 50), 1),
        "p90": round(percentile(data, 90), 1),
        "p95": round(percentile(data, 95), 1),
        "p99": round(percentile(data, 99), 1),
        "min": round(min(data), 1),
        "max": round(max(data), 1),
    }


def contains_any(text: str, keywords: Sequence[str], loose: bool = True) -> str | None:
    """返回第一个命中的关键词；``loose=True`` 时忽略空白与标点。"""
    if loose:
        haystack = squash(text)
        for kw in keywords:
            if squash(kw) in haystack:
                return kw
        return None
    for kw in keywords:
        if kw in text:
            return kw
    return None


def keyword_hit_rate(records: Sequence[Dict[str, Any]]) -> float:
    """关键词命中率 = 命中问题数 / 总问题数。

    records: [{"answer": str, "keywords": [...]}, ...]
    """
    if not records:
        return 0.0
    hit = sum(1 for r in records if contains_any(r.get("answer", ""), r.get("keywords", [])))
    return round(hit / len(records), 4)


def citation_accuracy(records: Sequence[Dict[str, Any]]) -> float:
    """引用来源准确率 = 期望来源出现在 meta 事件中的问题数 / 总问题数。"""
    if not records:
        return 0.0
    hit = 0
    for r in records:
        expected = r.get("expected_source")
        refs = " ".join(r.get("meta_refs") or [])
        if not expected or expected in refs:
            hit += 1
    return round(hit / len(records), 4)


def char_ngrams(text: str, n: int = 2) -> set:
    normalized = squash(text)
    if len(normalized) < n:
        return {normalized} if normalized else set()
    return {normalized[i:i + n] for i in range(len(normalized) - n + 1)}


def ngram_overlap(a: str, b: str, n: int = 2) -> float:
    """字符 n-gram Jaccard 相似度，用于快速判断两段文本是否同源。"""
    ga, gb = char_ngrams(a, n), char_ngrams(b, n)
    if not ga or not gb:
        return 0.0
    inter = len(ga & gb)
    union = len(ga | gb)
    return round(inter / union, 4) if union else 0.0


def ngram_containment(a: str, b: str, n: int = 2) -> float:
    """字符 n-gram 覆盖率（containment）：a 的 n-gram 中有多少比例出现在 b 中。

    用于忠实度衡量：分母是「待检验句子」自身，避免参考文本过长时
    Jaccard 的分母被并集撑大、导致指标恒接近 0 的问题。
    """
    ga, gb = char_ngrams(a, n), char_ngrams(b, n)
    if not ga:
        return 0.0
    inter = len(ga & gb)
    return round(inter / len(ga), 4)


def _split_sentences(text: str) -> List[str]:
    parts = re.split(r"[。！？；\n]", text or "")
    return [p.strip() for p in parts if len(p.strip()) >= 6]


def faithfulness_proxy(answer: str, contexts: Sequence[str],
                       threshold: float = 0.30) -> float:
    """忠实度代理指标：回答中"能在检索片段找到依据"的句子占比。

    注意这是启发式指标，不是学术意义上的 faithfulness，
    但足以在 CI 中快速发现"模型开始编造"的回归。
    """
    sentences = _split_sentences(answer)
    if not sentences:
        return 0.0
    if not contexts:
        return 0.0
    grounded = 0
    for sent in sentences:
        if any(ngram_containment(sent, ctx) >= threshold for ctx in contexts):
            grounded += 1
    return round(grounded / len(sentences), 4)


def char_precision_recall(text: str, expected_facts: Sequence[str],
                          unit: int = 10) -> Dict[str, float]:
    """生成质量的细粒度参考：期望事实被包含的比例。"""
    if not expected_facts:
        return {"recall": 0.0, "found": 0.0, "total": 0.0}
    found = sum(1 for fact in expected_facts if squash(fact) in squash(text))
    return {
        "recall": round(found / len(expected_facts), 4),
        "found": float(found),
        "total": float(len(expected_facts)),
    }
