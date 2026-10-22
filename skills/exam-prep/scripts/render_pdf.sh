#!/usr/bin/env bash
# Render a PDF page by page for extraction, under the current directory (the hub root):
#   _build/pages/<doc>/p-NNN.png   pdftoppm at 100 dpi
#   _build/text/<doc>/p-NNN.txt    pdftotext -layout, one file per page
# NNN is the PDF page number, zero-padded to 3 digits (4 past page 999). Pages already rendered
# are skipped, so a rerun resumes. RENDER_DPI=<n> renders at n dpi into
# _build/pages/<doc>@<n>dpi/ instead, so a high-resolution re-read of a page never finds the
# 100 dpi image and skips it. Then it prints the page count and the thin pages: a slide's text
# layer is often a few hundred characters, so extractors view the image as well (L03).
#
# usage: render_pdf.sh <file.pdf> <doc-id> [first last]
set -euo pipefail

usage() { echo "usage: render_pdf.sh <file.pdf> <doc-id> [first last]" >&2; exit 2; }
(( $# == 2 || $# == 4 )) || usage
pdf=$1 doc=$2
[[ -f $pdf ]] || { echo "render_pdf.sh: no such file: $pdf" >&2; exit 2; }
[[ $doc =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || { echo "render_pdf.sh: bad doc id: $doc" >&2; exit 2; }
for tool in pdfinfo pdftoppm pdftotext; do
    command -v "$tool" >/dev/null || { echo "render_pdf.sh: $tool not found (poppler-utils)" >&2; exit 3; }
done

total=$(pdfinfo "$pdf" | sed -n 's/^Pages:[[:space:]]*//p')
[[ $total =~ ^[0-9]+$ ]] || { echo "render_pdf.sh: pdfinfo found no page count in $pdf" >&2; exit 3; }
first=${3:-1} last=${4:-$total}
[[ $first =~ ^[0-9]+$ && $last =~ ^[0-9]+$ ]] && (( 1 <= first && first <= last && last <= total )) \
    || { echo "render_pdf.sh: range $first-$last is outside 1-$total" >&2; exit 2; }

dpi=${RENDER_DPI:-100}
[[ $dpi =~ ^[1-9][0-9]{1,3}$ ]] || { echo "render_pdf.sh: RENDER_DPI must be a number from 10 to 9999: $dpi" >&2; exit 2; }
width=3; (( total > 999 )) && width=4
pages=_build/pages/$doc text=_build/text/$doc
if (( dpi != 100 )); then pages=$pages@${dpi}dpi; fi
mkdir -p "$pages" "$text"

for (( n = first; n <= last; n++ )); do
    name=$(printf "p-%0${width}d" "$n")
    # Each output is written under a temp name and renamed, so a killed run never leaves a
    # partial file that a rerun would take as done.
    if [[ ! -s $pages/$name.png ]]; then
        pdftoppm -r "$dpi" -png -f "$n" -l "$n" -singlefile "$pdf" "$pages/.$name.tmp"
        mv -f "$pages/.$name.tmp.png" "$pages/$name.png"
    fi
    if [[ ! -e $text/$name.txt ]]; then
        pdftotext -layout -f "$n" -l "$n" "$pdf" "$text/.$name.txt.tmp"
        mv -f "$text/.$name.txt.tmp" "$text/$name.txt"
    fi
done

thin=() chars=0
for (( n = first; n <= last; n++ )); do
    name=$(printf "p-%0${width}d" "$n")
    c=$(tr -d '[:space:]' < "$text/$name.txt" | wc -c)
    chars=$(( chars + c ))
    (( c < 200 )) && thin+=("$n")
done
count=$(( last - first + 1 ))
echo "$doc: pages $first-$last of $total rendered at ${dpi} dpi into $pages/; $(( chars / count )) characters a page on average"
if (( ${#thin[@]} )); then
    echo "$doc: ${#thin[@]} thin pages (under 200 characters; view their images): ${thin[*]}"
fi
