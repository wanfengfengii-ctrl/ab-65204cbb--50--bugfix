/**
 * 将完整精度十进制字符串格式化为展示值：
 * 最多保留四位小数（四舍五入），并去除无意义尾零。
 *
 * 若精确值非零但按四位小数舍入后为 0（|值| < 0.00005），
 * 返回 "<0.0001"（负值为 ">-0.0001"）以明确指示仍有微量，
 * 避免与「禁止补加」等判定结论矛盾。
 *
 * 注意：本函数仅用于展示。容量判定必须使用后端返回的完整精度计算值，
 * 本函数的输出不得参与任何判定。
 */
export function formatDecimal(exact: string, maxDecimals = 4): string {
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(exact.trim());
  if (!match) {
    throw new Error(`无法解析的十进制字符串: ${exact}`);
  }
  const [, sign, intPart, fracPart = ''] = match;
  const digits = (intPart + fracPart).split('').map((ch) => ch.charCodeAt(0) - 48);
  const keep = intPart.length + maxDecimals;
  const kept = digits.slice(0, keep);
  const rest = digits.slice(keep);

  // 四舍五入：被舍弃部分的最高位 >= 5 则进位
  if (rest.length > 0 && rest[0] >= 5) {
    let i = kept.length - 1;
    while (i >= 0 && kept[i] === 9) {
      kept[i] = 0;
      i -= 1;
    }
    if (i < 0) {
      kept.unshift(1);
    } else {
      kept[i] += 1;
    }
  }
  while (kept.length < keep) kept.push(0);

  const intLen = kept.length - maxDecimals;
  let intStr = kept.slice(0, intLen).join('').replace(/^0+(?=\d)/, '');
  if (intStr === '') intStr = '0';
  const fracStr = kept.slice(intLen).join('').replace(/0+$/, '');
  const body = fracStr ? `${intStr}.${fracStr}` : intStr;
  if (body === '0') {
    // 精确值非零而展示舍入为零：指示微量而非显示 0
    if (/[1-9]/.test(intPart + fracPart)) {
      const unit = `0.${'0'.repeat(maxDecimals - 1)}1`;
      return sign === '-' ? `>-${unit}` : `<${unit}`;
    }
    return '0'; // 精确零（含负零）归一
  }
  return sign === '-' ? `-${body}` : body;
}
