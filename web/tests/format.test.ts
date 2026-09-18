import { describe, expect, it } from 'vitest';
import { formatDecimal } from '../src/lib/format';

describe('formatDecimal 展示格式化', () => {
  it('最多保留四位小数并四舍五入', () => {
    expect(formatDecimal('68.181818181818181818181818181818181818181818181818')).toBe('68.1818');
    expect(formatDecimal('31.81818181818181818181818181818181818181818181818')).toBe('31.8182');
    expect(formatDecimal('0.00005')).toBe('0.0001');
    expect(formatDecimal('1.000049999')).toBe('1');
  });

  it('非零但舍入为零时指示微量而非显示 0', () => {
    // 真实微量溢出值：超出 0.00000400008... mL，禁止补加但不得显示超出量为 0
    expect(formatDecimal('0.000004000080001600032000640012800256005120102')).toBe('<0.0001');
    expect(formatDecimal('0.000049999')).toBe('<0.0001');
    expect(formatDecimal('0.00001')).toBe('<0.0001');
    // 恰好达到最小展示单位的边界仍按四舍五入显示
    expect(formatDecimal('0.00005')).toBe('0.0001');
    // 负值微量
    expect(formatDecimal('-0.00001')).toBe('>-0.0001');
  });

  it('去除无意义尾零', () => {
    expect(formatDecimal('8.00')).toBe('8');
    expect(formatDecimal('31.8200')).toBe('31.82');
    expect(formatDecimal('100')).toBe('100');
    expect(formatDecimal('0.5000')).toBe('0.5');
    expect(formatDecimal('568.18180000')).toBe('568.1818');
  });

  it('小数进位可传播到整数部分', () => {
    expect(formatDecimal('99.99996')).toBe('100');
    expect(formatDecimal('9.99999')).toBe('10');
    expect(formatDecimal('0.99999')).toBe('1');
  });

  it('超大整数不丢精度（纯字符串运算）', () => {
    expect(formatDecimal('123456789012345678.12345')).toBe('123456789012345678.1235');
    expect(formatDecimal('99999999999999999999.99999')).toBe('100000000000000000000');
  });

  it('精确零（含负零）归一显示为 0', () => {
    expect(formatDecimal('0')).toBe('0');
    expect(formatDecimal('0.0000')).toBe('0');
    expect(formatDecimal('-0')).toBe('0');
    expect(formatDecimal('-0.0000')).toBe('0');
  });

  it('负数正常格式化', () => {
    expect(formatDecimal('-1.23456')).toBe('-1.2346');
  });

  it('非法输入抛错', () => {
    expect(() => formatDecimal('abc')).toThrow();
    expect(() => formatDecimal('')).toThrow();
  });
});
