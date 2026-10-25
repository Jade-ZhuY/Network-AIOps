package com.networkaiops.backend.business.ticket;

import java.util.List;

public enum Status {
  OPEN,
  IN_PROGRESS,
  RESOLVED,
  CLOSED;

  public List<Status> allowed() {
    return switch (this) {
      case OPEN -> List.of(IN_PROGRESS, CLOSED);
      case IN_PROGRESS -> List.of(OPEN, RESOLVED);
      case RESOLVED -> List.of(IN_PROGRESS, CLOSED);
      case CLOSED -> List.of(OPEN);
    };
  }
}
