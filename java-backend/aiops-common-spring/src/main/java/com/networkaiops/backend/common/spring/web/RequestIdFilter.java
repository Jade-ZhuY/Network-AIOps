package com.networkaiops.backend.common.spring.web;

import com.networkaiops.backend.common.context.RequestContext;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.UUID;
import org.slf4j.MDC;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class RequestIdFilter extends OncePerRequestFilter {
  public static String currentId() {
    return RequestContext.currentId();
  }

  @Override
  protected void doFilterInternal(
      HttpServletRequest request, HttpServletResponse response, FilterChain chain)
      throws ServletException, IOException {
    String id = "java_" + UUID.randomUUID().toString().replace("-", "");
    String previous = MDC.get("requestId");
    try (var ignored = RequestContext.open(id)) {
      MDC.put("requestId", id);
      response.setHeader("X-Request-ID", id);
      chain.doFilter(request, response);
    } finally {
      if (previous == null) MDC.remove("requestId");
      else MDC.put("requestId", previous);
    }
  }
}
