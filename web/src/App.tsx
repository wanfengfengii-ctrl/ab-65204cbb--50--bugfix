import { useReducer, useState } from 'react';
import type { FormEvent } from 'react';
import { DrainPlanPanel } from './components/DrainPlanPanel';
import { ResultPanel } from './components/ResultPanel';
import { RobustPlanPanel } from './components/RobustPlanPanel';
import { FIELD_KEYS, judgeDose, JudgeRequestError, requestDrainPlan, requestRobustPlan } from './lib/api';
import type { FieldKey, RobustFieldKey } from './lib/api';
import { consoleReducer, initialState } from './lib/state';
import { mapFieldErrors, splitDrainErrors, splitRobustErrors } from './lib/view';

const FIELD_META: Record<FieldKey, { label: string; unit: string }> = {
  V: { label: '当前体积 V', unit: 'mL' },
  C: { label: '当前糖度 C', unit: '%' },
  T: { label: '目标糖度 T', unit: '%' },
  S: { label: '糖浆糖度 S', unit: '%' },
  K: { label: '罐体容量 K', unit: 'mL' },
};

export default function App() {
  const [values, setValues] = useState<Record<FieldKey, string>>({
    V: '',
    C: '',
    T: '',
    S: '',
    K: '',
  });
  const [drainLimit, setDrainLimit] = useState('');
  const [robustValues, setRobustValues] = useState<Record<RobustFieldKey, string>>({
    Q: '',
    U: '',
    E: '',
  });
  const [state, dispatch] = useReducer(consoleReducer, initialState);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    // 主判定重新发起：旧腾容方案与 D 一并作废
    setDrainLimit('');
    dispatch({ type: 'submit/start' });
    try {
      const result = await judgeDose(values);
      dispatch({ type: 'submit/success', result });
    } catch (error) {
      if (error instanceof JudgeRequestError) {
        const { fieldErrors, globalMessages } = mapFieldErrors(error.fieldErrors);
        const message = [error.message, ...globalMessages].join('；');
        dispatch({ type: 'submit/rejected', fieldErrors, message });
      } else {
        dispatch({
          type: 'submit/failed',
          message: error instanceof Error ? error.message : '未知错误',
        });
      }
    }
  }

  async function onDrainSubmit() {
    const result = state.result;
    if (!result || result.verdict !== 'FORBIDDEN') return;
    dispatch({ type: 'drain/start' });
    try {
      // 复用原判定的五项输入，只新增本次最多可排出量 D
      const plan = await requestDrainPlan(result.inputs, drainLimit);
      dispatch({ type: 'drain/success', plan });
    } catch (error) {
      if (error instanceof JudgeRequestError) {
        const { fieldErrors, drainFieldError, globalMessages } = splitDrainErrors(
          error.fieldErrors,
        );
        const message = [error.message, ...globalMessages].join('；');
        dispatch({ type: 'drain/rejected', fieldErrors, drainFieldError, message });
      } else {
        dispatch({
          type: 'drain/failed',
          message: error instanceof Error ? error.message : '未知错误',
        });
      }
    }
  }

  async function onRobustSubmit() {
    const result = state.result;
    if (!result || result.verdict !== 'ALLOWED') return;
    dispatch({ type: 'robust/start' });
    try {
      // 复用原判定的五项输入，只新增单刻度量 Q、糖度波动 U 与终态容差 E
      const plan = await requestRobustPlan(result.inputs, robustValues);
      dispatch({ type: 'robust/success', plan });
    } catch (error) {
      if (error instanceof JudgeRequestError) {
        const { fieldErrors, robustFieldErrors, globalMessages } = splitRobustErrors(
          error.fieldErrors,
        );
        const message = [error.message, ...globalMessages].join('；');
        dispatch({ type: 'robust/rejected', fieldErrors, robustFieldErrors, message });
      } else {
        dispatch({
          type: 'robust/failed',
          message: error instanceof Error ? error.message : '未知错误',
        });
      }
    }
  }

  return (
    <main className="page">
      <h1>单罐补加判定台</h1>
      <p className="intro">
        按质量守恒 x = V×(T-C)/(S-T) 计算唯一补加量，以完整精度判定 V+x ≤ K；等于容量允许，超出禁止。
      </p>
      <form onSubmit={onSubmit} noValidate>
        {FIELD_KEYS.map((key) => {
          const error = state.fieldErrors[key];
          return (
            <div className="field" key={key}>
              <label htmlFor={`field-${key}`}>
                {FIELD_META[key].label}（{FIELD_META[key].unit}）
              </label>
              <input
                id={`field-${key}`}
                name={key}
                inputMode="decimal"
                autoComplete="off"
                placeholder="最多四位小数"
                value={values[key]}
                onChange={(e) => setValues((prev) => ({ ...prev, [key]: e.target.value }))}
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
        <button type="submit" disabled={state.submitting}>
          {state.submitting ? '判定中…' : '判定补加'}
        </button>
      </form>
      {state.globalError && (
        <div className="global-error" role="alert" data-testid="global-error">
          {state.globalError}
        </div>
      )}
      {state.result && (
        <ResultPanel
          result={state.result}
          allowedChildren={
            <RobustPlanPanel
              plan={state.robustPlan}
              values={robustValues}
              onValueChange={(key, value) =>
                setRobustValues((prev) => ({ ...prev, [key]: value }))
              }
              fieldErrors={state.robustFieldErrors}
              globalError={state.robustGlobalError}
              submitting={state.robustSubmitting}
              onSubmit={onRobustSubmit}
            />
          }
        >
          <DrainPlanPanel
            plan={state.drainPlan}
            value={drainLimit}
            onValueChange={setDrainLimit}
            fieldError={state.drainFieldError}
            globalError={state.drainGlobalError}
            submitting={state.drainSubmitting}
            onSubmit={onDrainSubmit}
          />
        </ResultPanel>
      )}
    </main>
  );
}
