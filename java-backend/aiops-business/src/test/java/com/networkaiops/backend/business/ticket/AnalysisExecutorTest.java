package com.networkaiops.backend.business.ticket;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.Test;

class AnalysisExecutorTest {
  @Test
  void runsSubmittedTasksAndRejectsWhenConcurrencyAndQueueAreFull() throws Exception {
    var executor = new AnalysisExecutor(new AnalysisProperties(1, 1));
    try {
      var running = new CountDownLatch(1);
      var finished = new CountDownLatch(2);
      assertThat(executor.submit(() -> latch(running, finished))).isTrue();
      assertThat(executor.submit(finished::countDown)).isTrue();
      assertThat(executor.submit(finished::countDown)).isFalse();
      running.countDown();
      assertThat(finished.await(5, TimeUnit.SECONDS)).isTrue();
    } finally {
      executor.destroy();
    }
  }

  @Test
  void defaultsAreAppliedWhenConfigurationIsAbsent() {
    var defaults = new AnalysisProperties(null, null);
    assertThat(defaults.concurrency()).isEqualTo(2);
    assertThat(defaults.queue()).isEqualTo(50);
    var bounded = new AnalysisProperties(99, -5);
    assertThat(bounded.concurrency()).isEqualTo(16);
    assertThat(bounded.queue()).isZero();
  }

  private static void latch(CountDownLatch running, CountDownLatch finished) {
    try {
      running.await();
    } catch (InterruptedException interrupted) {
      Thread.currentThread().interrupt();
    }
    finished.countDown();
  }
}
