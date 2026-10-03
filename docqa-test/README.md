# DocQA 自动化测试工程

针对 **智能 RAG 文档问答系统（DocQA）** 的自动化测试工程，使用 Python + pytest 编写，
在 PyCharm 中开箱即跑。

覆盖范围：**单元测试 → 接口测试 → RAG 端到端 → 效果评测 → 性能并发 → 前端 UI 自动化**，
并内置质量门禁（指标不达标即判失败）与 HTML 报告。

---

## 一、为什么需要这套测试

DocQA 是"Spring Boot + Spring AI + 大模型"的 RAG 系统，它的质量风险与传统 CRUD 系统完全不同：

| 风险点 | 传统断言为什么无效 | 本工程的应对 |
|--------|-------------------|-------------|
| 大模型输出是自然语言 | `assert answer == "10 天"` 必然失败 | 关键词命中率 + LLM-as-a-Judge 语义判分 |
| 检索依赖 Embedding 质量 | 无接口可断言 | Golden Set 评测集 + 引用来源准确率 |
| SSE 流式协议易退化 | 只能看到"最终有内容" | 逐事件断言（顺序 / 首 token 时延 / 分片数） |
| 切片参数漂移导致召回下降 | 无人发现 | 用参考实现做**差分测试**预测 `chunkCount` |
| 大模型调用成本高 | 只能事后看账单 | 断言"该短路时必须短路"（闲聊/无文档/检索为空） |
| 并发下的降级能力 | 单线程测试发现不了 | 多线程并发压测 + P95 时延门禁 |

---

## 二、目录结构

```
docqa-test/
├── run_all.py                  # ★ PyCharm 一键运行入口
├── requirements.txt
├── pytest.ini                  # 用例标记、默认参数、报告配置
├── .env.example                # 环境变量模板（复制为 .env）
│
├── conf/                       # 配置层
│   ├── config.yaml             # 全部可调参数（地址/阈值/切片规格/评测集）
│   └── settings.py             # YAML + 环境变量插值，支持 ${VAR:-default}
│
├── core/                       # 通用能力层（与业务无关，可复用）
│   ├── http_client.py          # Session 复用 / 鉴权注入 / 耗时统计 / 异常包装
│   ├── sse_client.py           # ★ SSE 流式解析与性能指标采集
│   ├── api_client.py           # API Object：登录/文档/会话/问答 + 资源自动回收
│   ├── assertions.py           # 公共断言（含泄露检测、失败信息可读化）
│   ├── schema.py               # JSON Schema 契约定义
│   └── logger.py               # 控制台 + 文件双通道日志
│
├── evaluation/                 # RAG 评测层
│   ├── dataset.yaml            # Golden Set：问题 + 期望事实 + 期望来源
│   ├── metrics.py              # 命中率 / 引用准确率 / 分位数 / 忠实度代理
│   └── judge.py                # LLM-as-a-Judge（忠实度/相关性/完整性 三维打分）
│
├── utils/
│   ├── doc_factory.py          # 生成 txt/md/html/docx/pdf 测试语料
│   └── chunker_model.py        # 切片算法参考实现（差分测试 Oracle）
│
├── tests/
│   ├── conftest.py             # 全局夹具装配、服务探测、自动跳过、资源清理
│   ├── unit/                   # 单元测试（无需后端）
│   │   ├── test_text_chunker.py        # 切片算法不变量
│   │   ├── test_chitchat_rule.py       # 闲聊规则等价类与边界
│   │   ├── test_evaluation_metrics.py  # 评测指标自检（先证明尺子是准的）
│   │   └── test_framework_selftest.py  # 框架自检（Mock Server 验证 SSE/HTTP 客户端）
│   ├── api/                    # 接口测试
│   │   ├── test_user_login.py          # 登录：等价类/边界/幂等/契约
│   │   ├── test_auth_security.py       # 鉴权 401 + 横向越权（IDOR）
│   │   ├── test_document_api.py        # 上传/多格式解析/差分测试/删除
│   │   ├── test_chat_session_api.py    # 会话与消息
│   │   ├── test_contract_schema.py     # 前后端契约（code/message/data）
│   │   └── test_boundary_injection.py  # SQL 注入 / XSS / 编码 / 超长输入
│   ├── rag/                    # RAG 测试
│   │   ├── test_sse_stream.py          # 流式协议与性能
│   │   ├── test_short_circuit.py       # 短路优化（省钱 & 降延迟）
│   │   ├── test_rag_qa.py              # 事实正确性 / 多轮 / 防幻觉
│   │   └── test_rag_evaluation.py      # ★ 评测集 + 质量门禁 + 报告落盘
│   ├── perf/
│   │   └── test_performance.py         # 并发上传 / 并发问答 / 时延漂移
│   └── e2e/
│       └── test_ui_flow.py             # Playwright 前端全流程
│
├── docs/
│   └── TECH_POINTS.md          # ★ 知识点梳理 + 简历写法
└── reports/                    # 运行产物：report.html / run.log / rag_evaluation.json
```

---

## 三、快速开始（PyCharm）

### 1. 安装依赖

```bash
cd docqa-test
pip install -r requirements.txt
```

> PyCharm：`Settings → Project → Python Interpreter → Add Interpreter` 选择本机 Python 3.10+，
> 再在 Terminal 中执行上面的命令即可。

### 2. 配置被测环境

```bash
copy .env.example .env      # Windows
# 编辑 .env，填写 DOCQA_TEST_BASE_URL 与 SILICONFLOW_API_KEY
```

### 3. 启动被测后端（可选）

```bash
# 只跑单元测试时无需启动后端
cd ../docker && docker compose up -d mysql redis rabbitmq
cd ../docqa-backend && mvn spring-boot:run
```

### 4. 运行

**方式 A：一键入口（推荐）**

PyCharm → `Run` → `Edit Configurations` → 新增 `Python`：
- Script path：`docqa-test/run_all.py`
- Parameters：`--scope all`
- Working directory：`docqa-test`

**方式 B：直接跑 pytest**

```bash
python run_all.py                    # 全部（单元 + 接口 + RAG）
python run_all.py --scope unit       # 只跑单元测试，不需要后端
python run_all.py --scope perf       # 性能并发用例
python run_all.py --scope e2e        # 前端 UI 自动化
python run_all.py --doc-format pdf   # 用 PDF 语料跑，验证 Tika 解析链路
python run_all.py --open-report      # 跑完自动打开 HTML 报告
```

**方式 C：pytest 原生**

```bash
pytest tests/unit -v
pytest tests/api tests/rag -v -m "not ai"
pytest --base-url http://192.168.1.10:8080/api
```

---

## 四、测试分层与用例分布

| 层级 | 目录 | 用例数 | 是否需要后端 | 关注点 |
|------|------|--------|-------------|--------|
| 单元 | `tests/unit` | 74 | 否 | 算法规格、规则等价类、评测指标、框架自检 |
| 接口 | `tests/api` | ~90 | 是 | 功能正确性、契约、边界、注入、越权 |
| RAG | `tests/rag` | ~40 | 是 + LLM | 流式协议、短路、事实正确性、质量评测 |
| 性能 | `tests/perf` | 3 | 是 | 并发成功率、P95 时延、时延漂移 |
| UI | `tests/e2e` | 8 | 是 + 前端 | 真实浏览器全流程 |

> 后端未启动时，集成类用例会**自动跳过**并给出原因，不会产生误报失败；
> 单元测试始终可跑，保证 `pytest` 在任何环境下都能给出有效结论。

---

## 五、自定义参数

| 参数 | 说明 |
|------|------|
| `--base-url` | 被测后端地址，覆盖配置文件 |
| `--doc-format` | 知识库语料格式 `txt/md/html/docx/pdf` |
| `--run-perf` | 执行性能并发用例（默认跳过） |
| `--run-e2e` | 执行 Playwright UI 用例（默认跳过） |
| `--no-judge` | 关闭 LLM 判分（省 token，只跑指标类断言） |
| `-m "smoke"` | 只跑冒烟用例 |

常用标记：`unit` / `smoke` / `api` / `rag` / `perf` / `e2e` / `ai`

---

## 六、质量门禁阈值

全部集中在 `conf/config.yaml` 的 `thresholds` 段，可按项目阶段调整：

```yaml
thresholds:
  first_token_latency_ms: 15000     # SSE 首 token 时延上限
  short_circuit_latency_ms: 3000    # 短路响应上限
  keyword_hit_rate: 0.75            # 评测集关键词命中率下限
  citation_accuracy: 0.75           # 引用来源准确率下限
  judge_min_score: 3.0              # LLM 判分（1~5）均分下限
  p95_latency_ms: 45000             # 问答 P95 时延上限
  concurrent_success_rate: 1.0      # 并发成功率下限
```

---

## 七、运行产物

| 文件 | 说明 |
|------|------|
| `reports/report.html` | pytest-html 可视化报告（用例耗时、失败详情、日志） |
| `reports/run.log` | 完整请求/响应链路日志，便于定位问题 |
| `reports/rag_evaluation.json` | RAG 评测明细：每条问题的回答、命中情况、时延、判分 |
| `reports/e2e/*.png` | UI 自动化各步骤截图 |
| `tmp_docs/` | 生成的测试语料（便于手工复现问题） |

---

## 八、常见问题

**Q1：全部集成用例都被 skip 了？**
说明后端未启动或地址不对。检查 `DOCQA_TEST_BASE_URL` 是否指向后端 `context-path`（默认 `/api`），
并确认 `curl http://localhost:8080/api/document/list` 能收到 401（收到响应即说明服务在跑）。

**Q2：RAG 用例被 skip，提示"检索未召回任何片段"？**
说明文档没有被成功向量化。依次检查：`SILICONFLOW_API_KEY` 是否有效、嵌入模型维度是否为 1024、
上传响应里的 `errorMsg` 字段是否提示"向量化失败"。

**Q3：LLM 判分用例被 skip？**
未配置 `SILICONFLOW_API_KEY` 或未安装 `openai`。配置后会额外消耗少量 token（每题一次判分调用）。

**Q4：性能用例太慢 / 打满 API 配额？**
调小 `conf/config.yaml` 中的 `thresholds.concurrent_users`（默认 5），或加 `--no-judge`、`-m "not rag"`。

**Q5：xpass / xfail 是什么？**
`xfail` 表示"**已知缺陷**，当前预期失败"。本工程用它固化扫出来的安全/健壮性问题
（如未校验归属导致的越权），修复后会变成 `XPASS`，提示把标记改成强制断言。

---

## 九、License

MIT
