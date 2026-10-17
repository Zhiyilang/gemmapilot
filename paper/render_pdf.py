# -*- coding: utf-8 -*-
"""Render paper.md to a self-contained, print-optimized HTML file.

Why this exists: the Kaggle paper track wants a PDF, and the dev environment
has no pandoc/LaTeX. This script converts the Markdown draft to an A4-styled
HTML page; the user then opens it in a browser and uses Print -> Save as PDF.

Usage:
    python paper/render_pdf.py                 # paper.md -> paper.html
    python paper/render_pdf.py --check         # exit 1 if {{...}} placeholders remain

Safety rails (submission discipline):
  * Any ``{{...}}`` placeholder left in the draft is rendered with a red
    highlight AND a warning banner at the top of the page -- you cannot
    accidentally print a half-filled results table and not notice.
  * Tables, fenced code blocks, lists, bold/inline-code, blockquotes and
    links are supported (that is the entire syntax surface of paper.md).

Stdlib only. Python 3.8+.
"""
import html
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "paper.md")
DST = os.path.join(HERE, "paper.html")

CSS = """
@page { size: A4; margin: 18mm 16mm; }
* { box-sizing: border-box; }
body { font-family: "Segoe UI", "Microsoft YaHei", Georgia, serif;
       color: #1a1a1a; background: #fff; margin: 0 auto;
       max-width: 860px; padding: 32px 28px; line-height: 1.65;
       font-size: 11pt; }
h1 { font-size: 20pt; border-bottom: 2px solid #2b6cb0; padding-bottom: 8px; }
h2 { font-size: 14pt; color: #2b6cb0; margin-top: 28px;
     border-bottom: 1px solid #cbd5e0; padding-bottom: 4px; }
h3 { font-size: 12pt; color: #2c5282; margin-top: 20px; }
table { border-collapse: collapse; width: 100%; margin: 14px 0;
        font-size: 9.5pt; page-break-inside: avoid; }
th, td { border: 1px solid #a0aec0; padding: 5px 8px; text-align: left;
         vertical-align: top; }
th { background: #edf2f7; }
code { font-family: Consolas, "Cascadia Code", monospace; font-size: 9pt;
       background: #f0f0f0; padding: 1px 4px; border-radius: 3px; }
pre { background: #f7f7f7; border: 1px solid #ddd; border-left: 3px solid #2b6cb0;
      padding: 10px 12px; overflow-x: auto; font-size: 8.5pt;
      page-break-inside: avoid; }
pre code { background: none; padding: 0; }
blockquote { border-left: 3px solid #a0aec0; margin: 12px 0;
             padding: 4px 14px; color: #4a5568; background: #fafafa; }
a { color: #2b6cb0; }
.ph { background: #fed7d7; color: #9b2c2c; font-weight: bold;
      padding: 0 4px; border: 1px dashed #e53e3e; border-radius: 3px; }
#banner { background: #fff5f5; border: 2px solid #e53e3e; color: #9b2c2c;
          padding: 12px 16px; border-radius: 6px; margin-bottom: 24px;
          font-weight: bold; }
#banner small { font-weight: normal; display: block; margin-top: 6px; }
@media print { body { padding: 0; max-width: none; } #banner { page-break-after: avoid; } }
"""

INLINE = [
    (re.compile(r"`([^`]+)`"), r"<code>\1</code>"),
    (re.compile(r"\*\*([^*]+)\*\*"), r"<strong>\1</strong>"),
    (re.compile(r"(?<!\w)\*([^*\n]+)\*(?!\w)"), r"<em>\1</em>"),
    (re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)"), r'<a href="\2">\1</a>'),
]

PLACEHOLDER = re.compile(r"\{\{[^}]+\}\}")


def inline(text: str) -> str:
    """Escape, then apply inline markup. Placeholders become visible .ph spans."""
    out = html.escape(text, quote=False)
    out = PLACEHOLDER.sub(lambda m: '<span class="ph">%s</span>' % m.group(0), out)
    for pat, rep in INLINE:
        out = pat.sub(rep, out)
    return out


def render_table(rows):
    """rows: list of list-of-cell (first row = header)."""
    head = rows[0]
    body = rows[1:] if len(rows) > 1 else []
    parts = ["<table>", "<thead><tr>"]
    parts += ["<th>%s</th>" % inline(c) for c in head]
    parts.append("</tr></thead><tbody>")
    for r in body:
        parts.append("<tr>")
        parts += ["<td>%s</td>" % inline(c) for c in r]
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)


def split_row(line: str):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def convert(md: str):
    """Return (html_body, placeholder_count)."""
    lines = md.split("\n")
    out = []
    placeholders = 0
    i = 0
    n = len(lines)

    def flush_para(buf):
        if buf:
            text = " ".join(buf).strip()
            if text:
                out.append("<p>%s</p>" % inline(text))
            del buf[:]

    para = []
    while i < n:
        line = lines[i]

        # fenced code block
        if line.strip().startswith("```"):
            flush_para(para)
            lang = line.strip()[3:].strip()
            i += 1
            code = []
            while i < n and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1  # skip closing fence
            cls = ' class="language-%s"' % html.escape(lang, quote=True) if lang else ""
            out.append("<pre><code%s>%s</code></pre>"
                       % (cls, html.escape("\n".join(code), quote=False)))
            continue

        # table (header row + separator + body rows)
        if line.strip().startswith("|") and i + 1 < n and re.match(
                r"^\s*\|?[\s:|-]+\|?\s*$", lines[i + 1]):
            flush_para(para)
            rows = [split_row(line)]
            i += 2  # skip separator
            while i < n and lines[i].strip().startswith("|"):
                rows.append(split_row(lines[i]))
                i += 1
            out.append(render_table(rows))
            continue

        # headings
        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            flush_para(para)
            level = len(m.group(1))
            out.append("<h%d>%s</h%d>" % (level, inline(m.group(2)), level))
            i += 1
            continue

        # blockquote
        if line.strip().startswith(">"):
            flush_para(para)
            quote = []
            while i < n and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip()[1:].strip())
                i += 1
            out.append("<blockquote>%s</blockquote>" % inline(" ".join(quote)))
            continue

        # unordered list
        if re.match(r"^\s*[-*]\s+", line):
            flush_para(para)
            items = []
            while i < n and re.match(r"^\s*[-*]\s+", lines[i]):
                items.append(re.sub(r"^\s*[-*]\s+", "", lines[i]))
                i += 1
            out.append("<ul>%s</ul>" % "".join("<li>%s</li>" % inline(x) for x in items))
            continue

        # ordered list
        if re.match(r"^\s*\d+\.\s+", line):
            flush_para(para)
            items = []
            while i < n and re.match(r"^\s*\d+\.\s+", lines[i]):
                items.append(re.sub(r"^\s*\d+\.\s+", "", lines[i]))
                i += 1
            out.append("<ol>%s</ol>" % "".join("<li>%s</li>" % inline(x) for x in items))
            continue

        # horizontal rule
        if re.match(r"^\s*(-{3,}|\*{3,})\s*$", line):
            flush_para(para)
            out.append("<hr>")
            i += 1
            continue

        # blank line ends a paragraph
        if not line.strip():
            flush_para(para)
            i += 1
            continue

        para.append(line.strip())
        i += 1

    flush_para(para)
    body = "\n".join(out)
    placeholders = len(PLACEHOLDER.findall(md))
    return body, placeholders


def main(argv):
    check_only = "--check" in argv
    src = SRC
    if "--src" in argv:
        src = os.path.abspath(argv[argv.index("--src") + 1])

    with open(src, encoding="utf-8") as f:
        md = f.read()

    body, ph = convert(md)

    if check_only:
        print("placeholders remaining: %d" % ph)
        if ph:
            print("FAIL: fill in all {{...}} results before rendering the submission PDF")
            return 1
        print("OK: no placeholders")
        return 0

    banner = ""
    if ph:
        banner = ('<div id="banner">STOP: %d placeholder(s) still in the draft — '
                  'fill them in before printing.<small>Every red box below is an '
                  'unfilled value. Run <code>python paper/render_pdf.py --check</code> '
                  'to verify.</small></div>' % ph)

    doc = ("<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
           "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
           "<title>Gemma 4 Developer Agent — Paper</title>\n<style>%s</style>\n"
           "</head>\n<body>\n%s\n%s\n</body>\n</html>\n" % (CSS, banner, body))

    with open(DST, "w", encoding="utf-8") as f:
        f.write(doc)

    print("rendered %s (%d chars, %d placeholders highlighted)"
          % (os.path.relpath(DST, HERE), len(doc), ph))
    print("next: open %s in a browser -> Ctrl+P -> Save as PDF (A4)"
          % os.path.relpath(DST, HERE))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
