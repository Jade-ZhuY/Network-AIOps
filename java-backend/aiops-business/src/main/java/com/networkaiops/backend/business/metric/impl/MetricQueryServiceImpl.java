package com.networkaiops.backend.business.metric.impl;

import com.networkaiops.backend.business.metric.MetricQueryMapper;
import com.networkaiops.backend.business.metric.MetricQueryService;
import com.networkaiops.backend.business.metric.MetricSeries;
import com.networkaiops.backend.business.metric.SeriesPoint;
import com.networkaiops.backend.business.monitor.Monitor;
import com.networkaiops.backend.business.monitor.MonitorService;
import com.networkaiops.backend.business.monitor.template.MetricTemplate;
import com.networkaiops.backend.business.monitor.template.MonitorTemplate;
import com.networkaiops.backend.business.monitor.template.TemplateRegistry;
import com.networkaiops.backend.common.exception.BusinessException;
import com.networkaiops.backend.common.identity.WorkspacePrincipal;
import java.time.Duration;
import java.time.Instant;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.util.List;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class MetricQueryServiceImpl implements MetricQueryService {
  static final int MAX_POINTS = 2000;
  static final Duration MAX_WINDOW = Duration.ofDays(31);

  private final MetricQueryMapper mapper;
  private final MonitorService monitors;
  private final TemplateRegistry templates;

  public MetricQueryServiceImpl(
      MetricQueryMapper mapper, MonitorService monitors, TemplateRegistry templates) {
    this.mapper = mapper;
    this.monitors = monitors;
    this.templates = templates;
  }

  @Override
  @Transactional(readOnly = true)
  public MetricSeries series(
      String monitorId,
      String metricId,
      Instant start,
      Instant end,
      String interfaceName,
      WorkspacePrincipal user) {
    if (start == null || end == null || !end.isAfter(start))
      throw new BusinessException(422, "invalid_window", "时间窗口必须提供 start 且 end 晚于 start。");
    if (Duration.between(start, end).compareTo(MAX_WINDOW) > 0)
      throw new BusinessException(422, "window_too_large", "时间窗口不能超过 31 天。");
    Monitor monitor = monitors.owned(monitorId, user);
    MonitorTemplate template = templates.require(monitor.type());
    MetricTemplate metric = template.metric(metricId);
    if (metric == null)
      throw new BusinessException(
          404, "metric_not_on_template", "监控类型 " + template.type() + " 未定义指标 " + metricId + "。");
    if (!metric.queryable())
      throw new BusinessException(422, "metric_not_queryable", "指标 " + metricId + " 不支持时序查询。");
    List<MetricQueryMapper.SeriesRow> rows =
        switch (metricId) {
          case "latency_ms" ->
              mapper.latencySeries(
                  monitor.hostname(), utc(start), utc(end), interfaceName, MAX_POINTS);
          case "packet_loss_pct" ->
              mapper.packetLossSeries(
                  monitor.hostname(), utc(start), utc(end), interfaceName, MAX_POINTS);
          case "utilization_pct" ->
              mapper.utilizationSeries(
                  monitor.hostname(), utc(start), utc(end), interfaceName, MAX_POINTS);
          default ->
              throw new BusinessException(
                  422, "metric_not_queryable", "指标 " + metricId + " 尚未接入查询通道。");
        };
    List<SeriesPoint> points =
        rows.stream()
            .map(row -> toPoint(row, metricId))
            .filter(point -> point.value() != null)
            .toList();
    boolean truncated = rows.size() == MAX_POINTS;
    return new MetricSeries(metricId, metric.unit(), points, points.isEmpty(), truncated);
  }

  private static SeriesPoint toPoint(MetricQueryMapper.SeriesRow row, String metricId) {
    return new SeriesPoint(
        row.sampleTime().toInstant(ZoneOffset.UTC), row.interfaceName(), row.metricValue());
  }

  private static LocalDateTime utc(Instant instant) {
    return LocalDateTime.ofInstant(instant, ZoneOffset.UTC);
  }
}
