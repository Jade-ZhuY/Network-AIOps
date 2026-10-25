package com.networkaiops.backend.config;

import com.networkaiops.backend.business.ticket.TicketAnalysisService;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.event.EventListener;

/** Application lifecycle belongs to startup, not the reusable business library. */
@Configuration
public class AnalysisRecoveryConfiguration {
  private final TicketAnalysisService analyses;

  public AnalysisRecoveryConfiguration(TicketAnalysisService analyses) {
    this.analyses = analyses;
  }

  @EventListener(ApplicationReadyEvent.class)
  public void recoverInterruptedAnalyses() {
    analyses.recover();
  }
}
