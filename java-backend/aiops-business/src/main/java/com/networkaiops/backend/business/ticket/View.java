package com.networkaiops.backend.business.ticket;

import java.time.Instant;
import java.util.List;

public record View(
    String id,
    String title,
    String device,
    String description,
    Priority priority,
    Status status,
    String analysisStatus,
    String agentSessionId,
    long version,
    Instant createdAt,
    Instant updatedAt,
    List<Status> allowedStatuses) {
  public static View from(Ticket ticket) {
    return new View(
        ticket.id(),
        ticket.title(),
        ticket.device(),
        ticket.description(),
        ticket.priority(),
        ticket.status(),
        ticket.analysisStatus(),
        ticket.agentSessionId(),
        ticket.version(),
        ticket.createdAt(),
        ticket.updatedAt(),
        ticket.status().allowed());
  }
}
