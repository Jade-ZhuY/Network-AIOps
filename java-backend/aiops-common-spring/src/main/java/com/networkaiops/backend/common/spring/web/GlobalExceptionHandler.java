package com.networkaiops.backend.common.spring.web;

import com.networkaiops.backend.common.context.RequestContext;
import com.networkaiops.backend.common.exception.BusinessException;
import com.networkaiops.backend.common.web.Result;
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
  ResponseEntity<Result> business(BusinessException exception) {
    return ResponseEntity.status(exception.getCode()).body(Result.error(exception.getMessage()));
  }

  @ExceptionHandler({
    MethodArgumentNotValidException.class,
    ConstraintViolationException.class,
    HttpMessageNotReadableException.class,
    HandlerMethodValidationException.class,
    org.springframework.web.bind.ServletRequestBindingException.class,
    org.springframework.web.method.annotation.MethodArgumentTypeMismatchException.class
  })
  ResponseEntity<Result> validation(Exception exception) {
    String message = "输入格式不正确，请核对必填内容、长度、版本和枚举值。";
    if (exception instanceof MethodArgumentNotValidException invalid
        && invalid.getFieldError() != null) {
      message = invalid.getFieldError().getDefaultMessage();
    }
    return ResponseEntity.unprocessableEntity().body(Result.error(message));
  }

  @ExceptionHandler(org.springframework.web.HttpRequestMethodNotSupportedException.class)
  ResponseEntity<Result> methodNotAllowed() {
    return ResponseEntity.status(405).body(Result.error("该接口不支持此 HTTP 方法。"));
  }

  @ExceptionHandler(MaxUploadSizeExceededException.class)
  ResponseEntity<Result> largeUpload() {
    return ResponseEntity.status(413).body(Result.error("上传文件超过 10 MB 限制。"));
  }

  @ExceptionHandler(NoResourceFoundException.class)
  ResponseEntity<Result> missing() {
    return ResponseEntity.status(404).body(Result.error("接口或资源不存在。"));
  }

  @ExceptionHandler(Exception.class)
  ResponseEntity<Result> unexpected(Exception exception) {
    // Never log request bodies, raw exception messages, SQL parameters or credentials.
    LOG.error(
        "Request failed requestId={} type={}",
        RequestContext.currentId(),
        exception.getClass().getSimpleName());
    boolean storage = exception instanceof DataAccessException;
    return ResponseEntity.status(storage ? 503 : 500)
        .body(Result.error(storage ? "业务存储暂不可用，请稍后重试。" : "服务处理异常，请凭请求 ID 排查。"));
  }
}
