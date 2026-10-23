# MinerU 切换与后续 Chunker 设计

更新（2026-10-18）：当前已直接输出两组原生 LangChain Document，父 1200/200 token、子 300/50 token，仅子块向量化，父块独立保存并回取供 LLM 阅读，见 [当前父子分块实现](langchain-chunking.md)。本文下面的自定义 Chunk、字符偏移、700/100 兼容桥接与旧版本适配均为历史设计，不是当前实现；表格、公式、代码等专用策略仍是后续方案。

## 本轮边界

2026-10-16：先完成远程 MinerU 4.0.12 解析切换及真实结果验证，再记录本文的下一阶段方案。

已落地：

- 业务解析入口只有 MinerU V1 API，不再使用 pypdf 或原来的 Markdown 标题正则解析器；pypdf 仅在开发依赖中用于构造/检查测试 PDF。
- PDF、图片直接上传，使用配置的 Standard/OCR 模式。Office/HTML 走 Flash。实测该服务不直接接收 MD/TXT，因此这两种源文件先转换为 HTML，再由 MinerU Flash 产生解析结果；这不是服务失败后的本地解析回退。
- 每份源文档保存 response.json、middle_json.json、structured_content.json、document.md 和带校验和的 manifest.json。目录为 data/parsed/<源路径指纹>/<内容与解析配置指纹>/，不提交 Git、不打包进 Docker 镜像。
- 识别 `docvortex.middle` / `2.0` 和生产者版本；失败、partial、未知协议或超时不会变成可索引结果。
- HTTP 202 根据同源的 status_url/result_url 有界轮询，Bearer 不发送到其他站点；服务端返回的图片 URL 不自动抓取。
- 相同源文件与解析配置复用完整本地产物，服务任务 ID 不作为永久结果索引。pending.json 仅供排错/人工续查，不自动恢复已过期的远程任务。
- 解析、规范化和切块模块已拆开。当前 700 字符/100 重叠的分块仍是明确的兼容桥接，不是本文提出的结构化 Chunker。

## 根据真实返回确定的数据契约

服务返回三份互补产物：

| 产物 | 用途 |
|---|---|
| Markdown | 人工核对、预览；不作为唯一来源定位依据 |
| Middle JSON | 权威结构与来源定位：schema、版本、page_idx、blocks、bbox、标题级别、表格/公式等原始结构 |
| Structured Content | 面向消费方的简化表示；没有 Middle JSON 的 schema 身份，不假装二者可以互换 |

本机实测：两页扫描 PDF 返回 9 个 text 块及真实 bbox；HTML 输入返回 doc_title、paragraph_title、text、table 等类型。扫描件上的视觉表格未必被识别为 table，应以实际块类型为准，不凭预期编造结构。

规范化模型位于 app/rag/document_types.py：

```text
ParsedDocument
  source / source_sha256 / source_suffix / submitted_suffix
  parser_version / markdown / middle_json / structured_content
  pages[] / artifacts_dir

ParsedPage
  page_idx / page_number / blocks[]

ParsedBlock
  block_id / block_type / text / level
  page_idx / page_number / bbox / raw
```

`page_idx` 保留 MinerU 的零起始索引。仅对来源为 PDF 且服务明确标为 physical 的页生成 `page_number=page_idx+1`；HTML、MD、TXT、Office 的 logical 页保持 `page_number=None`，不伪造纸面页码。bbox 按原值保留，坐标语义需结合 extensions 的页面布局解释。

原始块即使暂时没有可用 text，也保存在 raw/Middle JSON 中。正文片段在进入向量索引前脱敏；本地产物与源文件一样属于受保护资料，不经公开静态文件路由暴露。

## 当前保持运行的桥接

```text
MinerU API
  -> ParsedDocument
  -> 按真实页、标题分段
  -> 700 字符窗口 / 100 字符重叠
  -> 现有 Chunk -> BGE-M3 -> Milvus
```

该桥接保留来源、页码、章节、解析器版本、ACL 和原有 RAG 契约，但不承诺长表格、代码或公式不被字符窗口拆开。结构化块、bbox 等完整内容先落盘，不把它们当普通字符串丢弃。

## 下一阶段提议：基于结构块的 Chunker（尚未启用）

### 1. 单独定义 Chunker 接口

输入为 ParsedDocument 和服务端 DocumentMetadata，不让 Chunker 直接访问 HTTP 或读取原 PDF。输出扩展的 KnowledgeChunkV2，解析和分块可独立重跑、独立评估。

### 2. 按块类型执行策略

| 块类型 | 拟定处理方式 |
|---|---|
| doc_title / paragraph_title / chapter_title | 更新 section_path；作为子块的上下文前缀，而不是只生成孤立标题向量 |
| text / list | 同章节内按阅读顺序聚合；超长段落再按句子边界拆分，避免机械截断配置项和参数名 |
| table | 标题、表头、单位和数据行绑定；超长表按行组切分，每组保留表头和单位，不切断 HTML 标签或单元格 |
| equation | 完整公式与相邻解释绑定；保留 LaTeX/原始结构，不按字符截断公式 |
| code | 保留代码围栏、缩进、符号；超长代码按函数或明确段落拆分并标注续块 |
| image / chart | 先使用真实 caption/关联文本；没有文本则保留资源引用和缺口，不编造图像描述。图片二进制下载与持久化另作资产流程 |
| 未识别类型 | 保留 raw、记录诊断，依据明确的可提取文本处理；不静默丢弃，也不盲目把整份 JSON 塞进 Embedding |

目标预算应按 BGE-M3 适配的 tokenizer/输入限制评估，不把字符数等同于 token 数。先建立可配置预算，再用网络文档的检索评测确定参数。

### 3. 扩展 Chunk 与证据定位

拟定新增：

```text
display_text          展示/引用原文
embedding_text        带文档标题与章节路径的检索文本
section_path          完整标题路径
semantic_type         text/table/code/equation 等
source_block_ids[]    对应 ParsedBlock
locators[]            page_idx、真实页码、bbox、块内字符范围
parent_id             可选父章节，用于小块召回后补齐上下文
parser_artifact_id    解析缓存指纹
chunker_version       分块策略版本
```

租户、ACL、文档版本由服务器元数据提供，绝不从远程文档正文推导权限。Milvus 的 Chunk JSON 解码、Citation 输出和前端证据显示需要一并升级，并提供旧版本适配；不能直接给现有 dataclass 写入未知字段。

### 4. 迁移与验收顺序

1. 固定真实 MinerU 产物作为回归样本，不重复占用云端 GPU。
2. 实现文本/标题策略，再实现表格、公式、代码、图片引用策略。
3. 使用临时集合或新索引命名空间比较现有窗口与新策略；不直接覆盖正在使用的索引。
4. 评估 Recall@K、引用页码/块定位、表格单位和表头保留、长段完整性、ACL、重复内容与上下文长度。
5. 质量验收后切换新 Chunker，再处理旧索引空间回收。

## 验证入口

```powershell
uv run python -m scripts.parse_document "D:\Network AIOps\outputs\mineru-smoke-scan.pdf"
uv run python -m scripts.ingest_demo_docs
uv run python -m pytest -q --run-milvus --run-mineru
```

普通测试使用 tests/mineru_fixtures.py 的显式假远程响应；MinerU 客户端单测独立使用 MockTransport 检查请求、轮询、缓存、错误和凭据边界。带 --run-mineru 的测试才提交合成文档到真实服务；组合测试使用真实 MinerU、BGE-M3、临时 Milvus 集合和内存会话，不依赖 PostgreSQL 在线。

服务当前采用 HTTP，传输没有 TLS 加密；正式长期使用应部署 HTTPS 和来源访问限制。本文不会调整远端端口、密码或防火墙。

参考：[MinerU V1 API](https://opendatalab.github.io/MinerU/usage/http_api/)、[Middle JSON 与 Structured Content 契约](https://opendatalab.github.io/MinerU/reference/output_files/)。
