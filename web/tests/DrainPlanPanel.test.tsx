import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { DrainPlanPanel } from '../src/components/DrainPlanPanel';
import type { DrainPlanResponse } from '../src/lib/api';

// 响应取自真实 API 计算结果：d = 500-550×22/25 = 16，排出后 484，补加 66，终态恰为 550
const executablePlan: DrainPlanResponse = {
  status: 'EXECUTABLE',
  message: '可执行',
  minDrain: '16',
  volumeAfterDrain: '484',
  dose: '66',
  finalVolume: '550',
  shortfall: null,
  inputs: { V: '500', C: '5', T: '8', S: '30', K: '550', D: '20' },
};

const exceedsLimitPlan: DrainPlanResponse = {
  status: 'EXCEEDS_LIMIT',
  message: '超出排出上限',
  minDrain: '16',
  volumeAfterDrain: null,
  dose: null,
  finalVolume: null,
  shortfall: '6',
  inputs: { V: '500', C: '5', T: '8', S: '30', K: '550', D: '10' },
};

function renderPanel(overrides: Partial<Parameters<typeof DrainPlanPanel>[0]> = {}) {
  const props = {
    plan: null,
    value: '',
    onValueChange: vi.fn(),
    fieldError: null,
    globalError: null,
    submitting: false,
    onSubmit: vi.fn(),
    ...overrides,
  };
  render(<DrainPlanPanel {...props} />);
  return props;
}

describe('DrainPlanPanel 入口与提交', () => {
  it('渲染 D 输入与生成入口', () => {
    renderPanel();
    expect(screen.getByTestId('drain-entry')).toHaveTextContent('生成腾容方案');
    expect(screen.getByLabelText('本次最多可排出量 D（mL）')).toBeInTheDocument();
    expect(screen.queryByTestId('drain-result')).toBeNull();
  });

  it('提交表单触发生成回调', () => {
    const props = renderPanel({ value: '20' });
    fireEvent.click(screen.getByTestId('drain-entry'));
    expect(props.onSubmit).toHaveBeenCalledTimes(1);
  });

  it('D 的字段错误定位到输入框', () => {
    renderPanel({ fieldError: '排出上限 D 不能为负数' });
    expect(screen.getByTestId('error-D')).toHaveTextContent('排出上限 D 不能为负数');
    expect(screen.getByLabelText('本次最多可排出量 D（mL）')).toHaveAttribute(
      'aria-invalid',
      'true',
    );
  });
});

describe('DrainPlanPanel 方案展示', () => {
  it('可执行：展示最小排出量、排出后体积、补加量与终态', () => {
    renderPanel({ plan: executablePlan });
    expect(screen.getByTestId('drain-status')).toHaveTextContent('可执行');
    expect(screen.getByTestId('drain-min')).toHaveTextContent('16');
    expect(screen.getByTestId('drain-volume-after')).toHaveTextContent('484');
    expect(screen.getByTestId('drain-dose')).toHaveTextContent('66');
    expect(screen.getByTestId('drain-final-volume')).toHaveTextContent('550');
    expect(screen.queryByTestId('drain-shortfall')).toBeNull();
  });

  it('超出排出上限：只展示仍缺少的排出量，不呈现可执行剂量', () => {
    renderPanel({ plan: exceedsLimitPlan });
    expect(screen.getByTestId('drain-status')).toHaveTextContent('超出排出上限');
    expect(screen.getByTestId('drain-shortfall')).toHaveTextContent('6');
    expect(screen.queryByTestId('drain-dose')).toBeNull();
    expect(screen.queryByTestId('drain-min')).toBeNull();
    expect(screen.queryByTestId('drain-final-volume')).toBeNull();
  });

  it('请求级错误展示为全局错误而非方案', () => {
    renderPanel({ globalError: '无法连接判定服务，请稍后重试' });
    expect(screen.getByTestId('drain-error')).toHaveTextContent('无法连接判定服务');
    expect(screen.queryByTestId('drain-result')).toBeNull();
  });
});
