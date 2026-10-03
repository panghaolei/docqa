"""契约（JSON Schema）定义与校验。

被测后端统一响应结构为 ``ApiResult<T> = {code:int, message:str, data:T}``，
这里用 JSON Schema 固化字段类型与必填性，实现"契约测试"：
后端一旦改了响应结构，测试会立刻失败，而不是等到前端联调才发现。
"""

from __future__ import annotations

from typing import Any, Dict

try:
    import jsonschema
    _HAS_JSONSCHEMA = True
except ImportError:  # pragma: no cover
    _HAS_JSONSCHEMA = False


# ---------------------------------------------------------------- #
# 通用结构
# ---------------------------------------------------------------- #
API_RESULT = {
    "type": "object",
    "required": ["code", "message"],
    "properties": {
        "code": {"type": "integer"},
        "message": {"type": "string"},
        "data": {},
    },
    "additionalProperties": True,
}

LOGIN_DATA = {
    "type": "object",
    "required": ["userId", "username", "token"],
    "properties": {
        "userId": {"type": "integer"},
        "username": {"type": "string", "minLength": 1},
        "token": {"type": "string", "minLength": 8},
    },
}

DOCUMENT_ITEM = {
    "type": "object",
    "required": ["id", "fileName", "fileSize", "fileType", "status"],
    "properties": {
        "id": {"type": "integer"},
        "fileName": {"type": "string"},
        "fileSize": {"type": "integer", "minimum": 0},
        "fileType": {"type": "string"},
        "chunkCount": {"type": ["integer", "null"], "minimum": 0},
        "status": {"type": "string", "enum": ["PENDING", "PROCESSING", "DONE", "FAILED"]},
        "errorMsg": {"type": ["string", "null"]},
        "createdAt": {"type": ["string", "null"]},
        "preview": {"type": ["string", "null"]},
    },
    "additionalProperties": True,
}

DOCUMENT_LIST = {"type": "array", "items": DOCUMENT_ITEM}

CHAT_SESSION = {
    "type": "object",
    "required": ["id", "title", "userId"],
    "properties": {
        "id": {"type": "integer"},
        "title": {"type": "string"},
        "userId": {"type": "integer"},
    },
    "additionalProperties": True,
}

CHAT_SESSION_LIST = {"type": "array", "items": CHAT_SESSION}

CHAT_MESSAGE = {
    "type": "object",
    "required": ["id", "role", "content"],
    "properties": {
        "id": {"type": "integer"},
        "role": {"type": "string", "enum": ["USER", "ASSISTANT", "user", "assistant"]},
        "content": {"type": "string"},
        "references": {"type": ["string", "null"]},
        "createdAt": {"type": ["string", "null"]},
    },
    "additionalProperties": True,
}

CHAT_MESSAGE_LIST = {"type": "array", "items": CHAT_MESSAGE}


def validate(data: Any, schema: Dict[str, Any], label: str = "响应") -> None:
    """按 JSON Schema 校验数据，失败时给出可读的字段级错误。"""
    if not _HAS_JSONSCHEMA:  # 兜底：至少校验必填字段
        if isinstance(schema, dict) and isinstance(data, dict):
            for field in schema.get("required", []):
                assert field in data, f"{label} 缺少必填字段 '{field}'，实际字段：{list(data)}"
        return
    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as exc:
        path = "/".join(str(p) for p in exc.absolute_path) or "<root>"
        raise AssertionError(
            f"{label} 不符合契约\n  字段路径: {path}\n  原因: {exc.message}\n"
            f"  实际数据: {str(data)[:500]}"
        ) from exc
