package com.networkaiops.backend.business.monitor.template;

import java.io.IOException;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.beans.factory.InitializingBean;
import org.springframework.core.io.Resource;
import org.springframework.core.io.support.PathMatchingResourcePatternResolver;
import org.springframework.stereotype.Component;

/**
 * In-memory registry of every monitor template on the classpath. Loaded once at startup; a bad
 * template fails the boot. Instances reference templates by type name, so template metadata never
 * needs row-level synchronization with the database.
 */
@Component
public class TemplateRegistry implements InitializingBean {
  private final TemplateLoader loader;
  private final Map<String, MonitorTemplate> templates = new LinkedHashMap<>();

  public TemplateRegistry(TemplateLoader loader) {
    this.loader = loader;
  }

  @Override
  public void afterPropertiesSet() throws IOException {
    try {
      Resource[] resources =
          new PathMatchingResourcePatternResolver()
              .getResources("classpath*:templates/monitor/*.yml");
      for (MonitorTemplate template : loader.load(List.of(resources))) {
        if (templates.put(template.type(), template) != null)
          throw new IllegalStateException("监控模板类型重复: " + template.type());
      }
    } catch (IOException failure) {
      throw new IllegalStateException("监控模板目录无法读取。", failure);
    }
    if (templates.isEmpty())
      throw new IllegalStateException("未找到任何监控模板，请检查 templates/monitor/ 目录。");
  }

  public Collection<MonitorTemplate> all() {
    return templates.values();
  }

  public MonitorTemplate require(String type) {
    MonitorTemplate template = templates.get(type);
    if (template == null)
      throw new com.networkaiops.backend.common.exception.BusinessException(
          404, "unknown_monitor_type", "监控类型不存在或未注册: " + type);
    return template;
  }

  public MonitorTemplate find(String type) {
    return templates.get(type);
  }
}
