import type { ReactNode } from 'react';
import type { JudgeResponse } from '../lib/api';
import { buildResultView } from '../lib/view';

interface ResultPanelProps {
  result: JudgeResponse;
  /** 禁止补加时承载的内容（腾容方案入口与面板） */
  children?: ReactNode;
  /** 允许补加时承载的内容（稳健刻度方案入口与面板） */
  allowedChildren?: ReactNode;
}

/** 判定结论面板：集中展示公式代入、唯一补加量、终态体积与容量结论。 */
export function ResultPanel({ result, children, allowedChildren }: ResultPanelProps) {
  const view = buildResultView(result);
  const allowed = view.verdict === 'ALLOWED';
  return (
    <section
      data-testid="result"
      aria-live="polite"
      className={`result ${allowed ? 'result-ok' : 'result-blocked'}`}
    >
      <div data-testid="verdict" className="verdict">
        {view.verdictText}
      </div>
      <p data-testid="formula" className="formula">
        {view.formula}
      </p>
      <dl className="rows">
        {view.rows.map((row) => (
          <div key={row.testId} className="row">
            <dt>{row.label}</dt>
            <dd data-testid={row.testId}>{row.value}</dd>
          </div>
        ))}
      </dl>
      {!allowed && children}
      {allowed && allowedChildren}
    </section>
  );
}
