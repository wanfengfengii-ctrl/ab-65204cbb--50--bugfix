"""补加判定核心逻辑。

质量守恒（液体密度相同，按体积折算）：
    V·C + x·S = (V + x)·T   =>   x = V×(T-C)/(S-T)

判定使用完整精度的计算值，绝不使用经展示格式化处理后的数值：
    V + x <= K  → 允许补加（等于容量也允许）
    V + x >  K  → 禁止补加

腾容方案（禁止补加后由操作员发起，不改写原判定）：
    按排出料液糖度仍为 C 的业务假设，排出 d mL 后罐内为 (V-d, C)，
    再补加恰好恢复到容量上限：终态体积恰为 K、糖度恰为 T。
        (V-d)·C + (K-(V-d))·S = K·T   =>   d = V - K×(S-T)/(S-C)
    d 即恢复补加所需的最小排出量；排出后的糖浆剂量仍按原质量守恒公式计算。
    以完整精度比较 d 与本次最多可排出量 D：
    d <= D  → 可执行（终态恰好不超过容量）
    d >  D  → 超出排出上限（仍缺少 d-D，不给出可执行剂量）

稳健刻度方案（允许补加后由操作员发起，不改写判定与腾容方案）：
    现场泵按固定刻度投料，剂量为正整数 n 个刻度 nQ；糖浆实际糖度在
    [S-U, S+U] 内波动。对剂量 x 与糖浆糖度 s，终态糖度为
        f(x, s) = (V·C + x·s) / (V + x)
    刻度 n 的最坏偏差为两个端点终态糖度偏离 T 的最大者：
        W(n) = max(|f(nQ, S-U) - T|, |f(nQ, S+U) - T|)
    在 V+nQ ≤ K 的正整数刻度中选 W 最小者，同值取较小 n。
    记 A = V×(T-C)：两端点偏差分支在 x* = A/(S-T) 处相交（即名义补加量），
    W 在 (0, x*] 严格下降、在 [x*, +∞) 严格上升，故离散最优只可能出现在
    实数断点（容量上界 K-V、两端点命中 T 的 A/(S∓U-T)、分支相交 A/(S-T)）
    相邻整数或边界刻度上，无需逐刻度扫描，结果与穷举定义的全局最优一致。
    最优偏差 ≤ E → 有稳健刻度（展示剂量、终态糖度区间与最坏偏差）
    最优偏差 > E → 无稳健刻度（展示最小容差缺口 最优偏差-E）
    容量放不下一个刻度（V+Q > K）→ 业务结果，不按字段错误拒绝
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext
from fractions import Fraction

from .schemas import (
    DRAIN_INPUT_NAMES,
    FIELD_NAMES,
    ROBUST_INPUT_NAMES,
    DrainPlanRequest,
    JudgeRequest,
    RobustPlanRequest,
)

ALLOWED = "ALLOWED"
FORBIDDEN = "FORBIDDEN"
VERDICT_MESSAGES = {ALLOWED: "允许补加", FORBIDDEN: "禁止补加"}

EXECUTABLE = "EXECUTABLE"
EXCEEDS_LIMIT = "EXCEEDS_LIMIT"
DRAIN_MESSAGES = {EXECUTABLE: "可执行", EXCEEDS_LIMIT: "超出排出上限"}

ROBUST = "ROBUST"
NO_ROBUST_SCALE = "NO_ROBUST_SCALE"
CAPACITY_INSUFFICIENT = "CAPACITY_INSUFFICIENT"
ROBUST_MESSAGES = {
    ROBUST: "有稳健刻度",
    NO_ROBUST_SCALE: "无稳健刻度",
    CAPACITY_INSUFFICIENT: "容量放不下一个刻度",
}

# decimal 计算精度（有效数字位数），远高于展示所需的四位小数
COMPUTE_PRECISION = 50
# 大整数输入时在输入整数位数 L 之上追加的保护位。
# 各输入最多四位小数、糖度不超过 100：
#   容量间隙 V+x−K、最小排出量 d、排出缺口 d−D 非零时绝对值恒 ≥ 1e-10；
#   稳健刻度的偏差−容差间隙分母含 V+x（量级 10^L），非零时间隙 ≥ 约 5×10^-(L+13)。
# 连锁十进制在 L+20 位精度下的绝对舍入误差 < 10^(L+2)×10^-(L+20) = 1e-18（终态量级），
# 对偏差（量级 ≤100）更小于 1e-(L+17)，严格小于上述所有间隙下界，
# 故展示值的末位舍入永远不可能与精确判定（Fraction）的符号或相等关系相矛盾。
PRECISION_GUARD = 20


@dataclass
class FieldError:
    field: str | None  # None 表示不定位到具体字段的全局错误
    message: str


class JudgeRejected(Exception):
    """输入校验失败，整单拒绝。"""

    def __init__(self, errors: list[FieldError]) -> None:
        super().__init__("输入校验失败，已整单拒绝")
        self.errors = errors


def _fraction(value: Decimal) -> Fraction:
    """有限 Decimal 到精确 Fraction 的无损转换。

    所有判定（容量比较、排出比较、容量边界刻度、断点择优）都在 Fraction 上完成，
    任何固定有效数字精度都不可能因舍入改变判定结论。
    """
    sign, digits, exponent = value.as_tuple()
    numerator = int("".join(map(str, digits))) if digits else 0
    if sign:
        numerator = -numerator
    if exponent >= 0:
        return Fraction(numerator * 10**exponent, 1)
    return Fraction(numerator, 10**-exponent)


def _adaptive_precision(values) -> int:
    """按输入位数自适应的 decimal 精度。

    常规输入仍取 50 位有效数字（与既有契约一致）；当输入整数部分超过 50 位时，
    扩展为 最大输入位数 + 保护位，使结果中相对输入不足 50 位的修正量（例如精确解
    与容量之间的 1/2）不被舍入抹掉。展示用精度只影响字符串，判定始终以 Fraction 为准。
    """
    precision = COMPUTE_PRECISION
    for value in values:
        sign, digits, exponent = value.as_tuple()
        integer_digits = len(digits) + min(exponent, 0)
        precision = max(precision, integer_digits + PRECISION_GUARD)
    return precision


def _plain(value: Decimal) -> str:
    """完整精度十进制字符串（不使用科学计数法）。"""
    return format(value, "f")


def _decimal_from_fraction(value: Fraction, precision: int) -> Decimal:
    """精确 Fraction 在给定有效数字精度下的最近舍入（ROUND_HALF_EVEN）。

    大整数输入下“两个 O(1) 量相减得 1e-61 量级偏差”会在连锁十进制中发生
    灾难性抵消；直接由精确有理数舍入可给出该精度下正确的偏差值。
    """
    with localcontext() as ctx:
        ctx.prec = precision
        return Decimal(value.numerator) / Decimal(value.denominator)


def _strip(value: Decimal) -> str:
    """输入回显规范化：去除无意义尾零（精确、不受 decimal 上下文精度影响）。

    Decimal.normalize() 会按当前上下文精度舍入系数，直接用于超过该位数的输入会
    把回显值抹成整百整千；这里按 as_tuple 手工展开，任意位数都精确还原。
    """
    sign, digits, exponent = value.as_tuple()
    body = "".join(map(str, digits))
    if exponent >= 0:
        body += "0" * exponent
    else:
        places = -exponent
        if places < len(body):
            body = body[:-places] + "." + body[-places:]
        else:
            body = "0." + "0" * (places - len(body)) + body
    if "." in body:
        body = body.rstrip("0").rstrip(".")
    if body in ("", "0"):
        return "0"
    return ("-" if sign else "") + body


def _validate_relations(req: JudgeRequest) -> None:
    """关系校验：0<C<T<S≤100、V>0、K>0、V≤K。收集全部违规并定位字段。"""
    errors: list[FieldError] = []
    V, C, T, S, K = req.V, req.C, req.T, req.S, req.K
    if C <= 0:
        errors.append(FieldError("C", "当前糖度 C 必须大于 0"))
    if T <= C:
        errors.append(FieldError("T", "目标糖度 T 必须大于当前糖度 C"))
    if S <= T:
        errors.append(FieldError("S", "糖浆糖度 S 必须大于目标糖度 T"))
    if S > 100:
        errors.append(FieldError("S", "糖浆糖度 S 不能超过 100"))
    if V <= 0:
        errors.append(FieldError("V", "当前体积 V 必须大于 0"))
    if K <= 0:
        errors.append(FieldError("K", "罐体容量 K 必须大于 0"))
    if V > K:
        errors.append(FieldError("V", "当前体积 V 不能超过罐体容量 K"))
    if errors:
        raise JudgeRejected(errors)


def judge(req: JudgeRequest) -> dict:
    """计算唯一补加量并判定容量。关系错误时抛出 JudgeRejected 整单拒绝。"""
    _validate_relations(req)
    V, C, T, S, K = req.V, req.C, req.T, req.S, req.K
    precision = _adaptive_precision((V, K))
    # 判定走精确有理数：任何固定有效数字精度都不能决定 V+x 与 K 的关系
    v, c, t, s, k = (_fraction(x) for x in (V, C, T, S, K))
    dose_f = v * (t - c) / (s - t)
    final_f = v + dose_f
    allowed = final_f <= k
    # 展示链保持历史算式（常规输入仍为 50 位有效数字），仅大整数输入自适应提精度
    with localcontext() as ctx:
        ctx.prec = precision
        dose = V * (T - C) / (S - T)
        final_volume = V + dose
        # 边界钳制：精确终态恰等于容量时直接展示精确边界，避免大整数输入下
        # 末位舍入噪声（如放行却显示 V+x 比 K 大）；常规 50 位精度保持原值不变
        if precision > COMPUTE_PRECISION and final_f == k:
            final_volume = K
        remaining = K - final_volume if allowed else None
        excess = final_volume - K if not allowed else None
    verdict = ALLOWED if allowed else FORBIDDEN
    return {
        "verdict": verdict,
        "message": VERDICT_MESSAGES[verdict],
        "dose": _plain(dose),
        "finalVolume": _plain(final_volume),
        "remainingCapacity": _plain(remaining) if remaining is not None else None,
        "excess": _plain(excess) if excess is not None else None,
        "inputs": {name: _strip(getattr(req, name)) for name in FIELD_NAMES},
    }


def _validate_drain_limit(req: DrainPlanRequest) -> None:
    """排出上限 D 的关系校验：非负且必须小于当前体积 V。"""
    errors: list[FieldError] = []
    if req.D < 0:
        errors.append(FieldError("D", "排出上限 D 不能为负数"))
    if req.D >= req.V:
        errors.append(FieldError("D", "排出上限 D 必须小于当前体积 V"))
    if errors:
        raise JudgeRejected(errors)


def drain_plan(req: DrainPlanRequest) -> dict:
    """计算恢复补加所需的最小排出量并判定是否超出排出上限。

    复用判定五项的关系校验；任何输入非法时抛出 JudgeRejected 整单拒绝。
    本函数只产出方案，绝不改写 /api/judge 的判定结论。
    """
    _validate_relations(req)
    _validate_drain_limit(req)
    V, C, T, S, K, D = req.V, req.C, req.T, req.S, req.K, req.D
    precision = _adaptive_precision((V, K))
    # 排出量符号与可执行性比较走精确有理数，舍入不得改写判定
    v, c, t, s, k, d_limit = (_fraction(x) for x in (V, C, T, S, K, D))
    # 排出料液糖度仍为 C：反解终态恰为 (K, T) 所需的最小排出量
    min_drain_f = v - k * (s - t) / (s - c)
    # d <= 0 ⟺ V+x <= K：判定实为允许补加，无需排出，不生成腾容方案
    if min_drain_f <= 0:
        raise JudgeRejected([FieldError(None, "当前判定允许补加，无需腾容方案")])
    # 以完整精度比较最小排出量与本次最多可排出量
    executable = min_drain_f <= d_limit
    if executable:
        volume_after_f = v - min_drain_f
        # 排出后的糖浆剂量仍按原质量守恒公式计算
        dose_f = volume_after_f * (t - c) / (s - t)
        final_f = volume_after_f + dose_f
    else:
        volume_after_f = dose_f = final_f = None
    # 展示链保持历史算式（常规输入仍为 50 位有效数字），仅大整数输入自适应提精度
    with localcontext() as ctx:
        ctx.prec = precision
        min_drain = V - K * (S - T) / (S - C)
        if executable:
            volume_after = V - min_drain
            dose = volume_after * (T - C) / (S - T)
            final_volume = volume_after + dose
            # 边界钳制：最小排出量下终态在精确意义下恰等于容量，直接展示精确边界，
            # 避免大整数输入下末位舍入噪声；常规 50 位精度保持原值不变
            if precision > COMPUTE_PRECISION and final_f == k:
                final_volume = K
            shortfall = None
        else:
            volume_after = dose = final_volume = None
            shortfall = min_drain - D
    status = EXECUTABLE if executable else EXCEEDS_LIMIT
    return {
        "status": status,
        "message": DRAIN_MESSAGES[status],
        "minDrain": _plain(min_drain),
        "volumeAfterDrain": _plain(volume_after) if volume_after is not None else None,
        "dose": _plain(dose) if dose is not None else None,
        "finalVolume": _plain(final_volume) if final_volume is not None else None,
        "shortfall": _plain(shortfall) if shortfall is not None else None,
        "inputs": {name: _strip(getattr(req, name)) for name in DRAIN_INPUT_NAMES},
    }


def _validate_robust_params(req: RobustPlanRequest) -> None:
    """稳健刻度三项的关系校验：Q>0、U≥0、S-U>T、S+U≤100、E≥0。

    按 Q、U、E 顺序收集全部违规并定位字段，整单拒绝。
    """
    errors: list[FieldError] = []
    if req.Q <= 0:
        errors.append(FieldError("Q", "单刻度量 Q 必须大于 0"))
    if req.U < 0:
        errors.append(FieldError("U", "糖度波动 U 不能为负数"))
    if req.S - req.U <= req.T:
        errors.append(FieldError("U", "糖度波动下界 S-U 必须大于目标糖度 T"))
    if req.S + req.U > 100:
        errors.append(FieldError("U", "糖度波动上界 S+U 不能超过 100"))
    if req.E < 0:
        errors.append(FieldError("E", "终态容差 E 不能为负数"))
    if errors:
        raise JudgeRejected(errors)


def _floor(value: Fraction) -> int:
    """Fraction 向下取整（整除向负无穷）。"""
    return value.numerator // value.denominator


def _worst_deviation(
    n: int,
    q: Fraction,
    v: Fraction,
    c: Fraction,
    t: Fraction,
    low: Fraction,
    high: Fraction,
) -> Fraction:
    """刻度 n（剂量 nq）在两个端点糖度下最坏偏差的精确有理数 W(n)。"""
    x = q * n
    final_low = (v * c + x * low) / (v + x)
    final_high = (v * c + x * high) / (v + x)
    return max(abs(final_low - t), abs(final_high - t))


def robust_plan(req: RobustPlanRequest) -> dict:
    """在固定刻度与糖度波动下选择最坏端点偏差最小的刻度 n（剂量 nQ）。

    复用判定五项的关系校验；任何输入非法时抛出 JudgeRejected 整单拒绝。
    本函数只产出方案，绝不改写 /api/judge 的判定结论与 /api/drain-plan 的方案。

    算法不逐刻度扫描：最坏偏差 W 作为剂量 x 的函数在偏差分支相交处
    x* = V×(T-C)/(S-T) 两侧分别严格下降、严格上升，故离散最优只可能出现在
    实数断点（容量上界、两端点命中 T、分支相交）相邻整数或边界刻度上；
    仅评估这些候选，同值取较小 n，结果与穷举定义的全局最优一致。
    """
    _validate_relations(req)
    _validate_robust_params(req)
    V, C, T, S, K = req.V, req.C, req.T, req.S, req.K
    Q, U, E = req.Q, req.U, req.E
    inputs = {name: _strip(getattr(req, name)) for name in ROBUST_INPUT_NAMES}
    precision = _adaptive_precision((V, K, Q))
    # 容量边界、断点与择优全部走精确有理数：固定有效数字不得决定可行刻度或最优刻度
    v, c, t, s, k, q, e = (_fraction(x) for x in (V, C, T, S, K, Q, E))
    low_syrup = s - _fraction(U)  # > t（关系校验保证）
    high_syrup = s + _fraction(U)  # ≤ 100
    a = v * (t - c)
    # 实数断点（以剂量 x 计）：容量上界、两个端点命中 T、偏差分支相交
    capacity_dose = k - v
    breakpoints = (
        capacity_dose,
        a / (low_syrup - t),
        a / (high_syrup - t),
        a / (s - t),
    )
    # 容量边界刻度：满足 V + nQ ≤ K 的最大正整数 n（精确向下取整）
    n_max = _floor(capacity_dose / q)
    if n_max < 1:
        # 容量放不下一个刻度：业务结果，不按字段错误拒绝
        status = CAPACITY_INSUFFICIENT
        plan = {
            "n": None,
            "dose": None,
            "finalSugarLow": None,
            "finalSugarHigh": None,
            "worstDeviation": None,
            "toleranceGap": None,
        }
    else:
        # 候选刻度：边界刻度 + 各实数断点的相邻整数，绝不逐刻度扫描
        candidates = {1, n_max}
        for point in breakpoints:
            lower = _floor(point / q)
            for n in (lower, lower + 1):
                if 1 <= n <= n_max:
                    candidates.add(n)
        best_n = None
        best_deviation = None
        for n in sorted(candidates):
            deviation = _worst_deviation(n, q, v, c, t, low_syrup, high_syrup)
            # 按 n 升序评估，严格更小才替换：同值保留较小 n
            if best_deviation is None or deviation < best_deviation:
                best_n, best_deviation = n, deviation
        # 展示链：常规输入保持历史连锁十进制（50 位有效数字）；
        # 大整数输入改由精确有理数直接舍入，避免 O(1) 量相减得微小偏差时的灾难性抵消
        if precision > COMPUTE_PRECISION:
            x_f = q * best_n
            # nQ 恒为有限十进制（Q 至多四位小数、n 为整数），由精确有理数直接还原
            x = _decimal_from_fraction(x_f, precision)
            low_f = (v * c + x_f * low_syrup) / (v + x_f)
            high_f = (v * c + x_f * high_syrup) / (v + x_f)
            best_low = _decimal_from_fraction(low_f, precision)
            best_high = _decimal_from_fraction(high_f, precision)
            # 最坏偏差恰等于容差时直接展示 E，与 ROBUST（≤ E）结论自洽
            display_deviation = E if best_deviation == e else _decimal_from_fraction(
                best_deviation, precision
            )
            gap_decimal = _decimal_from_fraction(best_deviation - e, precision)
        else:
            with localcontext() as ctx:
                ctx.prec = precision
                x = Q * best_n
                best_low = (V * C + x * (S - U)) / (V + x)
                best_high = (V * C + x * (S + U)) / (V + x)
                display_deviation = max(abs(best_low - T), abs(best_high - T))
                gap_decimal = display_deviation - E
        if best_deviation <= e:
            status = ROBUST
            plan = {
                "n": best_n,
                "dose": _plain(x),
                "finalSugarLow": _plain(best_low),
                "finalSugarHigh": _plain(best_high),
                "worstDeviation": _plain(display_deviation),
                "toleranceGap": None,
            }
        else:
            status = NO_ROBUST_SCALE
            plan = {
                "n": None,
                "dose": None,
                "finalSugarLow": None,
                "finalSugarHigh": None,
                "worstDeviation": None,
                "toleranceGap": _plain(gap_decimal),
            }
    return {"status": status, "message": ROBUST_MESSAGES[status], **plan, "inputs": inputs}
