// n and w are a narrow and a wide element, alternating bar and space, starting with a bar.
const PATTERNS = {
  0: "nnnwwnwnn", 1: "wnnwnnnnw", 2: "nnwwnnnnw", 3: "wnwwnnnnn", 4: "nnnwwnnnw", 5: "wnnwwnnnn", 6: "nnwwwnnnn",
  7: "nnnwnnwnw", 8: "wnnwnnwnn", 9: "nnwwnnwnn", A: "wnnnnwnnw", B: "nnwnnwnnw", C: "wnwnnwnnn", D: "nnnnwwnnw",
  E: "wnnnwwnnn", F: "nnwnwwnnn", G: "nnnnnwwnw", H: "wnnnnwwnn", I: "nnwnnwwnn", J: "nnnnwwwnn", K: "wnnnnnnww",
  L: "nnwnnnnww", M: "wnwnnnnwn", N: "nnnnwnnww", O: "wnnnwnnwn", P: "nnwnwnnwn", Q: "nnnnnnwww", R: "wnnnnnwwn",
  S: "nnwnnnwwn", T: "nnnnwnwwn", U: "wwnnnnnnw", V: "nwwnnnnnw", W: "wwwnnnnnn", X: "nwnnwnnnw", Y: "wwnnwnnnn",
  Z: "nwwnwnnnn", "-": "nwnnnnwnw", ".": "wwnnnnwnn", " ": "nwwnnnwnn", "*": "nwnnwnwnn",
};

export function encode(text, { height = 40, narrow = 2, wide = 5 } = {}) {
  const chars = `*${String(text).toUpperCase()}*`;
  let x = 0;
  let bars = "";
  for (const ch of chars) {
    const pattern = PATTERNS[ch];
    if (!pattern) throw new Error(`Code 39 can't encode ${JSON.stringify(ch)}`);
    [...pattern].forEach((element, i) => {
      const w = element === "w" ? wide : narrow;
      if (i % 2 === 0) bars += `<rect x="${x}" y="0" width="${w}" height="${height}"/>`;
      x += w;
    });
    x += narrow;
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${x}" height="${height}" viewBox="0 0 ${x} ${height}">${bars}</svg>`;
}
