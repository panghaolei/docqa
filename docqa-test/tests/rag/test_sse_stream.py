"""SSE 流式问答协议测试（前端体验的核心）。

被测接口：``POST /api/chat/ask/stream``（text/event-stream）
事件协议：
    event: session → data: <sessionId>
    event: meta    → data: <引用文档名，逗号分隔>
    event: token   → data: <增量文本>（多次）
    event: done    → data: [DONE]
    : keep-alive   （每 15s 一条注释帧，用于防代理超时）

断言维度：
    1. 事件类型与顺序（协议正确性）
    2. 首 token 时延、总时长、生成吞吐（用户体验可量化）
    3. token 拼接后的完整回答是否正确
    4. 会话延续性（同一 sessionId 多轮对话）
"""

from __future__ import annotations

import pytest

from core.assertions import (
    assert_contains,
    assert_equal,
    assert_gte,
    assert_lte,
    assert_true,
)

pytestmark = [pytest.mark.rag, pytest.mark.smoke]

QUESTION = "入职满 3 年的员工每年可以享受多少天年假？"


# ===================================================================== #
# 一、事件协议
# ===================================================================== #
def test_sse_event_sequence_is_protocol_compliant(api, rag_ready):
    """事件顺序必须严格为 session → meta → token… → done。"""
    result = api.ask(QUESTION)

    assert_true(result.http_status == 200, f"HTTP 状态码应为 200，实际 {result.http_status}")
    assert_true(result.error is None, f"流式读取异常：{result.error}")
    assert_true(result.done, "未收到 done 事件，流可能被截断")

    events = result.event_order
    assert_gte(len(events), 3, "事件总数")
    assert_equal(events[0], "session", "首个事件")
    assert_equal(events[-1], "done", "末个事件")
    assert_equal(events[1], "meta", "第二个事件")

    token_events = [e for e in events if e == "token"]
    assert_gte(len(token_events), 1, "token 事件数量")
    # done 之前必须全部是 token，不允许出现未知事件类型
    unknown = [e for e in events if e not in ("session", "meta", "token", "done")]
    assert_equal(unknown, [], "出现了未定义的事件类型")


def test_session_event_carries_numeric_session_id(api, rag_ready):
    """session 事件必须携带可用的数字型会话 ID（前端据此续聊）。"""
    result = api.ask(QUESTION)
    assert result.session_id is not None, "缺少 session 事件"
    assert_true(result.session_id.isdigit(), f"sessionId 非数字：{result.session_id}")


def test_done_event_payload_is_done_marker(api, rag_ready):
    """done 事件载荷固定为 [DONE]，前端以此关闭流并渲染。"""
    result = api.ask(QUESTION)
    assert_equal(result.done_payload, "[DONE]", "done 事件载荷")


def test_meta_event_carries_reference_document_name(api, kb_doc, rag_ready):
    """meta 事件必须回传被引用的文档名，这是"可溯源"能力的体现。"""
    result = api.ask(QUESTION)
    assert_gte(len(result.meta_refs), 1, "meta 引用文档数量")
    joined = ",".join(result.meta_refs)
    assert_contains(joined, "星云科技员工手册", ignore_case=False)


# ===================================================================== #
# 二、流式性能
# ===================================================================== #
def test_first_token_latency_meets_budget(api, rag_ready, settings):
    """首 token 时延是流式体验的第一指标，必须在上限内。"""
    result = api.ask(QUESTION)
    limit = settings.get("thresholds.first_token_latency_ms", 15000)
    assert result.first_token_ms is not None, "未收到任何 token"
    assert_lte(result.first_token_ms, limit, f"首 token 时延（{result.summary()}）")


def test_full_answer_latency_meets_budget(api, rag_ready, settings):
    """完整回答总时长必须在上限内，避免用户长时间等待。"""
    result = api.ask(QUESTION)
    limit = settings.get("thresholds.full_answer_latency_ms", 60000)
    assert_lte(result.total_ms, limit, f"完整回答时延（{result.summary()}）")


def test_streaming_is_incremental_not_single_shot(api, rag_ready):
    """验证"真流式"：必须拆分成多个 token 分片推送，而不是一次性吐出整段。

    若 token 数为 1，说明后端退化成同步返回，打字机效果失效——
    这是 SSE 改造最容易出现的回归。
    """
    result = api.ask(QUESTION)
    assert_gte(result.token_count, 2, "token 分片数量（为 1 说明退化为非流式）")
    assert result.throughput_tps > 0, "生成吞吐异常"


def test_answer_completeness_and_length(api, rag_ready, settings):
    """token 拼接后的回答必须完整、非空、长度合理。"""
    result = api.ask(QUESTION)
    min_chars = settings.get("thresholds.answer_min_chars", 8)
    assert_gte(len(result.answer), min_chars, "回答长度")
    assert result.answer.strip() != "", "回答为空"


# ===================================================================== #
# 三、会话延续性
# ===================================================================== #
def test_ask_with_existing_session_reuses_it(api, chat_session, rag_ready):
    """会话延续：显式传入 sessionId 时，事件中的 session 必须与之一致。"""
    result = api.ask(QUESTION, session_id=chat_session)
    assert_equal(int(result.session_id), chat_session, "回传的 sessionId")


def test_ask_without_session_creates_new_one(api, rag_ready):
    """会话自动创建：不传 sessionId 时后端应新建会话并回传。"""
    first = api.ask(QUESTION)
    second = api.ask(QUESTION)
    assert first.session_id != second.session_id, "两次独立提问不应复用同一会话"


def test_multi_turn_exchange_is_persisted(api, chat_session, rag_ready):
    """多轮对话落库：一问一答应产生 2 条消息（USER + ASSISTANT）。"""
    api.ask(QUESTION, session_id=chat_session)
    messages = api.messages(chat_session).data
    assert_gte(len(messages), 2, "消息条数")

    assistant_msgs = [m for m in messages if m["role"] == "ASSISTANT"]
    assert assistant_msgs, "缺少 ASSISTANT 消息"
    assert_gte(len(assistant_msgs[-1]["content"]), 8, "AI 回答内容长度")


def test_keepalive_comment_does_not_break_parsing(api, rag_ready):
    """健壮性：keep-alive 注释帧不得被当作业务事件，也不得影响回答完整性。

    （15s 心跳在短回答中通常不出现，此处主要校验解析器对注释帧的容错。）
    """
    result = api.ask(QUESTION)
    assert result.done, "存在注释帧时流式解析被破坏"
    assert "keep-alive" not in result.answer, "心跳内容泄漏到了回答正文中"
