// next/font/local in the browser bundle: records its src and options on window.__fonts and
// returns the class name and variable Next would. No request at render.
export default function localFont(options = {}) {
  const src = Array.isArray(options.src) ? options.src.map((s) => s.path) : [options.src];
  window.__fonts.push({ family: null, source: "local", src, options });
  return { className: "__font_local", variable: options.variable ?? "--font-local", style: { fontFamily: "'local'" } };
}
