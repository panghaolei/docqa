"""接口契约测试（Consumer-Driven Contract）。

前端（Vue + axios 拦截器）强依赖后端的统一响应包装：
    resp.data.code === 0  → 取 data
    resp.data.code === 401→ 清 token 并刷新页面
    resp.data.message     → 弹错误提示

因此 code / message / data 三个字段一旦改名或语义变化，前端会整体失效。
本模块把这些**隐式契约**固化成可执行断言，是前后端并行开发的安全网。
"""

from __future__ import annotations

import pytest

from core import schema
from core.assertions import assert_api_success, assert_equal

pytestmark = pytest.mark.api


def test_response_is_json_object_with_code_and_message(api):
    """外层契约：所有接口返回 HTTP 200 + JSON，且包含 code/message 字段。"""
    resp = api.list_documents()
    assert_equal(resp.status_code, 200, "HTTP 状态码")
    assert "application/json" in resp.headers.get("Content-Type", ""), (
        f"Content-Type 应为 JSON，实际 {resp.headers.get('Content-Type')}"
    )
    assert isinstance(resp.json, dict), f"响应体不是 JSON 对象：{resp.text[:200]}"
    schema.validate(resp.json, schema.API_RESULT, "统一响应包装")


def test_success_code_is_zero_and_message_is_ok(api):
    """成功语义：code=0 且 message='ok'，前端据此走成功分支。"""
    resp = api.list_documents()
    assert_equal(resp.code, 0, "成功业务码")
    assert_equal(resp.message, "ok", "成功提示文案")


def test_error_response_keeps_same_outer_shape(anonymous_api):
    """失败语义：即使 401，响应体仍是同一套包装结构，前端可统一处理。"""
    resp = anonymous_api.http.get("/document/list")
    body = resp.json
    assert isinstance(body, dict), f"401 响应不是 JSON：{resp.text[:200]}"
    assert "code" in body and "message" in body, f"401 响应缺少 code/message：{body}"
    assert_equal(body.get("code"), 401, "401 业务码")


def test_login_data_contract(anonymous_api, account_name):
    """登录数据契约：前端依赖 userId / username / token 三个字段名。"""
    data = assert_api_success(anonymous_api.login(account_name))
    schema.validate(data, schema.LOGIN_DATA, "登录 data")


def test_document_data_contract(api, docs_dir, run_id):
    """文档数据契约：前端表格依赖 id/fileName/fileSize/fileType/chunkCount/status。"""
    from utils import doc_factory

    doc = api.upload_and_wait(doc_factory.build(docs_dir, "txt", f"契约_{run_id}.txt"))
    schema.validate(doc, schema.DOCUMENT_ITEM, "文档 data")


def test_status_enum_is_closed_set(api, docs_dir, run_id):
    """状态枚举契约：status 只能是 PENDING / PROCESSING / DONE / FAILED 四态，
    前端样式与轮询逻辑基于该枚举，不允许出现未定义值。"""
    from utils import doc_factory

    doc = api.upload_and_wait(doc_factory.build(docs_dir, "txt", f"枚举_{run_id}.txt"))
    assert doc["status"] in ("PENDING", "PROCESSING", "DONE", "FAILED"), (
        f"出现未定义的状态值：{doc['status']}"
    )


def test_sse_content_type_is_event_stream(api, kb_doc):
    """SSE 契约：流式问答必须返回 text/event-stream，否则前端 ReadableStream 解析失败。"""
    resp = api.http.request(
        "POST", "/chat/ask/stream",
        json_body={"question": "你好"},
        headers={"Accept": "text/event-stream"},
        timeout=60,
    )
    ctype = resp.headers.get("Content-Type", "")
    assert "text/event-stream" in ctype, f"SSE Content-Type 错误：{ctype}"


def test_message_role_enum_contract(api, chat_session):
    """消息角色契约：role 只有 USER / ASSISTANT 两种取值。"""
    api.ask("你好", session_id=chat_session)
    messages = assert_api_success(api.messages(chat_session))
    for msg in messages:
        assert msg["role"] in ("USER", "ASSISTANT", "user", "assistant"), (
            f"未定义的消息角色：{msg['role']}"
        )


def test_cors_headers_on_actual_request(anonymous_api, account_name):
    """CORS 契约：带 Origin 的实际请求必须返回允许跨域的响应头。"""
    resp = anonymous_api.http.post(
        "/user/login", json_body={"username": account_name},
        headers={"Origin": "http://localhost:5173"},
    )
    assert_api_success(resp)
    assert resp.headers.get("Access-Control-Allow-Origin"), (
        "缺少 Access-Control-Allow-Origin，浏览器将拦截前端请求"
    )
