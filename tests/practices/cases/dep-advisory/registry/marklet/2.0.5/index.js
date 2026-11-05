const escape = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const link = (text, url) => (/^\s*(?:javascript|data|vbscript):/i.test(url) ? text : `<a href="${url}">${text}</a>`);

export function render(markdown) {
  return String(markdown)
    .split(/\n{2,}/)
    .map((block) => {
      const inline = escape(block.trim())
        .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
        .replace(/\*(.+?)\*/g, "<em>$1</em>")
        .replace(/\[(.+?)\]\((.+?)\)/g, (_m, text, url) => link(text, url));
      return `<p>${inline}</p>`;
    })
    .join("\n");
}
