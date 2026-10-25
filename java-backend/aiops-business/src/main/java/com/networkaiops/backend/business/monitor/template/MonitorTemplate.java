package com.networkaiops.backend.business.monitor.template;

/**
 * A monitor template describes one device category: which launch parameters it takes and which
 * metrics it watches, after HertzBeat's per-type app definitions. Templates live as YAML under
 * {@code templates/monitor/} and are the single source for type and metric metadata; instances in
 * the database only reference the template type.
 */
public record MonitorTemplate(
    String type,
    String name,
    String category,
    java.util.List<ParamTemplate> params,
    java.util.List<MetricTemplate> metrics) {

  public MetricTemplate metric(String metricId) {
    return metrics.stream().filter(m -> m.id().equals(metricId)).findFirst().orElse(null);
  }
}
