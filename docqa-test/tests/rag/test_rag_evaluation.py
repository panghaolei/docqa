"""RAG 质量评测与质量门禁（Golden Set + LLM-as-a-Judge）。

这是整套测试里最有"RAG 工程"味道的部分：
    大模型的输出是自然语言，`assert answer == "10 天"` 这种写法既脆弱又没意义。
    工程上要回答的问题是"回答**整体上**有多好"，于是需要：
        1. 构建评测集（Golden Set）：问题 + 期望关键事实 + 期望引用来源；
        2. 定义可量化的指标：关键词命中率、引用准确率、忠实度代理指标；
        3. 引入 LLM-as-a-Judge 给语义质量打分（忠实度 / 相关性 / 完整性）；
        4. 设置**质量门禁阈值**：指标低于阈值即判失败，阻止劣化版本合入。

一次评测跑完全部样本，后续所有断言共享同一份报告（避免重复调用大模型烧钱）。
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path

import pytest
import yaml

from conf.settings import PROJECT_ROOT
from core.logger import get_logger
from evaluation import metrics
from evaluation.judge import aggregate

pytestmark = [pytest.mark.rag, pytest.mark.timeout(900)]

log = get_logger("evaluation")

# 报告输出路径（同时作为测试产物，可直接写进简历的"评测报告"）
REPORT_PATH = PROJECT_ROOT / "reports" / "rag_evaluation.json"


# ===================================================================== #
# 数据与执行
# ===================================================================== #
@pytest.fixture(scope="module")
def eval_cases(settings) -> list[dict]:
    """加载评测集，并按配置抽样（固定随机种子保证可复现）。"""
    dataset_path = settings.path("evaluation.dataset", "evaluation/dataset.yaml")
    with dataset_path.open("r", encoding="utf-8") as f:
        cases = yaml.safe_load(f) or []

    max_cases = settings.get("evaluation.max_cases", 8)
    seed = settings.get("evaluation.sample_seed", 20260915)

    answerable = [c for c in cases if c.get("keywords")]
    out_of_domain = [c for c in cases if c.get("expect_no_answer")]

    if len(answerable) + len(out_of_domain) <= max_cases:
        selected = cases
    else:
        pick = random.Random(seed).sample(answerable, k=max(0, max_cases - len(out_of_domain)))
        selected = sorted(pick + out_of_domain, key=lambda c: c["id"])

    log.info("评测集加载完成：共 %d 条，本次执行 %d 条", len(cases), len(selected))
    return selected


@pytest.fixture(scope="module")
def evaluation_report(module_api, kb_doc, rag_ready, eval_cases, judge, settings) -> dict:  # noqa: ARG001
    """执行评测集并产出完整报告（模块级只跑一次）。"""
    records: list[dict] = []
    judge_scores = []

    for case in eval_cases:
        result = module_api.ask(case["question"])
        answer = result.answer
        record = {
            "id": case["id"],
            "category": case.get("category", ""),
            "question": case["question"],
            "answer": answer,
            "keywords": case.get("keywords") or [],
            "expected_source": case.get("expected_source"),
            "meta_refs": result.meta_refs,
            "hit_keyword": metrics.contains_any(answer, case.get("keywords") or []),
            "first_token_ms": round(result.first_token_ms or 0, 1),
            "total_ms": round(result.total_ms, 1),
            "token_count": result.token_count,
            "done": result.done,
            "error": result.error,
            "expect_no_answer": bool(case.get("expect_no_answer")),
            "must_not_contain": case.get("must_not_contain") or [],
        }
        record["citation_ok"] = bool(
            not case.get("expected_source")
            or case["expected_source"] in " ".join(result.meta_refs)
        )
        record["faithfulness_proxy"] = metrics.faithfulness_proxy(answer, [kb_source_text()])
        records.append(record)

        log.info("[%s] 命中=%s 引用=%s 首token=%sms 回答=%s",
                 case["id"], record["hit_keyword"], record["citation_ok"],
                 record["first_token_ms"], answer[:60].replace("\n", " "))

        # ---- LLM 判分：只对"可回答"的样本判分，控制调用成本 ----
        if judge.available and not record["expect_no_answer"]:
            score = judge.score(case["question"], answer, [kb_source_text()])
            if score and score.error is None:
                judge_scores.append(score)
                record["judge"] = {
                    "faithfulness": score.faithfulness,
                    "relevance": score.relevance,
                    "completeness": score.completeness,
                    "average": score.average,
                    "reason": score.reason,
                }

    answerable = [r for r in records if not r["expect_no_answer"]]
    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "doc": kb_doc.get("fileName"),
        "chunk_count": kb_doc.get("chunkCount"),
        "top_k": settings.get("rag.top_k"),
        "similarity_threshold": settings.get("rag.similarity_threshold"),
        "model": settings.get("judge.model"),
        "summary": {
            "case_count": len(records),
            "answerable_count": len(answerable),
            "keyword_hit_rate": metrics.keyword_hit_rate(answerable),
            "citation_accuracy": metrics.citation_accuracy(answerable),
            "faithfulness_proxy_avg": round(
                sum(r["faithfulness_proxy"] for r in answerable) / max(1, len(answerable)), 4
            ),
            "first_token_latency_ms": metrics.latency_stats(
                [r["first_token_ms"] for r in records]),
            "total_latency_ms": metrics.latency_stats([r["total_ms"] for r in records]),
            "judge": aggregate(judge_scores),
        },
        "cases": records,
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _print_report(report)
    return report


_KB_TEXT_CACHE: dict[str, str] = {}


def kb_source_text() -> str:
    """延迟加载知识库原文（避免模块导入时就依赖 doc_factory 的重依赖）。"""
    if "text" not in _KB_TEXT_CACHE:
        from utils.doc_factory import KB_TEXT

        _KB_TEXT_CACHE["text"] = KB_TEXT
    return _KB_TEXT_CACHE["text"]


def _print_report(report: dict) -> None:
    s = report["summary"]
    lines = [
        "",
        "=" * 78,
        "  RAG 评测报告",
        "=" * 78,
        f"  语料文档      : {report['doc']}（{report['chunk_count']} 个切片）",
        f"  检索参数      : Top-{report['top_k']} / 相似度阈值 {report['similarity_threshold']}",
        f"  样本数        : {s['case_count']}（其中可回答 {s['answerable_count']}）",
        f"  关键词命中率  : {s['keyword_hit_rate']:.1%}",
        f"  引用来源准确率: {s['citation_accuracy']:.1%}",
        f"  忠实度(代理)  : {s['faithfulness_proxy_avg']:.1%}",
        f"  首 token 时延 : 均值 {s['first_token_latency_ms']['avg']}ms / P95 "
        f"{s['first_token_latency_ms']['p95']}ms",
        f"  总时延        : 均值 {s['total_latency_ms']['avg']}ms / P95 "
        f"{s['total_latency_ms']['p95']}ms",
    ]
    j = s["judge"]
    if j.get("count"):
        lines.append(
            f"  LLM 判分      : 均分 {j['avg']}（忠实 {j['faithfulness']} / "
            f"相关 {j['relevance']} / 完整 {j['completeness']}）"
        )
    lines.append("-" * 78)
    lines.append(f"  {'ID':<5}{'命中':<6}{'引用':<6}{'首token(ms)':<14}{'结果':<6}问题")
    for r in report["cases"]:
        lines.append(
            f"  {r['id']:<5}{_mark(bool(r['hit_keyword']) or bool(r['expect_no_answer'])):<6}"
            f"{_mark(bool(r['citation_ok'])):<6}{r['first_token_ms']:<14}"
            f"{_mark(bool(r['done'])):<6}{r['question'][:38]}"
        )
    lines.append(f"  报告已写入: {REPORT_PATH}")
    lines.append("=" * 78)
    print("\n".join(lines))


def _mark(flag: bool) -> str:
    """用 ASCII 标记代替 ✓/✗：Windows GBK 控制台下不会因编码报错。"""
    return "OK" if flag else "NG"


# ===================================================================== #
# 质量门禁断言
# ===================================================================== #
def test_all_evaluation_questions_completed(evaluation_report):
    """完整性：评测集所有问题都必须拿到 done 事件（不允许中途断流）。"""
    failed = [r["id"] for r in evaluation_report["cases"] if not r["done"]]
    assert not failed, f"以下样本未正常结束：{failed}"


def test_keyword_hit_rate_meets_threshold(evaluation_report, settings):
    """门禁①：关键词命中率 ≥ 阈值（检索 + 生成的整体正确率）。"""
    actual = evaluation_report["summary"]["keyword_hit_rate"]
    limit = settings.get("thresholds.keyword_hit_rate", 0.75)
    assert actual >= limit, (
        f"关键词命中率 {actual:.1%} 低于门禁 {limit:.1%}，"
        f"请检查检索 Top-K / 相似度阈值 / Prompt 模板"
    )


def test_citation_accuracy_meets_threshold(evaluation_report, settings):
    """门禁②：引用来源准确率 ≥ 阈值（meta 事件必须给出正确文档名）。"""
    actual = evaluation_report["summary"]["citation_accuracy"]
    limit = settings.get("thresholds.citation_accuracy", 0.75)
    assert actual >= limit, f"引用来源准确率 {actual:.1%} 低于门禁 {limit:.1%}"


def test_faithfulness_proxy_is_acceptable(evaluation_report):
    """门禁③：忠实度代理指标——回答中的论断应能在语料中找到依据，防止幻觉。

    阈值 0.5 是启发式下限：低于此值通常意味着模型在大量自由发挥。
    """
    actual = evaluation_report["summary"]["faithfulness_proxy_avg"]
    assert actual >= 0.5, (
        f"忠实度代理指标 {actual:.1%} 偏低，回答可能大量脱离参考资料（幻觉风险）"
    )


def test_no_fabrication_on_out_of_domain_cases(evaluation_report):
    """门禁④：域外提问不得出现"禁用语料"中的编造内容。"""
    for record in evaluation_report["cases"]:
        if not record["expect_no_answer"]:
            continue
        for forbidden in record["must_not_contain"]:
            assert forbidden not in record["answer"], (
                f"样本 {record['id']} 出现编造内容 '{forbidden}'：{record['answer'][:200]}"
            )


def test_latency_percentiles_meet_threshold(evaluation_report, settings):
    """门禁⑤：问答 P95 时延 ≤ 阈值（大模型链路最容易劣化的指标）。"""
    p95 = evaluation_report["summary"]["total_latency_ms"]["p95"]
    limit = settings.get("thresholds.p95_latency_ms", 45000)
    assert p95 <= limit, f"问答 P95 时延 {p95}ms 超出预算 {limit}ms"


@pytest.mark.ai
def test_llm_judge_average_score_meets_threshold(evaluation_report, judge, settings):
    """门禁⑥：LLM-as-a-Judge 三维均分 ≥ 阈值（语义质量，替代人工作答）。"""
    if not judge.available:
        pytest.skip("未配置 SILICONFLOW_API_KEY 或未安装 openai，跳过 AI 判分")
    stats = evaluation_report["summary"]["judge"]
    if not stats.get("count"):
        pytest.skip(f"本次未产生有效判分结果（count=0），模型：{settings.get('judge.model')}")

    limit = settings.get("thresholds.judge_min_score", 3.0)
    assert stats["avg"] >= limit, (
        f"LLM 判分均分 {stats['avg']} 低于门禁 {limit}\n"
        f"  忠实度={stats['faithfulness']} 相关性={stats['relevance']} 完整性={stats['completeness']}"
    )


def test_evaluation_report_is_generated(evaluation_report):
    """工程化产出：评测结果必须落盘为 JSON，便于趋势对比与 CI 归档。"""
    assert REPORT_PATH.exists(), f"评测报告未生成：{REPORT_PATH}"
    data = json.loads(Path(REPORT_PATH).read_text(encoding="utf-8"))
    assert "summary" in data and "cases" in data
    assert len(data["cases"]) == len(evaluation_report["cases"])
