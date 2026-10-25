package com.networkaiops.backend.business.audit;

import com.networkaiops.backend.common.context.RequestContext;
import com.networkaiops.backend.common.identity.WorkspacePrincipal;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.stereotype.Repository;

/** Facade over {@link AuditMapper}; keeps the externally visible event map shape unchanged. */
@Repository
public class AuditRepository {
  private final AuditMapper mapper;

  public AuditRepository(AuditMapper mapper) {
    this.mapper = mapper;
  }

  public void record(WorkspacePrincipal user, String action, String ticketId, String outcome) {
    record(user, action, ticketId, outcome, null);
  }

  public void record(
      WorkspacePrincipal user, String action, String ticketId, String outcome, String note) {
    mapper.insert(
        UUID.randomUUID().toString(),
        user.userId(),
        user.tenantId(),
        action,
        ticketId,
        null,
        RequestContext.currentId(),
        outcome,
        note,
        LocalDateTime.ofInstant(Instant.now(), ZoneOffset.UTC));
  }

  /** Audit a mutation of a non-ticket resource, e.g. a monitor instance. */
  public void recordResource(
      WorkspacePrincipal user, String action, String resourceId, String outcome) {
    mapper.insert(
        UUID.randomUUID().toString(),
        user.userId(),
        user.tenantId(),
        action,
        null,
        resourceId,
        RequestContext.currentId(),
        outcome,
        null,
        LocalDateTime.ofInstant(Instant.now(), ZoneOffset.UTC));
  }

  public List<Map<String, Object>> list(WorkspacePrincipal user, String ticketId, int limit) {
    return mapper.list(user.userId(), user.tenantId(), ticketId, limit).stream()
        .map(
            row -> {
              Map<String, Object> event = new LinkedHashMap<>();
              event.put("request_id", row.id());
              event.put("event_id", row.id());
              event.put("started_at", row.createdAt().toInstant(ZoneOffset.UTC));
              event.put("route", row.action());
              event.put("action", row.action());
              event.put("status", row.outcome());
              event.put("ticket_id", row.ticketId());
              event.put("trace_id", row.traceId());
              event.put("note", row.note());
              return event;
            })
        .toList();
  }
}
