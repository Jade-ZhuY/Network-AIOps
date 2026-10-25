package com.networkaiops.backend.business.monitor.template;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.nio.charset.StandardCharsets;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.core.io.ByteArrayResource;

class TemplateLoaderTest {
  private static final String VALID =
      """
      type: switch
      name: 交换机
      category: network
      params:
        - { name: hostname, label: 设备主机名, required: true }
      metrics:
        - { id: packet_loss_pct, unit: "%", warning: 5, critical: 20, queryable: true }
        - { id: latency_ms, unit: "ms", warning: 50, critical: 200, queryable: true }
      """;

  private final TemplateLoader loader = new TemplateLoader();

  @Test
  void parsesValidTemplateWithMetricsAndThresholds() {
    MonitorTemplate template = loader.load(List.of(resource("switch.yml", VALID))).getFirst();
    assertThat(template.type()).isEqualTo("switch");
    assertThat(template.name()).isEqualTo("交换机");
    assertThat(template.params()).hasSize(1);
    assertThat(template.params().getFirst().required()).isTrue();
    assertThat(template.metrics()).hasSize(2);
    assertThat(template.metric("latency_ms").warning()).isEqualTo(50.0);
    assertThat(template.metric("latency_ms").critical()).isEqualTo(200.0);
    assertThat(template.metric("latency_ms").queryable()).isTrue();
  }

  @Test
  void rejectsInvalidTypeName() {
    String yaml = VALID.replace("type: switch", "type: Core-Switch");
    assertThatThrownBy(() -> loader.load(List.of(resource("bad.yml", yaml))))
        .isInstanceOf(IllegalStateException.class)
        .hasMessageContaining("type");
  }

  @Test
  void rejectsEmptyMetrics() {
    String yaml =
        """
        type: switch
        name: 交换机
        category: network
        metrics: []
        """;
    assertThatThrownBy(() -> loader.load(List.of(resource("empty.yml", yaml))))
        .isInstanceOf(IllegalStateException.class)
        .hasMessageContaining("至少需要定义一个指标");
  }

  @Test
  void rejectsThresholdsOutOfOrder() {
    String yaml = VALID.replace("warning: 5, critical: 20", "warning: 30, critical: 20");
    assertThatThrownBy(() -> loader.load(List.of(resource("swap.yml", yaml))))
        .isInstanceOf(IllegalStateException.class)
        .hasMessageContaining("warning 阈值必须低于 critical");
  }

  @Test
  void rejectsDuplicateMetricIds() {
    String yaml = VALID.replace("id: latency_ms", "id: packet_loss_pct");
    assertThatThrownBy(() -> loader.load(List.of(resource("dup.yml", yaml))))
        .isInstanceOf(IllegalStateException.class)
        .hasMessageContaining("重复");
  }

  private static ByteArrayResource resource(String filename, String content) {
    return new ByteArrayResource(content.getBytes(StandardCharsets.UTF_8)) {
      @Override
      public String getFilename() {
        return filename;
      }
    };
  }
}
