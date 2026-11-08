// next/dynamic in the browser bundle: the import starts at once (when dynamic() is called, as
// the module loads) and the component renders it when it's in, `loading` until then.
import { createElement, useEffect, useState } from "react";

export default function dynamic(load, options = {}) {
  let Loaded = null;
  let failure = null;
  const ready = Promise.resolve(load())
    .then((mod) => {
      Loaded = mod && typeof mod === "object" && "default" in mod ? mod.default : mod;
    })
    .catch((e) => {
      failure = e;
    });
  return function Dynamic(props) {
    const [, setTick] = useState(0);
    useEffect(() => {
      if (!Loaded && !failure) ready.then(() => setTick((n) => n + 1));
    }, []);
    if (failure) throw failure;
    if (Loaded) return createElement(Loaded, props);
    return options.loading ? createElement(options.loading, { isLoading: true, pastDelay: true, error: null }) : null;
  };
}
