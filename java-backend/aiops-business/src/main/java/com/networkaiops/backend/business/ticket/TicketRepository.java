package com.networkaiops.backend.business.ticket;

import com.networkaiops.backend.common.identity.WorkspacePrincipal;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.springframework.stereotype.Repository;

/**
 * Facade over {@link TicketMapper} that owns escaping, enum handling and Instant/UTC conversion.
 */
@Repository
public class TicketRepository {
  private final TicketMapper mapper;

  public TicketRepository(TicketMapper mapper) {
    this.mapper = mapper;
  }

  public Optional<Ticket> find(String id, WorkspacePrincipal user, boolean lock) {
    TicketMapper.TicketRow row = mapper.find(id, user.userId(), user.tenantId(), lock);
    return row == null ? Optional.empty() : Optional.of(toTicket(row));
  }

  public List<Ticket> list(
      WorkspacePrincipal user, String query, Status status, int offset, int limit) {
    return mapper
        .list(user.userId(), user.tenantId(), likePattern(query), nameOrNull(status), limit, offset)
        .stream()
        .map(TicketRepository::toTicket)
        .toList();
  }

  public long count(WorkspacePrincipal user, String query, Status status) {
    return mapper.count(user.userId(), user.tenantId(), likePattern(query), nameOrNull(status));
  }

  public Map<String, Long> counts(WorkspacePrincipal user) {
    var values = new java.util.LinkedHashMap<String, Long>();
    for (Status status : Status.values()) values.put(status.name(), count(user, "", status));
    return values;
  }

  public void insert(Ticket ticket) {
    mapper.insert(
        ticket.id(),
        ticket.ownerId(),
        ticket.tenantId(),
        ticket.title(),
        ticket.device(),
        ticket.description(),
        ticket.priority().name(),
        utc(ticket.createdAt()));
  }

  public int update(String id, WorkspacePrincipal user, UpdateRequest request) {
    return mapper.update(
        id,
        user.userId(),
        user.tenantId(),
        request.version(),
        request.title().trim(),
        request.device().trim(),
        request.description().trim(),
        request.priority().name(),
        now());
  }

  public void changeStatus(String id, Status status) {
    mapper.changeStatus(id, status.name(), now());
  }

  public void softDelete(String id) {
    mapper.softDelete(id, now());
  }

  public void beginAnalysis(String id, String analysisId) {
    mapper.insertAnalysis(analysisId, id, now());
    mapper.markTicketAnalysisRunning(id, now());
  }

  public void saveAgentSession(String id, String sessionId) {
    mapper.saveAgentSession(id, sessionId);
  }

  public void completeAnalysis(
      String id,
      String analysisId,
      String status,
      String requestId,
      String json,
      String errorCode) {
    LocalDateTime at = now();
    mapper.completeAnalysisRow(analysisId, status, requestId, json, errorCode, at);
    mapper.completeAnalysisTicket(id, status, at);
  }

  public List<TicketMapper.AnalysisRow> analyses(String id) {
    return mapper.analyses(id);
  }

  public void reconcileInterrupted() {
    LocalDateTime at = now();
    mapper.failInterruptedAnalyses(at);
    mapper.failInterruptedTickets(at);
  }

  private static String likePattern(String query) {
    String escaped =
        query
            .toLowerCase(java.util.Locale.ROOT)
            .replace("!", "!!")
            .replace("%", "!%")
            .replace("_", "!_");
    return "%" + escaped + "%";
  }

  private static String nameOrNull(Status status) {
    return status == null ? null : status.name();
  }

  private static LocalDateTime now() {
    return LocalDateTime.ofInstant(Instant.now(), ZoneOffset.UTC);
  }

  private static LocalDateTime utc(Instant instant) {
    return LocalDateTime.ofInstant(instant, ZoneOffset.UTC);
  }

  private static Ticket toTicket(TicketMapper.TicketRow row) {
    return new Ticket(
        row.id(),
        row.ownerId(),
        row.tenantId(),
        row.title(),
        row.device(),
        row.description(),
        Priority.valueOf(row.priority()),
        Status.valueOf(row.status()),
        row.analysisStatus(),
        row.agentSessionId(),
        row.version(),
        row.deleted(),
        row.createdAt().toInstant(ZoneOffset.UTC),
        row.updatedAt().toInstant(ZoneOffset.UTC));
  }
}
