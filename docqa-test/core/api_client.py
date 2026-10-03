"""被测系统业务 API 封装层（API Object 模式）。

把 ``/user`` ``/document`` ``/chat`` 三组接口封装成方法，测试用例只表达业务意图，
不出现 url / header / json 拼装细节。好处：
1. 接口改动只需改这一层，用例零改动；
2. 统一处理"创建即登记、结束即清理"，避免测试脏数据污染环境；
3. 内置异步解析轮询，屏蔽 local（同步）与 full（MQ 异步）两种运行模式差异。
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core.http_client import ApiResponse, HttpClient
from core.logger import get_logger
from core.sse_client import StreamResult, stream_ask

log = get_logger("api")

CONTENT_TYPES = {
    "txt": "text/plain",
    "md": "text/markdown",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
    "html": "text/html",
    "csv": "text/csv",
}


@dataclass
class LoginAccount:
    user_id: int
    username: str
    token: str


class DocQaApi:
    """DocQA 后端接口门面。"""

    def __init__(self, base_url: str, timeout: float = 30, stream_timeout: float = 120):
        self.base_url = base_url.rstrip("/")
        self.http = HttpClient(self.base_url, timeout=timeout)
        self.stream_timeout = stream_timeout
        self.account: Optional[LoginAccount] = None
        # 资源登记表，用于用例结束后的自动清理
        self.created_docs: List[int] = []
        self.created_sessions: List[int] = []

    # ============================================================ #
    # 用户 / 鉴权
    # ============================================================ #
    @staticmethod
    def new_username(prefix: str = "qa_auto_") -> str:
        return f"{prefix}{uuid.uuid4().hex[:10]}"

    def login(self, username: str) -> ApiResponse:
        resp = self.http.post("/user/login", json_body={"username": username})
        if resp.ok and isinstance(resp.data, dict):
            self.account = LoginAccount(
                user_id=resp.data.get("userId"),
                username=resp.data.get("username"),
                token=resp.data.get("token"),
            )
            self.http.set_token(self.account.token)
        return resp

    def login_as(self, username: str) -> LoginAccount:
        resp = self.login(username)
        assert resp.ok and self.account, f"登录失败：{resp}"
        return self.account

    def relogin(self, username: str) -> ApiResponse:
        """重新登录但不改变当前会话 token（用于验证 token 稳定性）。"""
        return self.http.post("/user/login", json_body={"username": username})

    @property
    def token(self) -> Optional[str]:
        return self.http.token

    # ============================================================ #
    # 文档
    # ============================================================ #
    def upload(self, file_path: str | os.PathLike, filename: str | None = None,
               content_type: str | None = None, track: bool = True) -> ApiResponse:
        path = str(file_path)
        filename = filename or os.path.basename(path)
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        ctype = content_type or CONTENT_TYPES.get(ext, "application/octet-stream")
        resp = self.http.upload("/document/upload", path, filename=filename,
                                content_type=ctype)
        if track and resp.ok and isinstance(resp.data, dict) and resp.data.get("id"):
            self.created_docs.append(resp.data["id"])
        return resp

    def upload_raw(self, path: str, files: Any) -> ApiResponse:
        """直接透传 multipart 描述，用于异常入参用例（缺字段 / 空文件）。"""
        return self.http.request("POST", path, files=files)

    def list_documents(self) -> ApiResponse:
        return self.http.get("/document/list")

    def delete_document(self, doc_id: int) -> ApiResponse:
        resp = self.http.delete(f"/document/{doc_id}")
        if doc_id in self.created_docs:
            self.created_docs.remove(doc_id)
        return resp

    def get_document(self, doc_id: int) -> Optional[Dict[str, Any]]:
        resp = self.list_documents()
        for item in (resp.data or []):
            if item.get("id") == doc_id:
                return item
        return None

    def wait_document_ready(self, doc_id: int, timeout: float = 90,
                            interval: float = 1.0) -> Dict[str, Any]:
        """轮询等待文档解析完成（兼容 MQ 异步解析模式）。"""
        deadline = time.time() + timeout
        last: Dict[str, Any] = {}
        while time.time() < deadline:
            item = self.get_document(doc_id)
            if item:
                last = item
                if item.get("status") in ("DONE", "FAILED"):
                    return item
            time.sleep(interval)
        raise AssertionError(
            f"文档 {doc_id} 在 {timeout}s 内未解析完成，最后状态：{last}"
        )

    def upload_and_wait(self, file_path: str | os.PathLike, filename: str | None = None,
                        timeout: float = 90) -> Dict[str, Any]:
        resp = self.upload(file_path, filename=filename)
        assert resp.ok, f"文档上传失败：{resp}"
        doc_id = resp.data["id"]
        return self.wait_document_ready(doc_id, timeout=timeout)

    # ============================================================ #
    # 会话
    # ============================================================ #
    def create_session(self, title: str | None = None, track: bool = True) -> ApiResponse:
        body = {} if title is None else {"title": title}
        resp = self.http.post("/chat/session", json_body=body)
        if track and resp.ok and isinstance(resp.data, dict):
            self.created_sessions.append(resp.data.get("sessionId"))
        return resp

    def list_sessions(self) -> ApiResponse:
        return self.http.get("/chat/sessions")

    def messages(self, session_id: int) -> ApiResponse:
        return self.http.get(f"/chat/messages/{session_id}")

    def delete_session(self, session_id: int) -> ApiResponse:
        resp = self.http.delete(f"/chat/session/{session_id}")
        if session_id in self.created_sessions:
            self.created_sessions.remove(session_id)
        return resp

    # ============================================================ #
    # 问答
    # ============================================================ #
    def ask(self, question: str, session_id: int | str | None = None) -> StreamResult:
        """流式问答（SSE），自动登记新建的会话。"""
        result = stream_ask(
            self.base_url, self.token, question,
            session_id=session_id, timeout=self.stream_timeout,
        )
        if result.session_id and result.session_id.isdigit():
            sid = int(result.session_id)
            if sid not in self.created_sessions:
                self.created_sessions.append(sid)
        return result

    def ask_raw(self, question: str, session_id: int | None = None) -> ApiResponse:
        """以普通 POST 调用流式端点，用于校验入参异常时的响应。"""
        body: Dict[str, Any] = {"question": question}
        if session_id is not None:
            body["sessionId"] = session_id
        return self.http.request(
            "POST", "/chat/ask/stream", json_body=body,
            headers={"Accept": "text/event-stream"}, timeout=30,
        )

    # ============================================================ #
    # 清理
    # ============================================================ #
    def cleanup(self) -> None:
        """删除本次用例创建的所有会话与文档（失败不影响主流程）。"""
        for sid in list(self.created_sessions):
            try:
                self.delete_session(sid)
            except Exception as exc:  # pragma: no cover
                log.warning("清理会话 %s 失败: %s", sid, exc)
        for did in list(self.created_docs):
            try:
                self.delete_document(did)
            except Exception as exc:  # pragma: no cover
                log.warning("清理文档 %s 失败: %s", did, exc)

    def close(self) -> None:
        self.http.close()
