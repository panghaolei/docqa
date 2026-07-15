# 智能文档问答系统（DocQA）

基于 **Spring Boot 3.x + Spring AI** 的智能文档问答系统，LLM 与 Embedding 均通过 **硅基流动（SiliconFlow）API** 接入，实现 RAG（检索增强生成）式文档问答，支持流式打字机输出。

---

## 一、技术栈

| 层级 | 技术选型 |
|------|---------|
| 后端框架 | Spring Boot 3.3.x |
| AI 框架 | Spring AI 1.0 M3（`ChatClient` / `EmbeddingModel` / `VectorStore` 抽象） |
| LLM / Embedding | 硅基流动 API（兼容 OpenAI 协议）：`deepseek-ai/DeepSeek-V3` + `BAAI/bge-large-zh-v1.5` |
| 业务数据库 | MySQL 8.x |
| 向量库 / 缓存 | Redis（Redis Stack，含 RediSearch + RedisJSON 模块） |
| 消息队列 | RabbitMQ（文档解析与向量化异步削峰） |
| 文档解析 | Apache Tika 2.x（PDF / Word / TXT / HTML / Markdown） |
| 前端 | Vue 3 + Vite + Element Plus + marked.js + axios |
| 流式输出 | SSE（Server-Sent Events） |
| 部署 | Docker Compose 一键编排 |

---

## 二、系统架构

```
┌──────────┐    HTTP/SSE     ┌──────────────────────────────────────────┐
│  前端    │  ───────────▶   │           Spring Boot 后端                │
│ Vue3     │                 │  ┌────────┐ ┌─────────┐ ┌───────────┐    │
│ Element  │                 │  │Controller│ │ Service │ │ Spring AI │    │
│ marked   │                 │  └────────┘ └─────────┘ └─────┬─────┘    │
└──────────┘                 │                              │          │
                             │  ┌──────┐  ┌──────┐  ┌──────┐│          │
                             │  │MySQL │  │Redis │  │RabbitMQ│         │
                             │  └──────┘  └──┬───┘  └──┬───┘           │
                             └───────────────┼─────────┼───────────────┘
                                             │         │
                              向量库/缓存     │  异步解析│
                                             ▼         ▼
                                  ┌──────────────┐  ┌──────────────┐
                                  │  Redis Stack │  │  Tika 解析   │
                                  │ RediSearch   │  │  + Embedding │
                                  │  (KNN 检索)  │  └──────────────┘
                                  └──────────────┘
                                             │
                                             ▼
                                  ┌──────────────────────┐
                                  │  SiliconFlow API     │
                                  │  DeepSeek / BGE      │
                                  └──────────────────────┘
```

**核心流程：**
1. 用户上传文档 → 落盘 → 发送 MQ 消息
2. MQ 消费者：Tika 解析 → 文本切片 → Embedding → 写入 Redis 向量库
3. 用户提问 → 向量 KNN 检索相关片段 → 拼装 RAG Prompt → 调用 LLM 流式生成 → SSE 推送前端

---

## 三、目录结构

```
agentProject/
├── docqa-backend/                # 后端 Spring Boot 项目
│   ├── pom.xml
│   ├── Dockerfile
│   └── src/main/
│       ├── java/com/docqa/
│       │   ├── DocqaApplication.java
│       │   ├── config/           # AiConfig / RabbitMqConfig / RedisConfig / WebConfig
│       │   ├── controller/       # UserController / DocumentController / ChatController
│       │   ├── entity/           # UserEntity / DocumentEntity / ChatSession / ChatMessage
│       │   ├── repository/       # JPA Repository
│       │   ├── dto/              # API 请求/响应 DTO
│       │   ├── service/          # DocumentService / QaService / ChatSessionService ...
│       │   ├── vector/           # VectorService（封装 VectorStore）
│       │   ├── mq/               # RabbitMQ 消息与消费者
│       │   └── common/           # 拦截器 / 异常处理 / 用户上下文
│       └── resources/application.yml
├── docqa-frontend/               # 前端 Vue 3 项目
│   ├── package.json
│   ├── vite.config.js
│   ├── Dockerfile
│   ├── nginx.conf
│   └── src/
│       ├── main.js
│       ├── App.vue               # 主界面
│       ├── api.js                # axios 封装
│       ├── sse.js                # fetch 流式 SSE 工具
│       └── style.css
└── docker/
    ├── docker-compose.yml        # 一键编排
    ├── .env.example              # 环境变量模板
    └── init/sql/init.sql         # MySQL 初始化脚本
```

---

## 四、环境准备

### 4.1 必备条件
- JDK 17+
- Maven 3.9+
- Node.js 20+
- Docker & Docker Compose（推荐用于中间件）
- **硅基流动 API Key**（前往 https://siliconflow.cn 注册获取）

### 4.2 获取 SiliconFlow API Key
1. 访问 https://cloud.siliconflow.cn 注册账号
2. 在「API 密钥」页面创建密钥，形如 `sk-xxxxxxxxxxxx`
3. 可选模型：
   - 对话模型：`deepseek-ai/DeepSeek-V3`、`Qwen/Qwen2.5-7B-Instruct` 等
   - 嵌入模型：`BAAI/bge-large-zh-v1.5`（1024 维）、`BAAI/bge-m3` 等

---

## 五、快速启动（Docker Compose 一键部署）

> 最简单的启动方式，适合完整体验。

```bash
cd docker
cp .env.example .env
# 编辑 .env，填入你的 SILICONFLOW_API_KEY
docker compose up -d
```

启动完成后：
- 前端：http://localhost
- 后端 API：http://localhost:8080/api
- RabbitMQ 管理台：http://localhost:15672（guest/guest）
- RedisInsight：http://localhost:8001

---

## 六、本地开发启动（分别启动）

### 6.1 启动中间件（Docker）

```bash
cd docker
docker compose up -d mysql redis rabbitmq
```

### 6.2 启动后端

```bash
cd docqa-backend
# 方式一：配置环境变量（推荐）
# Windows PowerShell
$env:SILICONFLOW_API_KEY="sk-lhfpqklbnyketqckzffhpsmhlhplixuchrgrjoyfwyayxkde"
mvn spring-boot:run

# Linux/Mac
SILICONFLOW_API_KEY=sk-你的key mvn spring-boot:run
```

或直接编辑 `docqa-backend/src/main/resources/application.yml` 中的 `spring.ai.openai.api-key`。

后端启动于 http://localhost:8080/api

### 6.3 启动前端

```bash
cd docqa-frontend
npm install
npm run dev
```

前端启动于 http://localhost:5173

> Vite 已配置 `/api` 代理到后端 8080 端口。

---

## 七、配置说明（application.yml 关键项）

```yaml
spring:
  ai:
    openai:
      api-key: ${SILICONFLOW_API_KEY}        # 硅基流动 API Key
      base-url: https://api.siliconflow.cn   # 硅基流动地址（兼容 OpenAI）
      chat:
        options:
          model: deepseek-ai/DeepSeek-V3     # 对话模型，可切换
      embedding:
        options:
          model: BAAI/bge-large-zh-v1.5      # 嵌入模型，1024 维
    vectorstore:
      redis:
        index: docqa-vector-idx              # RediSearch 索引名
        prefix: "docqa:vec:"
        vector-dimension: 1024               # 与嵌入模型维度一致

docqa:
  chunk:
    size: 500        # 切片字符数
    overlap: 80      # 切片重叠
  rag:
    top-k: 4         # 检索返回条数
    system-prompt: |
      你是一个专业的文档问答助手...
  history:
    max-rounds: 6    # LLM 上下文保留轮数
```

**切换模型：** 修改 `application.yml` 或对应环境变量 `SILICONFLOW_CHAT_MODEL` / `SILICONFLOW_EMBEDDING_MODEL` 即可，无需改动代码（得益于 Spring AI 的抽象层）。

---

## 八、API 接口列表

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/user/login` | 登录（用户名自动注册并发放 token） |
| POST | `/api/document/upload` | 上传文档（multipart） |
| GET  | `/api/document/list` | 文档列表 |
| DELETE | `/api/document/{id}` | 删除文档 |
| POST | `/api/chat/session` | 创建会话 |
| GET  | `/api/chat/sessions` | 会话列表 |
| GET  | `/api/chat/messages/{sessionId}` | 历史消息 |
| DELETE | `/api/chat/session/{id}` | 删除会话 |
| POST | `/api/chat/ask/stream` | **流式问答（SSE）** |

**SSE 事件格式：**
- `event: session` → `data: <sessionId>`
- `event: token` → `data: <token片段>`
- `event: done` → `data: [DONE]`

> 除 `/user/login` 外，所有接口需在请求头携带 `Authorization: Bearer <token>`。

---

## 九、使用说明

1. 打开前端页面，输入用户名进入系统
2. 点击「上传文档」上传 PDF/Word/TXT 等文件，等待状态变为「已完成」
3. 在对话区输入问题，回车发送
4. AI 会基于文档内容流式输出 Markdown 格式的回答

---

## 十、常见问题

**Q1：Spring AI 依赖下载失败？**
A：需在 `pom.xml` 中配置 Spring Milestones 仓库（已配置）。若网络受限，可使用代理或镜像。

**Q2：Redis 向量检索不生效？**
A：必须使用 `redis/redis-stack` 镜像（含 RediSearch 模块），普通 Redis 不支持向量检索。

**Q3：文档解析失败？**
A：查看后端日志与 `doc_info.error_msg` 字段。Tika 对加密 PDF 等特殊文件可能无法解析。

**Q4：嵌入维度不匹配？**
A：`application.yml` 中 `vector-dimension` 必须与所选嵌入模型输出维度一致。`bge-large-zh-v1.5` 为 1024 维。

**Q5：SSE 在 Nginx 后被缓冲？**
A：前端 `nginx.conf` 已配置 `proxy_buffering off`。生产环境若使用其他反代需同样关闭缓冲。

---

## 十一、License

MIT
