"""补加判定核心逻辑。

质量守恒（液体密度相同，按体积折算）：
    V·C + x·S = (V + x)·T   =>   x = V×(T-C)/(S-T)

判定使用完整精度的计算值，绝不使用经展示格式化处理后的数值：
    V + x <= K  → 允许补加（等于容量也允许）
    V + x >  K  → 禁止补加

输入均为有限、至多四位小数的十进制数，因此所有判定比较都是有理数比较，
一律以 fractions.Fraction 精确交叉相乘完成（整数位再长也不丢低位），
不依赖任何固定有效数字精度；decimal 仅用于产出展示值，其精度随输入
整数位数自适应放大（常规输入仍为 50 位有效数字）。

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
    容量边界 n_max = floor((K-V)/Q)、各断点相邻整数与 W≤E 的容差判定均为
    精确有理运算，绝不舍去低位而把溢罐刻度当作可行刻度；decimal 仅用于展示。
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
# 超过该整数位数的输入会让固定 50 位精度损失低位（判定已全程精确，
# 此余量仅保证展示值能忠实反映精确判定，例如溢罐量为 1 个最小单位）
PRECISION_MARGIN = 10


@dataclass
class FieldError:
    field: str | None  # None 表示不定位到具体字段的全局错误
    message: str


class JudgeRejected(Exception):
    """输入校验失败，整单拒绝。"""

    def __init__(self, errors: list[FieldError]) -> None:
        super().__init__("输入校验失败，已整单拒绝")
        self.errors = errors


def _frac(value: Decimal) -> Fraction:
    """有限 Decimal 转精确 Fraction（无任何舍入）。"""
    return Fraction(value)


def _input_precision(values) -> int:
    """按输入整数位数自适应的 decimal 有效数字位数。

    常规输入保持 COMPUTE_PRECISION；整数部分超过 50 位时按最长输入
    加上余量放大，使判定差值（可能只有 1 个最小单位）在展示值中不被吞掉。
    """
    needed = COMPUTE_PRECISION
    for value in values:
        sig_digits = max(1, len(value.as_tuple().digits))
        needed = max(needed, sig_digits + PRECISION_MARGIN)
    return needed


def _exact_floor(ratio: Fraction) -> int:
    """floor(p/q) 的精确整数结果（q>0），任何位数都不发生二进制/精度溢出。"""
    return ratio.numerator // ratio.denominator


def _plain(value) -> str:
    """完整精度十进制字符串（不使用科学计数法）。"""
    return format(value, "f")


def _strip(value: Decimal) -> str:
    """输入回显规范化：去除无意义尾零。"""
    return format(value.normalize(), "f")


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
    """计算唯一补加量并判定容量。关系错误时抛出 JudgeRejected 整单拒绝。

    容量判定是精确有理数比较：V+x ≤ K ⟺ V×(S-C) ≤ K×(S-T)
    （分母 S-T>0 由关系校验保证），不经过任何有限精度舍入。
    """
    _validate_relations(req)
    V, C, T, S, K = req.V, req.C, req.T, req.S, req.K
    v, c, t, s, k = (_frac(x) for x in (V, C, T, S, K))
    # 精确判定（完整精度计算值）：x = V(T-C)/(S-T)
    allowed = v * (s - c) <= k * (s - t)
    precision = _input_precision((V, C, T, S, K))
    with localcontext() as ctx:
        ctx.prec = precision
        dose_dec = V * (T - C) / (S - T)
        final_volume = V + dose_dec
        remaining = K - final_volume if allowed else None
        excess = final_volume - K if not allowed else None
    verdict = ALLOWED if allowed else FORBIDDEN
    return {
        "verdict": verdict,
        "message": VERDICT_MESSAGES[verdict],
        "dose": _plain(dose_dec),
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

    两个判定均为精确有理数比较（分母 S-C>0 由关系校验保证）：
        d <= 0 ⟺ V×(S-C) <= K×(S-T)（等价于原判定允许补加，拒绝出方案）
        d <= D ⟺ (V-D)×(S-C) <= K×(S-T)
    """
    _validate_relations(req)
    _validate_drain_limit(req)
    V, C, T, S, K, D = req.V, req.C, req.T, req.S, req.K, req.D
    v, c, t, s, k, d_limit = (_frac(x) for x in (V, C, T, S, K, D))
    # d <= 0 ⟺ V+x <= K：判定实为允许补加，无需排出，不生成腾容方案
    if v * (s - c) <= k * (s - t):
        raise JudgeRejected([FieldError(None, "当前判定允许补加，无需腾容方案")])
    # 以完整精度比较最小排出量与本次最多可排出量
    executable = (v - d_limit) * (s - c) <= k * (s - t)
    precision = _input_precision((V, C, T, S, K, D))
    with localcontext() as ctx:
        ctx.prec = precision
        # 排出料液糖度仍为 C：反解终态恰为 (K, T) 所需的最小排出量
        min_drain = V - K * (S - T) / (S - C)
        if executable:
            volume_after = V - min_drain
            # 排出后的糖浆剂量仍按原质量守恒公式计算
            dose = volume_after * (T - C) / (S - T)
            final_volume = volume_after + dose
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


def _exact_endpoint_deviation(
    n: int,
    q: Fraction,
    v: Fraction,
    c: Fraction,
    t: Fraction,
    low: Fraction,
    high: Fraction,
) -> Fraction:
    """刻度 n（剂量 nQ）最坏偏差 W(n) 的精确有理值。

    f(nq, s) - T = nq×(s-T) - V×(T-C)，分母 V+nq 对两个端点相同，
    故比较两端点偏差大小时只需比较正分子，无需做任何除法。
    """
    x = q * n
    a = v * (t - c)  # A = V×(T-C)
    dev_low_num = abs(x * (low - t) - a)
    dev_high_num = abs(x * (high - t) - a)
    return max(dev_low_num, dev_high_num) / (v + x)


def robust_plan(req: RobustPlanRequest) -> dict:
    """在固定刻度与糖度波动下选择最坏端点偏差最小的刻度 n（剂量 nQ）。

    复用判定五项的关系校验；任何输入非法时抛出 JudgeRejected 整单拒绝。
    本函数只产出方案，绝不改写 /api/judge 的判定结论与 /api/drain-plan 的方案。

    算法不逐刻度扫描：最坏偏差 W 作为剂量 x 的函数在偏差分支相交处
    x* = V×(T-C)/(S-T) 两侧分别严格下降、严格上升，故离散最优只可能出现在
    实数断点（容量上界、两端点命中 T、分支相交）相邻整数或边界刻度上；
    仅评估这些候选，同值取较小 n，结果与穷举定义的全局最优一致。

    容量边界 floor((K-V)/Q)、断点相邻整数与 W≤E 容差比较全部使用
    精确有理数运算：整数部分再长也不会因固定有效数字精度把溢罐刻度
    （V+nQ>K）上舍入成可行刻度。
    """
    _validate_relations(req)
    _validate_robust_params(req)
    V, C, T, S, K = req.V, req.C, req.T, req.S, req.K
    Q, U, E = req.Q, req.U, req.E
    inputs = {name: _strip(getattr(req, name)) for name in ROBUST_INPUT_NAMES}

    v, c, t, s, k = (_frac(x) for x in (V, C, T, S, K))
    q, u, e = _frac(Q), _frac(U), _frac(E)
    low_syrup = s - u  # > t（关系校验保证）
    high_syrup = s + u  # ≤ 100
    a = v * (t - c)  # A = V×(T-C)
    capacity_dose = k - v
    # 容量边界刻度：满足 V + nQ ≤ K 的最大正整数 n（精确 floor，不舍低位）
    n_max = _exact_floor(capacity_dose / q)
    # 实数断点（以剂量 x 计）：容量上界、两个端点命中 T、偏差分支相交
    breakpoints = (
        capacity_dose,
        a / (low_syrup - t),
        a / (high_syrup - t),
        a / (s - t),
    )
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
            lower = _exact_floor(point / q)
            for n in (lower, lower + 1):
                if 1 <= n <= n_max:
                    candidates.add(n)
        # 候选 W 的精确有理比较：严格更小才替换，按 n 升序评估故同值保留较小 n
        best_n = None
        best_deviation = None
        for n in sorted(candidates):
            deviation = _exact_endpoint_deviation(
                n, q, v, c, t, low_syrup, high_syrup
            )
            if best_deviation is None or deviation < best_deviation:
                best_n, best_deviation = n, deviation
        precision = _input_precision((V, C, T, S, K, Q, U, E))
        with localcontext() as ctx:
            ctx.prec = precision
            # 展示值仍以 decimal 计算（常规输入 50 位有效数字，与既有契约一致）；
            # 择优与容差判定已在上方以精确有理数完成
            low_dec, high_dec = S - U, S + U
            dose_dec = Q * best_n
            final_low = (V * C + dose_dec * low_dec) / (V + dose_dec)
            final_high = (V * C + dose_dec * high_dec) / (V + dose_dec)
            worst_dec = max(abs(final_low - T), abs(final_high - T))
            if best_deviation <= e:
                status = ROBUST
                plan = {
                    "n": best_n,
                    "dose": _plain(dose_dec),
                    "finalSugarLow": _plain(final_low),
                    "finalSugarHigh": _plain(final_high),
                    "worstDeviation": _plain(worst_dec),
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
                    "toleranceGap": _plain(worst_dec - E),
                }
    return {"status": status, "message": ROBUST_MESSAGES[status], **plan, "inputs": inputs}
