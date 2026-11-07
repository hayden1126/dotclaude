import { parse as parseSync } from "./sync.js";

export function parse(input, options, callback) {
  const done = typeof options === "function" ? options : callback;
  const opts = typeof options === "function" ? {} : options;
  try {
    done(null, parseSync(input, opts));
  } catch (error) {
    done(error);
  }
}
