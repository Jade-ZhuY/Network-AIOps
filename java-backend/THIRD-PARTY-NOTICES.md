# Third-party code and design references

## General RAG System

- Repository: https://github.com/upupmake/general-rag-system
- Reviewed revision: `70423da5b516511739739fd433fc77a2e7d347af`
- License: Apache License 2.0, reproduced in `licenses/general-rag-system-LICENSE.txt`.
- Adapted source: `rag-server/src/main/java/com/rag/ragserver/exception/BusinessException.java` → `src/main/java/com/networkaiops/backend/common/BusinessException.java`.
- Changes: package, explicit Java getters instead of Lombok, stable error identifiers and constructor extension. The modified source carries its own notice.
- The upstream controller/service organization, ownership checks, global error handling, and Java-to-Python HTTP boundary informed the implementation. Other upstream source files were inspected but not copied wholesale.
- This project deliberately does not import the reference project's old Spring Boot 2.7 runtime, Redis authentication, RabbitMQ, Milvus Java client, or its different API response envelope. The current React/FastAPI contract is preserved.

All remaining application-specific Java code was implemented for Network AIOps. Spring and other runtime dependency licenses remain with their respective distributions.
