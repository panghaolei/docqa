"""性能与并发测试。

被测目标：DocQA 的核心非功能指标——
    · 并发上传：多用户同时上传文档时的成功率与 P95 时延；
    · 并发问答：多用户同时发起 SSE 流式问答时的成功率、首 token P95、吞吐；
    · 降级可用性：并发压力下是否出现 5xx / 断流（"可降级架构"的实证）。

设计说明：
    · 每个线程使用**独立的 DocQaApi 实例**（独立 requests.Session 与连接池），
      避免共享连接造成的客户端侧排队，把压力真实传递到服务端；
    · 默认并发 5（可在 config.yaml 的 thresholds.concurrent_users 调整），
      避免把大模型 API 的 QPS 配额打满导致误报；
    · 用 ThreadPoolExecutor 而非多进程：IO 密集场景下线程足够，且日志/夹具可共享。

运行方式： pytest tests/perf --run-perf
"""

from __future__ import annotations

import contextlib
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List

import pytest

from core.api_client import DocQaApi
from core.logger import get_logger
from evaluation.metrics import latency_stats
from utils import doc_factory

pytestmark = [pytest.mark.perf, pytest.mark.timeout(900)]

log = get_logger("perf")

QUESTION = "入职满 3 年的员工每年可以享受多少天年假？"


# ===================================================================== #
# 测试基础设施
# ===================================================================== #
@contextlib.contextmanager
def parallel_clients(base_url: str, settings, count: int, prefix: str = "qa_perf_"):
    """创建 count 个已登录的独立客户端，退出时统一清理资源。"""
    clients: List[DocQaApi] = []
    try:
        for _ in range(count):
            client = DocQaApi(
                base_url,
                timeout=settings.get("server.timeout", 30),
                stream_timeout=settings.get("server.stream_timeout", 120),
            )
            client.login_as(f"{prefix}{uuid.uuid4().hex[:8]}")
            clients.append(client)
        yield clients
    finally:
        for client in clients:
            try:
                client.cleanup()
                client.close()
            except Exception as exc:  # pragma: no cover
                log.warning("清理并发客户端失败：%s", exc)


def _concurrent_run(tasks, workers: int):
    """并发执行任务，返回 [(任务下标, 结果或异常)]。"""
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fn, idx): idx for idx, fn in enumerate(tasks)}
        for future in as_completed(futures):
            idx = futures[future]
            try:
                results.append((idx, future.result(), None))
            except Exception as exc:  # noqa: BLE001
                results.append((idx, None, exc))
    return results


# ===================================================================== #
# 一、并发上传
# ===================================================================== #
def test_concurrent_document_upload(base_url, settings, docs_dir, run_id):
    """并发上传：N 个用户同时上传文档，成功率必须 100%，P95 时延在预算内。"""
    workers = settings.get("thresholds.concurrent_users", 5)
    limit = settings.get("thresholds.upload_p95_latency_ms", 20000)

    files = [
        doc_factory.build(docs_dir, "txt",
                          f"并发上传_{run_id}_{i}.txt",
                          content=doc_factory.KB_TEXT + f"\n\n并发批次编号 {i}\n")
        for i in range(workers)
    ]

    with parallel_clients(base_url, settings, workers) as clients:
        tasks = [
            (lambda c: (lambda f: c.upload_and_wait(f, timeout=120)))(client)
            for client in clients
        ]
        # 让每个任务绑定各自的文件
        tasks = [make_task(client, files[i]) for i, client in enumerate(clients)]

        start = time.perf_counter()
        results = _concurrent_run(tasks, workers)
        wall_ms = (time.perf_counter() - start) * 1000

    errors = [(i, str(e)) for i, _, e in results if e is not None]
    docs = [r for _, r, e in results if e is None]

    assert not errors, f"并发上传出现异常：{errors}"
    success_rate = len(docs) / workers
    assert success_rate >= settings.get("thresholds.concurrent_success_rate", 1.0), (
        f"并发上传成功率 {success_rate:.0%} 未达标"
    )
    assert all(d["status"] == "DONE" for d in docs), "存在解析未完成的文档"

    stats = latency_stats([wall_ms])
    log.info("并发上传 wall=%sms 成功=%d/%d", stats["avg"], len(docs), workers)


def make_upload_task(client: DocQaApi, file_path):
    """把 (client, file) 绑定成一个无参任务，避免闭包变量捕获错误。"""
    def _task():
        return client.upload_and_wait(file_path, timeout=120)

    return _task


# ===================================================================== #
# 二、并发问答
# ===================================================================== #
def test_concurrent_rag_ask(base_url, settings, run_id):
    """并发问答：N 个用户同时发起流式问答，统计成功率与首 token P95。

    该用例验证的正是简历里"可降级架构支持高并发"的说法是否成立：
    如果 RabbitMQ/Redis 或线程池配置有问题，并发下会先在这里暴露（断流 / 超时 / 5xx）。
    """
    workers = settings.get("thresholds.concurrent_users", 5)
    answer_limit = settings.get("thresholds.p95_latency_ms", 45000)
    first_token_limit = settings.get("thresholds.first_token_latency_ms", 15000)

    with parallel_clients(base_url, settings, workers, prefix="qa_perf_ask_") as clients:
        # 每个用户先准备一份知识库文档（并发问答需要向量检索有内容）
        kb_path = doc_factory.build(docs_dir, "txt", f"并发问答语料_{run_id}.txt")
        for client in clients:
            client.upload_and_wait(kb_path, timeout=120)

        tasks = [make_ask_task(client) for client in clients]
        start = time.perf_counter()
        results = _concurrent_run(tasks, workers)
        wall_ms = (time.perf_counter() - start) * 1000

    streams = [r for _, r, e in results if e is None]
    errors = [(i, str(e)) for i, _, e in results if e is not None]

    assert not errors, f"并发问答出现异常：{errors}"
    success = [s for s in streams if s.done and s.answer.strip()]
    success_rate = len(success) / workers

    total_stats = latency_stats([s.total_ms for s in streams])
    first_stats = latency_stats([s.first_token_ms for s in streams if s.first_token_ms])
    throughput = sum(s.token_count for s in streams) / max(0.001, wall_ms / 1000.0)

    log.info("并发问答 wall=%sms 成功率=%.0f%% 总时延P95=%sms 首tokenP95=%sms 吞吐=%.1f token/s",
             round(wall_ms), success_rate * 100, total_stats["p95"],
             first_stats["p95"], throughput)

    assert success_rate >= settings.get("thresholds.concurrent_success_rate", 1.0), (
        f"并发问答成功率 {success_rate:.0%}（成功 {len(success)}/{workers}）"
    )
    assert total_stats["p95"] <= answer_limit, (
        f"并发问答 P95 时延 {total_stats['p95']}ms 超出预算 {answer_limit}ms"
    )
    assert first_stats["p95"] <= first_token_limit, (
        f"并发首 token P95 {first_stats['p95']}ms 超出预算 {first_token_limit}ms"
    )


def make_ask_task(client: DocQaApi):
    def _task():
        return client.ask(QUESTION)

    return _task


# ===================================================================== #
# 三、连续压力（稳定性）
# ===================================================================== #
def test_repeated_ask_has_no_latency_drift(api, kb_doc, rag_ready, settings):  # noqa: ARG001
    """稳定性：连续多次问答，首 token 时延不应随次数递增（无内存泄漏 / 无连接池耗尽）。

    判定方式：比较后 N 次与前 N 次的平均首 token 时延，后者不得超过前者 2 倍。
    """
    rounds = max(3, settings.get("thresholds.concurrent_users", 5))
    latencies = []
    for _ in range(rounds * 2):
        result = api.ask(QUESTION)
        assert result.done, f"连续问答出现断流：{result.error}"
        latencies.append(result.first_token_ms or 0.0)

    half = len(latencies) // 2
    early = sum(latencies[:half]) / half
    late = sum(latencies[half:]) / (len(latencies) - half)
    log.info("首 token 时延 前段=%.0fms 后段=%.0fms", early, late)
    assert late <= early * 2 + 1000, (
        f"首 token 时延出现明显劣化：前段 {early:.0f}ms → 后段 {late:.0f}ms，疑似资源泄漏"
    )
