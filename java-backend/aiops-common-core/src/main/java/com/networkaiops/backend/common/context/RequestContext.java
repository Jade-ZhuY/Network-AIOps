package com.networkaiops.backend.common.context;

import java.util.Objects;

/** Request-local correlation without Servlet, logging or Spring dependencies. */
public final class RequestContext {
  private static final ThreadLocal<String> REQUEST_ID = new ThreadLocal<>();

  private RequestContext() {}

  public static String currentId() {
    String value = REQUEST_ID.get();
    return value == null ? "internal" : value;
  }

  public static Scope open(String requestId) {
    Objects.requireNonNull(requestId, "requestId");
    if (requestId.isBlank() || requestId.length() > 128)
      throw new IllegalArgumentException("Invalid internal request ID");
    Scope scope = new Scope(REQUEST_ID.get());
    REQUEST_ID.set(requestId);
    return scope;
  }

  public static final class Scope implements AutoCloseable {
    private final String previous;
    private final Thread owner = Thread.currentThread();
    private boolean closed;

    private Scope(String previous) {
      this.previous = previous;
    }

    @Override
    public void close() {
      if (Thread.currentThread() != owner)
        throw new IllegalStateException("Request context must close on its owning thread");
      if (closed) return;
      closed = true;
      if (previous == null) REQUEST_ID.remove();
      else REQUEST_ID.set(previous);
    }
  }
}
