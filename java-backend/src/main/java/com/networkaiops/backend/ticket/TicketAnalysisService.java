package com.networkaiops.backend.ticket;

import static com.networkaiops.backend.ticket.TicketModels.*;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.networkaiops.backend.agent.AgentClient;
import com.networkaiops.backend.audit.AuditRepository;
import com.networkaiops.backend.common.BusinessException;
import com.networkaiops.backend.security.WorkspacePrincipal;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.UUID;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;

@Service
public class TicketAnalysisService {
  private final TicketService tickets;
  private final TicketRepository repository;
  private final AuditRepository audit;
  private final AgentClient agent;
  private final TransactionTemplate transactions;
  private final ObjectMapper mapper;

  public TicketAnalysisService(
      TicketService tickets,
      TicketRepository repository,
      AuditRepository audit,
      AgentClient agent,
      TransactionTemplate transactions,
      ObjectMapper mapper) {
    this.tickets = tickets;
    this.repository = repository;
    this.audit = audit;
    this.agent = agent;
    this.transactions = transactions;
    this.mapper = mapper;
  }

  @EventListener(ApplicationReadyEvent.class)
  public void recover() {
    transactions.executeWithoutResult(ignored -> repository.reconcileInterrupted());
  }

  public List<Analysis> list(String id, WorkspacePrincipal user) {
    tickets.owned(id, user, false);
    return repository.analyses(id).stream()
        .map(
            row -> {
              try {
                Object raw = row.get("RESPONSE_JSON");
                String json =
                    raw instanceof java.sql.Clob clob
                        ? clob.getSubString(1, Math.toIntExact(clob.length()))
                        : (String) raw;
                JsonNode response = json == null ? null : mapper.readTree(json);
                return new Analysis(
                    (String) row.get("ID"),
                    (String) row.get("STATUS"),
                    (String) row.get("REQUEST_ID"),
                    response,
                    (String) row.get("ERROR_CODE"),
                    ((OffsetDateTime) row.get("STARTED_AT")).toInstant(),
                    row.get("COMPLETED_AT") == null
                        ? null
                        : ((OffsetDateTime) row.get("COMPLETED_AT")).toInstant());
              } catch (Exception corrupt) {
                throw new BusinessException(500, "analysis_storage_invalid", "历史分析记录读取失败。");
              }
            })
        .toList();
  }

  public Analysis analyze(String id, long version, WorkspacePrincipal user, String authorization) {
    tickets.owned(id, user, false);
    agent.requireEnabled();
    String analysisId = UUID.randomUUID().toString();
    Ticket ticket =
        transactions.execute(
            ignored -> {
              Ticket current = tickets.owned(id, user, true);
              TicketService.checkEditable(current, version);
              if (current.status() == Status.CLOSED)
                throw new BusinessException(409, "ticket_closed", "请先重新打开咨询单再分析。");
              repository.beginAnalysis(id, analysisId);
              audit.record(user, "ANALYSIS_STARTED", id, "running");
              return current;
            });
    try {
      agent.verifyIdentity(authorization, user);
      String session = ticket.agentSessionId();
      if (session == null) {
        session = agent.createSession(ticket.title(), authorization);
        String createdSession = session;
        transactions.executeWithoutResult(
            ignored -> repository.saveAgentSession(id, createdSession));
      }
      // Description is the user's exact question. Device remains visible context, not an ACL claim.
      JsonNode result = agent.analyze(session, ticket.description(), authorization);
      String status = "failed".equals(result.path("status").asText()) ? "FAILED" : "SUCCEEDED";
      String json = mapper.writeValueAsString(result);
      transactions.executeWithoutResult(
          ignored -> {
            repository.completeAnalysis(
                id,
                analysisId,
                status,
                result.path("request_id").asText(),
                json,
                "FAILED".equals(status) ? "agent_execution_failed" : null);
            audit.record(user, "ANALYSIS_FINISHED", id, status.toLowerCase(java.util.Locale.ROOT));
          });
    } catch (Exception error) {
      String code =
          error instanceof BusinessException business ? business.getReason() : "analysis_failed";
      transactions.executeWithoutResult(
          ignored -> {
            repository.completeAnalysis(id, analysisId, "FAILED", null, null, code);
            audit.record(user, "ANALYSIS_FAILED", id, "failed");
          });
      if (error instanceof BusinessException business) throw business;
      throw new BusinessException(502, "analysis_failed", "分析尚未取得有效结果，请检查 Agent 会话后再重试。");
    }
    return list(id, user).stream()
        .filter(item -> analysisId.equals(item.id()))
        .findFirst()
        .orElseThrow();
  }
}
