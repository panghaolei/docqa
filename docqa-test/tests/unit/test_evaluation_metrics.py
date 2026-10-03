"""RAG 评测指标自检（纯单元测试）。

评测指标一旦算错，整套"质量门禁"就失去意义——甚至会把严重劣化的版本判为通过。
因此指标函数必须有独立的单元测试：先证明"尺子是准的"，再去量"东西"。
"""

from __future__ import annotations

import pytest

from evaluation import metrics

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------- #
# 文本归一化与匹配
# --------------------------------------------------------------------- #
def test_squash_ignores_whitespace_and_punctuation():
    """宽松匹配：空白与中英文标点不影响比对结果。"""
    assert metrics.squash("10 天") == metrics.squash("10天")
    assert metrics.squash("满 3 年，可享受 10 天") == metrics.squash("满3年可享受10天")


def test_contains_any_loose_matching():
    """关键词命中必须对空格、全角标点不敏感。"""
    assert metrics.contains_any("满 3 年可享受 10 天年假", ["15天", "10天"]) == "10天"
    assert metrics.contains_any("试用期为三个月", ["3个月", "三个月"]) == "三个月"
    assert metrics.contains_any("完全无关的回答", ["年假", "报销"]) is None


# --------------------------------------------------------------------- #
# 分位数
# --------------------------------------------------------------------- #
def test_percentile_matches_expected_values():
    data = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    assert metrics.percentile(data, 50) == 55.0
    assert metrics.percentile(data, 100) == 100
    assert metrics.percentile(data, 0) == 10
    assert metrics.percentile([], 95) == 0.0
    assert metrics.percentile([42], 95) == 42.0


def test_latency_stats_shape():
    stats = metrics.latency_stats([100, 200, 300, 400, 500])
    assert stats["count"] == 5
    assert stats["avg"] == 300.0
    assert stats["p50"] == 300.0
    assert stats["max"] == 500.0
    assert stats["p95"] >= stats["p50"]


# --------------------------------------------------------------------- #
# 命中率与引用准确率
# --------------------------------------------------------------------- #
def test_keyword_hit_rate_counts_correctly():
    records = [
        {"answer": "满 3 年可享受 10 天年假", "keywords": ["10天"]},
        {"answer": "加班费按 1.5 倍计算", "keywords": ["1.5倍"]},
        {"answer": "抱歉，未检索到相关内容", "keywords": ["3000元"]},
        {"answer": "培训预算为 3000 元", "keywords": ["3000元"]},
    ]
    assert metrics.keyword_hit_rate(records) == 0.75
    assert metrics.keyword_hit_rate([]) == 0.0


def test_citation_accuracy_handles_optional_source():
    records = [
        {"meta_refs": ["星云科技员工手册.txt"], "expected_source": "星云科技员工手册"},
        {"meta_refs": ["其他.docx"], "expected_source": "星云科技员工手册"},
        {"meta_refs": [], "expected_source": None},          # 不要求引用时视为命中
    ]
    assert metrics.citation_accuracy(records) == pytest.approx(2 / 3, abs=1e-3)


# --------------------------------------------------------------------- #
# 相似度与忠实度
# --------------------------------------------------------------------- #
def test_ngram_overlap_range():
    """n-gram Jaccard 相似度必须在 [0, 1]，且同源文本显著高于无关文本。"""
    same = metrics.ngram_overlap("员工满3年可以享受10天年假", "员工满3年可以享受10天年假")
    assert same == 1.0

    related = metrics.ngram_overlap("员工满3年可以享受10天年假", "满3年的员工年假为10天")
    unrelated = metrics.ngram_overlap("员工满3年可以享受10天年假", "今天杭州天气晴朗气温25度")
    assert 0.0 <= unrelated < related <= 1.0


def test_faithfulness_proxy_detects_fabrication():
    """忠实度代理：完全照抄参考资料的回答应远高于纯编造的回答。"""
    context = "新员工试用期为 3 个月，试用期工资为转正后工资的 80%。"

    grounded = metrics.faithfulness_proxy(context, [context])
    fabricated = metrics.faithfulness_proxy(
        "公司每年为员工提供股票期权，行权价为发行价的五折。", [context]
    )
    assert grounded == 1.0
    assert fabricated < 0.5
    assert metrics.faithfulness_proxy("", [context]) == 0.0
    assert metrics.faithfulness_proxy(context, []) == 0.0


def test_char_precision_recall_counts_expected_facts():
    text = "满 3 年可享受 10 天年假，满 5 年可享受 15 天年假。"
    stats = metrics.char_precision_recall(text, ["10天", "15天", "3000元"])
    assert stats["total"] == 3
    assert stats["found"] == 2
    assert stats["recall"] == pytest.approx(2 / 3, abs=1e-3)
