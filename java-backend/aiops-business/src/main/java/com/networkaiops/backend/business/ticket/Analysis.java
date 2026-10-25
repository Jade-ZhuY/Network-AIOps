package com.networkaiops.backend.business.ticket;

import com.fasterxml.jackson.databind.JsonNode;
import java.time.Instant;

public record Analysis(
    String id,
    String status,
    String requestId,
    JsonNode response,
    String errorCode,
    Instant startedAt,
    Instant completedAt) {}
