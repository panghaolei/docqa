"""边界值与注入攻击测试。

目标：验证"恶劣输入"下系统的**可用性与安全性**——
    · 不崩溃（无 5xx、无未捕获异常）
    · 不泄露（无堆栈、无 SQL、无密钥）
    · 不乱码（UTF-8 往返一致）
    · 不注入（SQL / 模板 / NoSQL 注入均按字面量处理）

这类用例是接口测试里性价比最高的一批：实现成本低，一旦命中就是线上事故。
"""

from __future__ import annotations

import pytest

from core.assertions import (
    assert_api_success,
    assert_equal,
    assert_failed,
    assert_no_leak,
    assert_no_server_error,
)

pytestmark = pytest.mark.api

# 典型注入载荷
SQL_INJECTION = [
    "' OR '1'='1",
    "1'; DROP TABLE doc_info; --",
    "admin'--",
    "\" OR \"\"=\"",
    "1 UNION SELECT username, token FROM sys_user",
]

XSS_PAYLOAD = [
    "<script>alert('xss')</script>",
    "<img src=x onerror=alert(1)>",
    "javascript:alert(document.cookie)",
    "\"><svg/onload=alert(1)>",
]

# 边界字符
WEIRD_TEXT = [
    "emoji 测试 😀🎉🚀",
    "换行\n测试\r\n第二行",
    "制表\t分隔\t符",
    "零宽字符\u200b\u200c\u200d",
    "全角：ＡＢＣ　１２３",
    "很长的单字" + "字" * 100,
]


# ===================================================================== #
# 注入防护
# ===================================================================== #
@pytest.mark.parametrize("payload", SQL_INJECTION)
def test_sql_injection_in_username_is_safe(anonymous_api, payload):
    """SQL 注入：用户名含注入串时，要么按字面量注册成功，要么被参数校验拒绝；
    绝不能返回 SQL 报错（说明使用了字符串拼接 SQL）。"""
    resp = anonymous_api.login(payload)
    assert_no_server_error(resp, f"SQL 注入载荷 {payload!r}")
    assert_no_leak(resp.text)
    if resp.ok:
        assert_equal(resp.data["username"], payload.strip(), "注入串应按字面量存储")


@pytest.mark.parametrize("payload", SQL_INJECTION)
def test_sql_injection_in_session_title_is_safe(api, payload):
    """SQL 注入：会话标题同样必须被安全处理。"""
    resp = api.http.post("/chat/session", json_body={"title": payload})
    assert_no_server_error(resp, f"会话标题注入载荷 {payload!r}")
    assert_no_leak(resp.text)


@pytest.mark.parametrize("payload", SQL_INJECTION)
def test_sql_injection_in_question_is_safe(api, payload):
    """SQL 注入：提问内容进入向量检索，必须被安全处理（防止检索层拼接查询）。"""
    resp = api.ask_raw(payload)
    assert resp.status_code < 500, f"提问注入载荷导致 HTTP {resp.status_code}"
    assert_no_leak(resp.text)


# ===================================================================== #
# XSS
# ===================================================================== #
@pytest.mark.parametrize("payload", XSS_PAYLOAD)
def test_xss_payload_is_stored_verbatim_and_safe(api, payload):
    """XSS：后端应原样存储（转义由前端 DOMPurify 负责），且不得报错。

    该用例锁定"后端存储原样、前端渲染净化"的责任边界；
    若后端开始做转义，此处会失败并提醒同步调整前端渲染策略。
    """
    resp = api.http.post("/chat/session", json_body={"title": payload})
    assert_no_server_error(resp, f"XSS 载荷 {payload!r}")
    if resp.ok:
        assert_equal(resp.data["title"], payload, "标题应原样存储")


# ===================================================================== #
# 编码与字符集
# ===================================================================== #
@pytest.mark.parametrize("text", WEIRD_TEXT)
def test_unicode_round_trip_without_mojibake(api, text):
    """编码鲁棒性：多字节字符经"请求 → 落库 → 查询"后必须一字不差。"""
    resp = api.http.post("/chat/session", json_body={"title": text})
    assert_no_server_error(resp, f"特殊字符 {text!r}")
    if resp.ok:
        assert_equal(resp.data["title"], text, "字符往返一致性")


# ===================================================================== #
# 超长与超大输入
# ===================================================================== #
def test_extreme_long_question_does_not_crash(api):
    """边界值：5000 字超长提问。

    期望：要么正常进入 RAG 流程，要么被明确拒绝（如长度校验），
    不得出现 5xx 或长时间无响应。
    """
    question = "请问员工手册中年假的规定是什么？" * 300
    resp = api.ask_raw(question)
    assert resp.status_code < 500, f"超长提问导致 HTTP {resp.status_code}"
    assert_no_leak(resp.text)


def test_question_with_only_whitespace_is_rejected(api):
    """异常入参：纯空白提问违反 @NotBlank 校验，必须被拒绝。"""
    resp = api.ask_raw("    ")
    assert_failed(resp)
    assert resp.status_code < 500


def test_question_with_markdown_and_code_block(api, chat_session):
    """内容边界：含 Markdown 代码块 / 反引号的提问必须能正常处理（前端 marked 渲染依赖）。"""
    question = "请解释这段配置：\n```yaml\ndocqa:\n  chunk:\n    size: 500\n```"
    result = api.ask(question, session_id=chat_session)
    assert result.done, f"含代码块的提问处理失败：{result.error}"


def test_session_title_boundary_at_200_chars(api):
    """边界值（内点）：chat_session.title 列为 varchar(200)，200 字标题应可正常创建。"""
    title = "标" * 200
    resp = api.http.post("/chat/session", json_body={"title": title})
    assert_api_success(resp)


def test_negative_and_zero_ids_are_handled(api):
    """异常入参：负数 / 0 作为路径参数，必须安全失败而不是 5xx。"""
    for bad_id in (0, -1, -99999):
        resp = api.messages(bad_id)
        assert resp.status_code < 500, f"messages({bad_id}) 触发 HTTP {resp.status_code}"


def test_huge_json_payload_is_handled(anonymous_api):
    """异常入参：超大 JSON 体积（约 1MB）不得导致服务端未处理异常。"""
    resp = anonymous_api.http.post("/user/login", json_body={"username": "u" * 500_000})
    assert resp.status_code < 500, f"超大请求体导致 HTTP {resp.status_code}"
