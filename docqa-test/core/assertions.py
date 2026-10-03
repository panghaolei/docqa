"""断言工具：把"检查什么"和"怎么描述失败"分离，让用例保持一行式表达。

核心思想：
- 断言失败信息必须自带上下文（实际值、期望值、响应原文），否则排查成本高；
- 公共断言集中维护，避免每个用例重复写 ``assert resp.json()["code"] == 0``。
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Sequence

from core.http_client import ApiResponse

# 判定"敏感信息/内部细节泄露"的模式
_SENSITIVE_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "疑似 API Key"),
    (re.compile(r"(?i)(password|passwd|secret)\s*[=:]\s*\S+"), "疑似口令"),
    (re.compile(r"(?i)java\.lang\.[A-Za-z.]+Exception"), "Java 异常堆栈"),
    (re.compile(r"(?i)at\s+com\.docqa[\w.$]*\("), "Java 调用栈"),
    (re.compile(r"(?i)(SQLSyntaxErrorException|BadSqlGrammar|Unknown column)"), "SQL 报错"),
    (re.compile(r"(?i)org\.springframework\.[\w.]+Exception"), "框架异常类名"),
]


def assert_http_status(resp: ApiResponse, expected: int) -> None:
    assert resp.status_code == expected, (
        f"HTTP 状态码不符\n  期望: {expected}\n  实际: {resp.status_code}\n  响应: {resp}"
    )


def assert_api_success(resp: ApiResponse) -> Any:
    """断言业务成功（HTTP 200 且 code == 0），返回 data。"""
    assert_http_status(resp, 200)
    assert resp.code == 0, (
        f"业务码非 0\n  期望: 0\n  实际: {resp.code} ({resp.message})\n  响应: {resp}"
    )
    return resp.data


def assert_api_error(resp: ApiResponse, *, http_status: int | None = None,
                     code: int | None = None, message_contains: str | None = None) -> None:
    """断言业务失败响应（支持 HTTP 状态码 / 业务码 / 文案三重校验）。"""
    if http_status is not None:
        assert_http_status(resp, http_status)
    if code is not None:
        assert resp.code == code, (
            f"业务错误码不符\n  期望: {code}\n  实际: {resp.code} ({resp.message})\n  响应: {resp}"
        )
    if message_contains is not None:
        assert resp.message and message_contains in resp.message, (
            f"错误文案未包含关键字 '{message_contains}'\n  实际: {resp.message}"
        )


def assert_contains(text: str, keyword: str, *, ignore_case: bool = False) -> None:
    haystack = text.lower() if ignore_case else text
    needle = keyword.lower() if ignore_case else keyword
    assert needle in haystack, f"文本未包含关键字 '{keyword}'\n  实际文本: {text[:500]}"


def assert_contains_any(text: str, keywords: Iterable[str]) -> str:
    """任一命中即通过，返回命中的关键字（便于日志记录）。"""
    for kw in keywords:
        if kw in text:
            return kw
    raise AssertionError(f"文本未命中任一关键字 {list(keywords)}\n  实际文本: {text[:500]}")


def assert_contains_all(text: str, keywords: Sequence[str]) -> None:
    missing = [kw for kw in keywords if kw not in text]
    assert not missing, f"文本缺失关键字 {missing}\n  实际文本: {text[:500]}"


def assert_equal(actual: Any, expected: Any, label: str = "值") -> None:
    assert actual == expected, f"{label}不符\n  期望: {expected!r}\n  实际: {actual!r}"


def assert_true(condition: bool, message: str) -> None:
    assert condition, message


def assert_lte(actual: float, limit: float, label: str = "数值") -> None:
    assert actual <= limit, f"{label}超出上限\n  上限: {limit}\n  实际: {round(actual, 2)}"


def assert_gte(actual: float, floor: float, label: str = "数值") -> None:
    assert actual >= floor, f"{label}低于下限\n  下限: {floor}\n  实际: {round(actual, 2)}"


def assert_no_leak(text: str) -> None:
    """断言响应中不含密钥、堆栈、SQL 语句等内部细节。"""
    hits = [desc for pattern, desc in _SENSITIVE_PATTERNS if pattern.search(text or "")]
    assert not hits, (
        f"响应疑似泄露内部信息：{hits}\n  响应片段: {(text or '')[:500]}"
    )


def assert_latency(resp: ApiResponse, limit_ms: float, label: str = "接口") -> None:
    assert resp.elapsed_ms <= limit_ms, (
        f"{label}耗时超限\n  上限: {limit_ms}ms\n  实际: {resp.elapsed_ms:.0f}ms\n  {resp.url}"
    )


def assert_failed(resp: ApiResponse, label: str = "请求") -> None:
    """断言请求未能成功——兼容两种失败表达方式：
    1. HTTP 4xx/5xx（框架层拦截）；
    2. HTTP 200 + 业务码非 0（业务层拦截，本项目的 GlobalExceptionHandler 属此类）。
    用它来写异常入参用例，可以避免测试与具体错误码耦合、因框架细节变化而脆弱。
    """
    if resp.status_code == 200:
        assert resp.code not in (None, 0), (
            f"{label}本应失败，却返回成功\n  响应: {resp}"
        )
    else:
        assert 400 <= resp.status_code < 600, (
            f"{label}返回了非预期的状态码 {resp.status_code}\n  响应: {resp}"
        )


def assert_no_server_error(resp: ApiResponse, label: str = "请求") -> None:
    """断言服务端未崩溃：HTTP 不得为 5xx，业务码不得为 500。"""
    assert resp.status_code < 500, f"{label}触发了服务端 5xx\n  响应: {resp}"
    assert resp.code != 500, f"{label}触发了业务 500（未处理的内部异常）\n  响应: {resp}"
