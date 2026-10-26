"""Read Java Result envelopes without changing direct Python API responses."""

from typing import Any


def unwrap_result(payload: Any) -> Any:
    if isinstance(payload, dict) and {"code", "msg", "data"} <= payload.keys():
        if payload["code"] != 1:
            raise ValueError(payload["msg"] or "接口返回失败结果")
        return payload["data"]
    return payload
