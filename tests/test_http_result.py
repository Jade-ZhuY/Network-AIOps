import pytest

from scripts.http_result import unwrap_result


def test_unwraps_java_success_without_copying_business_data():
    data = {"session_id": "session-test"}
    assert unwrap_result({"code": 1, "msg": "success", "data": data}) is data
    assert unwrap_result({"code": 1, "msg": "success", "data": None}) is None


def test_java_error_is_not_treated_as_success():
    with pytest.raises(ValueError, match="操作失败"):
        unwrap_result({"code": 0, "msg": "操作失败", "data": None})


def test_direct_python_payloads_are_unchanged():
    for payload in ({"session_id": "session-test"}, {"code": "domain-code", "message": "text"}, []):
        assert unwrap_result(payload) is payload
