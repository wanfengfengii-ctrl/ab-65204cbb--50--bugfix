"""超大整数（整数部分超过 50 位）合法十进制输入的判定回归。

复现缺陷：固定 ctx.prec=50 会把 V×(T-C)、K-V 等的低位舍掉，
例如 N=10^60、V=3N-1、K=6N-2 时把容量上界 (K-V)/3 = N-1/3 向上误取整为 N，
返回溢罐刻度并把恰等于容量的原判定误判为禁止。

这里的期望值全部用 Python 大整数 / 精确 decimal（200 位）计算，
不依赖服务端任何固定精度。
"""

from decimal import Decimal, localcontext

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

# N=10^60：V、K 的整数部分均为 61 位，远超 50 位有效数字
N = 10**60
BOUNDARY_FIVE = {"V": str(3 * N - 1), "C": "1", "T": "2", "S": "3", "K": str(6 * N - 2)}


def post_judge(payload):
    return client.post("/api/judge", json=payload)


def post_robust(payload):
    return client.post("/api/robust-plan", json=payload)


def post_drain(payload):
    return client.post("/api/drain-plan", json=payload)


# ---------- 原判定：精确名义剂量恰顶到容量 ----------


def test_judge_huge_exact_capacity_is_allowed():
    # 精确解 x = V×(2-1)/(3-2) = V，终态 V+x = 2V = 6N-2 = K：恰等于容量，必须放行
    resp = post_judge(BOUNDARY_FIVE)
    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"] == "ALLOWED"
    assert body["message"] == "允许补加"
    with localcontext() as ctx:
        ctx.prec = 200
        assert Decimal(body["dose"]) == Decimal(3 * N - 1)  # 名义剂量恰为 V
        assert Decimal(body["finalVolume"]) == Decimal(6 * N - 2)  # 终态恰等于 K
        assert Decimal(body["remainingCapacity"]) == 0
    assert body["excess"] is None


def test_judge_huge_inputs_echoed_without_rounding():
    # 超过 28/50 位的输入回显必须逐位精确，不得被任何 decimal 上下文舍入
    body = post_judge(BOUNDARY_FIVE).json()
    assert body["inputs"]["V"] == str(3 * N - 1)
    assert body["inputs"]["K"] == str(6 * N - 2)


def test_judge_huge_one_unit_overflow_is_forbidden():
    # 对称情形 V=3N、K=6N-1：精确终态 6N 比 K 大 1，必须禁止
    payload = {"V": str(3 * N), "C": "1", "T": "2", "S": "3", "K": str(6 * N - 1)}
    body = post_judge(payload).json()
    assert body["verdict"] == "FORBIDDEN"
    with localcontext() as ctx:
        ctx.prec = 200
        assert Decimal(body["excess"]) == 1
        assert Decimal(body["dose"]) == Decimal(3 * N)
    assert body["remainingCapacity"] is None


def test_judge_huge_fractional_gap_resolves_both_ways():
    # 61 位体积、K 与终态仅差 0.0001（四位小数）：两个方向都必须按精确符号判定
    v = 3 * N
    with localcontext() as ctx:
        ctx.prec = 200
        k_below = Decimal(6 * N) - Decimal("0.0001")
        k_above = Decimal(6 * N) + Decimal("0.0001")
    body_below = post_judge(
        {"V": str(v), "C": "1", "T": "2", "S": "3", "K": format(k_below, "f")}
    ).json()
    body_above = post_judge(
        {"V": str(v), "C": "1", "T": "2", "S": "3", "K": format(k_above, "f")}
    ).json()
    assert body_below["verdict"] == "FORBIDDEN"
    assert body_above["verdict"] == "ALLOWED"
    with localcontext() as ctx:
        ctx.prec = 200
        assert Decimal(body_below["excess"]) == Decimal("0.0001")
        assert Decimal(body_above["remainingCapacity"]) == Decimal("0.0001")


def test_fifty_one_digit_integer_beyond_fixed_precision():
    # 52 位整数（N=10^51）同样超过 50 位有效数字，边界判定仍须精确
    m = 10**51
    payload = {"V": str(3 * m - 1), "C": "1", "T": "2", "S": "3", "K": str(6 * m - 2)}
    body = post_judge(payload).json()
    assert body["verdict"] == "ALLOWED"
    with localcontext() as ctx:
        ctx.prec = 200
        assert Decimal(body["finalVolume"]) == Decimal(6 * m - 2)
        assert Decimal(body["remainingCapacity"]) == 0


# ---------- 稳健刻度：容量上界不得向上舍入 ----------


def test_robust_huge_capacity_boundary_scale_is_n_minus_one():
    # 精确最大可行刻度 floor((K-V)/Q) = (3N-1)/3 = N-1；旧实现误给 N（溢罐 1 单位）
    payload = {**BOUNDARY_FIVE, "Q": "3", "U": "0", "E": "100"}
    resp = post_robust(payload)
    assert resp.status_code == 200
    body = resp.json()
    exact_n_max = (3 * N - 1) // 3  # 与复现步骤 3 的 Python 整数计算一致
    assert exact_n_max == N - 1
    assert body["status"] == "ROBUST"
    assert body["n"] == exact_n_max
    assert body["n"] != N  # 绝不返回被向上舍入的溢罐刻度 N
    # 返回剂量必须满足硬约束 V + nQ ≤ K（精确整数验证）
    assert (3 * N - 1) + 3 * body["n"] <= 6 * N - 2
    with localcontext() as ctx:
        ctx.prec = 200
        assert Decimal(body["dose"]) == Decimal(3 * (N - 1))
        # nQ = V-2 比名义剂量少 2：U=0 时最坏偏差恰为 1/(V-1) = 1/(3N-2)
        # （偏差恰为 0 的刻度 n=N 正是溢罐刻度，绝不可选）；
        # 大整数输入下偏差由精确有理数直接舍入，81 位精度内吻合
        deviation = Decimal(body["worstDeviation"])
        exact_deviation = Decimal(1) / Decimal(3 * N - 2)
        assert deviation > 0
        assert abs(deviation - exact_deviation) / exact_deviation < Decimal("1e-75")


def test_robust_huge_capacity_insufficient_when_one_scale_overflows():
    # V 恰等于 K：任何正刻度都溢出，业务结果 CAPACITY_INSUFFICIENT
    payload = {"V": str(3 * N - 1), "C": "1", "T": "2", "S": "3", "K": str(3 * N - 1),
               "Q": "3", "U": "0", "E": "100"}
    body = post_robust(payload).json()
    assert body["status"] == "CAPACITY_INSUFFICIENT"
    assert body["n"] is None


# ---------- 腾容方案：大整数下符号与容量边界仍精确 ----------


def test_drain_huge_exact_boundary_plan():
    # 禁止情形 V=3N、K=6N-1：d = 3N-(6N-1)×1/2 = 0.5
    forbidden = {"V": str(3 * N), "C": "1", "T": "2", "S": "3", "K": str(6 * N - 1)}
    body = post_drain({**forbidden, "D": "0.5"}).json()
    assert body["status"] == "EXECUTABLE"
    with localcontext() as ctx:
        ctx.prec = 200
        assert Decimal(body["minDrain"]) == Decimal("0.5")
        assert Decimal(body["dose"]) == Decimal(3 * N - 1) + Decimal("0.5")
        assert Decimal(body["finalVolume"]) == Decimal(6 * N - 1)  # 终态恰为 K


def test_drain_huge_shortfall_by_one_ten_thousandth():
    forbidden = {"V": str(3 * N), "C": "1", "T": "2", "S": "3", "K": str(6 * N - 1)}
    body = post_drain({**forbidden, "D": "0.4999"}).json()
    assert body["status"] == "EXCEEDS_LIMIT"
    with localcontext() as ctx:
        ctx.prec = 200
        assert Decimal(body["shortfall"]) == Decimal("0.0001")
    assert body["dose"] is None


def test_drain_rejected_for_huge_allowed_at_exact_capacity():
    # 原判定在精确意义下恰允许（终态=K，d=0）：不生成腾容方案，422 整单拒绝
    resp = post_drain({**BOUNDARY_FIVE, "D": "1"})
    assert resp.status_code == 422
    assert any("无需腾容" in e["message"] for e in resp.json()["errors"])
