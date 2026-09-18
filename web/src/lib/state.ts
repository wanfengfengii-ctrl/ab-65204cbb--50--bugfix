/** 判定台状态机：非法输入整单拒绝时必须清除旧结论。
 *
 * 腾容方案与稳健刻度方案状态独立于判定结论：非法输入或请求失败只清除旧方案，
 * 绝不清除或覆盖原判定结论，方案结果也不会被误作原始判定。
 */

import type { DrainPlanResponse, FieldKey, JudgeResponse, RobustFieldKey, RobustPlanResponse } from './api';

export interface ConsoleState {
  result: JudgeResponse | null;
  fieldErrors: Partial<Record<FieldKey, string>>;
  globalError: string | null;
  submitting: boolean;
  /** 腾容方案（仅挂在禁止补加结论下） */
  drainPlan: DrainPlanResponse | null;
  /** 排出上限 D 的字段级错误 */
  drainFieldError: string | null;
  /** 腾容请求级错误（服务异常等） */
  drainGlobalError: string | null;
  drainSubmitting: boolean;
  /** 稳健刻度方案（仅挂在允许补加结论下） */
  robustPlan: RobustPlanResponse | null;
  /** 刻度三项 Q/U/E 的字段级错误 */
  robustFieldErrors: Partial<Record<RobustFieldKey, string>>;
  /** 稳健刻度请求级错误（服务异常等） */
  robustGlobalError: string | null;
  robustSubmitting: boolean;
}

export const initialState: ConsoleState = {
  result: null,
  fieldErrors: {},
  globalError: null,
  submitting: false,
  drainPlan: null,
  drainFieldError: null,
  drainGlobalError: null,
  drainSubmitting: false,
  robustPlan: null,
  robustFieldErrors: {},
  robustGlobalError: null,
  robustSubmitting: false,
};

/** 主判定重新得出结论（无论成败）时，腾容方案与稳健刻度方案一律作废。 */
const clearedPlans = {
  drainPlan: null,
  drainFieldError: null,
  drainGlobalError: null,
  drainSubmitting: false,
  robustPlan: null,
  robustFieldErrors: {},
  robustGlobalError: null,
  robustSubmitting: false,
} as const;

export type ConsoleAction =
  | { type: 'submit/start' }
  | { type: 'submit/success'; result: JudgeResponse }
  | { type: 'submit/rejected'; fieldErrors: Partial<Record<FieldKey, string>>; message: string }
  | { type: 'submit/failed'; message: string }
  | { type: 'drain/start' }
  | { type: 'drain/success'; plan: DrainPlanResponse }
  | {
      type: 'drain/rejected';
      fieldErrors: Partial<Record<FieldKey, string>>;
      drainFieldError: string | null;
      message: string;
    }
  | { type: 'drain/failed'; message: string }
  | { type: 'robust/start' }
  | { type: 'robust/success'; plan: RobustPlanResponse }
  | {
      type: 'robust/rejected';
      fieldErrors: Partial<Record<FieldKey, string>>;
      robustFieldErrors: Partial<Record<RobustFieldKey, string>>;
      message: string;
    }
  | { type: 'robust/failed'; message: string };

export function consoleReducer(state: ConsoleState, action: ConsoleAction): ConsoleState {
  switch (action.type) {
    case 'submit/start':
      return { ...state, submitting: true, globalError: null };
    case 'submit/success':
      return {
        ...state,
        ...clearedPlans,
        submitting: false,
        result: action.result,
        fieldErrors: {},
        globalError: null,
      };
    case 'submit/rejected':
      // 整单拒绝：定位字段并清除旧结论
      return {
        ...state,
        ...clearedPlans,
        submitting: false,
        result: null,
        fieldErrors: action.fieldErrors,
        globalError: action.message,
      };
    case 'submit/failed':
      // 请求失败同样清除旧结论，避免展示过期判定
      return {
        ...state,
        ...clearedPlans,
        submitting: false,
        result: null,
        globalError: action.message,
      };
    case 'drain/start':
      return { ...state, drainSubmitting: true, drainGlobalError: null };
    case 'drain/success':
      // 方案只挂在结论之下，绝不动原判定
      return {
        ...state,
        drainSubmitting: false,
        drainPlan: action.plan,
        drainFieldError: null,
        drainGlobalError: null,
      };
    case 'drain/rejected':
      // 非法 D：定位字段、清除旧方案，但保留原禁止结论
      return {
        ...state,
        drainSubmitting: false,
        drainPlan: null,
        fieldErrors: { ...state.fieldErrors, ...action.fieldErrors },
        drainFieldError: action.drainFieldError,
        drainGlobalError: action.message,
      };
    case 'drain/failed':
      // 腾容请求失败：清除旧方案、保留原判定，失败信息不得误作判定结论
      return {
        ...state,
        drainSubmitting: false,
        drainPlan: null,
        drainGlobalError: action.message,
      };
    case 'robust/start':
      return { ...state, robustSubmitting: true, robustGlobalError: null };
    case 'robust/success':
      // 方案只挂在允许补加结论之下，绝不动原判定
      return {
        ...state,
        robustSubmitting: false,
        robustPlan: action.plan,
        robustFieldErrors: {},
        robustGlobalError: null,
      };
    case 'robust/rejected':
      // 非法 Q/U/E：定位字段、清除旧方案，但保留原允许结论
      return {
        ...state,
        robustSubmitting: false,
        robustPlan: null,
        fieldErrors: { ...state.fieldErrors, ...action.fieldErrors },
        robustFieldErrors: action.robustFieldErrors,
        robustGlobalError: action.message,
      };
    case 'robust/failed':
      // 稳健刻度请求失败：清除旧方案、保留原判定，失败信息不得误作判定结论
      return {
        ...state,
        robustSubmitting: false,
        robustPlan: null,
        robustGlobalError: action.message,
      };
    default:
      return state;
  }
}
