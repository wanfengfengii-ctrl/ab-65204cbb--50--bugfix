"""API 网络验收：通过真实 HTTP 打到运行中的判定服务，覆盖放行、溢罐、非法输入主线。"""

from decimal import Decimal, localcontext

import httpx

ALLOW_PAYLOAD = {"V": "500", "C": "5", "T": "8", "S": "30", "K": "600"}


def expected() -> tuple[Decimal, Decimal, Decimal]:
    """按与服务相同的精度（50 位有效数字）复算 dose/final/remaining。"""
    with localcontext() as ctx:
        ctx.prec = 50
        dose = Decimal(500) * (Decimal(8) - Decimal(5)) / (Decimal(30) - Decimal(8))
        final = Decimal(500) + dose
        remaining = Decimal(600) - final
        return dose, final, remaining


def test_health(api_base_url: str):
    resp = httpx.get(f"{api_base_url}/api/health", timeout=10)
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_allow_mainline(api_base_url: str):
    resp = httpx.post(f"{api_base_url}/api/judge", json=ALLOW_PAYLOAD, timeout=10)
    assert resp.status_code == 200
    body = resp.json()
    assert body["message"] == "允许补加"
    dose, final, remaining = expected()
    assert Decimal(body["dose"]) == dose
    assert Decimal(body["finalVolume"]) == final
    assert Decimal(body["remainingCapacity"]) == remaining


def test_overflow_mainline(api_base_url: str):
    resp = httpx.post(
        f"{api_base_url}/api/judge", json={**ALLOW_PAYLOAD, "K": "550"}, timeout=10
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["message"] == "禁止补加"
    assert Decimal(body["excess"]) > 0
    assert body["remainingCapacity"] is None


def test_equal_capacity_allowed(api_base_url: str):
    resp = httpx.post(
        f"{api_base_url}/api/judge",
        json={"V": "400", "C": "5", "T": "9", "S": "25", "K": "500"},
        timeout=10,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["message"] == "允许补加"
    assert Decimal(body["remainingCapacity"]) == 0


def test_invalid_mainline_relation_error(api_base_url: str):
    resp = httpx.post(
        f"{api_base_url}/api/judge",
        json={"V": "500", "C": "8", "T": "5", "S": "30", "K": "600"},
        timeout=10,
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["detail"] == "输入校验失败，已整单拒绝"
    fields = {e["field"] for e in body["errors"]}
    assert "T" in fields  # 关系错误定位
    assert "dose" not in body  # 整单拒绝，无结论


def test_invalid_mainline_precision_overflow(api_base_url: str):
    resp = httpx.post(
        f"{api_base_url}/api/judge",
        json={"V": "500", "C": "5", "T": "8", "S": "30", "K": "1.23456"},
        timeout=10,
    )
    assert resp.status_code == 422
    body = resp.json()
    fields = {e["field"] for e in body["errors"]}
    assert "K" in fields  # 精度超限定位
    assert "dose" not in body
