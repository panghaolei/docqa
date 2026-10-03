"""会话与消息接口测试。

被测接口：
    POST   /api/chat/session            创建会话（title 可空，默认「新对话」）
    GET    /api/chat/sessions           会话列表（按 updatedAt 倒序）
    GET    /api/chat/messages/{id}      历史消息（按时间正序）
    DELETE /api/chat/session/{id}       删除会话（级联删除消息）
"""

from __future__ import annotations

import uuid

import pytest

from core import schema
from core.assertions import (
    assert_api_success,
    assert_equal,
    assert_failed,
)

pytestmark = pytest.mark.api


# ===================================================================== #
# 创建会话
# ===================================================================== #
def test_create_session_returns_id_and_title(api):
    """正常创建：返回 sessionId 与 title，结构符合契约。"""
    resp = api.create_session("季度复盘")
    schema.validate(resp.json, schema.API_RESULT, "创建会话外层")
    data = assert_api_success(resp)
    assert isinstance(data["sessionId"], int) and data["sessionId"] > 0
    assert_equal(data["title"], "季度复盘", "会话标题")


def test_create_session_without_body_uses_default_title(api):
    """默认值：不传 title 时后端应给出默认标题「新对话」。"""
    resp = api.http.post("/chat/session", json_body={})
    data = assert_api_success(resp)
    assert_equal(data["title"], "新对话", "默认标题")


def test_create_session_with_blank_title_uses_default(api):
    """边界值：title 为空串 / 纯空白，同样应回落到默认标题。"""
    for blank in ["", "   "]:
        data = assert_api_success(api.http.post("/chat/session", json_body={"title": blank}))
        assert_equal(data["title"], "新对话", f"title={blank!r} 时的默认标题")


def test_create_session_with_very_long_title(api):
    """边界值：超长标题（300 字）不得导致 5xx。"""
    title = "长标题" * 100
    resp = api.http.post("/chat/session", json_body={"title": title})
    assert resp.status_code < 500


# ===================================================================== #
# 会话列表
# ===================================================================== #
def test_session_list_contract_and_ordering(api):
    """列表契约：结构正确，且最近创建的会话排在最前（updatedAt 倒序）。"""
    first = assert_api_success(api.create_session("会话一"))["sessionId"]
    second = assert_api_success(api.create_session("会话二"))["sessionId"]

    resp = api.list_sessions()
    data = assert_api_success(resp)
    schema.validate(data, schema.CHAT_SESSION_LIST, "会话列表")
    ids = [s["id"] for s in data]
    assert first in ids and second in ids
    assert ids.index(second) < ids.index(first), "会话列表未按最近更新时间倒序"


def test_session_list_isolated_per_user(other_api):
    """数据隔离：新账号的会话列表为空。"""
    assert_equal(assert_api_success(other_api.list_sessions()), [], "新账号会话列表")


# ===================================================================== #
# 历史消息
# ===================================================================== #
def test_messages_of_new_session_is_empty(api, chat_session):
    """新会话没有历史消息，返回空数组而不是 null。"""
    data = assert_api_success(api.messages(chat_session))
    assert_equal(data, [], f"新会话消息列表应为空，实际 {data}")


def test_messages_of_nonexistent_session_returns_empty(api):
    """异常入参：查询不存在会话的消息，应安全返回空数组（不得 5xx）。"""
    resp = api.messages(999_999_999)
    assert_api_success(resp)
    assert_equal(resp.data, [], "不存在会话的消息列表")


def test_messages_schema_after_ask(api, chat_session):
    """消息落库：完成一轮问答后，历史消息应包含 USER 与 ASSISTANT 各一条且结构合规。"""
    result = api.ask("你好", session_id=chat_session)
    assert result.done, f"问答未正常结束：{result.error}"

    data = assert_api_success(api.messages(chat_session))
    schema.validate(data, schema.CHAT_MESSAGE_LIST, "消息列表")
    roles = [m["role"] for m in data]
    assert "USER" in roles and "ASSISTANT" in roles, f"消息角色缺失：{roles}"
    user_msg = next(m for m in data if m["role"] == "USER")
    assert_equal(user_msg["content"], "你好", "用户消息内容")


# ===================================================================== #
# 删除会话
# ===================================================================== #
def test_delete_session_removes_it_from_list(api):
    """删除闭环：删除后会话不再出现在列表中。"""
    sid = assert_api_success(api.create_session("待删除会话"))["sessionId"]
    assert_api_success(api.delete_session(sid))
    ids = [s["id"] for s in assert_api_success(api.list_sessions())]
    assert sid not in ids, f"会话 {sid} 删除后仍在列表中"


def test_delete_session_cascades_messages(api, chat_session):
    """级联删除：删除会话必须同时清理其历史消息，避免孤儿数据。"""
    api.ask("你好", session_id=chat_session)
    assert_api_success(api.delete_session(chat_session))
    resp = api.messages(chat_session)
    assert resp.status_code < 500, "删除会话后查询消息出现服务端错误"
    assert_equal(resp.data or [], [], "会话删除后仍能查到历史消息，级联删除失效")


def test_delete_nonexistent_session_fails_gracefully(api):
    """异常入参：删除不存在的会话应明确失败，不得 5xx。"""
    resp = api.delete_session(999_999_999)
    assert_failed(resp)
    assert resp.status_code < 500, f"删除不存在会话触发了 HTTP {resp.status_code}"


def test_session_title_is_truncated_when_created_by_ask(api):
    """业务规则：未指定 sessionId 提问时，后端用问题前 20 字 + "..." 作为会话标题。"""
    question = "请问入职满三年可以享受多少天年假呢，我想了解一下具体的计算规则"
    result = api.ask(question)
    assert result.session_id, "流式问答未返回 sessionId"

    sid = int(result.session_id)
    sessions = assert_api_success(api.list_sessions())
    target = next((s for s in sessions if s["id"] == sid), None)
    assert target is not None, f"自动创建的会话 {sid} 未出现在列表中"
    assert target["title"].startswith(question[:20]), (
        f"自动会话标题应为问题前 20 字，实际：{target['title']}"
    )
    assert len(target["title"]) <= 23, f"标题未截断：{target['title']}"


def test_concurrent_sessions_are_independent(api):
    """隔离性：不同会话的历史互不干扰。"""
    s1 = assert_api_success(api.create_session(f"会话A-{uuid.uuid4().hex[:6]}"))["sessionId"]
    s2 = assert_api_success(api.create_session(f"会话B-{uuid.uuid4().hex[:6]}"))["sessionId"]

    api.ask("你好", session_id=s1)
    m1 = assert_api_success(api.messages(s1))
    m2 = assert_api_success(api.messages(s2))
    assert len(m1) > 0, "会话 A 应有历史消息"
    assert_equal(m2, [], "会话 B 不应出现会话 A 的消息")
