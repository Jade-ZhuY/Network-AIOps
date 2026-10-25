package com.networkaiops.backend.business.monitor;

/** Monitor availability as last evaluated; new instances start unknown, never assumed up. */
public enum MonitorStatus {
  UP,
  DOWN,
  UNKNOWN
}
