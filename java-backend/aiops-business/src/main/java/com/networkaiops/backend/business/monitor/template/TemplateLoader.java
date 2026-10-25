package com.networkaiops.backend.business.monitor.template;

import java.io.IOException;
import java.io.InputStream;
import java.io.Reader;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.springframework.core.io.Resource;
import org.springframework.stereotype.Component;
import org.yaml.snakeyaml.Yaml;

/**
 * Parses and validates monitor templates. A malformed template aborts startup instead of running
 * half-configured, after HertzBeat's define validation.
 */
@Component
public class TemplateLoader {

  public List<MonitorTemplate> load(List<Resource> resources) {
    List<MonitorTemplate> templates = new ArrayList<>();
    for (Resource resource : resources) {
      templates.add(parse(resource));
    }
    return templates;
  }

  private MonitorTemplate parse(Resource resource) {
    String source = describe(resource);
    Map<String, Object> root = readYaml(resource, source);
    String type = text(root.get("type"), source, "type");
    String name = text(root.get("name"), source, "name");
    String category = text(root.get("category"), source, "category");
    if (!type.matches("[a-z][a-z0-9_]{0,31}"))
      throw invalid(source, "type 必须为小写字母开头的小写字母/数字/下划线，当前: " + type);
    List<ParamTemplate> params = params(root.get("params"), source);
    List<MetricTemplate> metrics = metrics(root.get("metrics"), source, type);
    return new MonitorTemplate(type, name, category, params, metrics);
  }

  private static Map<String, Object> readYaml(Resource resource, String source) {
    try (InputStream stream = resource.getInputStream();
        Reader reader = new java.io.InputStreamReader(stream, StandardCharsets.UTF_8)) {
      Object loaded = new Yaml().load(reader);
      if (!(loaded instanceof Map)) throw invalid(source, "模板必须是 YAML 映射结构。");
      @SuppressWarnings("unchecked")
      Map<String, Object> root = (Map<String, Object>) loaded;
      return root;
    } catch (IOException failure) {
      throw invalid(source, "模板文件无法读取: " + failure.getMessage());
    }
  }

  private List<ParamTemplate> params(Object raw, String source) {
    List<ParamTemplate> params = new ArrayList<>();
    if (!(raw instanceof List<?> entries) || entries.isEmpty()) return params;
    for (Object entry : entries) {
      if (!(entry instanceof Map<?, ?> map)) throw invalid(source, "params 条目必须是映射结构。");
      params.add(
          new ParamTemplate(
              text(map.get("name"), source, "params.name"),
              text(map.get("label"), source, "params.label"),
              Boolean.TRUE.equals(map.get("required"))));
    }
    return params;
  }

  private List<MetricTemplate> metrics(Object raw, String source, String type) {
    if (!(raw instanceof List<?> entries) || entries.isEmpty())
      throw invalid(source, "模板 " + type + " 至少需要定义一个指标。");
    List<MetricTemplate> metrics = new ArrayList<>();
    for (Object entry : entries) {
      if (!(entry instanceof Map<?, ?> map)) throw invalid(source, "metrics 条目必须是映射结构。");
      String id = text(map.get("id"), source, "metrics.id");
      if (metrics.stream().anyMatch(m -> m.id().equals(id)))
        throw invalid(source, "模板 " + type + " 的指标 " + id + " 重复。");
      Double warning = number(map.get("warning"), source, "metrics.warning");
      Double critical = number(map.get("critical"), source, "metrics.critical");
      if (warning != null && critical != null && warning >= critical)
        throw invalid(source, "模板 " + type + " 的指标 " + id + " warning 阈值必须低于 critical。");
      metrics.add(
          new MetricTemplate(
              id,
              text(map.get("unit"), source, "metrics.unit"),
              warning,
              critical,
              Boolean.TRUE.equals(map.get("queryable"))));
    }
    return metrics;
  }

  private static String text(Object value, String source, String field) {
    if (value instanceof String text && !text.isBlank()) return text.strip();
    throw invalid(source, "字段 " + field + " 缺失或为空。");
  }

  private static Double number(Object value, String source, String field) {
    if (value == null) return null;
    if (value instanceof Number number) return number.doubleValue();
    throw invalid(source, "字段 " + field + " 必须是数值。");
  }

  private static String describe(Resource resource) {
    try {
      return resource.getURL().toString();
    } catch (IOException failure) {
      return resource.getDescription();
    }
  }

  private static IllegalStateException invalid(String source, String message) {
    return new IllegalStateException("监控模板无效: " + source + " — " + message);
  }
}
