/*
 * SPDX-License-Identifier: Apache-2.0
 * Adapted from upupmake/general-rag-system, commit 70423da5b516511739739fd433fc77a2e7d347af,
 * rag-server/src/main/java/com/rag/ragserver/exception/BusinessException.java.
 * Modified 2026-10-22: package, explicit getters, stable error identifier, no Lombok.
 * See THIRD-PARTY-NOTICES.md and licenses/general-rag-system-LICENSE.txt.
 */
package com.networkaiops.backend.common;

public class BusinessException extends RuntimeException {
  private final Integer code;
  private final String reason;

  public BusinessException(String message) {
    this(400, "invalid_request", message);
  }

  public BusinessException(Integer code, String message) {
    this(code, "business_error", message);
  }

  public BusinessException(Integer code, String reason, String message) {
    super(message);
    this.code = code;
    this.reason = reason;
  }

  public Integer getCode() {
    return code;
  }

  public String getReason() {
    return reason;
  }
}
