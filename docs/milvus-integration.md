# Milvus 接入

## 范围与架构

本文描述 Milvus 阶段的存储接入。解析器为远程 MinerU，切分后直接保留原生 LangChain Document，见 [当前父子分块实现](langchain-chunking.md)。仅子 Document 建立向量索引，父 Document 在独立非向量存储中保存；检索后取回父块供 LLM 阅读。

```text
源文件 + PostgreSQL 文档清单
    -> MinerU / 脱敏 / LangChain 父子 Document
    -> 父 Document 写入 MySQL rag_parent_documents（无向量）
    -> 子 Document 指纹对账 -> 仅缺失/文本变化调用 BGE-M3
    -> Milvus upsert（子向量 + 子 Document JSON + ACL）

问题 -> Embedding
     -> Milvus ACL/命名空间前置过滤 + COSINE Top-K
     -> Milvus 原生 BM25 Top-K（原始问题文本）
     -> Milvus RRFRanker -> 应用候选词项重排 -> parent_id 去重 / MySQL 回取父块
     -> RagResult.context_documents -> Report LLM
```

## 模块职责

- `app/rag/milvus_store.py`：SDK 连接、专用集合校验、增量写入、分页读取、搜索、删除、探活。
- `app/rag/hybrid_retrieval.py`：Milvus 模式调用服务器 `hybrid_search`；显式 memory 测试模式仅使用向量与词项重合，不实现 BM25，也不是 Milvus 故障回退。
- `app/rag/management.py`：启动/管理员重索引对账、上传增量同步、删除同步；就绪状态在索引完成后保存。
- `app/main.py`：真实 Milvus 探活和资源关闭，健康响应显示 `vector_backend` 和 `vector_collection`，不返回连接凭证。

依赖为 `pymilvus>=2.6,<2.7`，具体版本由 uv.lock 锁定，服务端本机为 2.6.13。

## 集合与配置

默认项目混合集合为 `network_aiops_chunks_hybrid`，描述为 `network-aiops-rag-hybrid-v2`。旧 `network_aiops_chunks` 稠密集合保留，不直接复用其不含 BM25 函数的 schema；不删除或修改其他应用的集合。已有同名集合必须通过字段/维度/分析器/BM25 函数/索引参数校验。默认维度 1024 对应实测 BGE-M3 输出，不对 BGE 请求强制传 dimensions。

| 字段 | 用途 |
|---|---|
| id | 索引命名空间 + chunk_id 的 SHA-256 主键 |
| chunk_id / doc_id | 原有证据标识和文档撤销标识 |
| vector | FLOAT_VECTOR，COSINE / AUTOINDEX |
| search_text | 子块正文 + 标题路径，VARCHAR(65535 字节)，enable_analyzer=True |
| bm25_vector | SPARSE_FLOAT_VECTOR，由 Milvus BM25 函数自动生成，不由应用上传 |
| chunk | 原生子 Document JSON：id、page_content、metadata、type；不含父块正文 |
| access_scope | ARRAY<VARCHAR>，数据库搜索前 ACL 过滤 |
| index_key | 模型、服务端点、维度和处理流水线版本的指纹 |
| fingerprint / content_hash | 完整元数据指纹与正文指纹，分别控制更新和向量复用 |

配置项见 `.env.example`。Milvus 认证关闭时 token 为空；启用后配置私有 `MILVUS_TOKEN`。API 在主机上使用 `http://127.0.0.1:19530`；API 在容器内时需使用可达的 Docker 网络地址。

BM25 采用 `FunctionType.BM25`，输入 search_text、输出 bm25_vector；稀疏索引使用 SPARSE_INVERTED_INDEX / BM25 / DAAT_MAXSCORE，k1=1.2、b=0.75（可配置，变更时新建集合）。自定义分析器为 Jieba + lowercase + removepunct，保留 BGP/OSPF 等英文词。BM25 语料统计由集合维护，ACL/命名空间过滤控制候选范围，并不为每个用户重新计算 IDF。应用不再依赖 rank_bm25。

API Key、Milvus Token 不写入集合、不打印、不提交到 Git。PyMilvus 会隐式调用 load_dotenv；项目配置入口禁用这种进程环境注入，统一由 Pydantic Settings 显式读取 .env，保留测试的 `_env_file=None` 隔离语义。

## 增量与恢复

1. 首次启动为当前文档生成向量并持久化。随后正常启动读取原文以核对来源和指纹，但不重新计算未变化的向量。
2. 管理员上传只处理新文档；已有向量不下载到应用堆中。仅元数据变化时按需读取该 Chunk 的旧向量进行 upsert。
3. 完整重索引从内置资料与 PostgreSQL `ready` 清单构建目标集合，对当前索引命名空间进行缺失补齐和过期记录清理，不先清空集合。
4. 初始 WorkflowService 仅同步内置资料，不清理已有上传；KnowledgeManager 拿到完整清单后再对账，避免启动时误删上传文档。
5. 文档删除清理该文档的所有索引命名空间。切换模型不会混合检索其他命名空间，旧模型空间不自动回收。
6. 每次查询使用两个 AnnSearchRequest（COSINE 与 BM25）和同一授权过滤表达式，由 Milvus RRFRanker 融合。只返回候选子 Document，不再在每个请求中下载全量授权语料。Python 保留的是候选词项重排，不是 BM25，也不是神经 Reranker。

## 边界

- BM25 和向量索引均在 Milvus；源文件解析、启动时元数据加载及上传任务仍不是异步队列。应用保留的词项过滤仍可能排除无词项重合的纯语义候选。
- 管理写操作按单实例锁串行；多管理写实例应另加分布式协调，避免完整对账与并发上传互相覆盖。
- PostgreSQL、源文件和 Milvus 没有跨系统事务。上传失败会尽力清理本次新文档索引，后续完整对账也会清理失败上传的孤立记录；不宣称原子切换或分布式事务。
- 使用 Milvus 不代替 PostgreSQL 文档清单持久化；如使用 memory 会话模式，上传清单仍在重启后丢失。
- 备份需覆盖原文件、PostgreSQL、Milvus 持久卷以及 MySQL `rag_parent_documents`。多检索实例使用同一父块 MySQL 表，不再共享本地父文档目录。此接入不会启用或修改 Milvus 密码。

## 验证命令

```powershell
uv run python -m pytest -q
uv run python -m pytest -q tests/test_milvus_integration.py --run-milvus
uv run python -m scripts.ingest_demo_docs
uv run python -m scripts.migrate_milvus_bm25 --switch
```

集成测试只操作 `aiops_test_<UUID>` 临时集合并在结束后清理，使用 256 维 mock Embedding 隔离外部 API 花费；生产配置使用硅基流动 BGE-M3 的 1024 维真实向量。可通过 `MILVUS_TEST_URI` / `MILVUS_TEST_TOKEN` 为测试单独指定连接。

迁移默认读取有效的真实 MinerU 缓存，保存原有已索引文档的来源与权限，用当前切分器生成父子 Document。在新集合中完成实际嵌入、原生 BM25、混合召回、MySQL 父块和 ACL 验证后才切换 `.env`；旧集合保留。执行迁移时应停止并发管理写入，正在运行的应用需要重启读取新配置。恢复旧读路径需要旧版本代码与旧配置，单独把新版指回旧 schema 会触发校验错误。

参考：[Milvus 原生 BM25](https://milvus.io/docs/full-text-search.md)、[Jieba 分析器](https://milvus.io/docs/jieba-tokenizer.md)、[ARRAY 过滤](https://milvus.io/docs/v2.6.x/array-operators.md)。
