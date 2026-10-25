package com.networkaiops.backend.common.spring.web;

import static org.assertj.core.api.Assertions.*;

import com.networkaiops.backend.common.context.RequestContext;
import jakarta.servlet.ServletException;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.slf4j.MDC;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

class RequestIdFilterTest {
  @AfterEach
  void clearMdc() {
    MDC.clear();
  }

  @Test
  void usesServerIdAndCleansContextAfterNormalResponse() throws Exception {
    var request = new MockHttpServletRequest();
    request.addHeader("X-Request-ID", "untrusted_client_id");
    var response = new MockHttpServletResponse();
    new RequestIdFilter()
        .doFilter(
            request,
            response,
            (incoming, outgoing) -> {
              String id = response.getHeader("X-Request-ID");
              assertThat(id).startsWith("java_").isNotEqualTo("untrusted_client_id");
              assertThat(RequestContext.currentId()).isEqualTo(id);
              assertThat(MDC.get("requestId")).isEqualTo(id);
            });
    assertThat(RequestContext.currentId()).isEqualTo("internal");
    assertThat(MDC.get("requestId")).isNull();
  }

  @Test
  void restoresPreviousContextsEvenWhenDownstreamFails() {
    MDC.put("requestId", "existing_log_context");
    try (var previous = RequestContext.open("existing_core_context")) {
      assertThatThrownBy(
              () ->
                  new RequestIdFilter()
                      .doFilter(
                          new MockHttpServletRequest(),
                          new MockHttpServletResponse(),
                          (request, response) -> {
                            throw new ServletException("explicit failure fixture");
                          }))
          .isInstanceOf(ServletException.class);
      assertThat(RequestContext.currentId()).isEqualTo("existing_core_context");
      assertThat(MDC.get("requestId")).isEqualTo("existing_log_context");
    }
    assertThat(RequestContext.currentId()).isEqualTo("internal");
  }
}
