package com.networkaiops.backend.business.monitor.template;

/** Launch parameter of a device category, e.g. the management address of a switch. */
public record ParamTemplate(String name, String label, boolean required) {}
