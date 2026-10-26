package com.networkaiops.backend.common.context;

import static org.junit.jupiter.api.Assertions.*;

import java.util.concurrent.Executors;
import org.junit.jupiter.api.Test;

class RequestContextTest {
  @Test
  void nestedScopesRestorePreviousRequestAndClosingIsIdempotent() {
    assertEquals("internal", RequestContext.currentId());
    try (var outer = RequestContext.open("java_outer")) {
      assertEquals("java_outer", RequestContext.currentId());
      var inner = RequestContext.open("java_inner");
      assertEquals("java_inner", RequestContext.currentId());
      inner.close();
      inner.close();
      assertEquals("java_outer", RequestContext.currentId());
    }
    assertEquals("internal", RequestContext.currentId());
  }

  @Test
  void workerThreadsDoNotInheritOrLeakRequestContext() throws Exception {
    try (var outer = RequestContext.open("java_parent");
        var executor = Executors.newSingleThreadExecutor()) {
      assertEquals("internal", executor.submit(RequestContext::currentId).get());
      assertEquals(
          "java_worker",
          executor
              .submit(
                  () -> {
                    try (var worker = RequestContext.open("java_worker")) {
                      return RequestContext.currentId();
                    }
                  })
              .get());
      assertEquals("internal", executor.submit(RequestContext::currentId).get());
      assertEquals("java_parent", RequestContext.currentId());
    }
  }

  @Test
  void invalidIdsDoNotOpenAContext() {
    assertThrows(NullPointerException.class, () -> RequestContext.open(null));
    assertThrows(IllegalArgumentException.class, () -> RequestContext.open(" "));
    assertThrows(IllegalArgumentException.class, () -> RequestContext.open("x".repeat(129)));
    assertEquals("internal", RequestContext.currentId());
  }
}
