import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { RobustPlanPanel } from '../src/components/RobustPlanPanel';
import type { RobustPlanResponse } from '../src/lib/api';

// 响应取自真实 API 计算结果：最优刻度 n=7，剂量 70，
// 终态糖度区间 [4460/570, 4740/570]，最坏偏差 6/19
const robustPlan: RobustPlanResponse = {
  status: 'ROBUST',
  message: '有稳健刻度',
  n: 7,
  dose: '70',
  finalSugarLow: '7.8245614035087719298245614035087719298245614035088',
  finalSugarHigh: '8.3157894736842105263157894736842105263157894736842',
  worstDeviation: '0.3157894736842105263157894736842105263157894736842',
  toleranceGap: null,
  inputs: { V: '500', C: '5', T: '8', S: '30', K: '600', Q: '10', U: '2', E: '1' },
};

const noRobustPlan: RobustPlanResponse = {
  status: 'NO_ROBUST_SCALE',
  message: '无稳健刻度',
  n: null,
  dose: null,
  finalSugarLow: null,
  finalSugarHigh: null,
  worstDeviation: null,
  toleranceGap: '0.2157894736842105263157894736842105263157894736842',
  inputs: { V: '500', C: '5', T: '8', S: '30', K: '600', Q: '10', U: '2', E: '0.1' },
};

const capacityInsufficientPlan: RobustPlanResponse = {
  status: 'CAPACITY_INSUFFICIENT',
  message: '容量放不下一个刻度',
  n: null,
  dose: null,
  finalSugarLow: null,
  finalSugarHigh: null,
  worstDeviation: null,
  toleranceGap: null,
  inputs: { V: '500', C: '5', T: '8', S: '30', K: '550', Q: '100', U: '2', E: '1' },
};

function renderPanel(overrides: Partial<Parameters<typeof RobustPlanPanel>[0]> = {}) {
  const props = {
    plan: null,
    values: { Q: '', U: '', E: '' },
    onValueChange: vi.fn(),
    fieldErrors: {},
    globalError: null,
    submitting: false,
    onSubmit: vi.fn(),
    ...overrides,
  };
  render(<RobustPlanPanel {...props} />);
  return props;
}

describe('RobustPlanPanel 入口与提交', () => {
  it('渲染 Q/U/E 输入与生成入口', () => {
    renderPanel();
    expect(screen.getByTestId('robust-entry')).toHaveTextContent('生成稳健刻度方案');
    expect(screen.getByLabelText('单刻度量 Q（mL）')).toBeInTheDocument();
    expect(screen.getByLabelText('糖度波动 U（%）')).toBeInTheDocument();
    expect(screen.getByLabelText('终态容差 E（%）')).toBeInTheDocument();
    expect(screen.queryByTestId('robust-result')).toBeNull();
  });

  it('提交表单触发生成回调', () => {
    const props = renderPanel({ values: { Q: '10', U: '2', E: '1' } });
    fireEvent.click(screen.getByTestId('robust-entry'));
    expect(props.onSubmit).toHaveBeenCalledTimes(1);
  });

  it('输入变更回调携带字段名与新值', () => {
    const props = renderPanel();
    fireEvent.change(screen.getByLabelText('单刻度量 Q（mL）'), { target: { value: '10' } });
    expect(props.onValueChange).toHaveBeenCalledWith('Q', '10');
  });

  it('Q/U/E 的字段错误定位到对应输入框', () => {
    renderPanel({ fieldErrors: { Q: '单刻度量 Q 必须大于 0', E: '终态容差 E 不能为负数' } });
    expect(screen.getByTestId('error-Q')).toHaveTextContent('单刻度量 Q 必须大于 0');
    expect(screen.getByTestId('error-E')).toHaveTextContent('终态容差 E 不能为负数');
    expect(screen.getByLabelText('单刻度量 Q（mL）')).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByLabelText('糖度波动 U（%）')).toHaveAttribute('aria-invalid', 'false');
  });
});

describe('RobustPlanPanel 方案展示', () => {
  it('有稳健刻度：展示剂量、终态糖度区间与最坏偏差', () => {
    renderPanel({ plan: robustPlan });
    expect(screen.getByTestId('robust-status')).toHaveTextContent('有稳健刻度');
    expect(screen.getByTestId('robust-dose')).toHaveTextContent('70');
    expect(screen.getByTestId('robust-final-sugar')).toHaveTextContent('7.8246 ~ 8.3158');
    expect(screen.getByTestId('robust-worst-deviation')).toHaveTextContent('0.3158');
    expect(screen.queryByTestId('robust-tolerance-gap')).toBeNull();
  });

  it('无稳健刻度：只展示最小容差缺口，不呈现剂量', () => {
    renderPanel({ plan: noRobustPlan });
    expect(screen.getByTestId('robust-status')).toHaveTextContent('无稳健刻度');
    expect(screen.getByTestId('robust-tolerance-gap')).toHaveTextContent('0.2158');
    expect(screen.queryByTestId('robust-dose')).toBeNull();
    expect(screen.queryByTestId('robust-final-sugar')).toBeNull();
    expect(screen.queryByTestId('robust-worst-deviation')).toBeNull();
  });

  it('容量放不下一个刻度：仅展示结论', () => {
    renderPanel({ plan: capacityInsufficientPlan });
    expect(screen.getByTestId('robust-status')).toHaveTextContent('容量放不下一个刻度');
    expect(screen.queryByTestId('robust-dose')).toBeNull();
    expect(screen.queryByTestId('robust-tolerance-gap')).toBeNull();
  });

  it('请求级错误展示为全局错误而非方案', () => {
    renderPanel({ globalError: '无法连接判定服务，请稍后重试' });
    expect(screen.getByTestId('robust-error')).toHaveTextContent('无法连接判定服务');
    expect(screen.queryByTestId('robust-result')).toBeNull();
  });
});
