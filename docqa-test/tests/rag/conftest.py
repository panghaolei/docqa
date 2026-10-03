"""RAG 测试层常量。

公共夹具（module_api / kb_doc / kb_file / rag_ready）统一在 tests/conftest.py 中定义，
这样 api / rag / perf 各层可以复用同一套前置条件，避免夹具重复与作用域冲突。
"""

# 知识库文档名的关键片段，用于"引用来源"断言
KB_SOURCE_KEYWORD = "星云科技员工手册"
