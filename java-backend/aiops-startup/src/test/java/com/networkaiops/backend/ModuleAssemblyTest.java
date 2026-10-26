package com.networkaiops.backend;

import static org.assertj.core.api.Assertions.assertThat;

import com.networkaiops.backend.agent.client.AgentClient;
import com.networkaiops.backend.business.ticket.TicketService;
import com.networkaiops.backend.common.context.RequestContext;
import com.networkaiops.backend.common.spring.web.RequestIdFilter;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.HexFormat;
import org.junit.jupiter.api.Test;

class ModuleAssemblyTest {
  @Test
  void productionClassesComeFromFiveSeparateReactorArtifacts() {
    assertArtifact(RequestContext.class, "aiops-common-core");
    assertArtifact(RequestIdFilter.class, "aiops-common-spring");
    assertArtifact(AgentClient.class, "aiops-agent-client");
    assertArtifact(TicketService.class, "aiops-business");
    assertArtifact(BusinessApplication.class, "aiops-startup");
  }

  @Test
  void v1MigrationsAreDiscoveredExactlyOncePerVendorFromBusiness() throws Exception {
    assertSingleMigration(
        "db/migration/h2/V1__business_schema.sql",
        "42782e6abf42be143309cb3752e71f76c97e9ae3766d822f63ebdb7d9631937b");
    assertSingleMigration(
        "db/migration/mysql/V1__business_schema.sql",
        "71d0f81797712d6a2bb97f46e714194e8a695cb5c43a2d33850dcd2fdd765d81");
  }

  private static void assertSingleMigration(String path, String expectedDigest) throws Exception {
    var resources = Collections.list(ModuleAssemblyTest.class.getClassLoader().getResources(path));
    assertThat(resources).hasSize(1);
    assertThat(resources.getFirst().toString()).contains("aiops-business");
    try (var stream = resources.getFirst().openStream()) {
      // Git may check out CRLF on Windows. Compare the canonical LF content, like a
      // source migration contract, without rewriting the actual migration resource.
      byte[] canonical =
          new String(stream.readAllBytes(), StandardCharsets.UTF_8)
              .replace("\r\n", "\n")
              .getBytes(StandardCharsets.UTF_8);
      String digest =
          HexFormat.of()
              .formatHex(java.security.MessageDigest.getInstance("SHA-256").digest(canonical));
      assertThat(digest).isEqualTo(expectedDigest);
    }
  }

  @Test
  void applicationConfigurationIsOwnedOnlyByStartup() throws Exception {
    for (String name : new String[] {"application.yml", "logback-spring.xml"}) {
      var resources = Collections.list(getClass().getClassLoader().getResources(name));
      assertThat(resources).hasSize(1);
      assertThat(resources.getFirst().toString()).contains("aiops-startup");
    }
  }

  private static void assertArtifact(Class<?> type, String module) {
    assertThat(type.getProtectionDomain().getCodeSource().getLocation().toString())
        .contains("/" + module + "/");
  }
}
