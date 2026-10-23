package com.networkaiops.backend.common;

import jakarta.validation.ConstraintViolationException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataAccessException;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.HandlerMethodValidationException;
import org.springframework.web.multipart.MaxUploadSizeExceededException;
import org.springframework.web.servlet.resource.NoResourceFoundException;

@RestControllerAdvice
public class GlobalExceptionHandler {
  private static final Logger LOG = LoggerFactory.getLogger(GlobalExceptionHandler.class);

  @ExceptionHandler(BusinessException.class)
  ResponseEntity<ErrorResponse> business(BusinessException exception) {
    return ResponseEntity.status(exception.getCode())
        .body(ErrorResponse.of(exception.getMessage(), exception.getReason()));
  }

  @ExceptionHandler({
    MethodArgumentNotValidException.class,
    ConstraintViolationException.class,
    HttpMessageNotReadableException.class,
    HandlerMethodValidationException.class,
    org.springframework.web.bind.ServletRequestBindingException.class,
    org.springframework.web.method.annotation.MethodArgumentTypeMismatchException.class
  })
  ResponseEntity<ErrorResponse> validation(Exception exception) {
    String message = "输入格式不正确，请核对必填内容、长度、版本和枚举值。";
    if (exception instanceof MethodArgumentNotValidException invalid
        && invalid.getFieldError() != null) {
      message = invalid.getFieldError().getDefaultMessage();
    }
    return ResponseEntity.unprocessableEntity()
        .body(ErrorResponse.of(message, "validation_failed"));
  }

  @ExceptionHandler(org.springframework.web.HttpRequestMethodNotSupportedException.class)
  ResponseEntity<ErrorResponse> methodNotAllowed() {
    return ResponseEntity.status(405)
        .body(ErrorResponse.of("该接口不支持此 HTTP 方法。", "method_not_allowed"));
  }

  @ExceptionHandler(MaxUploadSizeExceededException.class)
  ResponseEntity<ErrorResponse> largeUpload() {
    return ResponseEntity.status(413)
        .body(ErrorResponse.of("上传文件超过 10 MB 限制。", "upload_too_large"));
  }

  @ExceptionHandler(NoResourceFoundException.class)
  ResponseEntity<ErrorResponse> missing() {
    return ResponseEntity.status(404).body(ErrorResponse.of("接口或资源不存在。", "not_found"));
  }

  @ExceptionHandler(Exception.class)
  ResponseEntity<ErrorResponse> unexpected(Exception exception) {
    // Never log request bodies, raw exception messages, SQL parameters or credentials.
    LOG.error(
        "Request failed requestId={} type={}",
        RequestIdFilter.currentId(),
        exception.getClass().getSimpleName());
    boolean storage = exception instanceof DataAccessException;
    return ResponseEntity.status(storage ? 503 : 500)
        .body(
            ErrorResponse.of(
                storage ? "业务存储暂不可用，请稍后重试。" : "服务处理异常，请凭请求 ID 排查。",
                storage ? "storage_unavailable" : "internal_error"));
  }
}
