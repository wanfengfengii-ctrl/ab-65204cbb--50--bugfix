import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ResultPanel } from '../src/components/ResultPanel';
import type { JudgeResponse } from '../src/lib/api';

// 响应取自真实 API 计算结果
const allowedResponse: JudgeResponse = {
  verdict: 'ALLOWED',
  message: '允许补加',
  dose: '68.181818181818181818181818181818181818181818181818',
  finalVolume: '568.18181818181818181818181818181818181818181818182',
  remainingCapacity: '31.81818181818181818181818181818181818181818181818',
  excess: null,
  inputs: { V: '500', C: '5', T: '8', S: '30', K: '600' },
};

const forbiddenResponse: JudgeResponse = {
  ...allowedResponse,
  verdict: 'FORBIDDEN',
  message: '禁止补加',
  remainingCapacity: null,
  excess: '18.18181818181818181818181818181818181818181818182',
  inputs: { V: '500', C: '5', T: '8', S: '30', K: '550' },
};

// 真实 API 计算值：仅超出 0.00000400008... mL
const microOverflowResponse: JudgeResponse = {
  verdict: 'FORBIDDEN',
  message: '禁止补加',
  dose: '0.20000400008000160003200064001280025600512010240205',
  finalVolume: '10000.200004000080001600032000640012800256005120102',
  remainingCapacity: null,
  excess: '0.000004000080001600032000640012800256005120102',
  inputs: { V: '10000', C: '5', T: '5.0001', S: '10', K: '10000.2' },
};

describe('ResultPanel 放行主线', () => {
  it('集中展示公式代入、唯一补加量、终态体积、剩余容量与允许补加', () => {
    render(<ResultPanel result={allowedResponse} />);
    expect(screen.getByTestId('verdict')).toHaveTextContent('允许补加');
    expect(screen.getByTestId('formula')).toHaveTextContent(
      'x = V×(T-C)/(S-T) = 500×(8-5)/(30-8) = 68.1818',
    );
    expect(screen.getByTestId('dose')).toHaveTextContent('68.1818');
    expect(screen.getByTestId('final-volume')).toHaveTextContent('568.1818');
    expect(screen.getByTestId('remaining')).toHaveTextContent('31.8182');
    expect(screen.queryByTestId('excess')).toBeNull();
  });
});

describe('ResultPanel 溢罐主线', () => {
  it('展示超出量与禁止补加，不展示剩余容量', () => {
    render(<ResultPanel result={forbiddenResponse} />);
    expect(screen.getByTestId('verdict')).toHaveTextContent('禁止补加');
    expect(screen.getByTestId('dose')).toHaveTextContent('68.1818');
    expect(screen.getByTestId('excess')).toHaveTextContent('18.1818');
    expect(screen.queryByTestId('remaining')).toBeNull();
  });

  it('微量溢出明确显示 <0.0001 而非 0', () => {
    render(<ResultPanel result={microOverflowResponse} />);
    expect(screen.getByTestId('verdict')).toHaveTextContent('禁止补加');
    expect(screen.getByTestId('excess')).toHaveTextContent('<0.0001');
    expect(screen.getByTestId('excess')).not.toHaveTextContent(/^0$/);
  });
});

describe('ResultPanel 腾容入口承载', () => {
  it('禁止补加时渲染传入的腾容入口', () => {
    render(
      <ResultPanel result={forbiddenResponse}>
        <div data-testid="drain-slot">腾容入口</div>
      </ResultPanel>,
    );
    expect(screen.getByTestId('drain-slot')).toBeInTheDocument();
  });

  it('允许补加时不渲染腾容入口', () => {
    render(
      <ResultPanel result={allowedResponse}>
        <div data-testid="drain-slot">腾容入口</div>
      </ResultPanel>,
    );
    expect(screen.queryByTestId('drain-slot')).toBeNull();
  });
});

describe('ResultPanel 稳健刻度入口承载', () => {
  it('允许补加时渲染传入的稳健刻度入口', () => {
    render(
      <ResultPanel
        result={allowedResponse}
        allowedChildren={<div data-testid="robust-slot">稳健刻度入口</div>}
      />,
    );
    expect(screen.getByTestId('robust-slot')).toBeInTheDocument();
  });

  it('禁止补加时不渲染稳健刻度入口', () => {
    render(
      <ResultPanel
        result={forbiddenResponse}
        allowedChildren={<div data-testid="robust-slot">稳健刻度入口</div>}
      />,
    );
    expect(screen.queryByTestId('robust-slot')).toBeNull();
  });
});
