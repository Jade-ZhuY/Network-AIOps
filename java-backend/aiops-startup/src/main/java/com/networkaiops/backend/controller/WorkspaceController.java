package com.networkaiops.backend.controller;

import com.networkaiops.backend.agent.client.AgentClient;
import com.networkaiops.backend.business.audit.AuditRepository;
import com.networkaiops.backend.business.ticket.AnalysisExecutor;
import com.networkaiops.backend.business.ticket.TicketRepository;
import com.networkaiops.backend.business.ticket.View;
import com.networkaiops.backend.common.identity.WorkspacePrincipal;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

@RestController
@Validated
public class WorkspaceController {
  private final AgentClient agent;
  private final TicketRepository tickets;
  private final AuditRepository audit;
  private final AnalysisExecutor analyses;
  private final JdbcTemplate jdbc;

  public WorkspaceController(
      AgentClient agent,
      TicketRepository tickets,
      AuditRepository audit,
      AnalysisExecutor analyses,
      JdbcTemplate jdbc) {
    this.agent = agent;
    this.tickets = tickets;
    this.audit = audit;
    this.analyses = analyses;
    this.jdbc = jdbc;
  }

  @GetMapping("/api/v1/me")
  WorkspacePrincipal me(@AuthenticationPrincipal WorkspacePrincipal user) {
    return user;
  }

  @GetMapping({"/health", "/api/v1/health"})
  Map<String, Object> health() {
    jdbc.queryForObject("SELECT 1", Integer.class);
    return Map.of(
        "status",
        "ok",
        "backend",
        "java",
        "business_storage",
        "mysql",
        "agent_status",
        agentHealth(),
        "model",
        "Agent 尚未调用验证",
        "database",
        "mysql",
        "checkpoint",
        "java-business",
        "data_kind",
        "business",
        "persistence_enabled",
        true);
  }

  /** Runtime registry view, after HertzBeat's collector status: last real call, not a probe. */
  @GetMapping("/api/v1/agent/status")
  Map<String, Object> agentStatus(@AuthenticationPrincipal WorkspacePrincipal user) {
    AgentClient.Runtime runtime = agent.runtime();
    Map<String, Object> status = new java.util.LinkedHashMap<>();
    status.put("enabled", runtime.enabled());
    status.put("health", agentHealth());
    status.put("last_outcome", runtime.lastOutcome());
    status.put("last_checked_at", runtime.lastCheckedAt());
    status.put("last_duration_ms", runtime.lastDurationMillis());
    status.put("analysis_active", analyses.active());
    status.put("analysis_queued", analyses.queued());
    return status;
  }

  private String agentHealth() {
    AgentClient.Runtime runtime = agent.runtime();
    if (!runtime.enabled()) return "disabled";
    if (runtime.lastOutcome() == null) return "configured_not_probed";
    return "ok".equals(runtime.lastOutcome()) ? "online" : "error";
  }

  @GetMapping("/api/v1/workspace")
  Map<String, Object> workspace() {
    return Map.of(
        "backend",
        "java",
        "agent_enabled",
        agent.enabled(),
        "business_storage",
        "mysql",
        "capabilities",
        List.of("tickets", "business_audit", "agent_relay"));
  }

  @GetMapping("/api/v1/business/overview")
  Map<String, Object> overview(@AuthenticationPrincipal WorkspacePrincipal user) {
    return Map.of(
        "total",
        tickets.count(user, "", null),
        "counts",
        tickets.counts(user),
        "recent",
        tickets.list(user, "", null, 0, 5).stream().map(View::from).toList(),
        "agent_enabled",
        agent.enabled(),
        "storage",
        "mysql");
  }

  @GetMapping("/api/v1/admin/audit")
  Map<String, Object> audit(
      @AuthenticationPrincipal WorkspacePrincipal user,
      @RequestParam(defaultValue = "50") @Min(1) @Max(200) int limit) {
    return Map.of("requests", audit.list(user, null, limit), "source", "java-business");
  }
}
