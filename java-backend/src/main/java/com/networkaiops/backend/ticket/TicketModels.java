package com.networkaiops.backend.ticket;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.time.Instant;
import java.util.List;

public final class TicketModels {
  private TicketModels() {}

  public enum Priority {
    LOW,
    MEDIUM,
    HIGH,
    CRITICAL
  }

  public enum Status {
    OPEN,
    IN_PROGRESS,
    RESOLVED,
    CLOSED;

    public List<Status> allowed() {
      return switch (this) {
        case OPEN -> List.of(IN_PROGRESS, CLOSED);
        case IN_PROGRESS -> List.of(OPEN, RESOLVED);
        case RESOLVED -> List.of(IN_PROGRESS, CLOSED);
        case CLOSED -> List.of(OPEN);
      };
    }
  }

  public record CreateRequest(
      @NotBlank @Size(min = 2, max = 100, message = "标题长度应为 2–100 字符。") String title,
      @NotNull @Size(max = 64) String device,
      @NotBlank @Size(min = 10, max = 4000, message = "问题描述长度应为 10–4000 字符。") String description,
      @NotNull Priority priority) {}

  public record UpdateRequest(
      @NotNull @Min(0) Long version,
      @NotBlank @Size(min = 2, max = 100) String title,
      @NotNull @Size(max = 64) String device,
      @NotBlank @Size(min = 10, max = 4000) String description,
      @NotNull Priority priority) {}

  public record StatusRequest(
      @NotNull @Min(0) Long version,
      @NotNull Status status,
      @NotBlank @Size(min = 5, max = 1200, message = "请填写至少 5 字符的处理说明。") String note) {}

  public record Ticket(
      String id,
      String ownerId,
      String tenantId,
      String title,
      String device,
      String description,
      Priority priority,
      Status status,
      String analysisStatus,
      String agentSessionId,
      long version,
      boolean deleted,
      Instant createdAt,
      Instant updatedAt) {}

  public record View(
      String id,
      String title,
      String device,
      String description,
      Priority priority,
      Status status,
      String analysisStatus,
      String agentSessionId,
      long version,
      Instant createdAt,
      Instant updatedAt,
      List<Status> allowedStatuses) {
    public static View from(Ticket ticket) {
      return new View(
          ticket.id(),
          ticket.title(),
          ticket.device(),
          ticket.description(),
          ticket.priority(),
          ticket.status(),
          ticket.analysisStatus(),
          ticket.agentSessionId(),
          ticket.version(),
          ticket.createdAt(),
          ticket.updatedAt(),
          ticket.status().allowed());
    }
  }

  public record Page(List<View> items, long total, int offset, int limit) {}

  public record Analysis(
      String id,
      String status,
      String requestId,
      JsonNode response,
      String errorCode,
      Instant startedAt,
      Instant completedAt) {}
}
