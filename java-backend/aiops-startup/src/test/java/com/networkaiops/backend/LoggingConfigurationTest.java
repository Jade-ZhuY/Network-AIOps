package com.networkaiops.backend;

import static org.assertj.core.api.Assertions.assertThat;

import ch.qos.logback.classic.LoggerContext;
import ch.qos.logback.classic.joran.JoranConfigurator;
import ch.qos.logback.classic.util.LogbackMDCAdapter;
import ch.qos.logback.core.rolling.RollingFileAppender;
import ch.qos.logback.core.rolling.SizeAndTimeBasedRollingPolicy;
import ch.qos.logback.core.status.Status;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import java.util.zip.GZIPInputStream;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.env.YamlPropertySourceLoader;
import org.springframework.core.env.MapPropertySource;
import org.springframework.core.env.StandardEnvironment;
import org.springframework.core.io.ClassPathResource;

class LoggingConfigurationTest {
  @TempDir Path directory;

  @Test
  void slf4jSelectsLogbackAndProductionConfigurationWritesUtf8WithRequestIds() throws Exception {
    assertThat(LoggerFactory.getILoggerFactory()).isInstanceOf(LoggerContext.class);
    LoggerContext context = configure(null);
    try {
      var root = context.getLogger(Logger.ROOT_LOGGER_NAME);
      assertThat(root.getAppender("CONSOLE")).isNotNull();
      assertThat(root.getAppender("FILE")).isInstanceOf(RollingFileAppender.class);
      var file = (RollingFileAppender<?>) root.getAppender("FILE");
      assertThat(file.getRollingPolicy()).isInstanceOf(SizeAndTimeBasedRollingPolicy.class);
      var policy = (SizeAndTimeBasedRollingPolicy<?>) file.getRollingPolicy();
      assertThat(policy.getMaxHistory()).isEqualTo(14);
      assertThat(policy.getFileNamePattern()).endsWith("network-aiops.%d{yyyy-MM-dd}.%i.log.gz");

      Logger logger = context.getLogger("com.networkaiops.backend.logging.test");
      context.getMDCAdapter().put("requestId", "java_logging_test");
      logger.info("中文日志验证");
      context.getMDCAdapter().clear();
      logger.warn("request context cleared");
    } finally {
      context.stop();
    }

    String log = Files.readString(directory.resolve("network-aiops.log"), StandardCharsets.UTF_8);
    assertThat(log).contains("中文日志验证", "requestId=java_logging_test");
    assertThat(log).contains("request context cleared", "requestId=internal");
  }

  @Test
  void oversizedLogsRollIntoCompressedArchives() throws Exception {
    LoggerContext context = configure("1KB");
    try {
      Logger logger = context.getLogger("com.networkaiops.backend.logging.test");
      for (int index = 0; index < 50; index++) {
        logger.info("rollover-fixture-{} {}", index, "x".repeat(256));
      }
    } finally {
      // Logback waits for its pending archive compression tasks during shutdown.
      context.stop();
    }
    try (var paths = Files.walk(directory)) {
      var archives = paths.filter(path -> path.toString().endsWith(".log.gz")).toList();
      assertThat(archives).isNotEmpty();
      StringBuilder archived = new StringBuilder();
      for (Path archive : archives) {
        try (var input = new GZIPInputStream(Files.newInputStream(archive))) {
          archived.append(new String(input.readAllBytes(), StandardCharsets.UTF_8));
        }
      }
      assertThat(archived.toString()).contains("rollover-fixture-0");
    }
  }

  private LoggerContext configure(String maxFileSize) throws Exception {
    var environment = new StandardEnvironment();
    environment
        .getPropertySources()
        .addFirst(
            new MapPropertySource(
                "isolated-test", Map.of("AIOPS_JAVA_LOG_PATH", directory.toString())));
    for (var source :
        new YamlPropertySourceLoader()
            .load("application", new ClassPathResource("application.yml"))) {
      environment.getPropertySources().addLast(source);
    }
    var context = new LoggerContext();
    context.setMDCAdapter(new LogbackMDCAdapter());
    context.putProperty("LOG_FILE", environment.getRequiredProperty("logging.file.name"));
    context.putProperty(
        "LOG_LEVEL_PATTERN", environment.getRequiredProperty("logging.pattern.level"));
    context.putProperty("FILE_LOG_CHARSET", "UTF-8");
    context.putProperty("CONSOLE_LOG_THRESHOLD", "OFF");
    for (String property :
        new String[] {
          "file-name-pattern",
          "max-file-size",
          "max-history",
          "total-size-cap",
          "clean-history-on-start"
        }) {
      context.putProperty(
          "LOGBACK_ROLLINGPOLICY_" + property.replace('-', '_').toUpperCase(java.util.Locale.ROOT),
          environment.getRequiredProperty("logging.logback.rollingpolicy." + property));
    }
    if (maxFileSize != null)
      context.putProperty("LOGBACK_ROLLINGPOLICY_MAX_FILE_SIZE", maxFileSize);
    try {
      var configurator = new JoranConfigurator();
      configurator.setContext(context);
      configurator.doConfigure(new ClassPathResource("logback-spring.xml").getURL());
      context.start();
      assertThat(context.getStatusManager().getCopyOfStatusList())
          .noneMatch(status -> status.getLevel() == Status.ERROR);
      return context;
    } catch (Exception | AssertionError failure) {
      context.stop();
      throw failure;
    }
  }
}
