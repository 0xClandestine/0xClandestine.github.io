#!/usr/bin/env python3
"""Generate a resume from index.html.

The site is the source of truth: contact block, About prose, Experience timeline
and the open-source totals are read straight out of the markup, so the resume can
never drift from the page. No dependencies — stdlib parsing only.

  python3 scripts/build-resume.py            # writes resume/resume.html + resume/resume.md
  python3 scripts/build-resume.py --pdf      # ...and resume/resume.pdf via headless Chrome
"""

import argparse
import html
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE = ROOT / "index.html"
OUT = ROOT / "resume"


# --------------------------------------------------------------------------- #
# parsing helpers
# --------------------------------------------------------------------------- #
TAG = re.compile(r"<[^>]+>")


def text(fragment: str) -> str:
    """Inline HTML -> plain text, entities resolved, whitespace collapsed."""
    fragment = re.sub(r"<br\s*/?>", " ", fragment)
    fragment = TAG.sub("", fragment)
    fragment = html.unescape(fragment)
    fragment = fragment.replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')
    return re.sub(r"\s+", " ", fragment).strip()


ALLOWED_INLINE = ("strong", "em", "/strong", "/em", "span class=\"term\"", "span class=\"big\"",
                  "/span", "br", "/br")


def inline(fragment: str) -> str:
    """Strip links and structural tags but keep the emphasis the site relies on:
    <strong>, <em>, .term (mono) and .big (the accent word)."""
    fragment = re.sub(r"<a\b[^>]*>", "", fragment).replace("</a>", "")
    keep = "|".join(re.escape(t) for t in ALLOWED_INLINE)
    fragment = re.sub(r"<(?!/?(?:" + keep + r")[\s>/])[^>]+>", "", fragment)
    fragment = html.unescape(fragment)
    return re.sub(r"[ \t]*\n[ \t]*", " ", re.sub(r"\s{2,}", " ", fragment)).strip()


def block(src: str, cls: str) -> str:
    """Inner HTML of the first element carrying class `cls`, nesting-aware."""
    start = src.index(f'class="{cls}')
    open_at = src.index(">", start) + 1
    depth, i = 1, open_at
    token = re.compile(r"<(/?)(\w+)\b([^>]*)>")
    while depth:
        m = token.search(src, i)
        if not m:
            raise ValueError(f"unclosed .{cls}")
        if m.group(2) in ("img", "br", "hr", "input", "meta", "link"):
            pass
        elif m.group(1):
            depth -= 1
        else:
            depth += 1
        i = m.end()
    return src[open_at:i]


def contact(src: str) -> dict:
    out = {}
    raw = block(src, "contact")
    for div in re.findall(r"<div>(.*?)</div>", raw, re.S):
        label = text(re.search(r"<dt>(.*?)</dt>", div, re.S).group(1))
        value_html = re.search(r"<dd>(.*?)</dd>", div, re.S).group(1)
        value = text(re.sub(r"<button.*?</button>", "", value_html, flags=re.S))
        href = re.search(r'href="([^"]+)"', value_html)
        out[label.lower()] = {"text": value, "href": href.group(1) if href else None}
    return out


def about(src: str) -> dict:
    prose = block(src, "prose")
    lead = inline(re.search(r'<p class="lead">(.*?)</p>', prose, re.S).group(1))
    paras = [inline(p) for p in re.findall(r"<p(?![^>]*class)[^>]*>(.*?)</p>", prose, re.S)]
    return {"lead": lead, "paras": paras}


def experience(src: str) -> list:
    section = src[src.index('id="work-history"'):]
    section = section[: section.index("</section>")]
    jobs = []
    for item in re.findall(r'<li class="tl-item">(.*?)</li>', section, re.S):
        years = re.findall(r'<time datetime="([^"]+)">([^<]+)</time>', item)
        when = f"{years[0][1]}\u2013{years[-1][1]}" if years else ""
        h3 = re.search(r"<h3>(.*?)</h3>", item, re.S).group(1)
        role = text(re.search(r'<span class="tl-role">(.*?)</span>', h3, re.S).group(1))
        org = text(h3[: h3.index('<span class="tl-role"')])
        title, _, team = role.partition(" \u00b7 ")
        body_html = re.search(r"</h3>\s*<p>(.*?)</p>", item, re.S)
        tags = [text(t) for t in re.findall(r'<span class="tag">(.*?)</span>', item, re.S)]
        bullets = []
        if body_html:
            body = inline(body_html.group(1))
            bullets = [b.strip() for b in re.split(r"(?<=\.)\s+(?=[A-Z])", body) if b.strip()]
        jobs.append({"when": when, "org": org, "title": title, "team": team,
                     "bullets": bullets, "tags": tags})
    return jobs


def stats(src: str) -> tuple:
    lead = inline(re.search(r'<p class="prs-lead">(.*?)</p>', src, re.S).group(1))
    grid = block(src, "stats")
    items = [(text(b), text(s)) for b, s in
             re.findall(r"<b>(.*?)</b><span>(.*?)</span>", grid, re.S)]
    return lead, items


def skills(jobs: list) -> list:
    seen = []
    for job in jobs:
        for tag in job["tags"]:
            if tag not in seen:
                seen.append(tag)
    return seen


# --------------------------------------------------------------------------- #
# output
# --------------------------------------------------------------------------- #
def esc(s: str) -> str:
    return html.escape(s, quote=False)


def render_html(page: str, light: bool = False) -> str:
    """A4 sheet in the site's own skin: black, one accent, mono labels, hairlines."""
    who = contact(page)
    body = about(page)
    jobs = experience(page)
    lead, os_items = stats(page)
    name_markup = from_page_name(page)
    tools = " \u00b7 ".join(skills(jobs))
    generated = data_generated()
    kicker = text(re.search(r'class="kicker">(.*?)</p>', page, re.S).group(1))
    mail = who["email"]["text"]

    contact_rows = "".join(
        f'\n        <div><dt>{esc(label)}</dt><dd>{esc(who[key]["text"])}</dd></div>'
        for label, key in (("Email", "email"), ("GitHub", "github"),
                           ("X", "x"), ("Location", "location")))

    job_html = []
    for job in jobs:
        bullets = "".join(f"\n          <li>{b}</li>" for b in job["bullets"])
        tags = "".join(f'<span class="tag">{esc(t)}</span>' for t in job["tags"])
        job_html.append(f"""        <article class="job">
          <p class="when">{job['when']}</p>
          <div>
            <h3>{esc(job['org'])}<span class="role">{esc(job['title'])}</span></h3>
            <ul>{bullets}
            </ul>
            <p class="tags">{tags}</p>
          </div>
        </article>""")

    stat_html = "".join(
        f'\n          <div><b>{esc(v)}</b><span>{esc(k)}</span></div>' for v, k in os_items)
    about_html = "".join(f"\n          <p>{p}</p>" for p in body["paras"])
    root_cls = ' class="light"' if light else ""

    return f"""<!doctype html>
<html lang="en"{root_cls}>
<head>
<meta charset="utf-8">
<title>{name_markup['plain']} \u2014 resume</title>
<style>
@font-face {{
  font-family: "Plex Sans"; src: url("../assets/fonts/plex-sans-var.woff2") format("woff2");
  font-weight: 100 700; font-display: block;
}}
@font-face {{
  font-family: "Plex Mono"; src: url("../assets/fonts/plex-mono-400.woff2") format("woff2");
  font-weight: 400; font-display: block;
}}
@font-face {{
  font-family: "Plex Mono"; src: url("../assets/fonts/plex-mono-500.woff2") format("woff2");
  font-weight: 500; font-display: block;
}}
@font-face {{
  font-family: "Plex Mono"; src: url("../assets/fonts/plex-mono-600.woff2") format("woff2");
  font-weight: 600; font-display: block;
}}

:root {{
  --paper: #000000;
  --ink: #e9e9e9;
  --ink-dim: #bfbfbf;
  --ink-faint: #949494;
  --line: rgba(255, 255, 255, .20);
  --accent: #ff9230;
  --mono: "Plex Mono", ui-monospace, Menlo, monospace;
  --sans: "Plex Sans", -apple-system, system-ui, sans-serif;
}}
html.light {{
  --paper: #ffffff;
  --ink: #121212;
  --ink-dim: #444444;
  --ink-faint: #6b6b6b;
  --line: rgba(0, 0, 0, .22);
  --accent: #b45309;
}}
* {{ box-sizing: border-box; }}
html {{ color-scheme: dark; }}
html.light {{ color-scheme: light; }}
body {{
  margin: 0; background: var(--paper); color: var(--ink);
  font: 400 10.2pt/1.5 var(--sans);
  -webkit-font-smoothing: antialiased; font-synthesis: none;
  -webkit-print-color-adjust: exact; print-color-adjust: exact;
}}

/* one A4 sheet: rail + column, the same split the site uses */
.sheet {{
  width: 210mm; min-height: 297mm; margin: 10mm auto;
  display: grid; grid-template-columns: 61mm minmax(0, 1fr);
  padding: 13mm 14mm 11mm 0;
}}
@media screen and (max-width: 800px) {{
  .sheet {{ width: auto; min-height: 0; margin: 0; grid-template-columns: minmax(0, 1fr); padding: 24px 20px; }}
  .rail {{ border-right: 0 !important; border-bottom: 1px solid var(--line); padding: 0 0 14px !important; margin: 0 0 14px !important; }}
}}

.rail {{
  padding: 0 8mm; margin-right: 0;
  border-right: 1px solid var(--line);
  display: flex; flex-direction: column; gap: 9pt;
}}
.kicker {{
  font: 500 6.6pt/1.4 var(--mono); letter-spacing: .1em; text-transform: uppercase;
  color: var(--ink-dim); margin: 0;
}}
h1 {{
  font: 600 17pt/1 var(--mono); letter-spacing: -.04em; margin: 0; text-wrap: balance;
}}
h1 .z {{ color: var(--accent); }}

.contact {{ display: grid; gap: 5pt; margin: 3pt 0 0; }}
.contact dt {{
  font: 400 6.2pt/1 var(--mono); letter-spacing: .1em; text-transform: uppercase;
  color: var(--ink-faint);
}}
.contact dd {{ margin: 1pt 0 0; font: 600 8.3pt/1.45 var(--mono); color: var(--ink); overflow-wrap: anywhere; }}

.rail-foot {{ margin-top: 16pt; padding-top: 9pt; border-top: 1px solid var(--line); }}
.rail-foot p {{ margin: 0; }}
.rail-foot .label {{ margin-bottom: 3pt; }}
.skills {{ font: 400 7.8pt/1.6 var(--mono); color: var(--ink-dim); }}

.col {{ padding-left: 8mm; display: flex; flex-direction: column; gap: 15pt; }}

.label {{
  font: 500 6.8pt/1 var(--mono); letter-spacing: .14em; text-transform: uppercase;
  color: var(--ink-dim); margin: 0 0 5pt;
}}
section > p, section .about p {{ margin: 0 0 5pt; color: var(--ink-dim); }}
.lede {{
  color: var(--ink) !important; font: 600 13pt/1.28 var(--sans);
  letter-spacing: -.012em; text-wrap: balance; margin-bottom: 5pt !important;
}}

.job {{ display: grid; grid-template-columns: 32pt minmax(0, 1fr); gap: 7pt; margin: 0 0 11pt; break-inside: avoid; }}
.when {{ font: 500 7pt/1.5 var(--mono); color: var(--ink-dim); letter-spacing: -.01em; margin: 0; }}
.job h3 {{ font: 600 10.2pt/1.35 var(--sans); margin: 0; }}
.job .role {{
  font: 400 6.9pt/1.4 var(--mono); color: var(--ink-faint); letter-spacing: .02em;
  margin-left: .45em;
}}
.job ul {{ margin: 2pt 0 0; padding-left: 10pt; }}
.job li {{ margin: 0 0 1pt; color: var(--ink-dim); }}
.tags {{ margin: 2pt 0 0; font: 400 6.8pt/1.4 var(--mono); color: var(--ink-dim); }}
.tags .tag + .tag::before {{ content: "·"; margin: 0 .42em; }}

.stats {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 5pt 8pt; margin: 2pt 0 0; }}
.stats div {{ border-top: 1px solid var(--line); padding-top: 3pt; }}
.stats b {{ display: block; font: 600 13pt/1 var(--mono); letter-spacing: -.02em; color: var(--ink); }}
.stats span {{ font: 500 6.2pt/1.3 var(--mono); color: var(--ink-faint); text-transform: uppercase; letter-spacing: .1em; }}

/* the site's three voices, kept in the prose */
.about strong, .job li strong, .lede strong, section > p strong {{ color: var(--ink); font-weight: 600; }}
.about em, .job li em {{ font-style: italic; }}
.term {{ font-family: var(--mono); font-size: .93em; white-space: nowrap; color: var(--ink-dim); }}
.big {{ color: var(--accent) !important; }}

.colophon {{
  margin-top: auto; padding-top: 7pt; border-top: 1px solid var(--line);
  font: 400 6.6pt/1.75 var(--mono); color: var(--ink-faint);
}}

@page {{ size: A4; margin: 0; }}
@media print {{
  .sheet {{ margin: 0; padding: 12mm 13mm 10mm 0; }}
  a {{ color: inherit; text-decoration: none; }}
}}
</style>
</head>
<body>
<main class="sheet">
  <aside class="rail">
    <p class="kicker">{esc(kicker)}</p>
    <h1>{name_markup['html']}</h1>
    <dl class="contact">{contact_rows}
    </dl>
    <div class="rail-foot">
      <p class="label">Tools</p>
      <p class="skills">{esc(tools)}</p>
    </div>
  </aside>

  <div class="col">
    <section>
      <p class="label">About</p>
      <p class="lede">{body['lead']}</p>
      <div class="about">{about_html}
      </div>
    </section>

    <section>
      <p class="label">Experience</p>
{chr(10).join(job_html)}
    </section>

    <section>
      <p class="label">Open source</p>
      <p>{lead}</p>
      <div class="stats">{stat_html}
      </div>
    </section>

    <p class="colophon">{esc(name_markup['plain'])} \u00b7 {esc(mail)} \u00b7 figures from GitHub, {esc(generated)}</p>
  </div>
</main>
</body>
</html>
"""


def from_page_name(page: str) -> dict:
    raw = re.search(r'<h1[^>]*>(.*?)</h1>', page, re.S).group(1)
    return {"html": raw.strip(), "plain": text(raw)}


def render_md(page: str) -> str:
    who = contact(page)
    body = about(page)
    jobs = experience(page)
    lead, os_items = stats(page)
    name = from_page_name(page)["plain"]
    lines = [f"# {name}", "",
             f"{who['email']['text']} · {who['github']['text']} · "
             f"{who['x']['text']} · {who['location']['text']}", ""]
    lines += ["## Summary", "", body["lead"], ""]
    lines += [p + "\n" for p in body["paras"]]
    lines += ["## Experience", ""]
    for job in jobs:
        lines.append(f"**{job['org']}** — {job['title']}  ")
        lines.append(f"{job['when']}  ")
        lines += [f"- {b}" for b in job["bullets"]]
        if job["tags"]:
            lines.append(f"- _{' · '.join(job['tags'])}_")
        lines.append("")
    lines += ["## Open source", "", lead, ""]
    lines += ["| " + " | ".join(k for _, k in os_items) + " |",
              "|" + "---|" * len(os_items),
              "| " + " | ".join(v for v, _ in os_items) + " |", ""]
    lines += ["## Tools", "", " · ".join(skills(jobs)), ""]
    return "\n".join(lines)


def data_generated() -> str:
    """Date the contribution figures came from, so the resume states its own vintage."""
    path = ROOT / "data" / "contributions.json"
    if path.exists():
        import json
        stamp = json.loads(path.read_text()).get("generated", "")
        if stamp:
            y, m, _ = stamp.split("-")
            months = ["January", "February", "March", "April", "May", "June", "July",
                      "August", "September", "October", "November", "December"]
            return f"{months[int(m) - 1]} {y}"
    return "this build"


def find_chrome():
    """Locate a Chrome/Chromium for headless PDF rendering, or None."""
    for name in ("chromium", "google-chrome", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    home = pathlib.Path.home()
    candidates = sorted(home.glob(
        "Library/Caches/ms-playwright/chromium-*/chrome-mac*/*.app/Contents/MacOS/*"))
    candidates += [
        pathlib.Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        pathlib.Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
    ]
    for path in candidates:
        if pathlib.Path(path).exists():
            return str(path)
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the resume from index.html")
    ap.add_argument("--pdf", action="store_true", help="also render resume.pdf")
    ap.add_argument("--light", action="store_true", help="print-friendly white version")
    args = ap.parse_args()

    page = SOURCE.read_text()
    OUT.mkdir(exist_ok=True)
    html = render_html(page, light=args.light)
    (OUT / ("resume-print.html" if args.light else "resume.html")).write_text(html)
    (OUT / "resume.md").write_text(render_md(page))
    stem = "resume-print" if args.light else "resume"
    print(f"wrote {OUT.relative_to(ROOT)}/{stem}.html and resume.md")

    if args.pdf:
        chrome = find_chrome()
        if not chrome:
            print("no Chrome/Chromium found — open resume/resume.html and print to PDF", file=sys.stderr)
            return 1
        pdf = OUT / f"{stem}.pdf"
        subprocess.run([chrome, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                        f"--print-to-pdf={pdf}", (OUT / f"{stem}.html").as_uri()],
                       check=True, capture_output=True)
        print(f"wrote {pdf.relative_to(ROOT)} ({pdf.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
