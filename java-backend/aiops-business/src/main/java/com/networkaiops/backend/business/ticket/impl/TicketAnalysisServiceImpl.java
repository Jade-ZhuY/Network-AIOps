package com.networkaiops.backend.business.ticket.impl;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.networkaiops.backend.agent.client.AgentClient;
import com.networkaiops.backend.business.audit.AuditRepository;
import com.networkaiops.backend.business.ticket.Analysis;
import com.networkaiops.backend.business.ticket.AnalysisExecutor;
import com.networkaiops.backend.business.ticket.Status;
import com.networkaiops.backend.business.ticket.Ticket;
import com.networkaiops.backend.business.ticket.TicketAnalysisService;
import com.networkaiops.backend.business.ticket.TicketMapper;
import com.networkaiops.backend.business.ticket.TicketRepository;
import com.networkaiops.backend.business.ticket.TicketService;
import com.networkaiops.backend.common.context.RequestContext;
import com.networkaiops.backend.common.exception.BusinessException;
import com.networkaiops.backend.common.identity.WorkspacePrincipal;
import java.time.ZoneOffset;
import java.util.List;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * Async analysis lifecycle, after HertzBeat's collect job split: the request thread only validates,
 * persists a RUNNING record and enqueues; the worker thread performs the long Agent call. Terminal
 * state always lands in ticket_analyses, including startup recovery.
 */
@Service
public class TicketAnalysisServiceImpl implements TicketAnalysisService {
  private final TicketService tickets;
  private final TicketRepository repository;
  private final AuditRepository audit;
  private final AgentClient agent;
  private final AnalysisExecutor executor;
  private final TransactionTemplate transactions;
  private final ObjectMapper mapper;

  public TicketAnalysisServiceImpl(
      TicketService tickets,
      TicketRepository repository,
      AuditRepository audit,
      AgentClient agent,
      AnalysisExecutor executor,
      TransactionTemplate transactions,
      ObjectMapper mapper) {
    this.tickets = tickets;
    this.repository = repository;
    this.audit = audit;
    this.agent = agent;
    this.executor = executor;
    this.transactions = transactions;
    this.mapper = mapper;
  }

  @Override
  public void recover() {
    transactions.executeWithoutResult(ignored -> repository.reconcileInterrupted());
  }

  @Override
  public List<Analysis> list(String id, WorkspacePrincipal user) {
    tickets.owned(id, user, false);
    return repository.analyses(id).stream().map(this::readAnalysis).toList();
  }

  @Override
  public Analysis start(String id, long version, WorkspacePrincipal user, String authorization) {
    tickets.owned(id, user, false);
    agent.requireEnabled();
    String analysisId = UUID.randomUUID().toString();
    Ticket ticket =
        transactions.execute(
            ignored -> {
              Ticket current = tickets.owned(id, user, true);
              tickets.checkEditable(current, version);
              if (current.status() == Status.CLOSED)
                throw new BusinessException(409, "ticket_closed", "请先重新打开咨询单再分析。");
              repository.beginAnalysis(id, analysisId);
              audit.record(user, "ANALYSIS_STARTED", id, "running");
              return current;
            });
    try {
      // Identity stays on the request thread: outage and mismatch fail fast with 502/503.
      agent.verifyIdentity(authorization, user);
      String trace = RequestContext.currentId();
      if (!executor.submit(() -> run(id, analysisId, ticket, user, authorization, trace)))
        throw new BusinessException(429, "analysis_queue_full", "分析并发已满，请稍后重试。");
    } catch (Exception error) {
      markFailed(id, analysisId, user, error);
      if (error instanceof BusinessException business) throw business;
      throw new BusinessException(502, "analysis_failed", "分析尚未取得有效结果，请检查 Agent 会话后再重试。");
    }
    return list(id, user).stream()
        .filter(item -> analysisId.equals(item.id()))
        .findFirst()
        .orElseThrow();
  }

  private void run(
      String id,
      String analysisId,
      Ticket ticket,
      WorkspacePrincipal user,
      String authorization,
      String trace) {
    try (RequestContext.Scope ignored = RequestContext.open(trace)) {
      String session = ticket.agentSessionId();
      if (session == null) {
        session = agent.createSession(ticket.title(), authorization);
        String createdSession = session;
        transactions.executeWithoutResult(
            ignoredInner -> repository.saveAgentSession(id, createdSession));
      }
      // Description is the user's exact question. Device remains visible context, not an ACL claim.
      JsonNode result = agent.analyze(session, ticket.description(), authorization);
      String status = "failed".equals(result.path("status").asText()) ? "FAILED" : "SUCCEEDED";
      String json = mapper.writeValueAsString(result);
      transactions.executeWithoutResult(
          ignoredInner -> {
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
      markFailed(id, analysisId, user, error);
    }
  }

  private void markFailed(String id, String analysisId, WorkspacePrincipal user, Exception error) {
    String code =
        error instanceof BusinessException business ? business.getReason() : "analysis_failed";
    transactions.executeWithoutResult(
        ignored -> {
          repository.completeAnalysis(id, analysisId, "FAILED", null, null, code);
          audit.record(user, "ANALYSIS_FAILED", id, "failed");
        });
  }

  private Analysis readAnalysis(TicketMapper.AnalysisRow row) {
    try {
      JsonNode response = row.responseJson() == null ? null : mapper.readTree(row.responseJson());
      return new Analysis(
          row.id(),
          row.status(),
          row.requestId(),
          response,
          row.errorCode(),
          row.startedAt().toInstant(ZoneOffset.UTC),
          row.completedAt() == null ? null : row.completedAt().toInstant(ZoneOffset.UTC));
    } catch (Exception corrupt) {
      throw new BusinessException(500, "analysis_storage_invalid", "历史分析记录读取失败。");
    }
  }
}
