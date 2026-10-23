# LangChain 原生 Document 与 Small-to-Big Retrieval

2026-10-18：移除 `Chunk`、`ParentChunk` 和列表兼容的 `ChunkingResult`，不再转换回旧检索对象。

## 数据流程

```text
MinerU middle_json
  -> ParsedDocument / ParsedPage / ParsedBlock（解析输入适配）
  -> MarkdownHeaderTextSplitter（H1–H6 标题语义段）
  -> RecursiveCharacterTextSplitter（父块）
  -> RecursiveCharacterTextSplitter（父块内的子块）
  -> {"parents": list[Document], "children": list[Document]}

children.page_content -> Embedding -> 子块向量索引
parents              -> MySQL rag_parent_documents（非向量）

问题 -> Milvus 子块 COSINE + 原生 BM25 -> Milvus RRF / 应用候选词项重排
     -> 按 parent_id 去重 -> 取回授权父 Document
     -> context_documents -> LLM 的 knowledge_context
```

两个列表中的每一个元素都是 `langchain_core.documents.Document`，不是自定义正文包装类。`ChunkedDocuments` 仅为普通字典的 TypedDict 类型注解，没有运行时包装。

## 独立使用，不需要向量库

```python
from app.config import Settings
from app.rag.chunking import chunk_parsed_document

result = chunk_parsed_document(parsed_document, metadata, settings=Settings())
parents = result["parents"]
children = result["children"]

print(children[0].id)
print(children[0].page_content)
print(children[0].metadata["parent_id"])
parent_by_id = {parent.id: parent for parent in parents}
parent = parent_by_id[children[0].metadata["parent_id"]]
print(parent.page_content)
```

这个调用只切分内存中已有的解析对象，不调用 MinerU、Embedding、Milvus 或 PostgreSQL。只有显式调用后续索引器时才会向量化子块。

## Document 内容

- `id`：稳定的父块/子块 ID。
- `page_content`：该块的正文。
- `metadata`：文档 ID、标题、完整标题路径、来源、页码、版本、更新时间、ACL、解析器/切分器版本等。
- `metadata.chunk_type`：`parent` 或 `child`。
- 子块的 `metadata.parent_id`：关联父 Document.id。
- `parent_index` / `child_index`：语义段内父块序号、父块内子块序号。
- `section_block_ids`：当前页面语义段涉及的 MinerU 块；它是章节级来源集合，不声称精确命中某个字符范围。

不将父块正文复制进子块 metadata，也不在子块内嵌父文档。Token 长度与字符偏移不是同一单位，本版不输出可能歧义的字符偏移；重复文本也不靠字符串首次匹配来伪造定位。bbox 和原始块仍保留在解析产物中。

## 切分边界和参数

```dotenv
RAG_PARENT_CHUNK_SIZE=1200
RAG_PARENT_CHUNK_OVERLAP=200
RAG_CHILD_CHUNK_SIZE=300
RAG_CHILD_CHUNK_OVERLAP=50
RAG_TOKEN_ENCODING=cl100k_base
```

长度与重叠预算的单位均为 **token**，通过 LangChain `RecursiveCharacterTextSplitter.from_tiktoken_encoder()` 实现。`cl100k_base` 是本项目的切分计量编码器，**不等同于 BGE-M3 的实际 tokenizer**；不把这个计数当作硅基流动接口的实际输入 token 统计。

优先按段落、换行、中文标点、英文句子/词边界切分，最后才退到字符边界。重叠是结合边界的目标预算，不保证每对块精确重叠指定 token 数。短章节可以只有一个父块和一个子块，两者正文相同。

真实标题先映射为 Markdown 标题，正文先映射为内部引用，Header Splitter 分组后恢复正文。这样正文中的 `# 注释` 不会变成假标题，正文缩进不会被 Header Splitter 改写。内部标记不进入最终 Document。

父块不跨当前标题语义段或页面；下一页继承标题上下文。物理 PDF 使用真实页码，逻辑页面保持 `page=None`。超过父块预算的长章节会有多个父块；“完整上下文”指命中父块的完整正文，不是无上限地发送整篇文档。超长表格、公式、代码的原子性保护仍未实现。

## 父块保存与检索

- 不再保留 `retriever.parents` 内存父块缓存，也不再将父块写入本地 JSON。
- 即使子向量使用内存测试后端，父 Document 也通过 MySQL 表保存与读取；测试中的 SQL 替身是显式注入的，不是运行时降级。
- Milvus 模式：只将子块正文送入 Embedding；Milvus 每行的 JSON 字段保存原生子 Document 的序列化数据。
- Milvus 自己对子块正文/标题路径进行 Jieba 分词、BM25 稀疏索引和打分；应用不再构建 Python BM25。仅显式内存向量测试模式保留简单词项重合测试，父块存储仍始终是 MySQL。
- 父 Document 保存于 MySQL `rag_parent_documents`：`page_content` 使用 LONGTEXT，`metadata/access_scope` 使用 JSON，`(index_key,parent_id)` 为联合主键，`doc_id` 有索引，不包含向量。
- 连接使用独立 `RAG_PARENT_MYSQL_URI`，运行账号仅授予该表 SELECT/INSERT/UPDATE/DELETE；原有 SQL Agent 的 `MYSQL_READONLY_URI` 保持不变。缺少配置或数据库出错直接报错，不回退到文件或内存。
- 每次检索按命中子块的 parent_id 批量查 MySQL，包含当前索引命名空间与 JSON 权限过滤；不会启动时加载全量父块进长期内存。
- 父存储与 Milvus 没有跨库事务，先提交父文档事务，再写子块引用；失败时可能留下可清理的孤立父文档。只有父块库内部的批量写入具备事务性。
- 父/子 ACL 均从服务端文档元数据继承。子块召回前过滤权限，回取父块时再次过滤并校验父子关系；缺失/无权限的父块不会作为上下文，也不会偷偷退回旧单块模式。
- 检索结果 `context_documents` 只包含去重后的父 Document。Report Agent 的 `knowledge_context` 直接接收它们，资料仍被视为不可信数据而非指令。
- `Citation.text/chunk_id` 仍明确标识命中的子块；API 的 `parent_text` 是取回父文档后生成的显示字段，不保存在子块索引里。
- 切分器版本、计量编码器和所有尺寸参数进入索引命名空间，原有旧格式不会被当作新 Document 解码；不自动启动、重建或清空向量库。

## 验证

```powershell
uv --directory "D:\Network AIOps" run python -m pytest -q tests/test_chunking.py tests/test_milvus_store.py
uv --directory "D:\Network AIOps" run python -m pytest -q tests/test_parent_mysql_integration.py --run-parent-mysql
uv --directory "D:\Network AIOps" run python -m scripts.inspect_chunks "D:\Network AIOps\outputs\mineru-smoke-scan.pdf" --output "D:\Network AIOps\outputs\langchain-documents.json"
```

默认测试显式使用临时 SQL 测试库与 Milvus 替身；`--run-parent-mysql` 才连接真实父块 MySQL 表。inspect_chunks 只解析/读缓存并导出父子 Document，不连接父块库或建立向量索引。

## 显式建表与账号

管理员在本机忽略提交的 `.env` 或当前进程设置 `MYSQL_ADMIN_PASSWORD`，必要时设置 `MYSQL_ADMIN_USER/HOST/PORT`，然后运行：

```powershell
uv run python -m scripts.migrate_rag_parents --create-account
```

脚本仅新建父块专用表和随机独立账号，授权限定为该表的 CRUD，将生成的 `RAG_PARENT_MYSQL_URI` 保存到忽略提交的 `.env`，不打印密码，不修改业务只读账号，不连接 Milvus。管理员密码不会由脚本另行保存。已有同名非本项目表会报错，不覆盖。运行账号不需要建表权限，应用启动也不隐式执行 DDL。已有写账号时不带 `--create-account` 执行幂等表结构检查。

参考：[LangChain RecursiveCharacterTextSplitter](https://reference.langchain.com/python/langchain-text-splitters/character/RecursiveCharacterTextSplitter)、[按 token 计量的构造方法](https://reference.langchain.com/python/langchain-text-splitters/base/TextSplitter/from_tiktoken_encoder)。
