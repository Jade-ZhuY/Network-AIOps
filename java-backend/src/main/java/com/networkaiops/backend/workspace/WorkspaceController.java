package com.networkaiops.backend.workspace;

import com.networkaiops.backend.agent.AgentClient;
import com.networkaiops.backend.audit.AuditRepository;
import com.networkaiops.backend.security.WorkspacePrincipal;
import com.networkaiops.backend.ticket.TicketModels;
import com.networkaiops.backend.ticket.TicketRepository;
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
  private final JdbcTemplate jdbc;

  public WorkspaceController(
      AgentClient agent, TicketRepository tickets, AuditRepository audit, JdbcTemplate jdbc) {
    this.agent = agent;
    this.tickets = tickets;
    this.audit = audit;
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
        "h2-file",
        "agent_status",
        agent.enabled() ? "configured_not_probed" : "disabled",
        "model",
        "Agent 尚未调用验证",
        "database",
        "h2",
        "checkpoint",
        "java-business",
        "data_kind",
        "business",
        "persistence_enabled",
        true);
  }

  @GetMapping("/api/v1/workspace")
  Map<String, Object> workspace() {
    return Map.of(
        "backend",
        "java",
        "agent_enabled",
        agent.enabled(),
        "business_storage",
        "h2-file",
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
        tickets.list(user, "", null, 0, 5).stream().map(TicketModels.View::from).toList(),
        "agent_enabled",
        agent.enabled(),
        "storage",
        "h2-file");
  }

  @GetMapping("/api/v1/admin/audit")
  Map<String, Object> audit(
      @AuthenticationPrincipal WorkspacePrincipal user,
      @RequestParam(defaultValue = "50") @Min(1) @Max(200) int limit) {
    return Map.of("requests", audit.list(user, null, limit), "source", "java-business");
  }
}
