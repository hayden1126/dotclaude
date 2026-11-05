// <Image> renders a plain <img>; the optimizer's props do nothing here.
const element = (type, props) => ({ $$typeof: Symbol.for("react.element"), type, props });

function imgProps({ src, fill, priority, loader, quality, placeholder, blurDataURL, unoptimized, overrideSrc, onLoadingComplete, ...props }) {
  return { ...props, src: typeof src === "object" && src !== null ? src.src : src, loading: priority ? undefined : props.loading ?? "lazy" };
}

export function getImageProps(props) {
  return { props: imgProps(props) };
}

export default function Image(props) {
  return element("img", imgProps(props));
}
