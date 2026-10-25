package com.networkaiops.backend.common.exception;

import com.networkaiops.backend.common.context.RequestContext;
import java.time.Instant;

public record ErrorResponse(String detail, String code, String requestId, Instant timestamp) {
  public static ErrorResponse of(String detail, String code) {
    return new ErrorResponse(detail, code, RequestContext.currentId(), Instant.now());
  }
}
