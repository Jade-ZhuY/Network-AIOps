package com.networkaiops.backend.business.metric;

import java.util.List;

/**
 * A metric series over a time window. An empty point list means no non-null samples exist in the
 * window (no_data), never the value zero, following the catalog's empty policy.
 */
public record MetricSeries(
    String metricId, String unit, List<SeriesPoint> points, boolean noData, boolean truncated) {}
