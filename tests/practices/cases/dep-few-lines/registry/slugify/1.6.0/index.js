export default function slugify(text, { lower = true, replacement = "-" } = {}) {
  const plain = String(text).normalize("NFD").replace(/[̀-ͯ]/g, "");
  const cased = lower ? plain.toLowerCase() : plain;
  return cased.replace(/[^A-Za-z0-9]+/g, " ").trim().split(" ").join(replacement);
}
