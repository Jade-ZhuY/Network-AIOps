package com.networkaiops.backend;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;

@SpringBootApplication(
    exclude =
        org.springframework.boot.autoconfigure.security.servlet.UserDetailsServiceAutoConfiguration
            .class)
@ConfigurationPropertiesScan
public class BusinessApplication {
  public static void main(String[] args) {
    SpringApplication.run(BusinessApplication.class, args);
  }
}
