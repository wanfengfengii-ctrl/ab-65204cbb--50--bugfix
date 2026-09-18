"""稳健刻度方案主线测试：断点择优、同值取小刻度、无可行解、超大范围不线性遍历。

通过 TestClient 驱动真实 FastAPI 应用与真实 decimal 计算；以小范围穷举为判据，
断言断点候选算法的结果与穷举定义的全局最优一致，不使用任何假数据或固定响应。
"""

import random
import time
from decimal import ROUND_FLOOR, Decimal, localcontext

from fastapi.testclient import TestClient

from app.main import app
from app.service import COMPUTE_PRECISION

client = TestClient(app)

# 该组输入下 /api/judge 判定为允许补加（终态 568.18... ≤ 600）
ALLOW_PAYLOAD = {"V": "500", "C": "5", "T": "8", "S": "30", "K": "600"}
ROBUST_PAYLOAD = {**ALLOW_PAYLOAD, "Q": "10", "U": "2", "E": "1"}


def _dec(x):
    """测试参数统一转为 Decimal（与服务的 decimal 计算对齐）。"""
    return x if isinstance(x, Decimal) else Decimal(x)


def endpoint_values(v, c, t, s, x, u):
    """按与服务相同的精度复算剂量 x 在两个端点糖度下的终态糖度与最坏偏差。"""
    v, c, t, s, x, u = (_dec(p) for p in (v, c, t, s, x, u))
    with localcontext() as ctx:
        ctx.prec = COMPUTE_PRECISION
        final_low = (v * c + x * (s - u)) / (v + x)
        final_high = (v * c + x * (s + u)) / (v + x)
        deviation = max(abs(final_low - t), abs(final_high - t))
        return final_low, final_high, deviation


def exhaustive(v, c, t, s, k, q, u):
    """穷举定义的全局最优：逐刻度评估取最坏偏差最小者，同值取较小 n。

    返回 (n, final_low, final_high, deviation)；n 为 None 表示容量放不下一个刻度。
    """
    v, c, t, s, k, q, u = (_dec(p) for p in (v, c, t, s, k, q, u))
    with localcontext() as ctx:
        ctx.prec = COMPUTE_PRECISION
        n_max = int(((k - v) / q).to_integral_value(rounding=ROUND_FLOOR))
        best = None
        for n in range(1, n_max + 1):
            final_low, final_high, deviation = endpoint_values(v, c, t, s, q * n, u)
            if best is None or deviation < best[3]:
                best = (n, final_low, final_high, deviation)
        return best if best is not None else (None, None, None, None)


def post(payload):
    return client.post("/api/robust-plan", json=payload)


def fields_of(body):
    return [e["field"] for e in body["errors"]]


def messages_of(body, field):
    return [e["message"] for e in body["errors"] if e["field"] == field]


# ---------- 有稳健刻度主线 ----------


def test_robust_mainline():
    # x* = 500×3/22 = 68.18...，最优刻度 n=7（剂量 70），最坏偏差 6/19
    resp = post(ROBUST_PAYLOAD)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ROBUST"
    assert body["message"] == "有稳健刻度"
    n, e_low, e_high, e_dev = exhaustive(500, 5, 8, 30, 600, 10, 2)
    assert n == 7
    assert body["n"] == 7
    assert Decimal(body["dose"]) == Decimal(70)
    assert Decimal(body["finalSugarLow"]) == e_low
    assert Decimal(body["finalSugarHigh"]) == e_high
    assert Decimal(body["worstDeviation"]) == e_dev
    assert e_low < Decimal(8) < e_high  # 终态糖度区间跨过目标
    assert body["toleranceGap"] is None
    assert body["inputs"] == {
        "V": "500",
        "C": "5",
        "T": "8",
        "S": "30",
        "K": "600",
        "Q": "10",
        "U": "2",
        "E": "1",
    }


def test_optimum_at_capacity_boundary():
    # 容量边界断点：x* = 68.18... 超出容量（K=560），最优为最大可行刻度 n=12
    resp = post({**ROBUST_PAYLOAD, "K": "560", "Q": "5"})
    assert resp.status_code == 200
    body = resp.json()
    n, _, _, e_dev = exhaustive(500, 5, 8, 30, 560, 5, 2)
    assert n == 12  # V + 12×5 = 560 恰顶到容量
    assert body["status"] == "ROBUST"
    assert body["n"] == 12
    assert Decimal(body["dose"]) == Decimal(60)
    assert Decimal(body["worstDeviation"]) == e_dev


def test_optimum_at_single_scale():
    # 分支相交点在第一个刻度之前：x* = 68.18... < Q = 100，最优为边界刻度 n=1
    resp = post({**ROBUST_PAYLOAD, "Q": "100", "E": "2"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ROBUST"
    assert body["n"] == 1
    assert Decimal(body["dose"]) == Decimal(100)


def test_tie_prefers_smaller_n():
    # 同值取较小 n：W(1) = W(2) = 1 精确相等（断点两侧对称命中）
    payload = {"V": "100", "C": "5", "T": "8.4", "S": "31.4", "K": "130",
               "Q": "10", "U": "0", "E": "1"}
    _, _, _, dev1 = exhaustive(100, 5, Decimal("8.4"), Decimal("31.4"), 130, 10, 0)
    resp = post(payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ROBUST"
    assert body["n"] == 1  # 并列最优取较小刻度
    assert Decimal(body["worstDeviation"]) == dev1 == Decimal("1.0")
    # 次刻度偏差同为 1：确属同值并列而非单调唯一最优
    _, _, dev2 = endpoint_values(100, 5, Decimal("8.4"), Decimal("31.4"), 20, 0)
    assert dev2 == dev1


def test_zero_fluctuation_hits_nominal_dose():
    # U = 0（无波动）：最优刻度使终态恰为目标糖度，最坏偏差为 0
    payload = {"V": "400", "C": "5", "T": "9", "S": "25", "K": "500",
               "Q": "100", "U": "0", "E": "0"}
    resp = post(payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ROBUST"
    assert body["n"] == 1  # x* = 400×4/16 = 100 恰为一个刻度
    assert Decimal(body["worstDeviation"]) == 0
    assert Decimal(body["finalSugarLow"]) == Decimal(9)
    assert Decimal(body["finalSugarHigh"]) == Decimal(9)


def test_deviation_equal_tolerance_is_robust():
    # 最优偏差恰等于容差 E：≤ 判定为有稳健刻度
    payload = {"V": "100", "C": "5", "T": "8.4", "S": "31.4", "K": "130",
               "Q": "10", "U": "0", "E": "1"}
    resp = post(payload)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ROBUST"
    # 容差差 0.0001 即变为无稳健刻度：完整精度比较，不得因展示舍入误判
    resp = post({**payload, "E": "0.9999"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "NO_ROBUST_SCALE"
    assert Decimal(body["toleranceGap"]) == Decimal("0.0001")


def test_forbidden_verdict_inputs_still_get_business_result():
    # 判定为禁止补加的输入（x* 超容量）也可计算：最优落在容量边界刻度
    resp = post({**ROBUST_PAYLOAD, "K": "550"})
    assert resp.status_code == 200
    body = resp.json()
    n, _, _, _ = exhaustive(500, 5, 8, 30, 550, 10, 2)
    assert n == 5
    assert body["status"] == "ROBUST"
    assert body["n"] == 5


# ---------- 无稳健刻度主线 ----------


def test_no_robust_scale_shows_tolerance_gap():
    # 最优偏差 6/19 ≈ 0.3158 > E = 0.1：展示最小容差缺口，不呈现剂量
    resp = post({**ROBUST_PAYLOAD, "E": "0.1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "NO_ROBUST_SCALE"
    assert body["message"] == "无稳健刻度"
    _, _, _, e_dev = exhaustive(500, 5, 8, 30, 600, 10, 2)
    with localcontext() as ctx:
        ctx.prec = COMPUTE_PRECISION
        e_gap = e_dev - Decimal("0.1")
    assert Decimal(body["toleranceGap"]) == e_gap
    assert body["n"] is None
    assert body["dose"] is None
    assert body["finalSugarLow"] is None
    assert body["finalSugarHigh"] is None
    assert body["worstDeviation"] is None


def test_zero_tolerance_gap_when_any_deviation():
    # E = 0 且任何刻度都有非零偏差：缺口即最优偏差本身
    resp = post({**ROBUST_PAYLOAD, "E": "0"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "NO_ROBUST_SCALE"
    _, _, _, e_dev = exhaustive(500, 5, 8, 30, 600, 10, 2)
    assert Decimal(body["toleranceGap"]) == e_dev


# ---------- 容量放不下一个刻度：业务结果 ----------


def test_capacity_insufficient_is_business_result():
    # V + Q > K：连一个刻度都放不下，返回业务结果而非字段错误
    resp = post({**ROBUST_PAYLOAD, "K": "550", "Q": "100"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "CAPACITY_INSUFFICIENT"
    assert body["message"] == "容量放不下一个刻度"
    assert body["n"] is None
    assert body["dose"] is None
    assert body["toleranceGap"] is None


def test_full_tank_cannot_fit_any_scale():
    # V 恰等于 K：任何正整数刻度都溢出
    resp = post({**ROBUST_PAYLOAD, "K": "500"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "CAPACITY_INSUFFICIENT"


# ---------- 非法 Q/U/E 主线：按 Q、U、E 顺序返回全部字段错误 ----------


def test_invalid_q_u_e_all_collected_in_order():
    resp = post({**ROBUST_PAYLOAD, "Q": "-1", "U": "-1", "E": "-1"})
    assert resp.status_code == 422
    body = resp.json()
    assert body["detail"] == "输入校验失败，已整单拒绝"
    assert fields_of(body) == ["Q", "U", "E"]  # 全部字段错误按 Q、U、E 顺序返回
    assert "n" not in body  # 整单拒绝，不产出任何方案


def test_q_not_positive_rejected():
    for bad_q in ("0", "-0.5"):
        resp = post({**ROBUST_PAYLOAD, "Q": bad_q})
        assert resp.status_code == 422
        assert "Q" in fields_of(resp.json())
        assert "大于 0" in messages_of(resp.json(), "Q")[0]


def test_negative_u_rejected():
    resp = post({**ROBUST_PAYLOAD, "U": "-0.1"})
    assert resp.status_code == 422
    assert "U" in fields_of(resp.json())
    assert "负数" in messages_of(resp.json(), "U")[0]


def test_zero_u_accepted():
    resp = post({**ROBUST_PAYLOAD, "U": "0"})
    assert resp.status_code == 200


def test_fluctuation_lower_bound_must_exceed_target():
    # S-U ≤ T：波动下界不再高于目标，整单拒绝并定位 U
    resp = post({**ROBUST_PAYLOAD, "U": "22"})  # S-U = 30-22 = 8 = T
    assert resp.status_code == 422
    assert "U" in fields_of(resp.json())
    assert "S-U" in messages_of(resp.json(), "U")[0]

    resp = post({**ROBUST_PAYLOAD, "U": "25"})
    assert resp.status_code == 422
    assert "U" in fields_of(resp.json())


def test_fluctuation_upper_bound_must_not_exceed_100():
    # S+U > 100：波动上界超出物理上限，整单拒绝并定位 U
    resp = post({**ROBUST_PAYLOAD, "S": "60", "U": "40.0001"})  # S+U = 100.0001
    assert resp.status_code == 422
    assert "U" in fields_of(resp.json())
    assert "S+U" in messages_of(resp.json(), "U")[0]

    resp = post({**ROBUST_PAYLOAD, "S": "60", "U": "40"})  # S+U = 100 恰为边界，受理
    assert resp.status_code == 200


def test_both_fluctuation_violations_collected():
    # S-U ≤ T 与 S+U > 100 同时成立：两个 U 错误一次返回
    payload = {"V": "100", "C": "80", "T": "90", "S": "95", "K": "200",
               "Q": "10", "U": "10", "E": "1"}
    resp = post(payload)
    assert resp.status_code == 422
    u_messages = messages_of(resp.json(), "U")
    assert len(u_messages) == 2
    assert any("S-U" in m for m in u_messages)
    assert any("S+U" in m for m in u_messages)


def test_negative_e_rejected():
    resp = post({**ROBUST_PAYLOAD, "E": "-0.1"})
    assert resp.status_code == 422
    assert "E" in fields_of(resp.json())
    assert "负数" in messages_of(resp.json(), "E")[0]


def test_precision_overflow_rejected():
    for field in ("Q", "U", "E"):
        resp = post({**ROBUST_PAYLOAD, field: "1.23456"})
        assert resp.status_code == 422
        assert field in fields_of(resp.json())
        assert "四位小数" in messages_of(resp.json(), field)[0]


def test_non_finite_rejected():
    for field in ("Q", "U", "E"):
        resp = post({**ROBUST_PAYLOAD, field: "Infinity"})
        assert resp.status_code == 422
        assert field in fields_of(resp.json())
        assert "有限" in messages_of(resp.json(), field)[0]


def test_missing_and_empty_fields_located():
    resp = post(ALLOW_PAYLOAD)  # 缺 Q、U、E
    assert resp.status_code == 422
    body = resp.json()
    for field in ("Q", "U", "E"):
        assert field in fields_of(body)
        assert "必填" in messages_of(body, field)[0]

    resp = post({**ROBUST_PAYLOAD, "Q": ""})
    assert resp.status_code == 422
    assert "必填" in messages_of(resp.json(), "Q")[0]


def test_invalid_five_inputs_still_rejected():
    resp = post({**ROBUST_PAYLOAD, "T": "5"})
    assert resp.status_code == 422
    assert "T" in fields_of(resp.json())
    assert "n" not in resp.json()


def test_extra_field_rejected():
    resp = post({**ROBUST_PAYLOAD, "X": "1"})
    assert resp.status_code == 422


def test_inputs_echo_strips_trailing_zeros():
    resp = post({**ROBUST_PAYLOAD, "Q": "10.00", "U": "2.0", "E": "1.0000"})
    assert resp.status_code == 200
    assert resp.json()["inputs"] == {
        "V": "500",
        "C": "5",
        "T": "8",
        "S": "30",
        "K": "600",
        "Q": "10",
        "U": "2",
        "E": "1",
    }


# ---------- 以小范围穷举为判据 ----------


def test_exhaustive_small_range_as_oracle():
    """小范围随机参数：断点候选算法的结果须与穷举定义的全局最优一致。"""
    rng = random.Random(20260917)
    checked = {"ROBUST": 0, "NO_ROBUST_SCALE": 0, "CAPACITY_INSUFFICIENT": 0}
    for _ in range(150):
        v = Decimal(rng.randint(1, 2000)) / 10
        c = Decimal(rng.randint(1, 90)) / 10
        t = c + Decimal(rng.randint(1, 50)) / 10
        s = t + Decimal(rng.randint(1, 100)) / 10
        if s > 100:
            continue
        k = v + Decimal(rng.randint(0, 1500)) / 10
        q = Decimal(rng.randint(10, 500)) / 100
        u = Decimal(rng.randint(0, 300)) / 100
        if s - u <= t or s + u > 100:
            continue
        e = Decimal(rng.randint(0, 300)) / 100
        payload = {"V": str(v), "C": str(c), "T": str(t), "S": str(s),
                   "K": str(k), "Q": str(q), "U": str(u), "E": str(e)}
        resp = post(payload)
        assert resp.status_code == 200
        body = resp.json()
        n, e_low, e_high, e_dev = exhaustive(v, c, t, s, k, q, u)
        if n is None:
            assert body["status"] == "CAPACITY_INSUFFICIENT"
        elif e_dev <= e:
            assert body["status"] == "ROBUST"
            assert body["n"] == n  # 与穷举全局最优一致（含同值取较小 n）
            assert Decimal(body["dose"]) == q * n
            assert Decimal(body["finalSugarLow"]) == e_low
            assert Decimal(body["finalSugarHigh"]) == e_high
            assert Decimal(body["worstDeviation"]) == e_dev
        else:
            assert body["status"] == "NO_ROBUST_SCALE"
            with localcontext() as ctx:
                ctx.prec = COMPUTE_PRECISION
                assert Decimal(body["toleranceGap"]) == e_dev - e
        checked[body["status"]] += 1
    # 三种业务结果均被穷举判据覆盖
    assert all(count > 0 for count in checked.values())


def test_huge_range_not_linearly_scanned():
    """超大范围不线性遍历：n_max ≈ 1e16，逐刻度扫描在可接受时间内无法完成。"""
    payload = {"V": "400", "C": "5", "T": "9", "S": "25", "K": "1000000000000",
               "Q": "0.0001", "U": "1", "E": "0.5"}
    started = time.monotonic()
    resp = post(payload)
    elapsed = time.monotonic() - started
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ROBUST"
    # x* = 400×4/16 = 100 恰为第 1000000 个刻度，最坏偏差 100×1/500 = 0.2
    assert body["n"] == 1000000
    assert Decimal(body["dose"]) == Decimal(100)
    assert Decimal(body["worstDeviation"]) == Decimal("0.2")
    assert elapsed < 5  # 断点候选算法为常数时间；线性遍历 1e16 刻度不可能完成


# ---------- 既有接口契约不变 ----------


def test_judge_and_drain_contract_unchanged():
    resp = client.post("/api/judge", json=ALLOW_PAYLOAD)
    assert resp.status_code == 200
    assert set(resp.json()) == {
        "verdict", "message", "dose", "finalVolume", "remainingCapacity", "excess", "inputs",
    }
    resp = client.post("/api/drain-plan", json={**ALLOW_PAYLOAD, "K": "550", "D": "20"})
    assert resp.status_code == 200
    assert set(resp.json()) == {
        "status", "message", "minDrain", "volumeAfterDrain", "dose", "finalVolume",
        "shortfall", "inputs",
    }
