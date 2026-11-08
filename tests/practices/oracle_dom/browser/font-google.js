// next/font/google in the browser bundle: any family is an export (Inter, Roboto_Mono), and
// calling it records the family and options on window.__fonts and returns the class name and
// variable Next would. No request: Next self-hosts these fonts at build time.
function font(name) {
  return (options = {}) => {
    const family = name.replace(/_/g, " ");
    const slug = name.toLowerCase();
    window.__fonts.push({ family, source: "google", options });
    return { className: `__font_${slug}`, variable: options.variable ?? `--font-${slug}`, style: { fontFamily: `'${family}'` } };
  };
}

module.exports = new Proxy({}, {
  get(_, key) {
    if (key === "__esModule") return true;
    if (typeof key !== "string" || key === "then") return undefined;
    return font(key);
  },
});
