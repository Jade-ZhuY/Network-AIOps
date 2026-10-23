package com.networkaiops.backend.config;

import java.nio.file.Path;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.ResourceHandlerRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

@Configuration
public class StaticWebConfig implements WebMvcConfigurer {
  private final Path root;

  public StaticWebConfig(@Value("${workspace.frontend-path}") String path) {
    root = Path.of(path).toAbsolutePath().normalize();
  }

  @Override
  public void addResourceHandlers(ResourceHandlerRegistry registry) {
    registry
        .addResourceHandler("/static/**")
        .addResourceLocations(root.toUri().toString())
        .setCachePeriod(0);
  }
}
