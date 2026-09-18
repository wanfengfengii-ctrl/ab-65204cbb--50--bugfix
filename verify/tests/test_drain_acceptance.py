"""腾容方案 API 网络验收：通过真实 HTTP 打到运行中的判定服务。

覆盖：可执行方案的容量边界、排出上限不足、非法 D 定位，以及原判定契约不变。
"""

from decimal import Decimal, localcontext

import httpx

# 该组输入下 /api/judge 判定为禁止补加（终态 568.18... > 550）
FORBIDDEN_PAYLOAD = {"V": "500", "C": "5", "T": "8", "S": "30", "K": "550"}


def expected_plan(v, c, t, s, k):
    """按与服务相同的精度（50 位有效数字）复算最小排出量与排出后剂量。"""
    with localcontext() as ctx:
        ctx.prec = 50
        min_drain = Decimal(v) - Decimal(k) * (Decimal(s) - Decimal(t)) / (Decimal(s) - Decimal(c))
        volume_after = Decimal(v) - min_drain
        dose = volume_after * (Decimal(t) - Decimal(c)) / (Decimal(s) - Decimal(t))
        final = volume_after + dose
        return min_drain, volume_after, dose, final


def test_executable_plan_hits_capacity_boundary(api_base_url: str):
    """可执行方案：终态恰好不超过容量（等于容量上限）。"""
    resp = httpx.post(
        f"{api_base_url}/api/drain-plan", json={**FORBIDDEN_PAYLOAD, "D": "20"}, timeout=10
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "EXECUTABLE"
    assert body["message"] == "可执行"
    min_drain, volume_after, dose, final = expected_plan(500, 5, 8, 30, 550)
    assert Decimal(body["minDrain"]) == min_drain == Decimal(16)
    assert Decimal(body["volumeAfterDrain"]) == volume_after == Decimal(484)
    assert Decimal(body["dose"]) == dose == Decimal(66)
    # 容量边界：终态恰好顶到容量上限，不多不少
    assert Decimal(body["finalVolume"]) == final == Decimal(550)
    assert body["shortfall"] is None


def test_drain_equal_to_limit_is_executable(api_base_url: str):
    """d 恰等于 D 时恰好可执行（完整精度比较 d <= D）。"""
    resp = httpx.post(
        f"{api_base_url}/api/drain-plan", json={**FORBIDDEN_PAYLOAD, "D": "16"}, timeout=10
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "EXECUTABLE"


def test_exceeds_limit_shows_shortfall_without_dose(api_base_url: str):
    """排出上限不足：展示仍缺少的排出量，不给出可执行剂量。"""
    resp = httpx.post(
        f"{api_base_url}/api/drain-plan", json={**FORBIDDEN_PAYLOAD, "D": "10"}, timeout=10
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "EXCEEDS_LIMIT"
    assert body["message"] == "超出排出上限"
    assert Decimal(body["shortfall"]) == Decimal(6)  # 16 - 10
    assert body["dose"] is None
    assert body["volumeAfterDrain"] is None
    assert body["finalVolume"] is None


def test_invalid_d_located(api_base_url: str):
    """非法 D：负数、精度超限、不小于 V 均 422 定位 D 字段。"""
    for bad_d, keyword in (("-1", "负数"), ("1.23456", "四位小数"), ("500", "小于当前体积")):
        resp = httpx.post(
            f"{api_base_url}/api/drain-plan", json={**FORBIDDEN_PAYLOAD, "D": bad_d}, timeout=10
        )
        assert resp.status_code == 422
        body = resp.json()
        assert body["detail"] == "输入校验失败，已整单拒绝"
        d_errors = [e for e in body["errors"] if e["field"] == "D"]
        assert d_errors, f"D={bad_d} 应定位 D 字段"
        assert keyword in d_errors[0]["message"]
        assert "minDrain" not in body


def test_allowed_verdict_produces_no_drain_plan(api_base_url: str):
    """允许补加的罐直接请求腾容：不生成方案（422），不得给出负的最小排出量。"""
    resp = httpx.post(
        f"{api_base_url}/api/drain-plan",
        json={"V": "500", "C": "5", "T": "8", "S": "30", "K": "600", "D": "20"},
        timeout=10,
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["detail"] == "输入校验失败，已整单拒绝"
    assert "minDrain" not in body
    assert any("无需腾容" in e["message"] for e in body["errors"])


def test_judge_contract_unchanged_by_drain_feature(api_base_url: str):
    """原 /api/judge 请求与响应契约不变。"""
    resp = httpx.post(
        f"{api_base_url}/api/judge",
        json={"V": "500", "C": "5", "T": "8", "S": "30", "K": "600"},
        timeout=10,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"] == "ALLOWED"
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
