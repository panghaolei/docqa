"""HTTP 客户端封装。

职责（与业务解耦，任何接口测试工程都可复用）：
1. 统一 Session 复用 / 连接池，降低握手开销；
2. 统一鉴权头注入（Bearer Token）；
3. 记录请求耗时、请求体、响应体到日志，失败时可回溯；
4. 把 ``requests.Response`` 包装成业务友好的 ``ApiResponse``；
5. 网络异常转换为带上下文的断言失败信息，而不是裸异常。
"""

from __future__ import annotations

import json as _json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import requests
from requests import Session

from core.logger import get_logger

log = get_logger("http")

# 不打日志的敏感/噪音字段
_MASK_KEYS = {"authorization", "api-key", "api_key", "token", "password"}


@dataclass
class ApiResponse:
    """统一响应模型：屏蔽 requests 细节，面向断言使用。"""

    method: str
    url: str
    status_code: int
    elapsed_ms: float
    text: str
    headers: Dict[str, str] = field(default_factory=dict)

    # ---- 业务响应体字段 ----
    @property
    def json(self) -> Optional[Any]:
        try:
            return _json.loads(self.text)
        except Exception:
            return None

    @property
    def code(self) -> Optional[int]:
        body = self.json
        return body.get("code") if isinstance(body, dict) else None

    @property
    def message(self) -> Optional[str]:
        body = self.json
        return body.get("message") if isinstance(body, dict) else None

    @property
    def data(self) -> Any:
        body = self.json
        return body.get("data") if isinstance(body, dict) else None

    @property
    def ok(self) -> bool:
        return self.status_code == 200 and self.code == 0

    def __str__(self) -> str:
        body = self.text if len(self.text) <= 500 else self.text[:500] + "...(truncated)"
        return (f"[{self.method} {self.url}] -> HTTP {self.status_code} "
                f"({self.elapsed_ms:.0f}ms)\n{body}")


class HttpClient:
    """被测服务的 HTTP 会话封装。"""

    def __init__(self, base_url: str, timeout: float = 30, verify: bool = False):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.verify = verify
        self.token: Optional[str] = None
        self._session = Session()
        self._session.headers.update({
            "Accept": "application/json",
            "User-Agent": "DocQA-AutoTest/1.0 (pytest)",
        })

    # ------------------------------------------------------------------ #
    # 鉴权
    # ------------------------------------------------------------------ #
    def set_token(self, token: str | None) -> None:
        self.token = token

    def clear_token(self) -> None:
        self.token = None

    def _build_headers(self, extra: Dict[str, str] | None = None) -> Dict[str, str]:
        headers = dict(extra or {})
        if self.token:
            headers.setdefault("Authorization", f"Bearer {self.token}")
        return headers

    # ------------------------------------------------------------------ #
    # 请求
    # ------------------------------------------------------------------ #
    def request(
        self,
        method: str,
        path: str,
        *,
        params: Dict[str, Any] | None = None,
        json_body: Any = None,
        data: Any = None,
        files: Any = None,
        headers: Dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> ApiResponse:
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        merged_headers = self._build_headers(headers)

        log.debug("→ %s %s | params=%s | json=%s", method, url, params, json_body)
        start = time.perf_counter()
        try:
            resp = self._session.request(
                method=method,
                url=url,
                params=params,
                json=json_body,
                data=data,
                files=files,
                headers=merged_headers,
                timeout=timeout or self.timeout,
                verify=self.verify,
            )
        except requests.exceptions.ReadTimeout as exc:
            raise AssertionError(f"请求超时 {method} {url}（>{timeout or self.timeout}s）") from exc
        except requests.exceptions.ConnectionError as exc:
            raise AssertionError(
                f"无法连接被测服务 {method} {url}，请确认后端已启动且地址正确。原始错误：{exc}"
            ) from exc
        except requests.exceptions.RequestException as exc:  # pragma: no cover
            raise AssertionError(f"请求异常 {method} {url}：{exc}") from exc

        elapsed_ms = (time.perf_counter() - start) * 1000
        api_resp = ApiResponse(
            method=method.upper(),
            url=url,
            status_code=resp.status_code,
            elapsed_ms=elapsed_ms,
            text=resp.text,
            headers=dict(resp.headers),
        )
        log.debug("← HTTP %s (%dms): %s", resp.status_code, elapsed_ms,
                  api_resp.text[:300].replace("\n", " "))
        return api_resp

    def get(self, path: str, **kwargs) -> ApiResponse:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs) -> ApiResponse:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs) -> ApiResponse:
        return self.request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs) -> ApiResponse:
        return self.request("DELETE", path, **kwargs)

    def upload(self, path: str, file_path: str, field_name: str = "file",
               filename: str | None = None, content_type: str | None = None,
               timeout: float | None = None) -> ApiResponse:
        """multipart 文件上传。"""
        import os

        filename = filename or os.path.basename(file_path)
        content_type = content_type or "application/octet-stream"
        with open(file_path, "rb") as fh:
            files = {field_name: (filename, fh, content_type)}
            return self.request("POST", path, files=files, timeout=timeout)

    def close(self) -> None:
        self._session.close()
