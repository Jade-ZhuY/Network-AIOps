package com.networkaiops.backend.business.ticket;

import java.time.Instant;

public record Ticket(
    String id,
    String ownerId,
    String tenantId,
    String title,
    String device,
    String description,
    Priority priority,
    Status status,
    String analysisStatus,
    String agentSessionId,
    long version,
    boolean deleted,
    Instant createdAt,
    Instant updatedAt) {}
