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

@SpringBootTest(
    properties = {
      "logging.file.name=target/test-logs/network-aiops.log",
      "logging.logback.rollingpolicy.file-name-pattern=target/test-logs/archive/network-aiops.%d{yyyy-MM-dd}.%i.log.gz",
      "spring.datasource.url=jdbc:h2:mem:business-test;DB_CLOSE_DELAY=-1",
      "workspace.agent.enabled=false",
      "workspace.auth.engineer-token=engineer-test-token-123456789012345",
      "workspace.auth.admin-token=admin-test-token-123456789012345"
    })
@AutoConfigureMockMvc
class BusinessApiTest {
  static final String ENGINEER = "Bearer engineer-test-token-123456789012345";
  static final String ADMIN = "Bearer admin-test-token-123456789012345";
  @Autowired MockMvc mvc;
  @Autowired ObjectMapper mapper;
  @Autowired JdbcTemplate jdbc;

  @BeforeEach
  void clean() {
    jdbc.update("DELETE FROM ticket_analyses");
    jdbc.update("DELETE FROM audit_events");
    jdbc.update("DELETE FROM tickets");
  }

  JsonNode create() throws Exception {
    String json =
        mvc.perform(
                post("/api/v1/tickets")
                    .header("Authorization", ENGINEER)
                    .contentType(MediaType.APPLICATION_JSON)
                    .content(
                        """
                        {"title":"R2 网络异常咨询","device":"R2","description":"R2 最近出现多次链路异常，请核查相关记录。","priority":"HIGH"}
                        """))
            .andExpect(status().isCreated())
            .andExpect(jsonPath("code").value(1))
            .andExpect(jsonPath("msg").value("success"))
            .andExpect(jsonPath("data.status").value("OPEN"))
            .andExpect(jsonPath("data.version").value(0))
            .andReturn()
            .getResponse()
            .getContentAsString();
    return mapper.readTree(json).path("data");
  }

  @Test
  void authorizationAndPublicHealth() throws Exception {
    mvc.perform(get("/api/v1/health"))
        .andExpect(status().isOk())
        .andExpect(jsonPath("code").value(1))
        .andExpect(jsonPath("data.backend").value("java"))
        .andExpect(jsonPath("data.agent_status").value("disabled"));
    mvc.perform(get("/api/v1/me")).andExpect(status().isUnauthorized());
    mvc.perform(get("/api/v1/me").header("Authorization", "Bearer invalid"))
        .andExpect(status().isUnauthorized())
        .andExpect(jsonPath("code").value(0))
        .andExpect(jsonPath("msg").value("访问令牌无效，请重新登录。"));
    mvc.perform(get("/api/v1/me").header("Authorization", ENGINEER))
        .andExpect(status().isOk())
        .andExpect(jsonPath("data.user_id").value("netops-engineer"));
    mvc.perform(get("/api/v1/agent/status")).andExpect(status().isUnauthorized());
    mvc.perform(get("/api/v1/agent/status").header("Authorization", ENGINEER))
        .andExpect(status().isOk())
        .andExpect(jsonPath("data.enabled").value(false))
        .andExpect(jsonPath("data.health").value("disabled"));
    mvc.perform(get("/api/v1/admin/audit").header("Authorization", ENGINEER))
        .andExpect(status().isForbidden());
    mvc.perform(get("/api/v1/admin/audit").header("Authorization", ADMIN))
        .andExpect(status().isOk());
  }

  @Test
  void resultContractUsesExactlyCodeMsgDataAndPreservesHttpStatuses() throws Exception {
    var success =
        mvc.perform(get("/api/v1/health"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("code").value(1))
            .andExpect(jsonPath("msg").value("success"))
            .andExpect(header().exists("X-Request-ID"))
            .andReturn()
            .getResponse();
    assertThat(mapper.readTree(success.getContentAsString()).size()).isEqualTo(3);

    var failure =
        mvc.perform(get("/api/v1/me").header("Authorization", "Bearer invalid"))
            .andExpect(status().isUnauthorized())
            .andExpect(header().exists("X-Request-ID"))
            .andReturn()
            .getResponse();
    assertThat(mapper.readTree(failure.getContentAsString()))
        .isEqualTo(
            mapper.readTree(
                """
            {"code":0,"msg":"访问令牌无效，请重新登录。","data":null}
            """));

    mvc.perform(get("/api/v1/admin/audit").header("Authorization", ENGINEER))
        .andExpect(status().isForbidden())
        .andExpect(jsonPath("code").value(0))
        .andExpect(jsonPath("msg").value("当前身份没有此操作权限。"));
    mvc.perform(post("/api/v1/me").header("Authorization", ENGINEER))
        .andExpect(status().isMethodNotAllowed())
        .andExpect(jsonPath("code").value(0))
        .andExpect(jsonPath("msg").value("该接口不支持此 HTTP 方法。"));
  }

  @Test
  void createsUpdatesChecksVersionAndScopesOwnership() throws Exception {
    JsonNode row = create();
    String id = row.path("id").asText();
    mvc.perform(get("/api/v1/business/overview").header("Authorization", ENGINEER))
        .andExpect(status().isOk())
        .andExpect(jsonPath("data.total").value(1));
    mvc.perform(get("/api/v1/tickets/" + id).header("Authorization", ADMIN))
        .andExpect(status().isNotFound());
    mvc.perform(get("/api/v1/tickets").header("Authorization", ADMIN))
        .andExpect(jsonPath("data.total").value(0));
    String update =
        """
            {"version":0,"title":"R2 异常已复核","device":"R2 / eth1","description":"已检查接口指标，继续核对相关告警与业务口径。","priority":"CRITICAL"}
            """;
    mvc.perform(
            put("/api/v1/tickets/" + id)
                .header("Authorization", ENGINEER)
                .contentType(MediaType.APPLICATION_JSON)
                .content(update))
        .andExpect(status().isOk())
        .andExpect(jsonPath("data.version").value(1))
        .andExpect(jsonPath("data.priority").value("CRITICAL"));
    mvc.perform(
            put("/api/v1/tickets/" + id)
                .header("Authorization", ENGINEER)
                .contentType(MediaType.APPLICATION_JSON)
                .content(update))
        .andExpect(status().isConflict())
        .andExpect(jsonPath("code").value(0))
        .andExpect(jsonPath("msg").value("记录已被修改，请刷新后重试。"));
    mvc.perform(get("/api/v1/tickets").header("Authorization", ENGINEER).param("q", "%' OR 1=1 --"))
        .andExpect(status().isOk())
        .andExpect(jsonPath("data.total").value(0));
    mvc.perform(get("/api/v1/tickets").header("Authorization", ENGINEER).param("q", "eth1"))
        .andExpect(jsonPath("data.total").value(1));
  }

  @Test
  void enforcesTransitionsAndPreservesHandlingNotes() throws Exception {
    String id = create().path("id").asText();
    mvc.perform(
            patch("/api/v1/tickets/" + id + "/status")
                .header("Authorization", ENGINEER)
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"version\":0,\"status\":\"RESOLVED\",\"note\":\"尝试跳过处理直接完成\"}"))
        .andExpect(status().isConflict());
    mvc.perform(
            patch("/api/v1/tickets/" + id + "/status")
                .header("Authorization", ENGINEER)
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"version\":0,\"status\":\"IN_PROGRESS\",\"note\":\"已检查接口状态，继续排查。\"}"))
        .andExpect(status().isOk())
        .andExpect(jsonPath("data.version").value(1))
        .andExpect(jsonPath("data.status").value("IN_PROGRESS"));
    mvc.perform(get("/api/v1/tickets/" + id + "/events").header("Authorization", ENGINEER))
        .andExpect(status().isOk())
        .andExpect(jsonPath("data.events[0].note").value("已检查接口状态，继续排查。"));
    mvc.perform(
            delete("/api/v1/tickets/" + id).header("Authorization", ENGINEER).param("version", "1"))
        .andExpect(status().isNoContent());
    mvc.perform(get("/api/v1/tickets/" + id).header("Authorization", ENGINEER))
        .andExpect(status().isNotFound());
    assertThat(jdbc.queryForObject("SELECT deleted FROM tickets WHERE id=?", Boolean.class, id))
        .isTrue();
    assertThat(
            jdbc.queryForObject(
                "SELECT COUNT(*) FROM audit_events WHERE ticket_id=?", Integer.class, id))
        .isEqualTo(3);
  }

  @Test
  void validationAndMissingVersionProduceClientErrors() throws Exception {
    mvc.perform(
            post("/api/v1/tickets")
                .header("Authorization", ENGINEER)
                .contentType(MediaType.APPLICATION_JSON)
                .content("{}"))
        .andExpect(status().isUnprocessableEntity())
        .andExpect(jsonPath("code").value(0))
        .andExpect(jsonPath("msg").isNotEmpty());
    mvc.perform(
            post("/api/v1/tickets")
                .header("Authorization", ENGINEER)
                .contentType(MediaType.APPLICATION_JSON)
                .content(
                    "{\"title\":\"测试标题\",\"device\":\"R2\",\"description\":\"这是一条合法的测试描述信息\",\"priority\":\"HIGH\",\"owner_id\":\"other\"}"))
        .andExpect(status().isUnprocessableEntity());
    mvc.perform(get("/api/v1/tickets").header("Authorization", ENGINEER).param("limit", "101"))
        .andExpect(status().isUnprocessableEntity());
    mvc.perform(get("/api/v1/tickets").header("Authorization", ENGINEER).param("offset", "-1"))
        .andExpect(status().isUnprocessableEntity());
    mvc.perform(delete("/api/v1/tickets/missing").header("Authorization", ENGINEER))
        .andExpect(status().isUnprocessableEntity());
  }

  @Test
  void disabledAgentNeverCreatesFabricatedAnalysis() throws Exception {
    String id = create().path("id").asText();
    mvc.perform(
            post("/api/v1/tickets/" + id + "/analyses")
                .header("Authorization", ENGINEER)
                .contentType(MediaType.APPLICATION_JSON)
                .content("{\"version\":0}"))
        .andExpect(status().isServiceUnavailable())
        .andExpect(jsonPath("msg").value("Agent 服务尚未启用；Java 业务功能可正常使用，待 Python 服务就绪后再配置连接。"));
    mvc.perform(get("/api/v1/tickets/" + id).header("Authorization", ENGINEER))
        .andExpect(jsonPath("data.analysis_status").value("NOT_STARTED"));
    mvc.perform(get("/api/v1/tickets/" + id + "/analyses").header("Authorization", ENGINEER))
        .andExpect(jsonPath("data.analyses.length()").value(0));
    mvc.perform(
            post("/api/v1/chat")
                .header("Authorization", ENGINEER)
                .contentType(MediaType.APPLICATION_JSON)
                .content("{}"))
        .andExpect(status().isServiceUnavailable())
        .andExpect(jsonPath("msg").value("Agent 服务尚未启用；Java 业务功能可正常使用，待 Python 服务就绪后再配置连接。"));
  }
}
