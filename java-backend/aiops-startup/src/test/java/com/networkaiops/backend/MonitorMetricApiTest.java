package com.networkaiops.backend;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

@SpringBootTest(
    properties = {
      "spring.datasource.url=jdbc:h2:mem:business-test;DB_CLOSE_DELAY=-1",
      "workspace.agent.enabled=false",
      "workspace.auth.engineer-token=engineer-test-token-123456789012345",
      "workspace.auth.admin-token=admin-test-token-123456789012345"
    })
@AutoConfigureMockMvc
class MonitorMetricApiTest {
  static final String ENGINEER = "Bearer engineer-test-token-123456789012345";

  @Autowired MockMvc mvc;
  @Autowired ObjectMapper mapper;
  @Autowired JdbcTemplate jdbc;

  @BeforeEach
  void clean() {
    jdbc.update("DELETE FROM network_metrics");
    jdbc.update("DELETE FROM network_interfaces");
    jdbc.update("DELETE FROM network_devices");
    jdbc.update("DELETE FROM monitor");
    jdbc.update(
        "INSERT INTO network_devices(device_id,hostname,device_type,region,tenant_id,status)"
            + " VALUES (11,'core-sw-1','switch','north','netops','ACTIVE')");
    jdbc.update(
        "INSERT INTO network_interfaces(interface_id,device_id,interface_name) VALUES (5,11,'eth0')");
    jdbc.update(
        "INSERT INTO network_metrics(metric_id,device_id,interface_id,sample_time,latency_ms,"
            + "packet_loss_pct,utilization_pct) VALUES (1,11,5,'2026-10-01 10:00:00',12.5,0.2,40.0)");
    jdbc.update(
        "INSERT INTO network_metrics(metric_id,device_id,interface_id,sample_time,latency_ms,"
            + "packet_loss_pct,utilization_pct) VALUES (2,11,5,'2026-10-01 10:05:00',18.0,0.4,55.0)");
    jdbc.update(
        "INSERT INTO network_metrics(metric_id,device_id,interface_id,sample_time,latency_ms,"
            + "packet_loss_pct,utilization_pct) VALUES (3,11,NULL,'2026-10-01 10:10:00',30.0,NULL,70.0)");
  }

  @Test
  void templatesAreServedFromYamlDefinitions() throws Exception {
    mvc.perform(get("/api/v1/monitor-templates").header("Authorization", ENGINEER))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.length()").value(3))
        .andExpect(jsonPath("$[?(@.type == 'switch')].name").value("交换机"));
    mvc.perform(get("/api/v1/monitor-templates/switch").header("Authorization", ENGINEER))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.metrics.length()").value(3))
        .andExpect(jsonPath("$.metrics[?(@.id == 'latency_ms')].warning").value(50.0));
    mvc.perform(get("/api/v1/monitor-templates/unknown").header("Authorization", ENGINEER))
        .andExpect(status().isNotFound());
  }

  @Test
  void monitorCrudScopesByWorkspaceAndAudits() throws Exception {
    JsonNode created = createMonitor("core-sw-1");
    assertThat(created.get("status").asText()).isEqualTo("UNKNOWN");
    assertThat(created.get("template_name").asText()).isEqualTo("交换机");

    mvc.perform(
            get("/api/v1/monitors/" + created.get("id").asText()).header("Authorization", ENGINEER))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.hostname").value("core-sw-1"));

    mvc.perform(
            put("/api/v1/monitors/" + created.get("id").asText())
                .header("Authorization", ENGINEER)
                .contentType(MediaType.APPLICATION_JSON)
                .content(
                    """
                    {"version":0,"name":"核心交换机一号","type":"switch","hostname":"core-sw-1",
                     "labels":["core","north"],"description":"核心层"}
                    """))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.version").value(1))
        .andExpect(jsonPath("$.labels.length()").value(2));

    Integer audited =
        jdbc.queryForObject(
            "SELECT COUNT(*) FROM audit_events WHERE resource_id = ? AND action = 'MONITOR_UPDATED'",
            Integer.class,
            created.get("id").asText());
    assertThat(audited).isEqualTo(1);

    mvc.perform(
            delete("/api/v1/monitors/" + created.get("id").asText())
                .queryParam("version", "1")
                .header("Authorization", ENGINEER))
        .andExpect(status().isNoContent());
    mvc.perform(
            get("/api/v1/monitors/" + created.get("id").asText()).header("Authorization", ENGINEER))
        .andExpect(status().isNotFound());
  }

  @Test
  void createRejectsUnknownTemplateTypeAndBadLabelCount() throws Exception {
    mvc.perform(
            post("/api/v1/monitors")
                .header("Authorization", ENGINEER)
                .contentType(MediaType.APPLICATION_JSON)
                .content(
                    """
                    {"name":"任意设备","type":"firewall","hostname":"fw-1"}
                    """))
        .andExpect(status().isNotFound());
    mvc.perform(
            post("/api/v1/monitors")
                .header("Authorization", ENGINEER)
                .contentType(MediaType.APPLICATION_JSON)
                .content(
                    """
                    {"name":"任意设备","type":"server","hostname":"app-1",
                     "labels":["1","2","3","4","5","6","7","8","9","10","11"]}
                    """))
        .andExpect(status().isUnprocessableEntity());
  }

  @Test
  void unauthenticatedRequestsAreRejected() throws Exception {
    mvc.perform(get("/api/v1/monitors")).andExpect(status().isUnauthorized());
    mvc.perform(get("/api/v1/metric-definitions")).andExpect(status().isUnauthorized());
  }

  @Test
  void metricDefinitionsAggregateAcrossTemplates() throws Exception {
    mvc.perform(get("/api/v1/metric-definitions").header("Authorization", ENGINEER))
        .andExpect(status().isOk())
        .andExpect(
            jsonPath("$.definitions[?(@.id == 'packet_loss_pct')].device_types.length()").value(2))
        .andExpect(
            jsonPath("$.definitions[?(@.id == 'latency_ms')].device_types.length()").value(3));
  }

  @Test
  void seriesReturnsPointsHonoringNullPolicy() throws Exception {
    JsonNode monitor = createMonitor("core-sw-1");
    String id = monitor.get("id").asText();
    mvc.perform(
            get("/api/v1/monitors/" + id + "/metrics/latency_ms/series")
                .queryParam("start", "2026-10-01T00:00:00Z")
                .queryParam("end", "2026-10-02T00:00:00Z")
                .header("Authorization", ENGINEER))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.metric_id").value("latency_ms"))
        .andExpect(jsonPath("$.no_data").value(false))
        .andExpect(jsonPath("$.points.length()").value(3))
        .andExpect(jsonPath("$.points[0].value").value(12.5))
        .andExpect(jsonPath("$.points[0].interface_name").value("eth0"))
        .andExpect(jsonPath("$.points[2].interface_name").doesNotExist());

    mvc.perform(
            get("/api/v1/monitors/" + id + "/metrics/packet_loss_pct/series")
                .queryParam("start", "2026-10-01T00:00:00Z")
                .queryParam("end", "2026-10-02T00:00:00Z")
                .header("Authorization", ENGINEER))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.points.length()").value(2))
        .andExpect(jsonPath("$.no_data").value(false));

    mvc.perform(
            get("/api/v1/monitors/" + id + "/metrics/latency_ms/series")
                .queryParam("start", "2025-01-01T00:00:00Z")
                .queryParam("end", "2025-01-02T00:00:00Z")
                .header("Authorization", ENGINEER))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.no_data").value(true))
        .andExpect(jsonPath("$.points.length()").value(0));
  }

  @Test
  void seriesValidatesWindowMetricAndInterfaceFilter() throws Exception {
    JsonNode monitor = createMonitor("core-sw-1");
    String id = monitor.get("id").asText();

    mvc.perform(
            get("/api/v1/monitors/" + id + "/metrics/latency_ms/series")
                .queryParam("start", "2026-01-01T00:00:00Z")
                .queryParam("end", "2026-03-01T00:00:00Z")
                .header("Authorization", ENGINEER))
        .andExpect(status().isUnprocessableEntity());

    mvc.perform(
            get("/api/v1/monitors/" + id + "/metrics/unknown_metric/series")
                .queryParam("start", "2026-10-01T00:00:00Z")
                .queryParam("end", "2026-10-02T00:00:00Z")
                .header("Authorization", ENGINEER))
        .andExpect(status().isNotFound());

    mvc.perform(
            get("/api/v1/monitors/" + id + "/metrics/latency_ms/series")
                .queryParam("start", "2026-10-01T00:00:00Z")
                .queryParam("end", "2026-10-02T00:00:00Z")
                .queryParam("interface", "eth0")
                .header("Authorization", ENGINEER))
        .andExpect(status().isOk())
        .andExpect(jsonPath("$.points.length()").value(2));
  }

  private JsonNode createMonitor(String hostname) throws Exception {
    MvcResult result =
        mvc.perform(
                post("/api/v1/monitors")
                    .header("Authorization", ENGINEER)
                    .contentType(MediaType.APPLICATION_JSON)
                    .content(
                        """
                        {"name":"核心交换机","type":"switch","hostname":"%s",
                         "labels":["core"],"description":"核心层交换机"}
                        """
                            .formatted(hostname)))
            .andExpect(status().isCreated())
            .andReturn();
    return mapper.readTree(result.getResponse().getContentAsString());
  }
}
