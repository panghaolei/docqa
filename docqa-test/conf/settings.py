"""配置加载：YAML 配置 + 环境变量插值 + .env 支持。

设计要点：
1. 配置与代码分离，改环境不改代码（可用 CI 环境变量覆盖）；
2. 支持 ``${VAR}`` 与 ``${VAR:-默认值}`` 两种插值语法；
3. 用点号路径读取嵌套配置，例如 ``cfg.get("rag.chunk_size")``。
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict

import yaml

try:  # python-dotenv 为可选依赖
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

# 工程根目录：docqa-test/
PROJECT_ROOT = Path(__file__).resolve().parents[1]

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z0-9_]+)(?::-([^}]*))?\}")


class Config:
    """轻量配置容器，支持点号路径访问。"""

    def __init__(self, data: Dict[str, Any], source: Path | None = None):
        self._data = data or {}
        self.source = source

    def get(self, key: str, default: Any = None) -> Any:
        cur: Any = self._data
        for part in key.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def require(self, key: str) -> Any:
        value = self.get(key)
        if value is None:
            raise KeyError(f"配置项缺失：{key}（请检查 conf/config.yaml）")
        return value

    def path(self, key: str, default: str | None = None) -> Path:
        """读取相对工程根目录的路径配置并转为绝对路径。"""
        raw = self.get(key, default)
        if raw is None:
            raise KeyError(f"路径配置缺失：{key}")
        p = Path(raw)
        return p if p.is_absolute() else (PROJECT_ROOT / p).resolve()

    def as_dict(self) -> Dict[str, Any]:
        return self._data

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Config source={self.source} keys={list(self._data)}>"


def _expand(value: Any) -> Any:
    """递归展开字符串中的环境变量占位符。"""
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    if not isinstance(value, str):
        return value

    def _replace(match: re.Match) -> str:
        name, default = match.group(1), match.group(2)
        env_val = os.environ.get(name)
        if env_val is not None and env_val != "":
            return env_val
        return default if default is not None else ""

    return _ENV_PATTERN.sub(_replace, value)


def load_config(path: str | Path | None = None) -> Config:
    """加载配置文件；默认读取 conf/config.yaml，并自动加载 .env。"""
    if load_dotenv is not None:
        env_file = PROJECT_ROOT / ".env"
        if env_file.exists():
            load_dotenv(env_file, override=False)

    cfg_path = Path(path) if path else (PROJECT_ROOT / "conf" / "config.yaml")
    if not cfg_path.exists():
        raise FileNotFoundError(f"配置文件不存在：{cfg_path}")

    with cfg_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return Config(_expand(raw), source=cfg_path)


def resolve_base_url(cfg: Config, cli_value: str | None = None) -> str:
    """确定被测服务地址，优先级：命令行 > 环境变量 > 配置文件。"""
    base = cli_value or cfg.get("server.base_url", "http://localhost:8080/api")
    return str(base).rstrip("/")
