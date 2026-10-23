package com.networkaiops.backend.common;

import java.time.Instant;

public record ErrorResponse(String detail, String code, String requestId, Instant timestamp) {
  public static ErrorResponse of(String detail, String code) {
    return new ErrorResponse(detail, code, RequestIdFilter.currentId(), Instant.now());
  }
}
