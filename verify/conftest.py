"""验收测试共享夹具：通过环境变量指向 compose 网络内的真实服务。"""

import os

import pytest


@pytest.fixture(scope="session")
def base_url() -> str:
    """Web 入口（nginx），Playwright 通过它访问真实前端。"""
    return os.environ.get("WEB_BASE_URL", "http://localhost:8080")


@pytest.fixture(scope="session")
def api_base_url() -> str:
    """API 入口，httpx 通过它访问真实后端。"""
    return os.environ.get("API_BASE_URL", "http://localhost:8000")
