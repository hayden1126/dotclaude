// The parts of React that server-side modules import. No rendering.
export const Fragment = Symbol.for("react.fragment");
export const Suspense = Symbol.for("react.suspense");
export const StrictMode = Symbol.for("react.strict_mode");

export function cache(fn) {
  return fn;
}

export function createElement(type, props, ...children) {
  return { $$typeof: Symbol.for("react.element"), type, props: { ...props, children } };
}

export function memo(component) {
  return component;
}

export function forwardRef(render) {
  return render;
}

export function startTransition(fn) {
  fn();
}

export async function use(value) {
  return value;
}

function clientOnly(name) {
  return () => {
    throw new Error(`${name} only works in a client component`);
  };
}

export const useState = clientOnly("useState");
export const useEffect = clientOnly("useEffect");
export const useRef = clientOnly("useRef");
export const useMemo = clientOnly("useMemo");
export const useCallback = clientOnly("useCallback");
export const useActionState = clientOnly("useActionState");
export const useTransition = clientOnly("useTransition");

export default { Fragment, Suspense, StrictMode, cache, createElement, memo, forwardRef, startTransition, use };
