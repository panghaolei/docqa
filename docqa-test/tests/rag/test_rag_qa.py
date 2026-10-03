"""RAG 问答端到端功能测试（单问题粒度）。

验证 RAG 全链路：``提问 → BGE 向量化 → Top-4 KNN 检索 → 拼装 RAG Prompt →
DeepSeek 流式生成 → 回答基于文档且可溯源``。

与 test_rag_evaluation.py 的分工：
    本模块关注"能不能答对、答得对不对"，逐条断言可读、失败易定位；
    评测模块关注"整体质量分数"，用评测集算指标并做质量门禁。
"""

from __future__ import annotations

import pytest

from core.assertions import assert_contains, assert_gte, assert_true

pytestmark = pytest.mark.rag

QUESTION_3Y = "入职满 3 年的员工每年可以享受多少天年假？"


# ===================================================================== #
# 一、事实正确性
# ===================================================================== #
def test_answer_contains_expected_fact(api, kb_doc, rag_ready):  # noqa: ARG001
    """核心能力：回答必须包含文档中的正确事实（满 3 年 = 10 天）。"""
    result = api.ask(QUESTION_3Y)
    assert_true(result.done, f"未正常结束：{result.error}")
    assert_contains(result.answer, "年假", ignore_case=False)
    assert any(token in result.answer for token in ["10 天", "10天", "十天"]), (
        f"回答未给出正确天数（应为 10 天）：{result.answer[:300]}"
    )


@pytest.mark.parametrize("question,expected", [
    ("工作日加班按几倍计算加班费？", ["1.5"]),
    ("法定节假日加班按几倍计算加班费？", ["3 倍", "3倍", "三倍"]),
    ("单笔报销超过多少钱需要财务总监审批？", ["5000"]),
    ("每位员工每年的培训预算是多少？", ["3000"]),
])
def test_multiple_facts_are_answered_correctly(api, kb_doc, rag_ready, question, expected):  # noqa: ARG001
    """多事实覆盖：覆盖数值、金额、倍数等不同类型的确定事实。"""
    result = api.ask(question)
    assert_true(result.done, f"未正常结束：{result.error}")
    assert_true(
        any(e in result.answer for e in expected),
        f"问题『{question}』的回答未包含期望值 {expected}：{result.answer[:300]}",
    )


def test_answer_is_grounded_and_cites_source(api, kb_doc, rag_ready):  # noqa: ARG001
    """可溯源性：回答应标注来源（系统提示词要求"注：来源：《文档名》"）。"""
    result = api.ask(QUESTION_3Y)
    citation_hints = ["来源", "文档", "星云科技员工手册", "手册"]
    assert_true(
        any(h in result.answer for h in citation_hints),
        f"回答未标注任何来源信息：{result.answer[:300]}",
    )


def test_out_of_domain_question_is_refused(api, kb_doc, rag_ready):  # noqa: ARG001
    """防幻觉：与文档无关的提问不得编造事实。"""
    result = api.ask("今天杭州的天气怎么样？气温多少度？")
    assert_true(result.done, f"未正常结束：{result.error}")

    import re
    fabricated_temp = re.search(r"\d{1,2}\s*(℃|摄氏|度)", result.answer)
    assert fabricated_temp is None, (
        f"域外提问出现编造的气温数据 '{fabricated_temp.group(0) if fabricated_temp else ''}'："
        f"{result.answer[:200]}"
    )


# ===================================================================== #
# 二、多轮上下文
# ===================================================================== #
def test_multi_turn_follow_up_uses_history(api, chat_session, kb_doc, rag_ready):  # noqa: ARG001
    """多轮对话：追问"那满5年呢"时，需结合上一轮语境理解（10 天 → 15 天）。"""
    first = api.ask(QUESTION_3Y, session_id=chat_session)
    assert_true(first.done, f"首轮失败：{first.error}")

    second = api.ask("那满 5 年的员工呢？", session_id=chat_session)
    assert_true(second.done, f"追问失败：{second.error}")
    assert any(t in second.answer for t in ["15 天", "15天", "十五天"]), (
        f"追问未正确利用上文语境：{second.answer[:300]}"
    )


def test_history_is_bounded_by_max_rounds(api, chat_session, kb_doc, settings, rag_ready):  # noqa: ARG001
    """上下文窗口：历史轮数受 docqa.history.max-rounds 限制，超出的旧消息不再进入 Prompt。

    这里通过"连续多轮后仍能正常回答"来间接验证裁剪逻辑不会破坏对话可用性。
    """
    max_rounds = settings.get("rag.history_max_rounds", 6)
    for i in range(max_rounds + 2):
        result = api.ask(f"第 {i + 1} 次提问：加班费怎么算？", session_id=chat_session)
        assert_true(result.done, f"第 {i + 1} 轮失败：{result.error}")

    messages = api.messages(chat_session).data
    assert_gte(len(messages), (max_rounds + 2) * 2, "多轮消息应全部落库")


# ===================================================================== #
# 三、稳定性
# ===================================================================== #
def test_repeated_question_returns_consistent_fact(api, kb_doc, rag_ready):  # noqa: ARG001
    """稳定性：同一问题重复提问三次，核心事实必须保持一致（温度 0.3 下不应漂移）。"""
    hits = 0
    for _ in range(3):
        answer = api.ask(QUESTION_3Y).answer
        if any(t in answer for t in ["10 天", "10天", "十天"]):
            hits += 1
    assert_gte(hits, 2, f"3 次提问中仅 {hits} 次给出正确事实，回答稳定性不足")


def test_answer_is_markdown_formatted(api, kb_doc, rag_ready):  # noqa: ARG001
    """输出格式：回答应为 Markdown（前端用 marked + DOMPurify 渲染）。

    只要求出现结构化特征（列表 / 标题 / 加粗），避免对具体排版过度约束。
    """
    result = api.ask("请汇总一下公司的假期制度有哪些种类？")
    markdown_hints = ["\n- ", "\n* ", "\n1.", "**", "##", "\n| "]
    assert_true(
        any(h in result.answer for h in markdown_hints),
        f"回答缺少 Markdown 结构特征：{result.answer[:300]}",
    )


def test_different_questions_produce_different_answers(api, kb_doc, rag_ready):  # noqa: ARG001
    """区分度：不同问题应得到不同回答，避免"检索失效导致回答千篇一律"。"""
    a1 = api.ask("年假怎么规定？").answer
    a2 = api.ask("报销流程是怎样的？").answer
    assert_true(a1.strip() != a2.strip(), "两个不同问题的回答完全相同，检索可能已失效")
