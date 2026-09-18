"""超大整数合法十进制输入的 API 网络验收（缺陷复现路径）。

输入为有限、最多四位小数、但整数部分超过 50 位的合法十进制字符串。
固定 50 位有效数字的旧实现会把容量上界向上舍入：既把恰等于容量的原判定
误判为 FORBIDDEN，又令稳健刻度返回溢罐刻度 n=N（V+nQ>K）。

本验收通过真实 HTTP 打运行中的服务，期望值全部用 Python 大整数精确计算
（不依赖任何固定有效数字精度），覆盖：
  1. /api/judge：精确名义剂量 V、终态恰等于 K 时必须 ALLOWED；
  2. /api/robust-plan：最大可行刻度 floor((K-V)/Q)=N-1，绝不溢罐；
  3. 输入回显逐位精确；
  4. 对称的仅超 1 单位情形必须 FORBIDDEN，且该输入的腾容方案可执行。
"""

import httpx

# N=10^60：V、K 的整数部分均为 61 位，远超 50 位有效数字
N = 10**60
# 精确名义剂量 x = V×(T-C)/(S-T) = V（C=1,T=2,S=3），且 2V = K：终态恰顶容量
BOUNDARY_FIVE = {
    "V": str(3 * N - 1),
    "C": "1",
    "T": "2",
    "S": "3",
    "K": str(6 * N - 2),
}


def test_judge_huge_exact_capacity_is_allowed(api_base_url: str):
    """原判定：精确终态恰等于容量（2V=K），必须 ALLOWED 且数值逐位精确。"""
    resp = httpx.post(f"{api_base_url}/api/judge", json=BOUNDARY_FIVE, timeout=10)
    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"] == "ALLOWED"
    assert body["message"] == "允许补加"
    # 用大整数解析返回值，不受 28 位默认 decimal 上下文影响
    assert int(body["dose"]) == 3 * N - 1  # 精确名义剂量 x=V
    assert int(body["finalVolume"]) == 6 * N - 2  # 终态恰等于 K
    assert body["remainingCapacity"] == "0"
    assert body["excess"] is None


def test_judge_huge_inputs_echoed_without_rounding(api_base_url: str):
    """超过 50 位的输入回显必须逐位精确，不得被任何 decimal 上下文舍入。"""
    resp = httpx.post(f"{api_base_url}/api/judge", json=BOUNDARY_FIVE, timeout=10)
    body = resp.json()
    assert body["inputs"]["V"] == str(3 * N - 1)
    assert body["inputs"]["K"] == str(6 * N - 2)


def test_robust_huge_capacity_upper_bound_not_rounded_up(api_base_url: str):
    """稳健刻度：最大可行刻度 floor((K-V)/Q)=N-1，返回刻度绝不溢罐。"""
    payload = {**BOUNDARY_FIVE, "Q": "3", "U": "0", "E": "100"}
    resp = httpx.post(f"{api_base_url}/api/robust-plan", json=payload, timeout=10)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ROBUST"
    # 复现步骤 3：Python 整数精确计算最大可行刻度
    exact_n_max = (3 * N - 1) // 3
    assert exact_n_max == N - 1
    assert body["n"] == exact_n_max
    assert body["n"] != N  # 旧实现误返回的溢罐刻度 N 不得出现
    # 硬约束 V+nQ ≤ K（精确整数验证）
    v, k, q = 3 * N - 1, 6 * N - 2, 3
    assert v + body["n"] * q <= k
    assert int(body["dose"]) == q * exact_n_max


def test_robust_huge_full_tank_is_capacity_insufficient(api_base_url: str):
    """V 恰等于 K：任何正刻度都溢出，返回业务结果 CAPACITY_INSUFFICIENT。"""
    payload = {
        "V": str(3 * N - 1),
        "C": "1",
        "T": "2",
        "S": "3",
        "K": str(3 * N - 1),
        "Q": "3",
        "U": "0",
        "E": "100",
    }
    resp = httpx.post(f"{api_base_url}/api/robust-plan", json=payload, timeout=10)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "CAPACITY_INSUFFICIENT"
    assert body["n"] is None


def test_judge_huge_one_unit_over_and_drain_plan(api_base_url: str):
    """对称情形 2V=K+1：终态恰超 1，必须 FORBIDDEN；腾容方案精确可执行。"""
    forbidden = {
        "V": str(3 * N),
        "C": "1",
        "T": "2",
        "S": "3",
        "K": str(6 * N - 1),
    }
    resp = httpx.post(f"{api_base_url}/api/judge", json=forbidden, timeout=10)
    body = resp.json()
    assert body["verdict"] == "FORBIDDEN"
    assert int(body["excess"]) == 1  # V+x 恰比 K 大 1
    assert body["remainingCapacity"] is None

    # d = V - K×(S-T)/(S-C) = 3N-(6N-1)/2 = 0.5；D=0.5 恰好可执行
    drain = httpx.post(
        f"{api_base_url}/api/drain-plan", json={**forbidden, "D": "0.5"}, timeout=10
    )
    assert drain.status_code == 200
    plan = drain.json()
    assert plan["status"] == "EXECUTABLE"
    assert plan["minDrain"] == "0.5"
    assert int(plan["finalVolume"]) == 6 * N - 1  # 终态恰为容量上限

    # 允许补加（恰等于容量）的输入直接请求腾容：422 整单拒绝，不生成方案
    rejected = httpx.post(
        f"{api_base_url}/api/drain-plan", json={**BOUNDARY_FIVE, "D": "1"}, timeout=10
    )
    assert rejected.status_code == 422
    assert any("无需腾容" in e["message"] for e in rejected.json()["errors"])
