"""用户登录接口测试：``POST /api/user/login``。

后端规格（UserService#login）：
    · 用户名自动注册：首次登录建档并发放 32 位 uuid token；
    · 已存在用户直接返回既有 token（不失效旧 token）；
    · 用户名为空 → IllegalArgumentException → GlobalExceptionHandler → code=400，HTTP 200。

测试覆盖：正常等价类、空值/空白/超长边界、幂等性、响应契约、错误信息安全。
"""

from __future__ import annotations

import uuid

import pytest

from core import schema
from core.assertions import (
    assert_api_error,
    assert_api_success,
    assert_equal,
    assert_failed,
    assert_no_leak,
)

pytestmark = pytest.mark.api


def test_login_success_and_response_contract(anonymous_api, account_name):
    """正常登录：返回 userId / username / token，且结构符合契约。"""
    resp = anonymous_api.login(account_name)
    data = assert_api_success(resp)
    schema.validate(resp.json, schema.API_RESULT, "登录响应外层")
    schema.validate(data, schema.LOGIN_DATA, "登录响应 data")

    assert_equal(data["username"], account_name, "回显用户名")
    assert len(data["token"]) >= 8, "token 长度异常"
    assert isinstance(data["userId"], int) and data["userId"] > 0


def test_login_is_idempotent_for_existing_user(anonymous_api, account_name):
    """幂等性：同一用户名重复登录应返回同一 userId 与同一 token（不使旧会话失效）。"""
    first = assert_api_success(anonymous_api.login(account_name))
    second = assert_api_success(anonymous_api.login(account_name))
    assert_equal(second["userId"], first["userId"], "userId")
    assert_equal(second["token"], first["token"], "token")


def test_login_username_is_trimmed(anonymous_api, account_name):
    """空格容错：前后空格应被 trim，且与无空格用户名视为同一账号。"""
    resp = anonymous_api.login(f"   {account_name}   ")
    data = assert_api_success(resp)
    assert_equal(data["username"], account_name, "trim 后的用户名")


@pytest.mark.parametrize("bad_username", ["", "   ", "\t\n"])
def test_login_rejects_blank_username(anonymous_api, bad_username):
    """异常入参：空串 / 纯空白必须被拒绝，并返回明确的业务错误码。"""
    resp = anonymous_api.login(bad_username)
    assert_failed(resp)
    assert_api_error(resp, code=400, message_contains="用户名")


def test_login_missing_username_field(anonymous_api):
    """异常入参：请求体缺少 username 字段，不得导致服务端崩溃。"""
    resp = anonymous_api.http.post("/user/login", json_body={})
    assert_failed(resp)
    assert_no_leak(resp.text)


def test_login_supports_unicode_and_special_chars(anonymous_api):
    """字符集覆盖：中文、emoji、常见符号用户名必须能正常注册与回显。"""
    username = f"测试用户_{uuid.uuid4().hex[:6]}_★"
    resp = anonymous_api.login(username)
    data = assert_api_success(resp)
    assert_equal(data["username"], username, "Unicode 用户名回显")


def test_login_with_username_at_column_limit(anonymous_api, run_id):
    """边界值（内点）：sys_user.username 列为 varchar(64)，取 64 字符应能正常注册。"""
    username = f"{run_id}_" + "u" * (64 - len(run_id) - 1)
    assert len(username) == 64
    resp = anonymous_api.login(username)
    data = assert_api_success(resp)
    assert_equal(data["username"], username, "边界长度用户名回显")


@pytest.mark.xfail(
    reason="已知缺陷：用户名超长（>64）未做入参校验，直接抛 DataIntegrityViolationException "
           "并被兜底处理器转为 code=500，应改为 400 参数错误",
    strict=False,
)
def test_oversized_username_is_rejected_gracefully(anonymous_api):
    """边界值（外点）：超过列长度的用户名应返回 400 参数错误，而不是 500 内部错误。"""
    resp = anonymous_api.login("u" * 200)
    assert_failed(resp)
    assert resp.code == 400, f"超长用户名应返回参数错误(400)，实际 code={resp.code}"


def test_login_response_does_not_leak_internals(anonymous_api, account_name):
    """安全性：登录响应不得包含堆栈、SQL、密钥等内部信息。"""
    assert_no_leak(anonymous_api.login(account_name).text)


def test_token_is_unpredictable_across_users(anonymous_api, run_id):
    """安全性：不同账号的 token 必须互不相同（防止固定 token 伪造）。"""
    t1 = assert_api_success(anonymous_api.login(f"qa_t1_{run_id}"))["token"]
    t2 = assert_api_success(anonymous_api.login(f"qa_t2_{run_id}"))["token"]
    assert t1 != t2, "不同用户的 token 不应相同"
    assert len(t1) >= 32, f"token 强度不足：{t1}"
