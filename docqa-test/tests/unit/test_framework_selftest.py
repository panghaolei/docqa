"""测试框架自检用例（Mock Server，无需真实后端）。

思路：好的自动化框架本身也要被测。
本模块起一个标准库 ``http.server`` 实现的**假后端**，模拟 DocQA 的登录、
文档列表与 SSE 流式问答协议，用来验证框架自身三块最容易出错的代码：

    1. ``core.sse_client``  —— SSE 帧解析、事件顺序、首 token 计时、心跳帧容错；
    2. ``core.http_client`` —— 响应包装、业务码提取、耗时统计；
    3. ``core.assertions``  —— 断言失败信息是否可读、是否真的会失败。

价值：即使后端未启动，这部分用例也能保证"测试工具链"是可信的——
否则工具误报会直接污染所有业务用例的结论。也常用于 CI 中对测试框架做冒烟。
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from core.api_client import DocQaApi
from core.assertions import (
    assert_api_success,
    assert_contains,
    assert_failed,
    assert_no_leak,
    assert_no_server_error,
)
from core.http_client import ApiResponse, HttpClient
from core.sse_client import stream_ask

pytestmark = pytest.mark.unit

# 模拟回答：3 个 token 分片
FAKE_TOKENS = ["满 3 年可", "享受 10 天", "年假。"]


class _FakeDocQaHandler(BaseHTTPRequestHandler):
    """极简假后端：只实现框架自检所需的 4 个端点。"""

    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # 关闭访问日志，保持输出干净
        pass

    # ---------------- 工具方法 ----------------
    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json;charset=UTF-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    # ---------------- 路由 ----------------
    def do_GET(self):  # noqa: N802
        if self.path.endswith("/document/list"):
            if not self.headers.get("Authorization"):
                self._send_json({"code": 401, "message": "未登录"}, status=401)
                return
            self._send_json({"code": 0, "message": "ok", "data": [
                {"id": 1, "fileName": "手册.txt", "fileSize": 1024, "fileType": "txt",
                 "chunkCount": 3, "status": "DONE"},
            ]})
        else:
            self._send_json({"code": 500, "message": "not found"}, status=404)

    def do_POST(self):  # noqa: N802
        raw = self._read_body()
        if self.path.endswith("/user/login"):
            payload = json.loads(raw or b"{}")
            username = (payload.get("username") or "").strip()
            if not username:
                self._send_json({"code": 400, "message": "用户名不能为空"})
                return
            self._send_json({"code": 0, "message": "ok", "data": {
                "userId": 1, "username": username, "token": "tok_" + "a" * 32,
            }})
        elif self.path.endswith("/chat/ask/stream"):
            self._stream_sse()
        else:
            self._send_json({"code": 500, "message": "not found"}, status=404)

    def _stream_sse(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream;charset=UTF-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        frames = [
            "event: session\ndata: 42\n\n",
            "event: meta\ndata: 星云科技员工手册.txt\n\n",
            ": keep-alive\n\n",                       # 心跳注释帧，必须被忽略
            *[f"event: token\ndata: {t}\n\n" for t in FAKE_TOKENS],
            "event: done\ndata: [DONE]\n\n",
        ]
        for frame in frames:
            self.wfile.write(frame.encode("utf-8"))
            self.wfile.flush()
            time.sleep(0.02)                          # 制造真实的"流式"间隔


@pytest.fixture(scope="module")
def mock_backend():
    """启动假后端，产出 base_url。"""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeDocQaHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}/api"
    yield base_url
    server.shutdown()
    server.server_close()


@pytest.fixture()
def mock_api(mock_backend: str) -> DocQaApi:
    return DocQaApi(mock_backend, timeout=10, stream_timeout=30)


# ===================================================================== #
# HTTP 客户端
# ===================================================================== #
def test_http_client_wraps_response_fields(mock_api: DocQaApi):
    """HttpClient 必须正确提取 HTTP 状态码、业务码、message、data 与耗时。"""
    resp = mock_api.login("tester")
    assert isinstance(resp, ApiResponse)
    assert resp.status_code == 200
    assert resp.code == 0
    assert resp.message == "ok"
    assert resp.data["username"] == "tester"
    assert resp.elapsed_ms > 0
    assert resp.ok is True


def test_http_client_does_not_inject_token_without_login(mock_backend: str):
    """未登录时不得携带 Authorization 头（避免测试之间串号）。"""
    client = HttpClient(mock_backend, timeout=10)
    resp = client.get("/document/list")
    assert resp.status_code == 401
    assert resp.code == 401
    assert client.token is None


def test_http_client_raises_readable_error_on_dead_host():
    """连接不可达时，必须抛出带上下文的断言错误，而不是裸 requests 异常。"""
    client = HttpClient("http://127.0.0.1:1/api", timeout=2)
    with pytest.raises(AssertionError) as exc:
        client.get("/document/list")
    assert "无法连接被测服务" in str(exc.value)


# ===================================================================== #
# SSE 客户端
# ===================================================================== #
def test_sse_client_parses_event_sequence(mock_backend: str):
    """事件顺序与类型解析：session → meta → token… → done。"""
    result = stream_ask(mock_backend, "fake-token", "年假几天？", timeout=20)

    assert result.http_status == 200
    assert result.error is None
    assert result.event_order == ["session", "meta", "token", "token", "token", "done"]
    assert result.done is True
    assert result.done_payload == "[DONE]"
    assert result.session_id == "42"
    assert result.meta_refs == ["星云科技员工手册.txt"]


def test_sse_client_concatenates_tokens(mock_backend: str):
    """token 分片必须按顺序拼接成完整回答。"""
    result = stream_ask(mock_backend, "fake-token", "年假几天？", timeout=20)
    assert result.answer == "".join(FAKE_TOKENS)
    assert result.token_count == 3


def test_sse_client_ignores_keepalive_comments(mock_backend: str):
    """心跳注释帧（: keep-alive）必须被忽略，不能污染回答或事件序列。"""
    result = stream_ask(mock_backend, "fake-token", "年假几天？", timeout=20)
    assert result.keepalive_count == 1
    assert "keep-alive" not in result.answer
    assert "message" not in result.event_order, "注释帧被误当作 message 事件"


def test_sse_client_measures_first_token_latency(mock_backend: str):
    """首 token 时延必须是"从发起到第一个 token"的耗时，且小于总耗时。"""
    result = stream_ask(mock_backend, "fake-token", "年假几天？", timeout=20)
    assert result.first_token_ms is not None
    assert result.first_token_ms > 0
    assert result.first_token_ms <= result.total_ms
    assert result.throughput_tps > 0


def test_sse_client_reports_error_on_non_200(mock_backend: str):
    """非 200 响应必须被记录为 error，而不是抛出异常中断测试。"""
    result = stream_ask(mock_backend, "fake-token", "年假几天？",
                        path="/document/list", timeout=10)
    assert result.done is False
    assert result.error is not None


def test_api_client_registers_and_tracks_sessions(mock_api: DocQaApi):
    """API 层必须自动登记流式问答产生的会话，供用例结束后统一回收。"""
    mock_api.login("tester")
    mock_api.ask("年假几天？")
    assert 42 in mock_api.created_sessions, "SSE 回传的 sessionId 未被登记"


# ===================================================================== #
# 断言工具
# ===================================================================== #
def test_assertions_pass_on_valid_response(mock_api: DocQaApi):
    """正向断言不应对正常响应误报。"""
    resp = mock_api.login("tester")
    data = assert_api_success(resp)
    assert_contains(data["username"], "test")
    assert_no_leak(resp.text)
    assert_no_server_error(resp)


def test_assert_failed_accepts_business_error():
    """assert_failed 必须兼容"HTTP 200 + 业务码非 0"和"HTTP 4xx"两种失败表达。"""
    business_error = ApiResponse("POST", "http://x/y", 200, 12.0,
                                 '{"code":400,"message":"用户名不能为空"}')
    http_error = ApiResponse("GET", "http://x/y", 401, 3.0, '{"code":401,"message":"未登录"}')
    assert_failed(business_error)
    assert_failed(http_error)

    with pytest.raises(AssertionError):
        assert_failed(ApiResponse("GET", "http://x/y", 200, 3.0, '{"code":0,"message":"ok"}'))


def test_assert_no_leak_detects_sensitive_content():
    """泄露检测必须能识别 API Key 与 Java 堆栈。"""
    leaked = '{"code":500,"message":"sk-abcdefghijklmnopqrstuvwxyz123456"}'
    with pytest.raises(AssertionError):
        assert_no_leak(leaked)

    with pytest.raises(AssertionError):
        assert_no_leak("java.lang.NullPointerException at com.docqa.service.QaService.ask")

    assert_no_leak('{"code":0,"message":"ok","data":[]}')


def test_assert_no_server_error_detects_business_500():
    """业务 500（未处理异常）必须被判为服务端错误。"""
    with pytest.raises(AssertionError):
        assert_no_server_error(ApiResponse("GET", "http://x", 200, 5.0,
                                           '{"code":500,"message":"boom"}'))
