"""SSE（Server-Sent Events）流式客户端。

被测系统的问答接口是 ``POST /chat/ask/stream``，返回 ``text/event-stream``：
    event: session → data: <sessionId>
    event: meta    → data: <引用文档名，逗号分隔>
    event: token   → data: <增量文本>      （多次）
    event: done    → data: [DONE]
    : keep-alive                           （每 15s 一条注释帧）

由于 EventSource 不支持自定义请求头，前端用 fetch + ReadableStream 实现；
本模块用 requests + iter_content 等价实现，可以完整断言：
    · 事件顺序（session → meta → token… → done）
    · 首 token 时延（流式体验的核心指标）
    · token 数量、吞吐（tokens/s）
    · 引用来源、完整回答是否拼接正确
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional

import requests

from core.logger import get_logger

log = get_logger("sse")


@dataclass
class SSEEvent:
    """一条 SSE 事件（或注释帧）。"""

    event: str
    data: str
    raw: str
    is_comment: bool = False

    def as_json(self) -> Optional[Any]:
        try:
            return json.loads(self.data)
        except Exception:
            return None


@dataclass
class StreamResult:
    """一次流式问答的完整观测结果。"""

    http_status: int = 0
    event_order: List[str] = field(default_factory=list)
    session_id: Optional[str] = None
    meta_refs: List[str] = field(default_factory=list)
    tokens: List[str] = field(default_factory=list)
    done: bool = False
    done_payload: str = ""
    keepalive_count: int = 0
    first_token_ms: Optional[float] = None
    total_ms: float = 0.0
    error: Optional[str] = None

    # ---- 派生指标 ----
    @property
    def answer(self) -> str:
        """按 SSE 规范拼接：同一事件的多行 data 用换行连接。"""
        return "".join(self.tokens)

    @property
    def token_count(self) -> int:
        return len(self.tokens)

    @property
    def throughput_tps(self) -> float:
        """生成阶段吞吐（token/s），剔除首 token 等待时间。"""
        if self.first_token_ms is None or self.total_ms <= self.first_token_ms:
            return 0.0
        return self.token_count / ((self.total_ms - self.first_token_ms) / 1000.0)

    def summary(self) -> str:
        return (f"session={self.session_id} tokens={self.token_count} "
                f"first_token={self.first_token_ms and round(self.first_token_ms)}ms "
                f"total={round(self.total_ms)}ms tps={self.throughput_tps:.1f} "
                f"refs={self.meta_refs} done={self.done}")

    def __str__(self) -> str:  # pragma: no cover
        return f"<StreamResult {self.summary()}>"


def _parse_frame(frame: str) -> SSEEvent:
    """解析一个 SSE 帧（已被空行分隔）。"""
    event_name = "message"
    data_lines: List[str] = []
    raw_lines: List[str] = []
    is_comment = False

    for line in frame.split("\n"):
        raw_lines.append(line)
        if line.startswith(":"):
            is_comment = True
            continue
        if not line:
            continue
        if ":" in line:
            fname, _, fvalue = line.partition(":")
            fvalue = fvalue[1:] if fvalue.startswith(" ") else fvalue
        else:
            fname, fvalue = line, ""
        if fname == "event":
            event_name = fvalue.strip()
        elif fname == "data":
            data_lines.append(fvalue)

    return SSEEvent(
        event=event_name,
        data="\n".join(data_lines),
        raw="\n".join(raw_lines),
        is_comment=is_comment and not data_lines,
    )


def stream_ask(
    base_url: str,
    token: Optional[str],
    question: str,
    *,
    session_id: Optional[str] = None,
    path: str = "/chat/ask/stream",
    timeout: float = 120,
    connect_timeout: float = 10,
) -> StreamResult:
    """发起一次流式问答并收集全部观测指标。"""
    url = f"{base_url.rstrip('/')}{path}"
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    body: Dict[str, Any] = {"question": question}
    if session_id is not None:
        body["sessionId"] = session_id

    result = StreamResult()
    start = time.perf_counter()
    resp = None
    try:
        resp = requests.post(
            url, json=body, headers=headers, stream=True,
            timeout=(connect_timeout, timeout),
        )
        result.http_status = resp.status_code
        if resp.status_code != 200:
            result.error = f"HTTP {resp.status_code}: {resp.text[:300]}"
            result.total_ms = (time.perf_counter() - start) * 1000
            return result

        buffer = ""
        for chunk in resp.iter_content(chunk_size=None):
            if not chunk:
                continue
            buffer += chunk.decode("utf-8", errors="replace").replace("\r\n", "\n")

            while "\n\n" in buffer:
                frame, buffer = buffer.split("\n\n", 1)
                evt = _parse_frame(frame)
                if not evt.raw.strip():
                    continue
                if evt.is_comment:
                    result.keepalive_count += 1
                    continue
                _consume(evt, result, start)
                if evt.event == "done":
                    raise _StopStream()

        # 处理末尾无空行结尾的残留帧
        if buffer.strip():
            evt = _parse_frame(buffer)
            if not evt.is_comment and evt.raw.strip():
                _consume(evt, result, start)
    except _StopStream:
        pass
    except requests.exceptions.ReadTimeout as exc:
        result.error = f"流式读取超时（>{timeout}s）：{exc}"
    except requests.exceptions.ConnectionError as exc:
        result.error = f"无法连接 SSE 接口：{exc}"
    except requests.exceptions.RequestException as exc:  # pragma: no cover
        result.error = f"SSE 请求异常：{exc}"
    finally:
        if resp is not None:
            resp.close()
        result.total_ms = (time.perf_counter() - start) * 1000

    log.debug("SSE %s", result.summary())
    return result


class _StopStream(Exception):
    """收到 done 事件后主动结束读取。"""


def _consume(evt: SSEEvent, result: StreamResult, start: float) -> None:
    result.event_order.append(evt.event)
    if evt.event == "session":
        result.session_id = evt.data.strip()
    elif evt.event == "meta":
        result.meta_refs = [x for x in (evt.data or "").split(",") if x.strip()]
    elif evt.event == "token":
        if result.first_token_ms is None:
            result.first_token_ms = (time.perf_counter() - start) * 1000
        result.tokens.append(evt.data)
    elif evt.event == "done":
        result.done = True
        result.done_payload = evt.data


def iter_events(base_url: str, token: Optional[str], question: str,
                **kwargs) -> Iterator[SSEEvent]:
    """按事件流式产出（用于观察"逐字输出"过程，而非只看结果）。"""
    url = f"{base_url.rstrip('/')}/chat/ask/stream"
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with requests.post(url, json={"question": question}, headers=headers,
                       stream=True, timeout=kwargs.get("timeout", 120)) as resp:
        buffer = ""
        for chunk in resp.iter_content(chunk_size=None):
            if not chunk:
                continue
            buffer += chunk.decode("utf-8", errors="replace").replace("\r\n", "\n")
            while "\n\n" in buffer:
                frame, buffer = buffer.split("\n\n", 1)
                evt = _parse_frame(frame)
                if evt.raw.strip():
                    yield evt
                if evt.event == "done":
                    return
