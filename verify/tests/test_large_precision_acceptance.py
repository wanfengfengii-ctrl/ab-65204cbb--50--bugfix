"""超过 50 位整数合法输入的 API 网络验收：真实 HTTP 复现溢罐刻度误判路径。

N=10^60，V=3N-1、K=6N-2、C=1、T=2、S=3、Q=3、U=0、E=100。
以 Python 任意精度整数为判据：
  1. /api/judge 精确名义剂量 x=V、终态恰为 K，必须 ALLOWED；
  2. /api/robust-plan 最大可行刻度 floor((K-V)/Q)=N-1，返回 n 绝不能使 V+nQ>K；
  3. K 仅差 0.0001 时判定必须翻转为 FORBIDDEN，超出量精确保留。
旧实现固定 50 位有效数字会把低位置零并上舍容量上界，本验收锁死该回归。
"""

from decimal import Decimal

import httpx

N = 10**60
V = 3 * N - 1
K = 6 * N - 2
FIVE = {"V": str(V), "C": "1", "T": "2", "S": "3", "K": str(K)}
ROBUST = {**FIVE, "Q": "3", "U": "0", "E": "100"}


def test_judge_huge_inputs_allows_at_exact_capacity(api_base_url: str):
    """复现步骤 1+4：精确名义剂量为 V，终态恰等于 K，必须 ALLOWED。"""
    resp = httpx.post(f"{api_base_url}/api/judge", json=FIVE, timeout=10)
    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"] == "ALLOWED"
    assert body["message"] == "允许补加"
    # Python 任意精度整数精确复算
    assert int(body["dose"]) == V
    assert V + int(body["dose"]) == K
    assert body["finalVolume"] == str(K)
    assert Decimal(body["remainingCapacity"]) == 0
    assert body["excess"] is None


def test_robust_plan_huge_capacity_boundary_not_rounded_up(api_base_url: str):
    """复现步骤 2+3：n 必须等于 floor((K-V)/Q)=N-1，且 V+nQ<=K。

    旧 bug 返回 n=N、dose=3N，使 V+dose=K+1 溢罐。
    """
    resp = httpx.post(f"{api_base_url}/api/robust-plan", json=ROBUST, timeout=10)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ROBUST"
    exact_n_max = (K - V) // 3
    assert exact_n_max == N - 1
    assert body["n"] == exact_n_max
    assert V + 3 * body["n"] <= K  # 返回刻度绝不溢罐
    # 再多一个刻度恰好超出 1：旧实现误返回的刻度必须被排除
    assert V + 3 * (body["n"] + 1) == K + 1
    assert int(body["dose"]) == 3 * body["n"]


def test_judge_huge_inputs_tiny_overflow_is_forbidden(api_base_url: str):
    """61 位整数 + 四位小数：仅超 0.0001 也必须精确保留并判 FORBIDDEN。"""
    k_just_below = str(K - 1) + ".9999"  # = K - 0.0001，仍满足 V <= K
    resp = httpx.post(
        f"{api_base_url}/api/judge", json={**FIVE, "K": k_just_below}, timeout=10
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"] == "FORBIDDEN"
    assert Decimal(body["excess"]) == Decimal("0.0001")
    assert body["remainingCapacity"] is None


def test_drain_plan_huge_boundary_exact_compare(api_base_url: str):
    """同源精确判定在 /api/drain-plan：d=V/2 的半点与 0.0001 缺口不得翻转。"""
    payload = {**FIVE, "K": str(V)}  # d = V - K×(S-T)/(S-C) = V/2
    half = (V - 1) // 2
    resp = httpx.post(
        f"{api_base_url}/api/drain-plan",
        json={**payload, "D": str(half) + ".5"},
        timeout=10,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "EXECUTABLE"

    resp = httpx.post(
        f"{api_base_url}/api/drain-plan",
        json={**payload, "D": str(half) + ".4999"},
        timeout=10,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "EXCEEDS_LIMIT"
    assert Decimal(body["shortfall"]) == Decimal("0.0001")
