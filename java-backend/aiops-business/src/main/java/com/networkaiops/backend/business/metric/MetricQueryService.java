package com.networkaiops.backend.business.metric;

import com.networkaiops.backend.common.identity.WorkspacePrincipal;
import java.time.Instant;

/** Time-series query contract for a monitor's metric over a bounded window. */
public interface MetricQueryService {
  MetricSeries series(
      String monitorId,
      String metricId,
      Instant start,
      Instant end,
      String interfaceName,
      WorkspacePrincipal user);
}
