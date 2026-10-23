"""MySQL-only parent Document persistence. No in-memory/file fallback or runtime DDL."""

import json
from datetime import UTC, datetime

from langchain_core.documents import Document
from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Index,
    MetaData,
    String,
    Table,
    Text,
    bindparam,
    create_engine,
    delete,
    func,
    select,
    update,
)
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.engine import make_url

PARENT_TABLE_NAME = "rag_parent_documents"
PARENT_TABLE_COMMENT = "network-aiops-rag-parents-v1"
PARENT_SCHEMA = MetaData()
PARENTS = Table(
    PARENT_TABLE_NAME,
    PARENT_SCHEMA,
    Column("index_key", String(64), primary_key=True),
    Column("parent_id", String(512), primary_key=True),
    Column("doc_id", String(512), nullable=False),
    Column("page_content", Text().with_variant(LONGTEXT(), "mysql"), nullable=False),
    Column("metadata", JSON, nullable=False),
    Column("access_scope", JSON, nullable=False),
    Column("created_at", DateTime, nullable=False),
    Column("updated_at", DateTime, nullable=False),
    Index("ix_rag_parent_documents_doc_id", "doc_id"),
    comment=PARENT_TABLE_COMMENT,
    mysql_engine="InnoDB",
    mysql_charset="utf8mb4",
    mysql_collate="utf8mb4_bin",
)


class ParentDocumentStore:
    def __init__(self, settings, namespace: str, *, engine=None):
        if not isinstance(namespace, str) or not namespace or len(namespace) > 64:
            raise ValueError("Parent document namespace must contain 1 to 64 characters")
        self.namespace = namespace
        self._owns_engine = engine is None
        if engine is None:
            uri = settings.rag_parent_mysql_uri.get_secret_value()
            if not uri:
                raise ValueError(
                    "Set RAG_PARENT_MYSQL_URI; parent storage requires MySQL (no memory/file fallback)"
                )
            url = make_url(uri)
            if url.drivername != "mysql+pymysql" or not url.database:
                raise ValueError("RAG_PARENT_MYSQL_URI must select a database using mysql+pymysql")
            if settings.mysql_readonly_uri.get_secret_value():
                readonly = make_url(settings.mysql_readonly_uri.get_secret_value())
                if (url.host, url.port, url.username) == (
                    readonly.host,
                    readonly.port,
                    readonly.username,
                ):
                    raise ValueError("Use a separate MySQL writer account for parent Documents")
            engine = create_engine(
                url,
                pool_pre_ping=True,
                hide_parameters=True,
                connect_args={"connect_timeout": 5, "read_timeout": 10, "write_timeout": 10},
            )
        self.engine = engine

    def put(self, parents):
        rows, ids = [], set()
        now = datetime.now(UTC).replace(tzinfo=None)
        for parent in parents:
            if (
                not isinstance(parent, Document)
                or not parent.id
                or parent.metadata.get("chunk_type") != "parent"
                or parent.id in ids
                or not parent.metadata.get("doc_id")
            ):
                raise ValueError("Parent store accepts only uniquely identified parent Documents")
            json.dumps(parent.metadata, allow_nan=False)
            metadata = parent.model_dump(mode="json")["metadata"]
            scopes = metadata.get("access_scope")
            if not isinstance(scopes, list) or not all(isinstance(item, str) for item in scopes):
                raise ValueError("Parent access_scope must be a list of strings")
            json.dumps(metadata, allow_nan=False)
            ids.add(parent.id)
            rows.append(
                {
                    "index_key": self.namespace,
                    "parent_id": parent.id,
                    "doc_id": metadata["doc_id"],
                    "page_content": parent.page_content,
                    "metadata": metadata,
                    "access_scope": scopes,
                    "created_at": now,
                    "updated_at": now,
                }
            )
        if not rows:
            return
        with self.engine.begin() as connection:
            if connection.dialect.name == "mysql":
                statement = mysql_insert(PARENTS)
                statement = statement.on_duplicate_key_update(
                    **{
                        key: statement.inserted[key]
                        for key in (
                            "doc_id",
                            "page_content",
                            "metadata",
                            "access_scope",
                            "updated_at",
                        )
                    }
                )
                for start in range(0, len(rows), 128):
                    connection.execute(statement, rows[start : start + 128])
            else:
                # Explicitly injected SQL test engines only; runtime URI is MySQL-only.
                for row in rows:
                    predicate = (PARENTS.c.index_key == self.namespace) & (
                        PARENTS.c.parent_id == row["parent_id"]
                    )
                    exists = connection.execute(
                        select(PARENTS.c.parent_id).where(predicate)
                    ).first()
                    if exists:
                        connection.execute(
                            update(PARENTS)
                            .where(predicate)
                            .values(
                                **{key: value for key, value in row.items() if key != "created_at"}
                            )
                        )
                    else:
                        connection.execute(PARENTS.insert().values(**row))

    def get_many(self, parent_ids, groups=None):
        ids = sorted(set(parent_ids))
        if not ids or groups is not None and not groups:
            return {}
        result = {}
        with self.engine.connect() as connection:
            for start in range(0, len(ids), 256):
                statement = select(PARENTS).where(
                    PARENTS.c.index_key == self.namespace,
                    PARENTS.c.parent_id.in_(ids[start : start + 256]),
                )
                parameters = {}
                if groups is not None:
                    statement = statement.where(
                        func.json_overlaps(
                            PARENTS.c.access_scope, bindparam("authorized_groups", type_=JSON)
                        )
                    )
                    parameters["authorized_groups"] = sorted(groups)
                for row in connection.execute(statement, parameters).mappings():
                    parent = Document(
                        id=row["parent_id"],
                        page_content=row["page_content"],
                        metadata=row["metadata"],
                    )
                    if (
                        parent.metadata.get("chunk_type") != "parent"
                        or parent.metadata.get("doc_id") != row["doc_id"]
                        or parent.metadata.get("access_scope") != row["access_scope"]
                    ):
                        raise ValueError("Inconsistent parent document record")
                    if groups is None or set(row["access_scope"]).intersection(groups):
                        result[parent.id] = parent
        return result

    def prune(self, active_ids, doc_ids=None):
        statement = select(PARENTS.c.parent_id).where(PARENTS.c.index_key == self.namespace)
        if doc_ids is not None:
            if not doc_ids:
                return
            statement = statement.where(PARENTS.c.doc_id.in_(sorted(doc_ids)))
        active = set(active_ids)
        with self.engine.begin() as connection:
            stale = [
                parent_id
                for parent_id in connection.execute(statement).scalars()
                if parent_id not in active
            ]
            for start in range(0, len(stale), 256):
                connection.execute(
                    delete(PARENTS).where(
                        PARENTS.c.index_key == self.namespace,
                        PARENTS.c.parent_id.in_(stale[start : start + 256]),
                    )
                )

    def delete_document(self, doc_id):
        # IDs are server-assigned and checked by KnowledgeManager before deletion.
        with self.engine.begin() as connection:
            connection.execute(delete(PARENTS).where(PARENTS.c.doc_id == doc_id))

    def count(self):
        with self.engine.connect() as connection:
            return connection.execute(
                select(func.count())
                .select_from(PARENTS)
                .where(PARENTS.c.index_key == self.namespace)
            ).scalar_one()

    def healthcheck(self):
        with self.engine.connect() as connection:
            connection.execute(select(PARENTS.c.parent_id).limit(1))

    def close(self):
        if self._owns_engine:
            self.engine.dispose()
