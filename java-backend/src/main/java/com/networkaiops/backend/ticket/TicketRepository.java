package com.networkaiops.backend.ticket;

import static com.networkaiops.backend.ticket.TicketModels.*;

import com.networkaiops.backend.security.WorkspacePrincipal;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class TicketRepository {
  private final NamedParameterJdbcTemplate jdbc;

  public TicketRepository(NamedParameterJdbcTemplate jdbc) {
    this.jdbc = jdbc;
  }

  private MapSqlParameterSource scope(WorkspacePrincipal user) {
    return new MapSqlParameterSource()
        .addValue("owner", user.userId())
        .addValue("tenant", user.tenantId());
  }

  public Optional<Ticket> find(String id, WorkspacePrincipal user, boolean lock) {
    var parameters = scope(user).addValue("id", id);
    return jdbc
        .query(
            "SELECT * FROM tickets WHERE id=:id AND owner_id=:owner AND tenant_id=:tenant AND deleted=FALSE"
                + (lock ? " FOR UPDATE" : ""),
            parameters,
            TicketRepository::map)
        .stream()
        .findFirst();
  }

  public List<Ticket> list(
      WorkspacePrincipal user, String query, Status status, int offset, int limit) {
    var parameters =
        listParameters(user, query, status).addValue("offset", offset).addValue("limit", limit);
    return jdbc.query(
        "SELECT * FROM tickets "
            + filters(status)
            + " ORDER BY updated_at DESC,id DESC LIMIT :limit OFFSET :offset",
        parameters,
        TicketRepository::map);
  }

  public long count(WorkspacePrincipal user, String query, Status status) {
    return jdbc.queryForObject(
        "SELECT COUNT(*) FROM tickets " + filters(status),
        listParameters(user, query, status),
        Long.class);
  }

  private String filters(Status status) {
    return "WHERE owner_id=:owner AND tenant_id=:tenant AND deleted=FALSE "
        + "AND (LOWER(title) LIKE :query ESCAPE '!' OR LOWER(device) LIKE :query ESCAPE '!') "
        + (status == null ? "" : "AND status=:status");
  }

  private MapSqlParameterSource listParameters(
      WorkspacePrincipal user, String query, Status status) {
    String escaped =
        query
            .toLowerCase(java.util.Locale.ROOT)
            .replace("!", "!!")
            .replace("%", "!%")
            .replace("_", "!_");
    return scope(user)
        .addValue("query", "%" + escaped + "%")
        .addValue("status", status == null ? null : status.name());
  }

  public Map<String, Long> counts(WorkspacePrincipal user) {
    var values = new java.util.LinkedHashMap<String, Long>();
    for (Status status : Status.values()) values.put(status.name(), count(user, "", status));
    return values;
  }

  public void insert(Ticket ticket) {
    jdbc.update(
        "INSERT INTO tickets(id,owner_id,tenant_id,title,device,description,priority,status,analysis_status,version,deleted,created_at,updated_at) "
            + "VALUES(:id,:owner,:tenant,:title,:device,:description,:priority,'OPEN','NOT_STARTED',0,FALSE,:at,:at)",
        new MapSqlParameterSource()
            .addValue("id", ticket.id())
            .addValue("owner", ticket.ownerId())
            .addValue("tenant", ticket.tenantId())
            .addValue("title", ticket.title())
            .addValue("device", ticket.device())
            .addValue("description", ticket.description())
            .addValue("priority", ticket.priority().name())
            .addValue(
                "at", OffsetDateTime.ofInstant(ticket.createdAt(), java.time.ZoneOffset.UTC)));
  }

  public int update(String id, WorkspacePrincipal user, UpdateRequest request) {
    return jdbc.update(
        "UPDATE tickets SET title=:title,device=:device,description=:description,priority=:priority,version=version+1,updated_at=CURRENT_TIMESTAMP "
            + "WHERE id=:id AND owner_id=:owner AND tenant_id=:tenant AND version=:version AND deleted=FALSE",
        scope(user)
            .addValue("id", id)
            .addValue("version", request.version())
            .addValue("title", request.title().trim())
            .addValue("device", request.device().trim())
            .addValue("description", request.description().trim())
            .addValue("priority", request.priority().name()));
  }

  public void changeStatus(String id, Status status) {
    jdbc.update(
        "UPDATE tickets SET status=:status,version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=:id",
        Map.of("id", id, "status", status.name()));
  }

  public void softDelete(String id) {
    jdbc.update(
        "UPDATE tickets SET deleted=TRUE,version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=:id",
        Map.of("id", id));
  }

  public void beginAnalysis(String id, String analysisId) {
    jdbc.update(
        "INSERT INTO ticket_analyses(id,ticket_id,status,started_at) VALUES(:analysis,:id,'RUNNING',CURRENT_TIMESTAMP)",
        Map.of("analysis", analysisId, "id", id));
    jdbc.update(
        "UPDATE tickets SET analysis_status='RUNNING',version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=:id",
        Map.of("id", id));
  }

  public void saveAgentSession(String id, String sessionId) {
    jdbc.update(
        "UPDATE tickets SET agent_session_id=:session WHERE id=:id",
        Map.of("id", id, "session", sessionId));
  }

  public void completeAnalysis(
      String id,
      String analysisId,
      String status,
      String requestId,
      String json,
      String errorCode) {
    var parameters =
        new MapSqlParameterSource()
            .addValue("id", id)
            .addValue("analysis", analysisId)
            .addValue("status", status)
            .addValue("request", requestId)
            .addValue("json", json)
            .addValue("error", errorCode);
    jdbc.update(
        "UPDATE ticket_analyses SET status=:status,request_id=:request,response_json=:json,error_code=:error,completed_at=CURRENT_TIMESTAMP WHERE id=:analysis AND status='RUNNING'",
        parameters);
    jdbc.update(
        "UPDATE tickets SET analysis_status=:status,version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=:id",
        parameters);
  }

  public List<Map<String, Object>> analyses(String id) {
    return jdbc.queryForList(
        "SELECT * FROM ticket_analyses WHERE ticket_id=:id ORDER BY started_at DESC,id DESC LIMIT 50",
        Map.of("id", id));
  }

  public void reconcileInterrupted() {
    jdbc.update(
        "UPDATE ticket_analyses SET status='FAILED',error_code='server_restarted',completed_at=CURRENT_TIMESTAMP WHERE status='RUNNING'",
        Map.of());
    jdbc.update(
        "UPDATE tickets SET analysis_status='FAILED',version=version+1,updated_at=CURRENT_TIMESTAMP WHERE analysis_status='RUNNING'",
        Map.of());
  }

  private static Ticket map(ResultSet row, int ignored) throws SQLException {
    return new Ticket(
        row.getString("id"),
        row.getString("owner_id"),
        row.getString("tenant_id"),
        row.getString("title"),
        row.getString("device"),
        row.getString("description"),
        Priority.valueOf(row.getString("priority")),
        Status.valueOf(row.getString("status")),
        row.getString("analysis_status"),
        row.getString("agent_session_id"),
        row.getLong("version"),
        row.getBoolean("deleted"),
        row.getObject("created_at", OffsetDateTime.class).toInstant(),
        row.getObject("updated_at", OffsetDateTime.class).toInstant());
  }
}
