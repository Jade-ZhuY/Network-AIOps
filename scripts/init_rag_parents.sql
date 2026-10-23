-- Generated from app.rag.parent_store.PARENTS; explicit administrator migration only.
CREATE TABLE rag_parent_documents (
	index_key VARCHAR(64) NOT NULL,
	parent_id VARCHAR(512) NOT NULL,
	doc_id VARCHAR(512) NOT NULL,
	page_content LONGTEXT NOT NULL,
	metadata JSON NOT NULL,
	access_scope JSON NOT NULL,
	created_at DATETIME NOT NULL,
	updated_at DATETIME NOT NULL,
	PRIMARY KEY (index_key, parent_id)
)ENGINE=InnoDB CHARSET=utf8mb4 COMMENT='network-aiops-rag-parents-v1' COLLATE utf8mb4_bin;
CREATE INDEX ix_rag_parent_documents_doc_id ON rag_parent_documents (doc_id);
