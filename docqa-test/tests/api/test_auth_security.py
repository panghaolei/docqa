"""鉴权与越权（安全）测试。

被测点：``com.docqa.common.TokenInterceptor`` + ``WebConfig`` 拦截器配置。
    · 除 /user/login、/error、/favicon.ico 外的所有接口都要求 Authorization；
    · 缺少或无效 token → HTTP 401 + {"code":401,"message":"..."}；
    · 接受 "Bearer xxx" 与裸 token 两种写法；
    · OPTIONS 预检请求放行（CORS）。

同时覆盖**横向越权**（IDOR）检查：A 用户不得读取/删除 B 用户的文档与会话。
"""

from __future__ import annotations

import pytest

from core.assertions import (
    assert_api_success,
    assert_equal,
    assert_no_leak,
)

pytestmark = pytest.mark.api

# 所有受保护接口的 (方法, 路径, 请求体)
PROTECTED_ENDPOINTS = [
    ("GET", "/document/list", None),
    ("GET", "/chat/sessions", None),
    ("POST", "/document/upload", None),
    ("POST", "/chat/session", {"title": "x"}),
    ("GET", "/chat/messages/1", None),
    ("DELETE", "/chat/session/1", None),
    ("POST", "/chat/ask/stream", {"question": "你好"}),
]


@pytest.mark.parametrize("method,path,body", PROTECTED_ENDPOINTS)
def test_protected_endpoints_require_token(anonymous_api, method, path, body):
    """未携带 token：所有受保护接口都必须返回 401，不能泄露任何业务数据。"""
    resp = anonymous_api.http.request(method, path, json_body=body)
    assert resp.status_code == 401, (
        f"{method} {path} 未携带 token 时返回 {resp.status_code}，应为 401\n  响应: {resp}"
    )
    assert resp.json.get("code") == 401, f"未登录业务码应为 401，实际：{resp.json}"


@pytest.mark.parametrize("bad_token", [
    "invalid-token-1234567890",
    "Bearer",
    "Bearer ",
    "null",
    "0",
    "' OR '1'='1",
])
def test_invalid_token_is_rejected(anonymous_api, bad_token):
    """伪造/畸形 token：必须 401，且不得出现 SQL 报错（注入防护）。"""
    resp = anonymous_api.http.get("/document/list", headers={"Authorization": bad_token})
    assert resp.status_code == 401, f"非法 token '{bad_token}' 应返回 401，实际 {resp.status_code}"
    assert_no_leak(resp.text)


def test_login_endpoint_is_public(anonymous_api, account_name):
    """白名单校验：登录接口无需 token 即可访问。"""
    resp = anonymous_api.http.post("/user/login", json_body={"username": account_name})
    assert_api_success(resp)


def test_raw_token_without_bearer_prefix_is_accepted(api):
    """兼容性：Authorization 直接携带裸 token 也应被识别。"""
    resp = api.http.get("/document/list", headers={"Authorization": api.token})
    assert_api_success(resp)


def test_options_preflight_is_allowed(anonymous_api, base_url):
    """CORS 预检：OPTIONS 请求必须放行，且返回允许跨域的响应头。"""
    resp = anonymous_api.http.request(
        "OPTIONS", "/document/list",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert resp.status_code in (200, 204), f"预检请求被拦截：{resp.status_code}"
    allow_origin = resp.headers.get("Access-Control-Allow-Origin", "")
    assert allow_origin, "缺少 Access-Control-Allow-Origin 响应头，前端跨域将被浏览器拦截"


# ===================================================================== #
# 横向越权（IDOR）
# ===================================================================== #
def test_document_list_only_returns_own_data(api, other_api, docs_dir, run_id):
    """数据隔离：文档列表必须只返回当前用户的数据。"""
    from utils import doc_factory

    mine = api.upload_and_wait(doc_factory.build(docs_dir, "txt", f"我的文档_{run_id}.txt"))
    others = other_api.list_documents()
    assert_api_success(others)
    other_ids = [d["id"] for d in others.data]
    assert mine["id"] not in other_ids, "B 用户能看到 A 用户的文档，数据隔离失效"


def test_session_list_only_returns_own_data(api, other_api):
    """数据隔离：会话列表必须只返回当前用户的会话。"""
    sid = assert_api_success(api.create_session("我的会话"))["sessionId"]
    others = assert_api_success(other_api.list_sessions())
    assert sid not in [s["id"] for s in others], "会话列表存在越权，能看到他人会话"


@pytest.mark.xfail(reason="已知缺陷：/chat/messages/{id} 未校验会话归属，存在横向越权（IDOR）",
                   strict=False)
def test_read_other_user_session_messages_is_forbidden(api, other_api):
    """越权读取：B 用户不应用 A 用户的 sessionId 读到 A 的聊天记录。

    当前实现 ChatSessionService#messages 只按 sessionId 查询，未校验 userId，
    属于典型的 IDOR 缺陷。用例以 xfail 固化该缺陷：修复后会自动变为 XPASS，
    提示测试人员把 xfail 标记移除，转为强制断言。
    """
    sid = assert_api_success(api.create_session("A 的私密会话"))["sessionId"]
    resp = other_api.messages(sid)
    assert resp.status_code == 403 or resp.code == 403, (
        f"越权读取未被拒绝：HTTP {resp.status_code} code={resp.code}"
    )


@pytest.mark.xfail(reason="已知缺陷：/document/{id} 删除未校验文档归属，存在横向越权（IDOR）",
                   strict=False)
def test_delete_other_user_document_is_forbidden(api, other_api, docs_dir, run_id):
    """越权删除：B 用户不应用 documentId 删除 A 用户的文档（高危）。

    当前实现 DocumentService#delete 只按 id 查文档，未校验 userId。
    """
    from utils import doc_factory

    doc = api.upload_and_wait(doc_factory.build(docs_dir, "txt", f"待保护文档_{run_id}.txt"))
    resp = other_api.delete_document(doc["id"])
    assert resp.status_code == 403 or resp.code == 403, (
        f"越权删除未被拒绝：HTTP {resp.status_code} code={resp.code}"
    )


def test_token_of_other_user_cannot_be_used_after_change(api, other_api):
    """会话隔离：两个账号的 token 互不通用，各自的数据互不可见。"""
    api_sid = assert_api_success(api.create_session("A"))["sessionId"]
    other_api_sid = assert_api_success(other_api.create_session("B"))["sessionId"]
    assert api_sid != other_api_sid

    mine = [s["id"] for s in assert_api_success(api.list_sessions())]
    theirs = [s["id"] for s in assert_api_success(other_api.list_sessions())]
    assert_equal(set(mine) & set(theirs), set(), "两个账号的会话出现交集")
