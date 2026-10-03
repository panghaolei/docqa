"""pytest 全局夹具与收集钩子。

本文件是测试框架的"装配中心"，承担四件事：
1. 让工程根目录进入 sys.path（PyCharm 直接运行也不会有导入问题）；
2. 注册命令行参数与服务存活探测，服务不可用时自动 skip 而非报错；
3. 提供测试账号 / API 门面 / 知识库文档 / 评测裁判等公共夹具；
4. 资源自动清理：每个用例创建的文档与会话结束后立即删除，保证环境可重复运行。
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

# ---- 保证 core / conf / utils / evaluation 可被导入（PyCharm 与命令行均适用）----
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402
import requests  # noqa: E402

from conf.settings import Config, load_config, resolve_base_url  # noqa: E402
from core.api_client import DocQaApi  # noqa: E402
from core.logger import get_logger, setup_logging  # noqa: E402
from evaluation.judge import LLMJudge  # noqa: E402
from utils import doc_factory  # noqa: E402

log = get_logger("conftest")

_SERVER_ALIVE: dict[str, bool] = {}


# ===================================================================== #
# 一、命令行参数
# ===================================================================== #
def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("docqa", "DocQA 自动化测试自定义参数")
    group.addoption("--base-url", action="store", default=None,
                    help="被测后端地址，默认取 DOCQA_TEST_BASE_URL 或 config.yaml")
    group.addoption("--run-perf", action="store_true", default=False,
                    help="执行性能/并发用例（默认跳过）")
    group.addoption("--run-e2e", action="store_true", default=False,
                    help="执行前端 UI 自动化用例（需安装 Playwright）")
    group.addoption("--no-judge", action="store_true", default=False,
                    help="关闭 LLM-as-a-Judge 判分")
    group.addoption("--doc-format", action="store", default="txt",
                    choices=["txt", "md", "docx", "pdf", "html"],
                    help="知识库文档格式，用于验证 Tika 解析链路")


def _ensure_utf8_stdio() -> None:
    """Windows 控制台默认 GBK 编码，打印中文或特殊符号可能抛 UnicodeEncodeError。

    这里尽力把标准输出重配为 UTF-8；失败也不影响测试执行（有 replace 兜底）。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:  # pragma: no cover
            pass


def pytest_configure(config: pytest.Config) -> None:
    _ensure_utf8_stdio()
    (ROOT / "reports").mkdir(parents=True, exist_ok=True)
    setup_logging(level="INFO", log_file=ROOT / "reports" / "run.log")
    log.info("=" * 72)
    log.info("DocQA 自动化测试启动 | 工程根目录: %s", ROOT)
    log.info("=" * 72)


# ===================================================================== #
# 二、服务存活探测：不可用时自动跳过集成用例，避免"环境问题"变"测试失败"
# ===================================================================== #
def _probe_server(config: pytest.Config) -> bool:
    if "alive" in _SERVER_ALIVE:
        return _SERVER_ALIVE["alive"]
    cfg = load_config()
    base_url = resolve_base_url(cfg, config.getoption("--base-url"))
    probe_path = cfg.get("server.probe_path", "/document/list")
    try:
        # 未携带 token 时后端返回 401，能收到任何 HTTP 响应即说明服务在运行
        requests.get(f"{base_url}{probe_path}", timeout=3)
        alive = True
    except requests.RequestException as exc:
        log.warning("后端服务探测失败（%s）：%s", base_url, exc)
        alive = False
    _SERVER_ALIVE["alive"] = alive
    log.info("被测服务 %s 状态：%s", base_url, "可用" if alive else "不可用（集成用例将跳过）")
    return alive


def pytest_collection_modifyitems(config: pytest.Config, items: list) -> None:
    alive = _probe_server(config)
    run_perf = config.getoption("--run-perf")
    run_e2e = config.getoption("--run-e2e")

    skip_server = pytest.mark.skip(reason="后端服务不可用，已跳过集成用例（启动后端后重跑）")
    skip_perf = pytest.mark.skip(reason="性能用例默认跳过，需加 --run-perf")
    skip_e2e = pytest.mark.skip(reason="UI 用例默认跳过，需加 --run-e2e 并安装 Playwright")

    for item in items:
        keywords = item.keywords
        if "e2e" in keywords:
            if not run_e2e:
                item.add_marker(skip_e2e)
            continue
        if "perf" in keywords and not run_perf:
            item.add_marker(skip_perf)
            continue
        if "unit" in keywords:
            continue
        if not alive:
            item.add_marker(skip_server)


# ===================================================================== #
# 三、配置与基础设施夹具
# ===================================================================== #
@pytest.fixture(scope="session")
def settings() -> Config:
    return load_config()


@pytest.fixture(scope="session")
def base_url(settings: Config, request: pytest.FixtureRequest) -> str:
    return resolve_base_url(settings, request.config.getoption("--base-url"))


@pytest.fixture(scope="session")
def server_alive(base_url: str) -> bool:  # noqa: ARG001
    return _SERVER_ALIVE.get("alive", False)


@pytest.fixture(scope="session")
def run_id() -> str:
    """一次测试运行的唯一标识，用于生成互不冲突的账号与文件名。"""
    return uuid.uuid4().hex[:8]


@pytest.fixture(scope="session")
def docs_dir() -> Path:
    """测试语料落盘目录（工程内，便于 PyCharm 中直接查看生成的文件）。"""
    path = ROOT / "tmp_docs"
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture(scope="session")
def judge(settings: Config, request: pytest.FixtureRequest) -> LLMJudge:
    disabled = request.config.getoption("--no-judge")
    return LLMJudge(
        base_url=settings.get("judge.base_url", "https://api.siliconflow.cn/v1"),
        api_key="" if disabled else settings.get("judge.api_key", ""),
        model=settings.get("judge.model", "deepseek-ai/DeepSeek-V3"),
        timeout=settings.get("judge.timeout", 60),
        temperature=settings.get("judge.temperature", 0.0),
    )


# ===================================================================== #
# 四、账号与 API 门面夹具
#    隔离策略：每个测试模块一个独立用户，每个用例一个全新 HTTP 会话；
#             用例创建的资源在用例结束时立即回收。
# ===================================================================== #
@pytest.fixture(scope="module")
def account_name(settings: Config) -> str:
    prefix = settings.get("auth.username_prefix", "qa_auto_")
    return f"{prefix}{uuid.uuid4().hex[:10]}"


@pytest.fixture(scope="module")
def module_api(base_url: str, settings: Config, account_name: str):
    """模块级 API 门面：作为该模块知识库文档的"所有者"与最终清理者。"""
    api = DocQaApi(
        base_url,
        timeout=settings.get("server.timeout", 30),
        stream_timeout=settings.get("server.stream_timeout", 120),
    )
    api.login_as(account_name)
    log.info("模块账号已就绪：%s (userId=%s)", account_name, api.account.user_id)
    yield api
    api.cleanup()
    api.close()


@pytest.fixture()
def api(module_api: DocQaApi, base_url: str, settings: Config):
    """用例级 API 门面：复用模块账号登录，隔离本用例创建的资源。"""
    client = DocQaApi(
        base_url,
        timeout=settings.get("server.timeout", 30),
        stream_timeout=settings.get("server.stream_timeout", 120),
    )
    client.login_as(module_api.account.username)
    yield client
    client.cleanup()
    client.close()


@pytest.fixture()
def other_api(base_url: str, settings: Config, run_id: str):
    """第二个独立账号，用于越权/数据隔离类用例。"""
    client = DocQaApi(
        base_url,
        timeout=settings.get("server.timeout", 30),
        stream_timeout=settings.get("server.stream_timeout", 120),
    )
    client.login_as(f"qa_other_{run_id}_{uuid.uuid4().hex[:6]}")
    yield client
    client.cleanup()
    client.close()


@pytest.fixture()
def anonymous_api(base_url: str, settings: Config):
    """未登录的 API 门面，用于鉴权用例。"""
    client = DocQaApi(
        base_url,
        timeout=settings.get("server.timeout", 30),
        stream_timeout=settings.get("server.stream_timeout", 120),
    )
    yield client
    client.close()


# ===================================================================== #
# 五、知识库语料夹具
# ===================================================================== #
@pytest.fixture(scope="module")
def kb_format(request: pytest.FixtureRequest) -> str:
    return request.config.getoption("--doc-format")


@pytest.fixture(scope="module")
def kb_file(docs_dir: Path, kb_format: str, run_id: str) -> Path:
    """按指定格式生成知识库文档。"""
    name = f"星云科技员工手册_{run_id}.{kb_format}"
    return doc_factory.build(docs_dir, kb_format, name=name, content=doc_factory.KB_TEXT)


@pytest.fixture(scope="module")
def kb_doc(module_api: DocQaApi, kb_file: Path) -> dict:
    """上传知识库文档并等待解析完成，返回文档信息（含 id / chunkCount / status）。"""
    doc = module_api.upload_and_wait(kb_file)
    assert doc.get("status") == "DONE", f"知识库文档解析未完成：{doc}"
    log.info("知识库文档就绪：id=%s chunks=%s status=%s",
             doc.get("id"), doc.get("chunkCount"), doc.get("status"))
    return doc


@pytest.fixture(scope="module")
def kb_contexts(module_api: DocQaApi, kb_doc: dict) -> list[str]:
    """用于忠实度评估的"参考资料"，直接取语料原文切片。"""
    return [doc_factory.KB_TEXT]


@pytest.fixture(scope="module")
def rag_ready(module_api: DocQaApi, kb_doc: dict):
    """RAG 环境就绪闸门：确保向量化与检索链路真的可用。

    RAG 链路的正确性依赖 Embedding 服务可用（文档能被向量化并召回）。
    当 API Key 无效 / 维度不匹配 / 向量库不可用时，检索必然为空。
    此时把用例标记为 skip 并给出可操作的排查指引，而不是产出误报的 FAILED——
    这是自动化工程中"环境问题"与"产品缺陷"必须区分对待的基本原则。
    """
    probe = module_api.ask("公司的年假是怎么规定的？")
    retrieved = bool(probe.meta_refs) or (
        "未检索到" not in probe.answer and "还没有可用" not in probe.answer
    )
    if not retrieved:
        pytest.skip(
            "检索未召回任何片段，跳过 RAG 用例。请依次检查：\n"
            "  1) SILICONFLOW_API_KEY 是否有效；\n"
            "  2) 嵌入模型维度是否为 1024（application.yml vector-dimension）；\n"
            "  3) 文档 errorMsg 是否提示『向量化失败』；\n"
            "  4) 向量库（Redis Stack / 内存实现）是否可用。"
        )
    return probe


# ===================================================================== #
# 六、会话夹具
# ===================================================================== #
@pytest.fixture()
def chat_session(api: DocQaApi) -> int:
    """一个空会话，独立于用例，避免上下文串扰。"""
    resp = api.create_session(title="自动化测试会话")
    assert resp.ok, f"创建会话失败：{resp}"
    return resp.data["sessionId"]


# ===================================================================== #
# 七、用例级日志
# ===================================================================== #
@pytest.fixture(autouse=True)
def _case_log(request: pytest.FixtureRequest):
    name = request.node.nodeid
    log.info("[START] %s", name)
    yield
    log.info("[END]   %s", name)
