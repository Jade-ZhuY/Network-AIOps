package com.networkaiops.backend.business.monitor.impl;

import com.networkaiops.backend.business.audit.AuditRepository;
import com.networkaiops.backend.business.common.Page;
import com.networkaiops.backend.business.monitor.CreateMonitorRequest;
import com.networkaiops.backend.business.monitor.Monitor;
import com.networkaiops.backend.business.monitor.MonitorRepository;
import com.networkaiops.backend.business.monitor.MonitorService;
import com.networkaiops.backend.business.monitor.MonitorStatus;
import com.networkaiops.backend.business.monitor.MonitorView;
import com.networkaiops.backend.business.monitor.UpdateMonitorRequest;
import com.networkaiops.backend.business.monitor.template.MonitorTemplate;
import com.networkaiops.backend.business.monitor.template.TemplateRegistry;
import com.networkaiops.backend.common.exception.BusinessException;
import com.networkaiops.backend.common.identity.WorkspacePrincipal;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class MonitorServiceImpl implements MonitorService {
  private final MonitorRepository repository;
  private final TemplateRegistry templates;
  private final AuditRepository audit;

  public MonitorServiceImpl(
      MonitorRepository repository, TemplateRegistry templates, AuditRepository audit) {
    this.repository = repository;
    this.templates = templates;
    this.audit = audit;
  }

  @Override
  public Monitor owned(String id, WorkspacePrincipal user) {
    return repository
        .find(id, user, false)
        .orElseThrow(() -> new BusinessException(404, "monitor_not_found", "监控对象不存在或不在当前身份范围。"));
  }

  @Override
  @Transactional(readOnly = true)
  public Page<MonitorView> list(
      WorkspacePrincipal user,
      String query,
      String type,
      MonitorStatus status,
      int offset,
      int limit) {
    if (type != null) templates.require(type);
    List<MonitorView> items =
        repository.list(user, query, type, status, offset, limit).stream()
            .map(monitor -> MonitorView.from(monitor, templates.find(monitor.type())))
            .toList();
    return new Page<>(items, repository.count(user, query, type, status), offset, limit);
  }

  @Override
  @Transactional(readOnly = true)
  public MonitorView get(String id, WorkspacePrincipal user) {
    Monitor monitor = owned(id, user);
    return MonitorView.from(monitor, templates.require(monitor.type()));
  }

  @Override
  @Transactional
  public MonitorView create(CreateMonitorRequest request, WorkspacePrincipal user) {
    MonitorTemplate template = templates.require(request.type().strip().toLowerCase());
    Instant now = Instant.now();
    Monitor monitor =
        new Monitor(
            UUID.randomUUID().toString(),
            user.userId(),
            user.tenantId(),
            request.name().strip(),
            template.type(),
            request.hostname().strip(),
            normalizeLabels(request.labels()),
            request.description() == null ? "" : request.description().strip(),
            MonitorStatus.UNKNOWN,
            0,
            false,
            now,
            now);
    repository.insert(monitor);
    audit.recordResource(user, "MONITOR_CREATED", monitor.id(), "completed");
    return MonitorView.from(monitor, template);
  }

  @Override
  @Transactional
  public MonitorView update(String id, UpdateMonitorRequest request, WorkspacePrincipal user) {
    Monitor monitor =
        repository
            .find(id, user, true)
            .orElseThrow(
                () -> new BusinessException(404, "monitor_not_found", "监控对象不存在或不在当前身份范围。"));
    if (monitor.version() != request.version())
      throw new BusinessException(409, "version_conflict", "记录已被修改，请刷新后重试。");
    MonitorTemplate template = templates.require(request.type().strip().toLowerCase());
    Monitor changes =
        new Monitor(
            monitor.id(),
            monitor.ownerId(),
            monitor.tenantId(),
            request.name().strip(),
            template.type(),
            request.hostname().strip(),
            normalizeLabels(request.labels()),
            request.description() == null ? "" : request.description().strip(),
            monitor.status(),
            monitor.version(),
            false,
            monitor.createdAt(),
            monitor.updatedAt());
    if (repository.update(id, user, request.version(), changes) != 1)
      throw new BusinessException(409, "version_conflict", "记录已被修改，请刷新后重试。");
    audit.recordResource(user, "MONITOR_UPDATED", id, "completed");
    return get(id, user);
  }

  @Override
  @Transactional
  public void delete(String id, long version, WorkspacePrincipal user) {
    Monitor monitor =
        repository
            .find(id, user, true)
            .orElseThrow(
                () -> new BusinessException(404, "monitor_not_found", "监控对象不存在或不在当前身份范围。"));
    if (monitor.version() != version)
      throw new BusinessException(409, "version_conflict", "记录已被修改，请刷新后重试。");
    repository.softDelete(id);
    audit.recordResource(user, "MONITOR_DELETED", id, "completed");
  }

  private static List<String> normalizeLabels(List<String> labels) {
    if (labels == null) return List.of();
    List<String> normalized =
        labels.stream().map(String::strip).filter(s -> !s.isEmpty()).distinct().toList();
    if (normalized.size() > 10)
      throw new BusinessException(422, "too_many_labels", "标签数量不能超过 10 个。");
    return normalized;
  }
}
