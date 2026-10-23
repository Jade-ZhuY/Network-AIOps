package com.networkaiops.backend.audit;

import com.networkaiops.backend.common.RequestIdFilter;
import com.networkaiops.backend.security.WorkspacePrincipal;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class AuditRepository {
  private final JdbcTemplate jdbc;

  public AuditRepository(JdbcTemplate jdbc) {
    this.jdbc = jdbc;
  }

  public void record(WorkspacePrincipal user, String action, String ticketId, String outcome) {
    record(user, action, ticketId, outcome, null);
  }

  public void record(
      WorkspacePrincipal user, String action, String ticketId, String outcome, String note) {
    jdbc.update(
        "INSERT INTO audit_events(id,owner_id,tenant_id,action,ticket_id,trace_id,outcome,note,created_at) VALUES(?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
        UUID.randomUUID().toString(),
        user.userId(),
        user.tenantId(),
        action,
        ticketId,
        RequestIdFilter.currentId(),
        outcome,
        note);
  }

  public List<Map<String, Object>> list(WorkspacePrincipal user, String ticketId, int limit) {
    String filter = ticketId == null ? "" : " AND ticket_id=?";
    Object[] args =
        ticketId == null
            ? new Object[] {user.userId(), user.tenantId(), limit}
            : new Object[] {user.userId(), user.tenantId(), ticketId, limit};
    return jdbc.query(
        "SELECT * FROM audit_events WHERE owner_id=? AND tenant_id=?"
            + filter
            + " ORDER BY created_at DESC,id DESC LIMIT ?",
        (row, number) -> {
          var event = new java.util.LinkedHashMap<String, Object>();
          event.put("request_id", row.getString("id"));
          event.put("event_id", row.getString("id"));
          event.put("started_at", row.getObject("created_at", OffsetDateTime.class).toInstant());
          event.put("route", row.getString("action"));
          event.put("action", row.getString("action"));
          event.put("status", row.getString("outcome"));
          event.put("ticket_id", row.getString("ticket_id"));
          event.put("trace_id", row.getString("trace_id"));
          event.put("note", row.getString("note"));
          return event;
        },
        args);
  }
}
