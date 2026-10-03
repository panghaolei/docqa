"""文档接口测试：上传 / 列表 / 删除 + 解析链路（Tika → 切片 → 向量化）。

被测接口：
    POST   /api/document/upload   multipart 上传，同步或异步解析
    GET    /api/document/list     当前用户文档列表
    DELETE /api/document/{id}     删除文档（同时清理向量）

重点：
1. 多格式解析覆盖（txt / md / html / docx / pdf）——Tika 是 RAG 链路的入口，风险最高；
2. **差分测试**：用参考实现预测 chunkCount，与后端真实返回值比对，锁住切片参数；
3. 状态机：PENDING → PROCESSING → DONE|FAILED，FAILED 必须带 errorMsg；
4. 幂等与清理：删除后再查列表不应存在，重复上传应生成独立记录。
"""

from __future__ import annotations

import pytest

from core import schema
from core.assertions import (
    assert_api_success,
    assert_contains,
    assert_equal,
    assert_failed,
    assert_gte,
    assert_latency,
    assert_no_leak,
    assert_no_server_error,
)
from utils import doc_factory
from utils.chunker_model import DEFAULT_CHUNK_SIZE, DEFAULT_OVERLAP, predict_chunk_count

pytestmark = pytest.mark.api


# ===================================================================== #
# 上传：正常路径
# ===================================================================== #
def test_upload_txt_success_and_contract(api, docs_dir, run_id):
    """正常上传 txt：返回体契约正确、状态机收敛到 DONE、切片数 > 0。"""
    file_path = doc_factory.build(docs_dir, "txt", f"手册_{run_id}.txt")
    resp = api.upload(file_path)
    data = assert_api_success(resp)
    schema.validate(data, schema.DOCUMENT_ITEM, "上传响应 data")

    assert_equal(data["fileName"], file_path.name, "文件名")
    assert_equal(data["fileType"], "txt", "文件类型")
    assert data["fileSize"] > 0

    # 解析已异步化，轮询等待状态收敛到 DONE 后再断言解析结果
    done = api.wait_document_ready(data["id"])
    assert_equal(done["status"], "DONE", "解析状态")
    assert_gte(done["chunkCount"], 1, "切片数量")


def test_upload_returns_persisted_document_in_list(api, docs_dir, run_id):
    """一致性：上传返回的文档必须能被列表接口查到，字段一致。"""
    doc = api.upload_and_wait(doc_factory.build(docs_dir, "txt", f"列表校验_{run_id}.txt"))
    listed = api.get_document(doc["id"])
    assert listed is not None, "刚上传的文档未出现在列表中"
    assert_equal(listed["status"], "DONE", "列表中的状态")
    assert_equal(listed["chunkCount"], doc["chunkCount"], "列表中的切片数")


def test_upload_same_file_twice_creates_independent_records(api, docs_dir, run_id):
    """幂等性反向验证：同一文件重复上传应生成两条独立记录（不同 docId）。"""
    file_path = doc_factory.build(docs_dir, "txt", f"重复上传_{run_id}.txt")
    first = api.upload_and_wait(file_path)
    second = api.upload_and_wait(file_path)
    assert first["id"] != second["id"], "重复上传被错误地去重了"
    assert_equal(second["chunkCount"], first["chunkCount"], "同一文件两次切片数")


@pytest.mark.parametrize("ext", ["txt", "md", "html", "docx", "pdf"])
def test_upload_supported_formats_are_parsed(api, docs_dir, run_id, ext):
    """多格式解析覆盖：Tika 对主流格式都必须能提取出正文并完成切片。"""
    try:
        file_path = doc_factory.build(docs_dir, ext, f"多格式_{ext}_{run_id}.{ext}")
    except ImportError as exc:  # reportlab / python-docx 未安装
        pytest.skip(f"生成 {ext} 需要的依赖未安装：{exc}")

    doc = api.upload_and_wait(file_path)
    assert_equal(doc["status"], "DONE", f"{ext} 文档解析状态")
    assert_gte(doc["chunkCount"], 1, f"{ext} 文档切片数")


def test_upload_long_document_creates_more_chunks(api, docs_dir, run_id):
    """单调性不变量：文档越长，切片数必须越多（不能出现固定切片数）。"""
    short = api.upload_and_wait(doc_factory.build(docs_dir, "txt", f"短文档_{run_id}.txt"))
    long_path = doc_factory.make_long_text_doc(docs_dir / f"长文档_{run_id}.txt", repeat=8)
    long_doc = api.upload_and_wait(long_path)

    assert long_doc["chunkCount"] > short["chunkCount"], (
        f"长文档切片数({long_doc['chunkCount']}) 未大于短文档({short['chunkCount']})，"
        "切片逻辑可能失效"
    )


def test_chunk_count_matches_reference_model(api, docs_dir, run_id):
    """【差分测试】后端 chunkCount 必须与切片算法参考实现的预测值一致。

    允许 ±1 的偏差：Tika 在解析纯文本时可能对首尾空白/换行做微小规整，
    折叠后会影响边界处的切片数量。若偏差超过 1，说明切片参数已漂移。
    """
    file_path = doc_factory.build(docs_dir, "txt", f"差分测试_{run_id}.txt")
    doc = api.upload_and_wait(file_path)

    predicted = predict_chunk_count(
        doc_factory.KB_TEXT, DEFAULT_CHUNK_SIZE, DEFAULT_OVERLAP
    )
    actual = doc["chunkCount"]
    assert abs(actual - predicted) <= 1, (
        f"chunkCount 与参考模型不一致：后端={actual} 预测={predicted}\n"
        f"（语料 {len(doc_factory.KB_TEXT)} 字，chunk={DEFAULT_CHUNK_SIZE} overlap={DEFAULT_OVERLAP}）\n"
        "请检查 docqa.chunk.size / overlap 配置或 TextChunker 实现是否被改动。"
    )


def test_upload_filename_with_chinese_and_spaces(api, docs_dir, run_id):
    """文件名边界：中文、空格、括号等特殊字符必须能正确落库并回显。"""
    name = f"员工手册 2026（终版）_{run_id}.txt"
    doc = api.upload_and_wait(doc_factory.build(docs_dir, "txt", name))
    assert_equal(doc["fileName"], name, "中文/特殊字符文件名")


def test_upload_large_file_within_latency_budget(api, docs_dir, run_id, settings):
    """大文件（约 600KB）上传：必须成功且耗时在预算内。"""
    file_path = doc_factory.make_large_padded_doc(docs_dir / f"大文件_{run_id}.txt", target_kb=600)
    resp = api.upload(file_path)
    assert_api_success(resp)
    limit = settings.get("thresholds.upload_p95_latency_ms", 20000)
    assert_latency(resp, limit, "600KB 文档上传")


# ===================================================================== #
# 上传：异常路径
# ===================================================================== #
def test_upload_empty_file_is_rejected(api, docs_dir):
    """异常入参：0 字节文件必须被拒绝（否则会产生空向量、污染检索结果）。"""
    empty = doc_factory.make_empty_file(docs_dir / "empty.txt")
    resp = api.upload(empty, track=False)
    assert_failed(resp)


def test_upload_missing_file_field_is_rejected(api, docs_dir):
    """异常入参：multipart 中缺少 file 字段，必须被拒绝且不出现 5xx。"""
    resp = api.http.request("POST", "/document/upload", data={"foo": "bar"})
    assert_failed(resp)
    assert_no_server_error(resp, "缺少 file 字段的上传")


def test_upload_binary_file_fails_gracefully(api, docs_dir):
    """鲁棒性：上传非文档二进制文件（.exe）。

    期望：接口正常受理（记录落库），解析失败时状态为 FAILED 且 errorMsg 给出原因，
    绝不允许服务端抛未捕获异常或返回 5xx。
    """
    binary = doc_factory.make_fake_binary(docs_dir / "malware.exe")
    resp = api.upload(binary)
    assert_api_success(resp)
    doc = api.wait_document_ready(resp.data["id"])
    assert doc["status"] in ("DONE", "FAILED"), f"状态非法：{doc['status']}"
    if doc["status"] == "FAILED":
        assert doc.get("errorMsg"), "FAILED 状态必须携带 errorMsg 便于排查"


def test_upload_response_does_not_leak_internals(api, docs_dir):
    """安全性：上传响应不得泄露服务器路径、堆栈或密钥。"""
    path = doc_factory.build(docs_dir, "txt", "泄漏检查.txt")
    resp = api.upload(path)
    assert_no_leak(resp.text)


# ===================================================================== #
# 列表
# ===================================================================== #
def test_document_list_contract_and_ordering(api, docs_dir, run_id):
    """列表契约：数组结构正确，且按创建时间倒序（最新在前）。"""
    first = api.upload_and_wait(doc_factory.build(docs_dir, "txt", f"排序A_{run_id}.txt"))
    second = api.upload_and_wait(doc_factory.build(docs_dir, "txt", f"排序B_{run_id}.txt"))

    resp = api.list_documents()
    data = assert_api_success(resp)
    schema.validate(data, schema.DOCUMENT_LIST, "文档列表")
    ids = [d["id"] for d in data]
    assert first["id"] in ids and second["id"] in ids
    assert ids.index(second["id"]) < ids.index(first["id"]), "文档列表未按创建时间倒序"


def test_document_list_is_empty_for_new_user(other_api):
    """新建账号的文档列表应为空（验证按 userId 过滤生效）。"""
    assert_equal(assert_api_success(other_api.list_documents()), [], "新账号文档列表")


# ===================================================================== #
# 删除
# ===================================================================== #
def test_delete_document_removes_it_from_list(api, docs_dir, run_id):
    """删除闭环：删除成功后列表中不应再出现该文档。"""
    doc = api.upload_and_wait(doc_factory.build(docs_dir, "txt", f"待删除_{run_id}.txt"))
    assert_api_success(api.delete_document(doc["id"]))
    resp = api.list_documents()
    ids = [d["id"] for d in assert_api_success(resp)]
    assert doc["id"] not in ids, f"文档 {doc['id']} 删除后仍出现在列表中"


def test_delete_nonexistent_document_fails_gracefully(api):
    """异常入参：删除不存在的文档必须明确失败，不能静默成功、也不能 5xx。"""
    resp = api.delete_document(999_999_999)
    assert_failed(resp)
    assert resp.status_code < 500, f"删除不存在文档触发了 HTTP {resp.status_code}"


def test_delete_is_not_repeatable(api, docs_dir, run_id):
    """幂等性：同一文档删除两次，第二次必须失败（说明资源确实被回收）。"""
    doc = api.upload_and_wait(doc_factory.build(docs_dir, "txt", f"二次删除_{run_id}.txt"))
    assert_api_success(api.delete_document(doc["id"]))
    second = api.delete_document(doc["id"])
    assert_failed(second)
