package com.networkaiops.backend.common.web;

import static org.junit.jupiter.api.Assertions.*;

import java.util.Map;
import org.junit.jupiter.api.Test;

class ResultTest {
  @Test
  void successWithoutDataUsesOneAndSuccessMessage() {
    Result result = Result.success();
    assertEquals(1, result.getCode());
    assertEquals("success", result.getMsg());
    assertNull(result.getData());
  }

  @Test
  void successPreservesThePayloadObject() {
    Object payload = Map.of("value", 7);
    Result result = Result.success(payload);
    assertEquals(1, result.getCode());
    assertEquals("success", result.getMsg());
    assertSame(payload, result.getData());
    assertNull(Result.success(null).getData());
  }

  @Test
  void errorUsesZeroAndOnlyTheProvidedMessage() {
    Result result = Result.error("输入格式不正确");
    assertEquals(0, result.getCode());
    assertEquals("输入格式不正确", result.getMsg());
    assertNull(result.getData());
  }

  @Test
  void lombokProvidesBeanAccessorsAndValueMethods() {
    Result result = new Result();
    result.setCode(1);
    result.setMsg("success");
    result.setData("payload");
    assertEquals(Result.success("payload"), result);
    assertEquals(Result.success("payload").hashCode(), result.hashCode());
    assertTrue(result.toString().contains("msg=success"));
  }
}
