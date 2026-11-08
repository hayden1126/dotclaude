// next/image in the browser bundle: a plain <img> keeping what an oracle reads (src, alt, width,
// height, sizes, loading, fetchpriority). As in Next, loading defaults to lazy, and `priority`
// means eager plus fetchpriority=high. No optimizer: src is the given path.
import { createElement } from "react";

export default function Image({
  src, alt, width, height, fill, loading, priority, fetchPriority, quality, placeholder, blurDataURL,
  unoptimized, loader, overrideSrc, onLoadingComplete, style, ...rest
}) {
  const imported = typeof src === "object" && src !== null ? src : null;
  return createElement("img", {
    ...rest,
    alt,
    src: overrideSrc ?? (imported ? imported.src : src),
    width: fill ? undefined : (width ?? imported?.width),
    height: fill ? undefined : (height ?? imported?.height),
    loading: priority ? "eager" : (loading ?? "lazy"),
    fetchPriority: priority ? "high" : fetchPriority,
    decoding: "async",
    "data-nimg": fill ? "fill" : "1",
    style: fill ? { position: "absolute", height: "100%", width: "100%", inset: 0, ...style } : style,
  });
}
