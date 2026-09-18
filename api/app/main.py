"""FastAPI 入口：单罐补加判定台 API。"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .schemas import (
    ALL_FIELD_NAMES,
    DrainPlanRequest,
    DrainPlanResponse,
    JudgeRequest,
    JudgeResponse,
    RobustPlanRequest,
    RobustPlanResponse,
)
from .service import JudgeRejected, drain_plan, judge, robust_plan

app = FastAPI(title="单罐补加判定台", version="1.0.0")

REJECT_DETAIL = "输入校验失败，已整单拒绝"


def _error_body(errors: list[dict]) -> dict:
    return {"detail": REJECT_DETAIL, "errors": errors}


@app.exception_handler(JudgeRejected)
async def judge_rejected_handler(request: Request, exc: JudgeRejected) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=_error_body([{"field": e.field, "message": e.message} for e in exc.errors]),
    )


@app.exception_handler(RequestValidationError)
async def request_validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """把 Pydantic 校验错误规整为 {field, message} 列表，定位到具体字段。"""
    errors: list[dict] = []
    for err in exc.errors():
        loc = [str(part) for part in err.get("loc", [])]
        field = next((p for p in reversed(loc) if p in ALL_FIELD_NAMES), None)
        err_type = err.get("type", "")
        msg = str(err.get("msg", "输入无效"))
        if err_type == "missing":
            msg = "必填项缺失"
        elif err_type == "finite_number":
            msg = "必须是有限数值，不能为 NaN 或无穷大"
        elif err_type.startswith("decimal") or err_type in ("float_parsing", "int_parsing"):
            msg = "必须是数值"
        elif msg.startswith("Value error, "):
            msg = msg[len("Value error, "):]
        elif err_type == "extra_forbidden":
            msg = f"未知字段 {loc[-1] if loc else ''}".strip()
        elif err_type == "json_invalid":
            msg = "请求体不是有效的 JSON"
        if field is None and err_type not in ("json_invalid",):
            msg = f"请求无效：{msg}"
        errors.append({"field": field, "message": msg})
    return JSONResponse(status_code=422, content=_error_body(errors))


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/judge", response_model=JudgeResponse)
def judge_endpoint(payload: JudgeRequest) -> dict:
    return judge(payload)


@app.post("/api/drain-plan", response_model=DrainPlanResponse)
def drain_plan_endpoint(payload: DrainPlanRequest) -> dict:
    return drain_plan(payload)


@app.post("/api/robust-plan", response_model=RobustPlanResponse)
def robust_plan_endpoint(payload: RobustPlanRequest) -> dict:
    return robust_plan(payload)
