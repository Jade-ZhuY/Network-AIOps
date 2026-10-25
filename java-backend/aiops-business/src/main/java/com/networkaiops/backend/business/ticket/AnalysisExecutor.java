package com.networkaiops.backend.business.ticket;

import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import org.springframework.beans.factory.DisposableBean;
import org.springframework.stereotype.Component;

/**
 * Dedicated pool for long Agent analyses so request threads never block for the full Agent read
 * timeout. Saturation is reported to the caller instead of queueing without bound; a pool killed
 * mid-task is reconciled to FAILED by the next startup.
 */
@Component
public class AnalysisExecutor implements DisposableBean {
  private static final AtomicInteger WORKERS = new AtomicInteger();
  private final ThreadPoolExecutor pool;

  public AnalysisExecutor(AnalysisProperties properties) {
    int concurrency = properties.concurrency();
    pool =
        new ThreadPoolExecutor(
            concurrency,
            concurrency,
            60,
            TimeUnit.SECONDS,
            new LinkedBlockingQueue<>(properties.queue()),
            task -> new Thread(task, "ticket-analysis-" + WORKERS.incrementAndGet()),
            new ThreadPoolExecutor.AbortPolicy());
    pool.allowCoreThreadTimeOut(true);
  }

  /**
   * @return false when concurrency and queue are both saturated; callers must persist that.
   */
  public boolean submit(Runnable analysis) {
    try {
      pool.execute(analysis);
      return true;
    } catch (RejectedExecutionException saturated) {
      return false;
    }
  }

  public int active() {
    return pool.getActiveCount();
  }

  public int queued() {
    return pool.getQueue().size();
  }

  @Override
  public void destroy() throws InterruptedException {
    pool.shutdown();
    // Interrupted tasks are marked FAILED by reconcileInterrupted on the next startup.
    if (!pool.awaitTermination(45, TimeUnit.SECONDS)) pool.shutdownNow();
  }
}
