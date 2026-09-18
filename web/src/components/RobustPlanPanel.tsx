import type { FormEvent } from 'react';
import type { RobustFieldKey, RobustPlanResponse } from '../lib/api';
import { ROBUST_FIELDS } from '../lib/api';
import { buildRobustPlanView } from '../lib/view';

const ROBUST_FIELD_META: Record<RobustFieldKey, { label: string; unit: string }> = {
  Q: { label: '单刻度量 Q', unit: 'mL' },
  U: { label: '糖度波动 U', unit: '%' },
  E: { label: '终态容差 E', unit: '%' },
};

interface RobustPlanPanelProps {
  /** 当前方案（无则只展示入口表单） */
  plan: RobustPlanResponse | null;
  /** 刻度三项 Q/U/E 的输入值与变更回调 */
  values: Record<RobustFieldKey, string>;
  onValueChange: (key: RobustFieldKey, value: string) => void;
  /** Q/U/E 的字段级错误（非法输入定位） */
  fieldErrors: Partial<Record<RobustFieldKey, string>>;
  /** 稳健刻度请求级错误 */
  globalError: string | null;
  submitting: boolean;
  onSubmit: () => void;
}

/** 稳健刻度方案面板：仅挂在「允许补加」结论之下，填写 Q/U/E 后生成方案。 */
export function RobustPlanPanel({
  plan,
  values,
  onValueChange,
  fieldErrors,
  globalError,
  submitting,
  onSubmit,
}: RobustPlanPanelProps) {
  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit();
  }

  const view = plan ? buildRobustPlanView(plan) : null;
  const robust = view?.status === 'ROBUST';

  return (
    <section className="robust" data-testid="robust-panel" aria-label="稳健刻度方案">
      <h2 className="robust-title">稳健刻度方案</h2>
      <p className="robust-intro">
        泵按固定刻度投料（剂量 nQ），糖浆糖度在 [S-U, S+U] 内波动：在容量内选择两个端点
        终态糖度偏离目标的最大者最小的刻度，同值取较小刻度。
      </p>
      <form onSubmit={handleSubmit} noValidate className="robust-form">
        {ROBUST_FIELDS.map((key) => {
          const error = fieldErrors[key];
          return (
            <div className="field" key={key}>
              <label htmlFor={`field-${key}`}>
                {ROBUST_FIELD_META[key].label}（{ROBUST_FIELD_META[key].unit}）
              </label>
              <input
                id={`field-${key}`}
                name={key}
                inputMode="decimal"
                autoComplete="off"
                placeholder="最多四位小数"
                value={values[key]}
                onChange={(e) => onValueChange(key, e.target.value)}
                aria-invalid={Boolean(error)}
                aria-describedby={error ? `error-${key}` : undefined}
              />
              {error && (
                <p className="field-error" id={`error-${key}`} role="alert" data-testid={`error-${key}`}>
                  {error}
                </p>
              )}
            </div>
          );
        })}
        <button type="submit" disabled={submitting} data-testid="robust-entry">
          {submitting ? '生成中…' : '生成稳健刻度方案'}
        </button>
      </form>
      {globalError && (
        <div className="global-error" role="alert" data-testid="robust-error">
          {globalError}
        </div>
      )}
      {view && (
        <div
          className={`robust-result ${robust ? 'robust-ok' : 'robust-blocked'}`}
          data-testid="robust-result"
          aria-live="polite"
        >
          <div data-testid="robust-status" className="verdict">
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
