package com.networkaiops.backend.business.monitor;

import com.networkaiops.backend.business.monitor.template.MonitorTemplate;
import java.time.Instant;
import java.util.List;

/** API shape of a monitor instance, enriched with display metadata from its template. */
public record MonitorView(
    String id,
    String name,
    String type,
    String templateName,
    String category,
    String hostname,
    List<String> labels,
    String description,
    MonitorStatus status,
    long version,
    Instant createdAt,
    Instant updatedAt) {
  public static MonitorView from(Monitor monitor, MonitorTemplate template) {
    return new MonitorView(
        monitor.id(),
        monitor.name(),
        monitor.type(),
        template == null ? monitor.type() : template.name(),
        template == null ? null : template.category(),
        monitor.hostname(),
        monitor.labels(),
        monitor.description(),
        monitor.status(),
        monitor.version(),
        monitor.createdAt(),
        monitor.updatedAt());
  }
}
