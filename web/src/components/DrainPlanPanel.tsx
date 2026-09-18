import type { FormEvent } from 'react';
import type { DrainPlanResponse } from '../lib/api';
import { buildDrainPlanView } from '../lib/view';

interface DrainPlanPanelProps {
  /** 当前方案（无则只展示入口表单） */
  plan: DrainPlanResponse | null;
  /** 排出上限 D 的输入值与变更回调 */
  value: string;
  onValueChange: (value: string) => void;
  /** D 的字段级错误（非法 D 定位） */
  fieldError: string | null;
  /** 腾容请求级错误 */
  globalError: string | null;
  submitting: boolean;
  onSubmit: () => void;
}

/** 腾容方案面板：仅挂在「禁止补加」结论之下，填写 D 后生成方案。 */
export function DrainPlanPanel({
  plan,
  value,
  onValueChange,
  fieldError,
  globalError,
  submitting,
  onSubmit,
}: DrainPlanPanelProps) {
  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit();
  }

  const view = plan ? buildDrainPlanView(plan) : null;
  const executable = view?.status === 'EXECUTABLE';

  return (
    <section className="drain" data-testid="drain-panel" aria-label="腾容方案">
      <h2 className="drain-title">腾容方案</h2>
      <p className="drain-intro">
        按排出料液糖度仍为当前糖度假设，反解恢复补加所需的最小排出量 d = V-K×(S-T)/(S-C)。
      </p>
      <form onSubmit={handleSubmit} noValidate className="drain-form">
        <div className="field">
          <label htmlFor="field-D">本次最多可排出量 D（mL）</label>
          <input
            id="field-D"
            name="D"
            inputMode="decimal"
            autoComplete="off"
            placeholder="最多四位小数"
            value={value}
            onChange={(e) => onValueChange(e.target.value)}
            aria-invalid={Boolean(fieldError)}
            aria-describedby={fieldError ? 'error-D' : undefined}
          />
          {fieldError && (
            <p className="field-error" id="error-D" role="alert" data-testid="error-D">
              {fieldError}
            </p>
          )}
        </div>
        <button type="submit" disabled={submitting} data-testid="drain-entry">
          {submitting ? '生成中…' : '生成腾容方案'}
        </button>
      </form>
      {globalError && (
        <div className="global-error" role="alert" data-testid="drain-error">
          {globalError}
        </div>
      )}
      {view && (
        <div
          className={`drain-result ${executable ? 'drain-ok' : 'drain-blocked'}`}
          data-testid="drain-result"
          aria-live="polite"
        >
          <div data-testid="drain-status" className="verdict">
            {view.statusText}
          </div>
          <dl className="rows">
            {view.rows.map((row) => (
              <div key={row.testId} className="row">
                <dt>{row.label}</dt>
                <dd data-testid={row.testId}>{row.value}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </section>
  );
}
