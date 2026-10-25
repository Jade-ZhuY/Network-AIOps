package com.networkaiops.backend;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;

@SpringBootTest(
    properties = {
      "spring.datasource.url=jdbc:h2:mem:agent-test;DB_CLOSE_DELAY=-1",
      "workspace.agent.enabled=true",
      "workspace.auth.engineer-token=engineer-test-token-123456789012345",
      "workspace.auth.admin-token=admin-test-token-123456789012345"
    })
@AutoConfigureMockMvc
class AgentIntegrationTest {
  private static final HttpServer UPSTREAM;
  private static final AtomicInteger SESSIONS = new AtomicInteger();
  private static final AtomicInteger CHATS = new AtomicInteger();
  private static volatile String mode = "ok";

  static {
    try {
      UPSTREAM = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
      UPSTREAM.createContext(
          "/api/v1/",
          exchange -> {
            String path = exchange.getRequestURI().getPath();
            exchange.getRequestBody().readAllBytes();
            int status = 200;
            String body;
            if (path.endsWith("/me")) {
              String authorization = exchange.getRequestHeaders().getFirst("Authorization");
              boolean admin =
                  authorization != null
                      && authorization.contains(BusinessApiTest.ADMIN.substring(7));
              body =
                  "{\"user_id\":\""
                      + (mode.equals("mismatch")
                          ? "other-user"
                          : admin ? "netops-admin" : "netops-engineer")
                      + "\",\"role\":\""
                      + (admin && !mode.equals("mismatch") ? "admin" : "engineer")
                      + "\",\"tenant_id\":\"demo-tenant\",\"scope\":{\"tenant_id\":\"demo-tenant\",\"device_ids\":[1,2,3,4],\"knowledge_groups\":[\"netops\"]}}";
            } else if (path.endsWith("/sessions")) {
              SESSIONS.incrementAndGet();
              status = 201;
              body = "{\"session_id\":\"upstream-session\"}";
            } else {
              CHATS.incrementAndGet();
              body =
                  "{\"request_id\":\"req_upstream\",\"session_id\":\"upstream-session\",\"status\":\"completed\",\"report\":{\"summary\":\"Explicit upstream integration fixture\"}}";
            }
            if (mode.equals("error")) {
              status = 503;
              body = "{\"detail\":\"SECRET_RAW_UPSTREAM_ERROR\"}";
            }
            if (mode.equals("invalid")) body = "<html>invalid response</html>";
            byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(status, bytes.length);
            exchange.getResponseBody().write(bytes);
            exchange.close();
          });
      UPSTREAM.start();
    } catch (Exception error) {
      throw new ExceptionInInitializerError(error);
    }
  }

  @DynamicPropertySource
  static void properties(DynamicPropertyRegistry registry) {
    registry.add(
        "workspace.agent.base-url", () -> "http://127.0.0.1:" + UPSTREAM.getAddress().getPort());
  }

  @AfterAll
  static void shutdown() {
    UPSTREAM.stop(0);
  }

  @Autowired MockMvc mvc;
  @Autowired ObjectMapper mapper;
  @Autowired JdbcTemplate jdbc;

  @BeforeEach
  void clean() {
    mode = "ok";
    SESSIONS.set(0);
    CHATS.set(0);
    jdbc.update("DELETE FROM ticket_analyses");
    jdbc.update("DELETE FROM audit_events");
    jdbc.update("DELETE FROM tickets");
  }

  String create() throws Exception {
    return mapper
        .readTree(
            mvc.perform(
                    post("/api/v1/tickets")
                        .header("Authorization", BusinessApiTest.ENGINEER)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(
                            "{\"title\":\"Agent 接入测试\",\"device\":\"R2\",\"description\":\"显式测试上游模型接口，不调用真实付费服务。\",\"priority\":\"MEDIUM\"}"))
                .andExpect(status().isCreated())
                .andReturn()
                .getResponse()
                .getContentAsString())
        .path("id")
        .asText();
  }

  @Test
  void acceptsQueuesAndPersistsActualUpstreamReport() throws Exception {
    String id = create();
    mvc.perform(
            post("/api/v1/tickets/" + id + "/analyses")
                .header("Authorization", BusinessApiTest.ENGINEER)
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"version\":0}"))
        .andExpect(status().isAccepted())
        .andExpect(jsonPath("status").value("RUNNING"));
    String terminal = awaitAnalysis(id);
    assertThat(terminal).contains("\"SUCCEEDED\"");
    assertThat(terminal).contains("req_upstream");
    assertThat(terminal).contains("Explicit upstream integration fixture");
    mvc.perform(get("/api/v1/tickets/" + id).header("Authorization", BusinessApiTest.ENGINEER))
        .andExpect(jsonPath("status").value("OPEN"))
        .andExpect(jsonPath("version").value(2))
        .andExpect(jsonPath("agent_session_id").value("upstream-session"));
    assertThat(SESSIONS.get()).isEqualTo(1);
    assertThat(CHATS.get()).isEqualTo(1);
  }

  /** The 202 contract means completion is only observable through the stored record. */
  private String awaitAnalysis(String id) throws Exception {
    long deadline = System.currentTimeMillis() + 15_000;
    String body = "";
    while (System.currentTimeMillis() < deadline) {
      body =
          mvc.perform(
                  get("/api/v1/tickets/" + id + "/analyses")
                      .header("Authorization", BusinessApiTest.ENGINEER))
              .andExpect(status().isOk())
              .andReturn()
              .getResponse()
              .getContentAsString();
      if (body.contains("\"SUCCEEDED\"") || body.contains("\"FAILED\"")) return body;
      Thread.sleep(100);
    }
    return body;
  }

  @Test
  void agentStatusRegistryTracksLastRealCall() throws Exception {
    mvc.perform(get("/api/v1/agent/status")).andExpect(status().isUnauthorized());
    String id = create();
    mvc.perform(
            post("/api/v1/tickets/" + id + "/analyses")
                .header("Authorization", BusinessApiTest.ENGINEER)
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"version\":0}"))
        .andExpect(status().isAccepted());
    awaitAnalysis(id);
    mvc.perform(get("/api/v1/agent/status").header("Authorization", BusinessApiTest.ENGINEER))
        .andExpect(status().isOk())
        .andExpect(jsonPath("enabled").value(true))
        .andExpect(jsonPath("health").value("online"))
        .andExpect(jsonPath("last_outcome").value("ok"));
    mvc.perform(get("/api/v1/health")).andExpect(jsonPath("agent_status").value("online"));
  }

  @Test
  void knowledgeMutationsAreAuditedOnTheJavaSide() throws Exception {
    mvc.perform(
            multipart("/api/v1/knowledge/documents")
                .file(
                    new org.springframework.mock.web.MockMultipartFile(
                        "file",
                        "handbook.txt",
                        "text/plain",
                        "demo manual".getBytes(StandardCharsets.UTF_8)))
                .param("title", "Network Disposal Manual")
                .header("Authorization", BusinessApiTest.ADMIN))
        .andExpect(status().isOk());
    mvc.perform(
            post("/api/v1/knowledge/reindex")
                .header("Authorization", BusinessApiTest.ADMIN)
                .contentType(MediaType.APPLICATION_JSON)
                .content("{}"))
        .andExpect(status().isOk());
    mvc.perform(
            post("/api/v1/knowledge/reindex")
                .header("Authorization", BusinessApiTest.ENGINEER)
                .contentType(MediaType.APPLICATION_JSON)
                .content("{}"))
        .andExpect(status().isForbidden());
    mode = "error";
    mvc.perform(
            post("/api/v1/knowledge/reindex")
                .header("Authorization", BusinessApiTest.ADMIN)
                .contentType(MediaType.APPLICATION_JSON)
                .content("{}"))
        .andExpect(status().isBadGateway());
    String auditBody =
        mvc.perform(get("/api/v1/admin/audit").header("Authorization", BusinessApiTest.ADMIN))
            .andExpect(status().isOk())
            .andReturn()
            .getResponse()
            .getContentAsString();
    assertThat(auditBody).contains("KNOWLEDGE_DOCUMENT_UPLOADED");
    assertThat(auditBody).contains("KNOWLEDGE_REINDEXED");
    assertThat(
            jdbc.queryForObject(
                "SELECT COUNT(*) FROM audit_events WHERE action LIKE 'KNOWLEDGE_%'", Integer.class))
        .isEqualTo(3);
    assertThat(
            jdbc.queryForObject(
                "SELECT COUNT(*) FROM audit_events WHERE action='KNOWLEDGE_DOCUMENT_UPLOADED'"
                    + " AND note LIKE '%Network Disposal Manual%'",
                Integer.class))
        .isEqualTo(1);
    assertThat(
            jdbc.queryForObject(
                "SELECT COUNT(*) FROM audit_events WHERE action='KNOWLEDGE_REINDEXED'"
                    + " AND outcome='failed'",
                Integer.class))
        .isEqualTo(1);
  }

  @Test
  void rejectsIdentityMismatchBeforeSendingQuestion() throws Exception {
    String id = create();
    mode = "mismatch";
    mvc.perform(
            post("/api/v1/tickets/" + id + "/analyses")
                .header("Authorization", BusinessApiTest.ENGINEER)
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"version\":0}"))
        .andExpect(status().isBadGateway())
        .andExpect(jsonPath("code").value("agent_identity_mismatch"));
    assertThat(CHATS.get()).isZero();
    mvc.perform(get("/api/v1/tickets/" + id).header("Authorization", BusinessApiTest.ENGINEER))
        .andExpect(jsonPath("analysis_status").value("FAILED"));
  }

  @Test
  void upstreamErrorsAreSanitizedAndDoNotDisableBusiness() throws Exception {
    String id = create();
    mode = "error";
    String response =
        mvc.perform(
                post("/api/v1/tickets/" + id + "/analyses")
                    .header("Authorization", BusinessApiTest.ENGINEER)
                    .contentType(MediaType.APPLICATION_JSON)
                    .content("{\"version\":0}"))
            .andExpect(status().isBadGateway())
            .andReturn()
            .getResponse()
            .getContentAsString();
    assertThat(response).doesNotContain("SECRET_RAW_UPSTREAM_ERROR");
    mvc.perform(get("/api/v1/business/overview").header("Authorization", BusinessApiTest.ENGINEER))
        .andExpect(status().isOk())
        .andExpect(jsonPath("total").value(1));
  }

  @Test
  void relayUsesExplicitAllowlistAndRejectsInvalidJson() throws Exception {
    mvc.perform(
            get("/api/v1/not-an-agent-endpoint").header("Authorization", BusinessApiTest.ENGINEER))
        .andExpect(status().isNotFound());
    mode = "invalid";
    mvc.perform(get("/api/v1/sessions").header("Authorization", BusinessApiTest.ENGINEER))
        .andExpect(status().isBadGateway())
        .andExpect(jsonPath("code").value("agent_invalid_response"));
  }
}
