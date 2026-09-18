"""请求 / 响应模型与字段级校验。

所有糖度为质量分数百分数，体积单位为毫升。
数值一律以 decimal.Decimal 处理，避免二进制浮点误差。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

FIELD_NAMES = ("V", "C", "T", "S", "K")
DRAIN_FIELD = "D"
# 稳健刻度方案的三项输入：单刻度量 Q(mL)、糖度波动 U(%)、终态容差 E(%)
ROBUST_FIELDS = ("Q", "U", "E")
# 腾容方案输入回显字段（判定五项 + 排出上限）
DRAIN_INPUT_NAMES = FIELD_NAMES + (DRAIN_FIELD,)
# 稳健刻度方案输入回显字段（判定五项 + 刻度三项）
ROBUST_INPUT_NAMES = FIELD_NAMES + ROBUST_FIELDS
# 422 响应中可定位的全部字段（判定五项 + 腾容排出上限 + 稳健刻度三项）
ALL_FIELD_NAMES = FIELD_NAMES + (DRAIN_FIELD,) + ROBUST_FIELDS
MAX_DECIMAL_PLACES = 4


def _normalize_value(value: Any) -> Any:
    """入参归一化：布尔、空串、JSON 浮点的统一处理。"""
    # 布尔值不是合法数值输入
    if isinstance(value, bool):
        raise ValueError("必须是数值，不能是布尔值")
    # 空字符串按空值处理
    if isinstance(value, str) and not value.strip():
        raise ValueError("必填项缺失")
    # JSON 浮点数按其最短十进制表示转换，保证 decimal 精度不丢失
    if isinstance(value, float):
        return repr(value)
    return value


def _check_decimal_value(value: Decimal) -> Decimal:
    """有限性与小数位数校验（最多四位小数）。"""
    if not value.is_finite():
        raise ValueError("必须是有限数值，不能为 NaN 或无穷大")
    if value.as_tuple().exponent < -MAX_DECIMAL_PLACES:
        raise ValueError("最多允许四位小数")
    return value


class JudgeRequest(BaseModel):
    """补加判定请求。

    V: 当前体积(mL)  C: 当前糖度(%)  T: 目标糖度(%)
    S: 糖浆糖度(%)  K: 罐体容量(mL)
    """

    model_config = ConfigDict(extra="forbid")

    V: Decimal
    C: Decimal
    T: Decimal
    S: Decimal
    K: Decimal

    @field_validator(*FIELD_NAMES, mode="before")
    @classmethod
    def _normalize(cls, value: Any) -> Any:
        return _normalize_value(value)

    @field_validator(*FIELD_NAMES)
    @classmethod
    def _check_decimal(cls, value: Decimal) -> Decimal:
        return _check_decimal_value(value)


class DrainPlanRequest(JudgeRequest):
    """腾容方案请求：判定五项 + 本次最多可排出的当前料液量 D(mL)。

    业务假设：排出的当前料液糖度仍为 C（罐内混合均匀）。
    """

    D: Decimal

    @field_validator(DRAIN_FIELD, mode="before")
    @classmethod
    def _normalize_d(cls, value: Any) -> Any:
        return _normalize_value(value)

    @field_validator(DRAIN_FIELD)
    @classmethod
    def _check_decimal_d(cls, value: Decimal) -> Decimal:
        return _check_decimal_value(value)


class RobustPlanRequest(JudgeRequest):
    """稳健刻度方案请求：判定五项 + 单刻度量 Q(mL)、糖度波动 U(%)、终态容差 E(%)。

    现场泵按固定刻度投料：剂量为正整数 n 个刻度，即 nQ；
    糖浆实际糖度在区间 [S-U, S+U] 内波动。
    """

    Q: Decimal
    U: Decimal
    E: Decimal

    @field_validator(*ROBUST_FIELDS, mode="before")
    @classmethod
    def _normalize_que(cls, value: Any) -> Any:
        return _normalize_value(value)

    @field_validator(*ROBUST_FIELDS)
    @classmethod
    def _check_decimal_que(cls, value: Decimal) -> Decimal:
        return _check_decimal_value(value)


class JudgeResponse(BaseModel):
    """判定结果。数值字段为完整精度十进制字符串，展示格式化由前端负责。"""

    verdict: str  # ALLOWED / FORBIDDEN
    message: str  # 允许补加 / 禁止补加
    dose: str  # 唯一补加量 x (mL)
    finalVolume: str  # 终态体积 V+x (mL)
    remainingCapacity: str | None  # 剩余容量 K-(V+x) (mL)，放行时给出
    excess: str | None  # 超出容量 (V+x)-K (mL)，禁止时给出
    inputs: dict[str, str]  # 规范化后的输入回显（去除无意义尾零）


class DrainPlanResponse(BaseModel):
    """腾容方案结果。数值字段为完整精度十进制字符串，展示格式化由前端负责。"""

    status: str  # EXECUTABLE / EXCEEDS_LIMIT
    message: str  # 可执行 / 超出排出上限
    minDrain: str  # 恢复补加所需的最小排出量 d (mL)
    volumeAfterDrain: str | None  # 排出后体积 V-d (mL)，可执行时给出
    dose: str | None  # 排出后的糖浆补加量 (mL)，可执行时给出
    finalVolume: str | None  # 终态体积 (mL)，可执行时给出，恰好不超过容量
    shortfall: str | None  # 仍缺少的排出量 d-D (mL)，超出排出上限时给出
    inputs: dict[str, str]  # 规范化后的输入回显（含 D，去除无意义尾零）


class RobustPlanResponse(BaseModel):
    """稳健刻度方案结果。数值字段为完整精度十进制字符串，展示格式化由前端负责。"""

    status: str  # ROBUST / NO_ROBUST_SCALE / CAPACITY_INSUFFICIENT
    message: str  # 有稳健刻度 / 无稳健刻度 / 容量放不下一个刻度
    n: int | None  # 最优刻度数（正整数），有稳健刻度时给出
    dose: str | None  # 最优剂量 nQ (mL)，有稳健刻度时给出
    finalSugarLow: str | None  # 终态糖度区间下界 (%)，有稳健刻度时给出
    finalSugarHigh: str | None  # 终态糖度区间上界 (%)，有稳健刻度时给出
    worstDeviation: str | None  # 最坏偏差（最大端点偏差，%），有稳健刻度时给出
    toleranceGap: str | None  # 最小容差缺口 最优偏差-E (%)，无稳健刻度时给出
    inputs: dict[str, str]  # 规范化后的输入回显（含 Q、U、E，去除无意义尾零）
