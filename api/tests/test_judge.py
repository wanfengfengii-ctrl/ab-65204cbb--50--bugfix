"""API 主线测试：放行、溢罐、非法输入。

通过 TestClient 驱动真实 FastAPI 应用与真实 decimal 计算，不使用任何假数据或固定响应。
"""

from decimal import Decimal, localcontext

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.service import COMPUTE_PRECISION

client = TestClient(app)

ALLOW_PAYLOAD = {"V": "500", "C": "5", "T": "8", "S": "30", "K": "600"}


def expected(v, c, t, s, k):
    """按与服务相同的精度复算期望结果，返回 (dose, final, remaining, excess)。"""
    with localcontext() as ctx:
        ctx.prec = COMPUTE_PRECISION
        dose = Decimal(v) * (Decimal(t) - Decimal(c)) / (Decimal(s) - Decimal(t))
        final = Decimal(v) + dose
        return dose, final, Decimal(k) - final, final - Decimal(k)


def post(payload):
    return client.post("/api/judge", json=payload)


def fields_of(body):
    return {e["field"] for e in body["errors"]}


def messages_of(body, field):
    return [e["message"] for e in body["errors"] if e["field"] == field]


# ---------- 放行主线 ----------


def test_health():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_allow_mainline():
    resp = post(ALLOW_PAYLOAD)
    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"] == "ALLOWED"
    assert body["message"] == "允许补加"

    dose = Decimal(body["dose"])
    final_volume = Decimal(body["finalVolume"])
    remaining = Decimal(body["remainingCapacity"])
    e_dose, e_final, e_remaining, _ = expected(500, 5, 8, 30, 600)
    assert dose == e_dose  # 68.1818...
    assert final_volume == e_final
    assert remaining == e_remaining
    assert remaining > 0
    assert body["excess"] is None
    assert body["inputs"] == {"V": "500", "C": "5", "T": "8", "S": "30", "K": "600"}


def test_equal_capacity_is_allowed():
    # x = 400×(9-5)/(25-9) = 100，终态体积恰好等于容量
    resp = post({"V": "400", "C": "5", "T": "9", "S": "25", "K": "500"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"] == "ALLOWED"
    assert Decimal(body["dose"]) == Decimal(100)
    assert Decimal(body["finalVolume"]) == Decimal(500)
    assert Decimal(body["remainingCapacity"]) == Decimal(0)


def test_inputs_echo_strips_trailing_zeros():
    resp = post({"V": "500.00", "C": "5.0", "T": "8.00", "S": "30", "K": "600.0"})
    assert resp.status_code == 200
    assert resp.json()["inputs"] == {"V": "500", "C": "5", "T": "8", "S": "30", "K": "600"}


def test_json_numbers_keep_decimal_fidelity():
    # JSON 浮点数按最短十进制表示处理：0.1 即 0.1，而非二进制近似
    resp = post({"V": 100, "C": 0.1, "T": 0.2, "S": 0.3, "K": 200})
    assert resp.status_code == 200
    body = resp.json()
    assert Decimal(body["dose"]) == Decimal(100)
    assert body["verdict"] == "ALLOWED"


# ---------- 溢罐主线 ----------


def test_overflow_is_forbidden():
    resp = post({"V": "500", "C": "5", "T": "8", "S": "30", "K": "550"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"] == "FORBIDDEN"
    assert body["message"] == "禁止补加"
    dose = Decimal(body["dose"])
    final_volume = Decimal(body["finalVolume"])
    excess = Decimal(body["excess"])
    e_dose, e_final, _, e_excess = expected(500, 5, 8, 30, 550)
    assert dose == e_dose
    assert final_volume == e_final
    assert excess == e_excess
    assert excess > 0
    assert body["remainingCapacity"] is None


def test_judgment_uses_unformatted_value():
    # 终态体积 10000.20000400008...，四位小数展示为 10000.2，看似等于容量，
    # 但完整精度计算值超出容量，必须禁止补加。
    resp = post({"V": "10000", "C": "5", "T": "5.0001", "S": "10", "K": "10000.2"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"] == "FORBIDDEN"
    excess = Decimal(body["excess"])
    assert Decimal(0) < excess < Decimal("0.00005")  # 展示值将四舍五入为 0，判定仍禁止


def test_tiny_overflow_beyond_four_decimals_still_forbidden():
    # 仅超出 0.00001 mL（五位小数量级），等于容量才允许，超出即禁止
    resp = post({"V": "400", "C": "5", "T": "9", "S": "25", "K": "499.9999"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"] == "FORBIDDEN"
    assert Decimal(body["excess"]) == Decimal("0.0001")


# ---------- 非法输入主线 ----------


def test_missing_field_is_located():
    payload = {k: v for k, v in ALLOW_PAYLOAD.items() if k != "K"}
    resp = post(payload)
    assert resp.status_code == 422
    body = resp.json()
    assert body["detail"] == "输入校验失败，已整单拒绝"
    assert "K" in fields_of(body)
    assert "必填" in messages_of(body, "K")[0]
    assert "dose" not in body  # 整单拒绝，不产出任何结论


def test_empty_string_is_located():
    resp = post({**ALLOW_PAYLOAD, "V": ""})
    assert resp.status_code == 422
    body = resp.json()
    assert "V" in fields_of(body)
    assert "必填" in messages_of(body, "V")[0]


def test_null_is_located():
    resp = post({**ALLOW_PAYLOAD, "C": None})
    assert resp.status_code == 422
    assert "C" in fields_of(resp.json())


def test_too_many_decimal_places():
    resp = post({**ALLOW_PAYLOAD, "C": "1.23456"})
    assert resp.status_code == 422
    body = resp.json()
    assert "C" in fields_of(body)
    assert "四位小数" in messages_of(body, "C")[0]


def test_four_decimal_places_accepted():
    resp = post({"V": "1.2345", "C": "0.0001", "T": "0.0002", "S": "0.0003", "K": "3"})
    assert resp.status_code == 200


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity", "nan", "inf"])
def test_non_finite_rejected(bad):
    resp = post({**ALLOW_PAYLOAD, "V": bad})
    assert resp.status_code == 422
    body = resp.json()
    assert "V" in fields_of(body)
    assert "有限" in messages_of(body, "V")[0]


def test_non_numeric_rejected():
    resp = post({**ALLOW_PAYLOAD, "T": "abc"})
    assert resp.status_code == 422
    assert "T" in fields_of(resp.json())


def test_bool_rejected():
    resp = post({**ALLOW_PAYLOAD, "V": True})
    assert resp.status_code == 422
    assert "V" in fields_of(resp.json())


def test_relation_chain_all_collected():
    # C=0、T=0、S=0、V=-1、K=-1：五个字段全部违规，一次响应全部定位
    resp = post({"V": "-1", "C": "0", "T": "0", "S": "0", "K": "-1"})
    assert resp.status_code == 422
    body = resp.json()
    assert fields_of(body) == {"V", "C", "T", "S", "K"}
    assert "dose" not in body


def test_relation_target_not_greater_than_current():
    resp = post({**ALLOW_PAYLOAD, "T": "5"})
    assert resp.status_code == 422
    assert "T" in fields_of(resp.json())


def test_relation_syrup_not_greater_than_target():
    resp = post({**ALLOW_PAYLOAD, "S": "8"})
    assert resp.status_code == 422
    assert "S" in fields_of(resp.json())


def test_relation_syrup_above_100():
    resp = post({**ALLOW_PAYLOAD, "S": "100.0001"})
    assert resp.status_code == 422
    assert "S" in fields_of(resp.json())


def test_relation_syrup_equal_100_allowed():
    resp = post({**ALLOW_PAYLOAD, "S": "100"})
    assert resp.status_code == 200


def test_relation_volume_exceeds_capacity():
    resp = post({**ALLOW_PAYLOAD, "V": "600", "K": "500"})
    assert resp.status_code == 422
    assert "V" in fields_of(resp.json())


def test_relation_zero_volume_and_capacity():
    resp = post({**ALLOW_PAYLOAD, "V": "0", "K": "0"})
    assert resp.status_code == 422
    body = resp.json()
    assert "V" in fields_of(body)
    assert "K" in fields_of(body)


def test_extra_field_rejected():
    resp = post({**ALLOW_PAYLOAD, "X": "1"})
    assert resp.status_code == 422


def test_invalid_json_body():
    resp = client.post(
        "/api/judge", content="{not json", headers={"Content-Type": "application/json"}
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["detail"] == "输入校验失败，已整单拒绝"
    assert any(e["field"] is None for e in body["errors"])
