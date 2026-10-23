package com.networkaiops.backend.security;

import java.util.List;

public record WorkspacePrincipal(String userId, String role, String tenantId, Scope scope) {
  public record Scope(String tenantId, List<Integer> deviceIds, List<String> knowledgeGroups) {}

  public static WorkspacePrincipal forRole(String role) {
    return new WorkspacePrincipal(
        "admin".equals(role) ? "netops-admin" : "netops-engineer",
        role,
        "demo-tenant",
        new Scope("demo-tenant", List.of(1, 2, 3, 4), List.of("netops")));
  }
}
