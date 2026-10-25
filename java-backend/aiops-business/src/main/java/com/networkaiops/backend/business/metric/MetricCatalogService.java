package com.networkaiops.backend.business.metric;

import com.networkaiops.backend.business.monitor.template.MetricTemplate;
import com.networkaiops.backend.business.monitor.template.MonitorTemplate;
import com.networkaiops.backend.business.monitor.template.TemplateRegistry;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Service;

/**
 * Metric catalog aggregated from monitor templates. The SQL caliber of each metric stays owned by
 * the Python metric catalog; this view only serves management-ui metadata (units, thresholds, which
 * device types watch which metric).
 */
@Service
public class MetricCatalogService {
  private final TemplateRegistry templates;

  public MetricCatalogService(TemplateRegistry templates) {
    this.templates = templates;
  }

  public List<MetricDefinitionView> definitions() {
    Map<String, Builder> byId = new LinkedHashMap<>();
    for (MonitorTemplate template : templates.all()) {
      for (MetricTemplate metric : template.metrics()) {
        Builder builder =
            byId.computeIfAbsent(metric.id(), id -> new Builder(id, metric.queryable()));
        builder.deviceTypes.add(template.type());
        if (builder.unit == null) builder.unit = metric.unit();
        if (builder.warning == null) builder.warning = metric.warning();
        if (builder.critical == null) builder.critical = metric.critical();
      }
    }
    return byId.values().stream().map(Builder::build).toList();
  }

  private static final class Builder {
    final String id;
    final boolean queryable;
    final List<String> deviceTypes = new ArrayList<>();
    String unit;
    Double warning;
    Double critical;

    Builder(String id, boolean queryable) {
      this.id = id;
      this.queryable = queryable;
    }

    MetricDefinitionView build() {
      return new MetricDefinitionView(
          id, unit, warning, critical, queryable, List.copyOf(deviceTypes));
    }
  }
}
