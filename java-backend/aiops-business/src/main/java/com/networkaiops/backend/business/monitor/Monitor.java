package com.networkaiops.backend.business.monitor;

import java.time.Instant;
import java.util.List;

/**
 * A monitored device instance. The template type carries the definition; {@code hostname} links the
 * instance to the demo dataset device tables that both the SQL agent and this backend read.
 */
public record Monitor(
    String id,
    String ownerId,
    String tenantId,
    String name,
    String type,
    String hostname,
    List<String> labels,
    String description,
    MonitorStatus status,
    long version,
    boolean deleted,
    Instant createdAt,
    Instant updatedAt) {}
