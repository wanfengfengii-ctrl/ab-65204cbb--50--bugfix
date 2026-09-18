"""超过 50 位整数的合法十进制输入回归：判定、容量上界与最小差值必须精确。

复现路径：N=10^60，V=3N-1、K=6N-2、C=1、T=2、S=3、Q=3、U=0、E=100。
精确名义剂量 x=V，终态恰等于 K；最大可行刻度 floor((K-V)/Q)=N-1。
旧实现固定 50 位有效数字，把 V(T-C) 与 K-V 的低位置零/上舍为 3N，
导致 /api/judge 误判禁止、/api/robust-plan 返回溢罐刻度 n=N。
判定已改为精确有理数比较，本测试以 Python 任意精度整数为判据锁死该路径。
"""

import random
from decimal import Decimal
from fractions import Fraction

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

N = 10**60
V = 3 * N - 1          # 61 位整数：3000...000-1
K = 6 * N - 2          # 61 位整数：6000...000-2，精确终态 V+x=K
FIVE = {"V": str(V), "C": "1", "T": "2", "S": "3", "K": str(K)}


def post_judge():
    return client.post("/api/judge", json=FIVE)


def post_robust(e="100"):
    return client.post("/api/robust-plan", json={**FIVE, "Q": "3", "U": "0", "E": e})


# ---------- /api/judge：完整精度判定 ----------


def test_huge_integer_judge_allowed_at_exact_capacity():
    resp = post_judge()
    assert resp.status_code == 200
    body = resp.json()
    # 精确名义剂量 x = V×(2-1)/(3-2) = V，终态恰等于 K → 必须放行
    assert body["verdict"] == "ALLOWED"
    assert body["message"] == "允许补加"
    assert body["dose"] == str(V)
    assert body["finalVolume"] == str(K)
    assert Decimal(body["remainingCapacity"]) == 0
    assert body["excess"] is None


def test_huge_integer_exact_dose_and_final_state():
    # Python 任意精度整数复算复现步骤 4：名义剂量恰为 V，终态体积恰等于 K
    body = post_judge().json()
    assert int(body["dose"]) == V
    assert V + int(body["dose"]) == K


def test_huge_integer_tiny_overflow_still_forbidden():
    # K 仅减 0.0001（61 位整数 + 四位小数）：精确终态超出 0.0001，必须禁止，
    # 且超出量在展示值中不得被固定有效数字精度吞成 0
    k_just_below = str(K - 1) + ".9999"  # = K - 0.0001，仍满足 V <= K
    resp = client.post("/api/judge", json={**FIVE, "K": k_just_below})
    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"] == "FORBIDDEN"
    assert Decimal(body["excess"]) == Decimal("0.0001")
    assert body["remainingCapacity"] is None


# ---------- /api/robust-plan：容量上界精确取整 ----------


def test_huge_integer_capacity_boundary_not_rounded_up():
    resp = post_robust()
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ROBUST"
    # 复现步骤 3：floor((K-V)/Q) = floor((3N-1)/3) = N-1
    exact_n_max = (K - V) // 3
    assert exact_n_max == N - 1
    assert body["n"] == exact_n_max
    # 返回刻度绝不能溢罐：V+nQ <= K
    assert V + 3 * body["n"] <= K
    # 旧 bug 返回的 n=N 恰好多投 1 个单位，必须被排除
    assert V + 3 * (body["n"] + 1) == K + 1 > K
    assert int(body["dose"]) == 3 * body["n"]
    assert Decimal(body["worstDeviation"]) >= 0


def test_huge_integer_one_more_unit_capacity_fits_n():
    # 容量恰好多 1：(K2-V)/Q = N 整除，精确 n_max 变为 N 且不溢罐
    k2 = 6 * N - 1
    resp = client.post(
        "/api/robust-plan",
        json={**FIVE, "K": str(k2), "Q": "3", "U": "0", "E": "100"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert (k2 - V) // 3 == N
    assert body["n"] == N
    assert V + 3 * body["n"] <= k2


# ---------- /api/drain-plan：同源精确判定在超大输入下不翻转 ----------


def test_huge_integer_drain_boundary_exact():
    # K=V 时 d = V - K×(S-T)/(S-C) = V/2（61 位的半点）
    payload = {**FIVE, "K": str(V)}
    half = (V - 1) // 2
    resp = client.post("/api/drain-plan", json={**payload, "D": str(half) + ".5"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "EXECUTABLE"
    assert Decimal(body["minDrain"]) == Decimal(str(half) + ".5")

    # D 差 0.0001 即翻转结论，缺口精确为 0.0001
    resp = client.post("/api/drain-plan", json={**payload, "D": str(half) + ".4999"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "EXCEEDS_LIMIT"
    assert Decimal(body["shortfall"]) == Decimal("0.0001")


def test_huge_integer_inputs_are_accepted_as_four_decimal_inputs():
    # 前置条件：有限、四位小数、整数部分 61 位——全部合法，不得 422
    resp = post_judge()
    assert resp.status_code == 200
    resp = client.post(
        "/api/judge", json={**FIVE, "V": str(V) + ".0000", "K": str(K) + ".0000"}
    )
    assert resp.status_code == 200


# ---------- 大整数缩放下以小范围穷举为判据（断点择优不得因位数失真） ----------


def test_breakpoint_selection_matches_enumeration_at_huge_scale():
    """小系数确定断点结构，整体放大 10^60 后，断点候选算法仍与穷举全局最优一致。

    容量范围控制在 60 个刻度内以便逐刻度穷举；V、K 为 60 位以上整数，
    V(T-C) 等量远超旧的 50 位有效数字。返回刻度还须满足 V+nQ<=K。
    """

    def oracle(v, c, t, s, k, q, u):
        v, c, t, s, k, q, u = (Fraction(x) for x in (v, c, t, s, k, q, u))
        n_max = (k - v) // q
        best = None
        for n in range(1, n_max + 1):
            x = q * n
            a = v * (t - c)
            w = max(abs(x * (s - u - t) - a), abs(x * (s + u - t) - a)) / (v + x)
            if best is None or w < best[1]:
                best = (n, w)
        return n_max, best

    rng = random.Random(20260918)
    scale = 10**60
    checked = 0
    for _ in range(60):
        v0 = rng.randint(1, 500)
        c0 = rng.randint(1, 20)
        t0 = rng.randint(c0 + 1, 60)
        s0 = rng.randint(t0 + 1, 100)
        q0 = rng.randint(1, 50)
        u0 = rng.randint(0, min(100 - s0, s0 - t0 - 1))
        v = v0 * scale
        k = v + rng.randint(1, 60) * q0
        payload = {
            "V": str(v), "C": str(c0), "T": str(t0), "S": str(s0), "K": str(k),
            "Q": str(q0), "U": str(u0), "E": "1000",
        }
        resp = client.post("/api/robust-plan", json=payload)
        assert resp.status_code == 200
        n_max, (best_n, _) = oracle(v, c0, t0, s0, k, q0, u0)
        assert n_max >= 1
        body = resp.json()
        assert body["status"] == "ROBUST"
        assert body["n"] == best_n  # 与穷举全局最优一致（含同值取较小 n）
        assert v + q0 * body["n"] <= k  # 绝不返回溢罐刻度
        checked += 1
    assert checked == 60
