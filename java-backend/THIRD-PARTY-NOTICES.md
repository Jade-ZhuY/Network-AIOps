# Third-party code and design references

## General RAG System

- Repository: https://github.com/upupmake/general-rag-system
- Reviewed revision: `70423da5b516511739739fd433fc77a2e7d347af`
- License: Apache License 2.0, reproduced in `licenses/general-rag-system-LICENSE.txt`.
- Adapted source: `rag-server/src/main/java/com/rag/ragserver/exception/BusinessException.java` → `aiops-common-core/src/main/java/com/networkaiops/backend/common/error/BusinessException.java`.
- Changes: package, explicit Java getters instead of Lombok, stable error identifiers and constructor extension. The modified source carries its own notice.
- The upstream controller/service organization, ownership checks, global error handling, and Java-to-Python HTTP boundary informed the implementation. Other upstream source files were inspected but not copied wholesale.
- This project deliberately does not import the reference project's old Spring Boot 2.7 runtime, Redis authentication, RabbitMQ, Milvus Java client, or its different API response envelope. The current React/FastAPI contract is preserved.

## Runtime dependencies introduced 2026-10-25 (MySQL + MyBatis switch)

- MyBatis 3.5.19, mybatis-spring 3.0.5, mybatis-spring-boot-starter 3.0.5 — Apache License 2.0.
- MySQL Connector/J (com.mysql:mysql-connector-j, version managed by Spring Boot) — GPLv2 with the FOSS Exception, standard for client-side JDBC drivers; not adapted or modified.

All remaining application-specific Java code was implemented for Network AIOps. Spring and other runtime dependency licenses remain with their respective distributions.
