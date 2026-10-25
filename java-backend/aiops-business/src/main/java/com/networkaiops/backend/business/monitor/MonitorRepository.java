package com.networkaiops.backend.business.monitor;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.networkaiops.backend.common.identity.WorkspacePrincipal;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Locale;
import java.util.Optional;
import org.springframework.stereotype.Repository;

/**
 * Facade over {@link MonitorMapper} that owns label JSON serialization, enum handling and
 * Instant/UTC conversion, mirroring {@code TicketRepository}.
 */
@Repository
public class MonitorRepository {
  private static final TypeReference<List<String>> LABEL_LIST = new TypeReference<>() {};

  private final MonitorMapper mapper;
  private final ObjectMapper json;

  public MonitorRepository(MonitorMapper mapper, ObjectMapper json) {
    this.mapper = mapper;
    this.json = json;
  }

  public Optional<Monitor> find(String id, WorkspacePrincipal user, boolean lock) {
    MonitorMapper.MonitorRow row = mapper.find(id, user.userId(), user.tenantId(), lock);
    return row == null ? Optional.empty() : Optional.of(toMonitor(row));
  }

  public List<Monitor> list(
      WorkspacePrincipal user,
      String query,
      String type,
      MonitorStatus status,
      int offset,
      int limit) {
    return mapper
        .list(
            user.userId(),
            user.tenantId(),
            likePattern(query),
            type,
            status == null ? null : status.name(),
            limit,
            offset)
        .stream()
        .map(this::toMonitor)
        .toList();
  }

  public long count(WorkspacePrincipal user, String query, String type, MonitorStatus status) {
    return mapper.count(
        user.userId(),
        user.tenantId(),
        likePattern(query),
        type,
        status == null ? null : status.name());
  }

  public void insert(Monitor monitor) {
    mapper.insert(
        monitor.id(),
        monitor.ownerId(),
        monitor.tenantId(),
        monitor.name(),
        monitor.type(),
        monitor.hostname(),
        writeLabels(monitor.labels()),
        monitor.description(),
        utc(monitor.createdAt()));
  }

  public int update(String id, WorkspacePrincipal user, long version, Monitor changes) {
    return mapper.update(
        id,
        user.userId(),
        user.tenantId(),
        version,
        changes.name(),
        changes.type(),
        changes.hostname(),
        writeLabels(changes.labels()),
        changes.description(),
        now());
  }

  public void softDelete(String id) {
    mapper.softDelete(id, now());
  }

  private String writeLabels(List<String> labels) {
    try {
      return json.writeValueAsString(labels == null ? List.of() : labels);
    } catch (java.io.IOException failure) {
      throw new IllegalStateException("标签序列化失败。", failure);
    }
  }

  private List<String> readLabels(String raw) {
    if (raw == null || raw.isBlank()) return List.of();
    try {
      return json.readValue(raw, LABEL_LIST);
    } catch (java.io.IOException failure) {
      throw new IllegalStateException("标签数据损坏: " + raw, failure);
    }
  }

  private static String likePattern(String query) {
    String escaped =
        query.toLowerCase(Locale.ROOT).replace("!", "!!").replace("%", "!%").replace("_", "!_");
    return "%" + escaped + "%";
  }

  private static LocalDateTime now() {
    return LocalDateTime.ofInstant(Instant.now(), ZoneOffset.UTC);
  }

  private static LocalDateTime utc(Instant instant) {
    return LocalDateTime.ofInstant(instant, ZoneOffset.UTC);
  }

  private Monitor toMonitor(MonitorMapper.MonitorRow row) {
    return new Monitor(
        row.id(),
        row.ownerId(),
        row.tenantId(),
        row.name(),
        row.type(),
        row.hostname(),
        List.copyOf(readLabels(row.labels())),
        row.description(),
        MonitorStatus.valueOf(row.status()),
        row.version(),
        row.deleted(),
        row.createdAt().toInstant(ZoneOffset.UTC),
        row.updatedAt().toInstant(ZoneOffset.UTC));
  }
}
