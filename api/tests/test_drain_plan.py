"""腾容方案主线测试：可执行、超出排出上限、非法 D。

通过 TestClient 驱动真实 FastAPI 应用与真实 decimal 计算，不使用任何假数据或固定响应。
"""

from decimal import Decimal, localcontext

from fastapi.testclient import TestClient

from app.main import app
from app.service import COMPUTE_PRECISION

client = TestClient(app)

# 该组输入下 /api/judge 判定为禁止补加（终态 568.18... > 550）
FORBIDDEN_PAYLOAD = {"V": "500", "C": "5", "T": "8", "S": "30", "K": "550"}


def expected(v, c, t, s, k, d_limit):
    """按与服务相同的精度复算期望结果。

    返回 (min_drain, volume_after, dose, final, shortfall, executable)。
    """
    with localcontext() as ctx:
        ctx.prec = COMPUTE_PRECISION
        min_drain = Decimal(v) - Decimal(k) * (Decimal(s) - Decimal(t)) / (Decimal(s) - Decimal(c))
        executable = min_drain <= Decimal(d_limit)
        if executable:
            volume_after = Decimal(v) - min_drain
            dose = volume_after * (Decimal(t) - Decimal(c)) / (Decimal(s) - Decimal(t))
            final = volume_after + dose
            shortfall = None
        else:
            volume_after = dose = final = None
            shortfall = min_drain - Decimal(d_limit)
        return min_drain, volume_after, dose, final, shortfall, executable


def post(payload):
    return client.post("/api/drain-plan", json=payload)


def fields_of(body):
    return {e["field"] for e in body["errors"]}


def messages_of(body, field):
    return [e["message"] for e in body["errors"] if e["field"] == field]


# ---------- 可执行主线 ----------


def test_executable_mainline():
    # d = 500 - 550×(30-8)/(30-5) = 16，排出后 484，补加 66，终态恰为 550
    resp = post({**FORBIDDEN_PAYLOAD, "D": "20"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "EXECUTABLE"
    assert body["message"] == "可执行"
    e_drain, e_after, e_dose, e_final, _, _ = expected(500, 5, 8, 30, 550, 20)
    assert Decimal(body["minDrain"]) == e_drain == Decimal(16)
    assert Decimal(body["volumeAfterDrain"]) == e_after == Decimal(484)
    assert Decimal(body["dose"]) == e_dose == Decimal(66)
    assert Decimal(body["finalVolume"]) == e_final
    assert body["shortfall"] is None
    assert body["inputs"] == {
        "V": "500",
        "C": "5",
        "T": "8",
        "S": "30",
        "K": "550",
        "D": "20",
    }


def test_executable_final_volume_exactly_at_capacity():
    # 容量边界：可执行方案的终态恰好不超过容量（等于容量）
    resp = post({**FORBIDDEN_PAYLOAD, "D": "100"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "EXECUTABLE"
    final_volume = Decimal(body["finalVolume"])
    assert final_volume <= Decimal(550)
    assert final_volume == Decimal(550)  # 最小排出量使终态恰好顶到容量上限


def test_drain_equal_to_limit_is_executable():
    # d 恰等于 D：完整精度比较 d <= D，恰好可执行
    resp = post({**FORBIDDEN_PAYLOAD, "D": "16"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "EXECUTABLE"
    assert Decimal(body["minDrain"]) == Decimal(16)


def test_full_precision_compare_near_boundary():
    # d = 500 - 555.5×22/25 = 11.16；D 差 0.0001 即改变结论，不得因展示舍入误判
    base = {**FORBIDDEN_PAYLOAD, "K": "555.5"}
    resp = post({**base, "D": "11.1599"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "EXCEEDS_LIMIT"
    assert Decimal(body["shortfall"]) == Decimal("0.0001")

    resp = post({**base, "D": "11.16"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "EXECUTABLE"


def test_executable_non_terminating_decimal_precision():
    # (S-T)/(S-C) = 21.9/24.9 除不尽：按 50 位有效数字复算验证完整精度
    payload = {"V": "500", "C": "5", "T": "8", "S": "29.9", "K": "550", "D": "20"}
    resp = post(payload)
    assert resp.status_code == 200
    body = resp.json()
    e_drain, e_after, e_dose, e_final, _, _ = expected(500, 5, 8, "29.9", 550, 20)
    assert Decimal(body["minDrain"]) == e_drain
    assert Decimal(body["volumeAfterDrain"]) == e_after
    assert Decimal(body["dose"]) == e_dose
    assert Decimal(body["finalVolume"]) == e_final
    # 终态仍恰好不超过容量（50 位精度下与 K 的差异在 1e-49 量级内）
    assert abs(Decimal(body["finalVolume"]) - Decimal(550)) < Decimal("1e-40")


# ---------- 超出排出上限主线 ----------


def test_exceeds_limit_mainline():
    # d = 16 > D = 10：仍缺少 6，不给出可执行剂量
    resp = post({**FORBIDDEN_PAYLOAD, "D": "10"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "EXCEEDS_LIMIT"
    assert body["message"] == "超出排出上限"
    e_drain, _, _, _, e_shortfall, _ = expected(500, 5, 8, 30, 550, 10)
    assert Decimal(body["minDrain"]) == e_drain == Decimal(16)
    assert Decimal(body["shortfall"]) == e_shortfall == Decimal(6)
    assert body["dose"] is None
    assert body["volumeAfterDrain"] is None
    assert body["finalVolume"] is None


def test_zero_limit_exceeds_when_drain_needed():
    # D = 0（一滴都不能排）：仍缺少全部最小排出量
    resp = post({**FORBIDDEN_PAYLOAD, "D": "0"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "EXCEEDS_LIMIT"
    assert Decimal(body["shortfall"]) == Decimal(16)
    assert body["dose"] is None


# ---------- 非法 D 主线 ----------


def test_missing_d_is_located():
    resp = post(FORBIDDEN_PAYLOAD)
    assert resp.status_code == 422
    body = resp.json()
    assert body["detail"] == "输入校验失败，已整单拒绝"
    assert "D" in fields_of(body)
    assert "必填" in messages_of(body, "D")[0]
    assert "minDrain" not in body  # 整单拒绝，不产出任何方案


def test_empty_d_is_located():
    resp = post({**FORBIDDEN_PAYLOAD, "D": ""})
    assert resp.status_code == 422
    assert "D" in fields_of(resp.json())


def test_negative_d_rejected():
    resp = post({**FORBIDDEN_PAYLOAD, "D": "-1"})
    assert resp.status_code == 422
    body = resp.json()
    assert "D" in fields_of(body)
    assert "负数" in messages_of(body, "D")[0]


def test_d_precision_overflow_rejected():
    resp = post({**FORBIDDEN_PAYLOAD, "D": "1.23456"})
    assert resp.status_code == 422
    body = resp.json()
    assert "D" in fields_of(body)
    assert "四位小数" in messages_of(body, "D")[0]


def test_d_not_less_than_volume_rejected():
    # D >= V：把罐排空也无法接受，整单拒绝并定位 D
    resp = post({**FORBIDDEN_PAYLOAD, "D": "500"})
    assert resp.status_code == 422
    body = resp.json()
    assert "D" in fields_of(body)
    assert "小于当前体积" in messages_of(body, "D")[0]

    resp = post({**FORBIDDEN_PAYLOAD, "D": "600"})
    assert resp.status_code == 422
    assert "D" in fields_of(resp.json())


def test_non_finite_d_rejected():
    resp = post({**FORBIDDEN_PAYLOAD, "D": "NaN"})
    assert resp.status_code == 422
    body = resp.json()
    assert "D" in fields_of(body)
    assert "有限" in messages_of(body, "D")[0]


def test_non_numeric_d_rejected():
    resp = post({**FORBIDDEN_PAYLOAD, "D": "abc"})
    assert resp.status_code == 422
    assert "D" in fields_of(resp.json())


# ---------- 允许补加不生成方案 ----------


def test_allowed_inputs_do_not_produce_plan():
    # K=600 时判定为允许补加：d = 500-600×22/25 = -28 <= 0，不生成腾容方案
    resp = post({**FORBIDDEN_PAYLOAD, "K": "600", "D": "20"})
    assert resp.status_code == 422
    body = resp.json()
    assert body["detail"] == "输入校验失败，已整单拒绝"
    assert "minDrain" not in body  # 不产出任何方案，更不得给出负排出量
    assert any("无需腾容" in e["message"] for e in body["errors"])


def test_zero_drain_needed_at_exact_capacity_rejected():
    # V+x 恰好等于容量（允许补加边界）：d = 0，同样不生成方案
    resp = post({"V": "400", "C": "5", "T": "9", "S": "25", "K": "500", "D": "10"})
    assert resp.status_code == 422
    body = resp.json()
    assert "minDrain" not in body
    assert any("无需腾容" in e["message"] for e in body["errors"])


# ---------- 五项输入仍按原规则整单拒绝 ----------


def test_invalid_five_inputs_still_rejected():
    resp = post({**FORBIDDEN_PAYLOAD, "T": "5", "D": "10"})
    assert resp.status_code == 422
    body = resp.json()
    assert "T" in fields_of(body)
    assert "minDrain" not in body


def test_extra_field_rejected():
    resp = post({**FORBIDDEN_PAYLOAD, "D": "10", "X": "1"})
    assert resp.status_code == 422


# ---------- 原判定契约不变 ----------


def test_judge_contract_unchanged():
    resp = client.post(
        "/api/judge",
        json={"V": "500", "C": "5", "T": "8", "S": "30", "K": "600"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {
        "verdict",
        "message",
        "dose",
        "finalVolume",
        "remainingCapacity",
        "excess",
        "inputs",
    }
    assert set(body["inputs"]) == {"V", "C", "T", "S", "K"}
