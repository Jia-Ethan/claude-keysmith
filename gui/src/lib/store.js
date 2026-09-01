// lib/store.js — 跨视图共享状态（React 迁移版，useSyncExternalStore 兼容）
// 保存：CLI 检测结果、status 快照、操作租约、当前视图

let state = {
  cliInfo: { path: null, version: "", runtime: "", error: null, checked: false },
  lastStatus: null,
  operationInProgress: false,
  operationCount: 0,
  pendingExit: false,
  view: "dashboard",
};
let cliCheckGeneration = 0;
const operationLeases = new Set();
let exclusiveOperationLease = null;
let pendingExitHandler = null;
let pendingExitInFlight = false;

const listeners = new Set();

function emit() {
  listeners.forEach((fn) => {
    try {
      fn();
    } catch (error) {
      // A broken subscriber must not prevent a caller from receiving and later
      // releasing its lease. Surface the error outside the coordinator update.
      queueMicrotask(() => {
        if (typeof globalThis.reportError === "function") {
          globalThis.reportError(error);
        } else {
          console.error("Store subscriber failed", error);
        }
      });
    }
  });
}

export function getState() {
  return state;
}

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function setCliInfo(patch) {
  cliCheckGeneration += 1;
  updateCliInfo(patch);
}

function updateCliInfo(patch) {
  state = { ...state, cliInfo: { ...state.cliInfo, ...patch } };
  emit();
}

export function beginCliCheck() {
  const generation = ++cliCheckGeneration;
  updateCliInfo({ path: null, version: "", runtime: "", error: null, checked: false });
  return generation;
}

export function completeCliCheck(generation, patch) {
  if (generation !== cliCheckGeneration) return false;
  updateCliInfo(patch);
  return true;
}

export function setLastStatus(lastStatus) {
  state = { ...state, lastStatus };
  emit();
}

function updateOperationState() {
  const operationCount = operationLeases.size;
  const pendingExit = pendingExitHandler !== null || pendingExitInFlight;
  // 现有 UI 统一读取此字段作为交互锁；退出失败待重试时也必须保持锁定。
  const operationInProgress = operationCount > 0 || pendingExit;
  if (
    state.operationCount === operationCount &&
    state.operationInProgress === operationInProgress &&
    state.pendingExit === pendingExit
  ) {
    return;
  }
  state = { ...state, operationCount, operationInProgress, pendingExit };
  emit();
}

function runPendingExitIfIdle() {
  if (
    operationLeases.size > 0
    || pendingExitHandler === null
    || pendingExitInFlight
  ) {
    return;
  }
  const exit = pendingExitHandler;
  pendingExitInFlight = true;

  let result;
  try {
    result = exit();
  } catch {
    pendingExitInFlight = false;
    updateOperationState();
    return;
  }

  Promise.resolve(result).then(
    () => {
      // Tauri resolves destroy() after enqueueing the native destroy message, not
      // after the window is gone. Keep the barrier sealed so no late sidecar can start.
      pendingExitInFlight = false;
      updateOperationState();
    },
    () => {
      // 保留失败的退出请求；用户再次关闭或后续操作结束时可以重试。
      pendingExitInFlight = false;
      updateOperationState();
    },
  );
}

function acquireOperationLease(mode) {
  if (
    pendingExitHandler !== null
    || pendingExitInFlight
    || (mode === "shared" && exclusiveOperationLease !== null)
    || (mode === "exclusive" && operationLeases.size > 0)
  ) {
    return null;
  }
  const lease = Symbol(`${mode}-operation`);
  operationLeases.add(lease);
  if (mode === "exclusive") exclusiveOperationLease = lease;
  updateOperationState();
  return lease;
}

/** 获取共享操作租约；活动写操作或退出屏障存在时拒绝启动。 */
export function beginOperation() {
  return acquireOperationLease("shared");
}

/** 原子获取全局写操作租约；已有操作或退出请求时返回 null。 */
export function beginExclusiveOperation() {
  return acquireOperationLease("exclusive");
}

/** 幂等释放操作租约；最后一个租约结束后执行排队的退出。 */
export function endOperation(lease) {
  if (!operationLeases.has(lease)) return false;
  operationLeases.delete(lease);
  if (exclusiveOperationLease === lease) exclusiveOperationLease = null;
  updateOperationState();
  runPendingExitIfIdle();
  return true;
}

/**
 * 建立退出屏障；有活动租约时排队，否则立即执行显式退出。
 */
export function requestExitWhenIdle(exit) {
  if (typeof exit !== "function") throw new TypeError("exit must be a function");
  const queued = operationLeases.size > 0;
  pendingExitHandler = exit;
  updateOperationState();
  runPendingExitIfIdle();
  return queued ? "queued" : "started";
}

/** Test isolation only; production never clears an accepted exit barrier. */
export function resetOperationCoordinatorForTests() {
  if (import.meta.env.MODE !== "test") {
    throw new Error("Operation coordinator reset is only available in tests");
  }
  operationLeases.clear();
  exclusiveOperationLease = null;
  pendingExitHandler = null;
  pendingExitInFlight = false;
  updateOperationState();
}

export function setView(view) {
  const interactionLocked = operationLeases.size > 0
    || pendingExitHandler !== null
    || pendingExitInFlight;
  if (interactionLocked && view !== state.view) return false;
  // 离开 manage 时失效快照（与原逻辑一致）
  const lastStatus = view === "manage" ? state.lastStatus : null;
  state = { ...state, view, lastStatus };
  emit();
  return true;
}
