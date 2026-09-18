"""稳健刻度方案 API 网络验收：通过真实 HTTP 打到运行中的判定服务。

覆盖：断点择优（以小范围穷举为判据）、同值取小刻度、无稳健刻度、
容量放不下一个刻度的业务结果、非法 Q/U/E 定位，以及超大范围不线性遍历。
"""

import random
import time
from decimal import ROUND_FLOOR, Decimal, localcontext

import httpx

# 该组输入下 /api/judge 判定为允许补加（终态 568.18... ≤ 600）
ALLOW_PAYLOAD = {"V": "500", "C": "5", "T": "8", "S": "30", "K": "600"}
ROBUST_PAYLOAD = {**ALLOW_PAYLOAD, "Q": "10", "U": "2", "E": "1"}


def _dec(x):
    return x if isinstance(x, Decimal) else Decimal(x)


def endpoint_values(v, c, t, s, x, u):
    """按与服务相同的精度（50 位有效数字）复算剂量 x 的端点终态糖度与最坏偏差。"""
    v, c, t, s, x, u = (_dec(p) for p in (v, c, t, s, x, u))
    with localcontext() as ctx:
        ctx.prec = 50
        final_low = (v * c + x * (s - u)) / (v + x)
        final_high = (v * c + x * (s + u)) / (v + x)
        deviation = max(abs(final_low - t), abs(final_high - t))
        return final_low, final_high, deviation


def exhaustive(v, c, t, s, k, q, u):
    """穷举定义的全局最优：逐刻度评估取最坏偏差最小者，同值取较小 n。"""
    v, c, t, s, k, q, u = (_dec(p) for p in (v, c, t, s, k, q, u))
    with localcontext() as ctx:
        ctx.prec = 50
        n_max = int(((k - v) / q).to_integral_value(rounding=ROUND_FLOOR))
        best = None
        for n in range(1, n_max + 1):
            final_low, final_high, deviation = endpoint_values(v, c, t, s, q * n, u)
            if best is None or deviation < best[3]:
                best = (n, final_low, final_high, deviation)
        return best if best is not None else (None, None, None, None)


def test_robust_mainline(api_base_url: str):
    """有稳健刻度：最优刻度 n=7，展示剂量、终态糖度区间与最坏偏差。"""
    resp = httpx.post(f"{api_base_url}/api/robust-plan", json=ROBUST_PAYLOAD, timeout=10)
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
    assert body["toleranceGap"] is None


def test_tie_prefers_smaller_n(api_base_url: str):
    """同值取较小刻度：W(1) = W(2) = 1 精确相等，最优取 n=1。"""
    payload = {"V": "100", "C": "5", "T": "8.4", "S": "31.4", "K": "130",
               "Q": "10", "U": "0", "E": "1"}
    resp = httpx.post(f"{api_base_url}/api/robust-plan", json=payload, timeout=10)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ROBUST"
    assert body["n"] == 1
    assert Decimal(body["worstDeviation"]) == Decimal("1.0")


def test_no_robust_scale_shows_tolerance_gap(api_base_url: str):
    """最优偏差超出容差：展示最小容差缺口，不呈现剂量。"""
    resp = httpx.post(
        f"{api_base_url}/api/robust-plan", json={**ROBUST_PAYLOAD, "E": "0.1"}, timeout=10
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "NO_ROBUST_SCALE"
    assert body["message"] == "无稳健刻度"
    _, _, _, e_dev = exhaustive(500, 5, 8, 30, 600, 10, 2)
    with localcontext() as ctx:
        ctx.prec = 50
        assert Decimal(body["toleranceGap"]) == e_dev - Decimal("0.1")
    assert body["dose"] is None
    assert body["n"] is None


def test_capacity_insufficient_is_business_result(api_base_url: str):
    """容量放不下一个刻度：返回业务结果（200），不按字段错误拒绝。"""
    resp = httpx.post(
        f"{api_base_url}/api/robust-plan",
        json={**ROBUST_PAYLOAD, "K": "550", "Q": "100"},
        timeout=10,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "CAPACITY_INSUFFICIENT"
    assert body["message"] == "容量放不下一个刻度"
    assert body["dose"] is None
    assert body["toleranceGap"] is None


def test_invalid_q_u_e_all_collected_in_order(api_base_url: str):
    """非法 Q/U/E：422 整单拒绝，全部字段错误按 Q、U、E 顺序返回。"""
    resp = httpx.post(
        f"{api_base_url}/api/robust-plan",
        json={**ROBUST_PAYLOAD, "Q": "-1", "U": "-1", "E": "-1"},
        timeout=10,
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["detail"] == "输入校验失败，已整单拒绝"
    assert [e["field"] for e in body["errors"]] == ["Q", "U", "E"]
    assert "n" not in body


def test_fluctuation_interval_validation(api_base_url: str):
    """S-U ≤ T 或 S+U > 100：整单拒绝并定位 U。"""
    for bad_u, keyword in (("22", "S-U"), ("70.0001", "S+U")):
        payload = {**ROBUST_PAYLOAD, "U": bad_u}
        if keyword == "S+U":
            payload["S"] = "60"
            payload["U"] = "40.0001"
        resp = httpx.post(f"{api_base_url}/api/robust-plan", json=payload, timeout=10)
        assert resp.status_code == 422
        u_errors = [e for e in resp.json()["errors"] if e["field"] == "U"]
        assert u_errors, f"U={bad_u} 应定位 U 字段"
        assert keyword in u_errors[0]["message"]


def test_exhaustive_small_range_as_oracle(api_base_url: str):
    """小范围穷举为判据：断点候选算法的结果与穷举定义的全局最优一致。"""
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
        resp = httpx.post(f"{api_base_url}/api/robust-plan", json=payload, timeout=10)
        assert resp.status_code == 200
        body = resp.json()
        n, _, _, e_dev = exhaustive(v, c, t, s, k, q, u)
        if n is None:
            assert body["status"] == "CAPACITY_INSUFFICIENT"
        elif e_dev <= e:
            assert body["status"] == "ROBUST"
            assert body["n"] == n
            assert Decimal(body["worstDeviation"]) == e_dev
        else:
            assert body["status"] == "NO_ROBUST_SCALE"
            with localcontext() as ctx:
                ctx.prec = 50
                assert Decimal(body["toleranceGap"]) == e_dev - e
        checked[body["status"]] += 1
    assert all(count > 0 for count in checked.values())


def test_huge_range_not_linearly_scanned(api_base_url: str):
    """超大范围不线性遍历：n_max ≈ 1e16，服务仍须常数时间作答。"""
    payload = {"V": "400", "C": "5", "T": "9", "S": "25", "K": "1000000000000",
               "Q": "0.0001", "U": "1", "E": "0.5"}
    started = time.monotonic()
    resp = httpx.post(f"{api_base_url}/api/robust-plan", json=payload, timeout=30)
    elapsed = time.monotonic() - started
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ROBUST"
    assert body["n"] == 1000000  # x* = 100 恰为第 1000000 个刻度
    assert Decimal(body["dose"]) == Decimal(100)
    assert Decimal(body["worstDeviation"]) == Decimal("0.2")
    assert elapsed < 30  # 线性遍历 1e16 刻度不可能在超时内完成


def test_judge_and_drain_contract_unchanged_by_robust_feature(api_base_url: str):
    """原 /api/judge 与 /api/drain-plan 请求与响应契约不变。"""
    resp = httpx.post(f"{api_base_url}/api/judge", json=ALLOW_PAYLOAD, timeout=10)
    assert resp.status_code == 200
    assert set(resp.json()) == {
        "verdict", "message", "dose", "finalVolume", "remainingCapacity", "excess", "inputs",
    }
    resp = httpx.post(
        f"{api_base_url}/api/drain-plan",
        json={"V": "500", "C": "5", "T": "8", "S": "30", "K": "550", "D": "20"},
        timeout=10,
    )
    assert resp.status_code == 200
    assert set(resp.json()) == {
        "status", "message", "minDrain", "volumeAfterDrain", "dose", "finalVolume",
        "shortfall", "inputs",
    }
