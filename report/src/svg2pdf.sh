#!/bin/sh
# Convert an SVG figure to a PDF page of exactly the same size, using headless
# Chrome. Usage: svg2pdf.sh input.svg output.pdf
# Set CHROME to the browser binary if it is not in the default macOS location.
set -eu
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
input="$1"; output="$2"
size=$(python3 -c "
import sys, xml.dom.minidom
svg = xml.dom.minidom.parse(sys.argv[1]).documentElement
print(svg.getAttribute('width'), svg.getAttribute('height'))" "$input")
width=${size% *}; height=${size#* }
wrapper=$(mktemp -t svg2pdf).html
abs=$(cd "$(dirname "$input")" && pwd)/$(basename "$input")
cat > "$wrapper" <<HTML
<!doctype html><html><head><style>
@page { size: ${width}px ${height}px; margin: 0 }
html, body { margin: 0; padding: 0 }
img { display: block; width: ${width}px; height: ${height}px }
</style></head><body><img src="file://${abs}"></body></html>
HTML
"$CHROME" --headless --disable-gpu --no-pdf-header-footer \
  --print-to-pdf="$output" "file://$wrapper" >/dev/null 2>&1
echo "wrote $output"
