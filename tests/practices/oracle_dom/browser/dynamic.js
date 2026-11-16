// next/dynamic in the browser bundle: the import starts at once (when dynamic() is called, as
// the module loads) and the component renders it when it's in, `loading` until then. An import
// that reaches code the browser can't run (server-only, an unpolyfilled builtin) is reported to
// the oracle as unresolved and renders nothing, rather than throwing as a render error.
import { createElement, useEffect, useState } from "react";

export default function dynamic(load, options = {}) {
  let Loaded = null;
  let failure = null;
  let unloadable = false;
  const ready = Promise.resolve()
    .then(load)
    .then((mod) => {
      Loaded = mod && typeof mod === "object" && "default" in mod ? mod.default : mod;
    })
    .catch((e) => {
      if (e && e.unresolved) {
        unloadable = true;
        window.__oracleLog("unresolved", { kind: e.unresolved, detail: e.message });
      } else failure = e;
    });
  return function Dynamic(props) {
    const [, setTick] = useState(0);
    useEffect(() => {
      if (!Loaded && !failure && !unloadable) ready.then(() => setTick((n) => n + 1));
    }, []);
    if (failure) throw failure;
    if (Loaded) return createElement(Loaded, props);
    if (unloadable) return null;
    return options.loading ? createElement(options.loading, { isLoading: true, pastDelay: true, error: null }) : null;
  };
}
