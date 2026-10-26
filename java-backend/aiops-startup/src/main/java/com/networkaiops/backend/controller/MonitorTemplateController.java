package com.networkaiops.backend.controller;

import com.networkaiops.backend.business.monitor.template.MonitorTemplate;
import com.networkaiops.backend.business.monitor.template.TemplateRegistry;
import com.networkaiops.backend.common.web.Result;
import java.util.List;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/monitor-templates")
public class MonitorTemplateController {
  record MetricView(String id, String unit, Double warning, Double critical, boolean queryable) {
    static MetricView from(MonitorTemplate m, String metricId) {
      var metric = m.metric(metricId);
      return new MetricView(
          metricId, metric.unit(), metric.warning(), metric.critical(), metric.queryable());
    }
  }

  record TemplateView(
      String type, String name, String category, int metricCount, List<MetricView> metrics) {}

  private final TemplateRegistry registry;

  public MonitorTemplateController(TemplateRegistry registry) {
    this.registry = registry;
  }

  @GetMapping
  Result list() {
    return Result.success(registry.all().stream().map(t -> view(t, false)).toList());
  }

  @GetMapping("/{type}")
  Result get(@PathVariable String type) {
    return Result.success(view(registry.require(type), true));
  }

  private static TemplateView view(MonitorTemplate template, boolean withMetrics) {
    return new TemplateView(
        template.type(),
        template.name(),
        template.category(),
        template.metrics().size(),
        withMetrics
            ? template.metrics().stream().map(m -> MetricView.from(template, m.id())).toList()
            : List.of());
  }
}
