"""Rewrite the #open-source section of index.html from the cached contribution rows.

Every repo appears, sorted by owner then name. A repo's signature lists what the
work actually was — prs, reviews, issues — because a merged-PR count alone hides
review and triage work, and evaluate-only repos would otherwise vanish.
"""
import json, pathlib, re

# Work that predates this GitHub account: real, but not attributable to a handle.
PRE_ACCOUNT = {"OlympusDAO/olympus-contracts": "2021–22 · pre-account"}

DATA = json.loads(pathlib.Path("data/contributions.json").read_text())
rows = DATA["repos"]
known = {r[0] for r in rows}
for repo in PRE_ACCOUNT:
    if repo not in known:
        rows.append([repo, 0, 0, 0, 0, 0])
rows.sort(key=lambda t: (t[0].split("/")[0].lower(), t[0].lower()))
html = pathlib.Path("index.html")
src = html.read_text()

def plural(n, one, many):
    return f"{n} {one if n == 1 else many}"

def signature(repo, p, a, v, i, c):
    if repo in PRE_ACCOUNT:
        return PRE_ACCOUNT[repo]
    parts = []
    if p: parts.append(plural(p, "pr", "prs"))
    if v: parts.append(plural(v, "rev", "revs"))
    if i: parts.append(plural(i, "issue", "issues"))
    if not parts and c: parts.append(plural(c, "commit", "commits"))
    if not parts: parts.append("commented")
    return " · ".join(parts)

lines = []
for repo, p, a, v, i, c in rows:
    lines.append(
        f'            <div class="prs-row"><a href="https://github.com/{repo}">{repo}</a>'
        f'<span class="prs-n{" note" if repo in PRE_ACCOUNT else ""}">{signature(repo, p, a, v, i, c)}</span></div>')

total_prs = sum(r[1] for r in rows)
total_open = sum(r[2] for r in rows)
total_rev = sum(r[3] for r in rows)
total_iss = sum(r[4] for r in rows)
total_com = sum(r[5] for r in rows)
half = (len(rows) + 1) // 2

section = f'''      <section id="open-source" aria-labelledby="open-source-h">
        <h2 class="label" id="open-source-h">Open source work</h2>

        <p class="prs-lead">
          <strong>{total_prs} pull requests</strong> merged since 2020, out of {total_open} opened,
          across <strong>{len(rows)} repositories</strong> — every one I've touched, listed below.
          Where the work was review or triage rather than code, the row says so.
        </p>

        <div class="stats">
          <div class="stat"><b>{total_prs}</b><span>merged PRs</span></div>
          <div class="stat"><b>{total_open}</b><span>PRs opened</span></div>
          <div class="stat"><b>{total_rev}</b><span>reviews</span></div>
          <div class="stat"><b>{total_iss}</b><span>issues</span></div>
          <div class="stat"><b>{total_com:,}</b><span>commits</span></div>
          <div class="stat"><b>1,062</b><span>private work</span></div>
        </div>

        <div class="prs">
{chr(10).join(lines)}
        </div>

        <p class="prs-note">
          Olympus DAO comes before this GitHub account, so it isn't in the numbers; the
          Experience section covers it. Private work is only ever shown as a total.
        </p>
      </section>'''

start = src.index('      <section id="open-source"')
end = src.index('      </section>', start) + len('      </section>')
src = src[:start] + section + src[end:]

src = re.sub(r'\n\.prs-group \+ \.prs-group[^}]*}\n\.prs-head \{[^}]*}\n\.prs \{ display: grid;[^}]*}',
             '\n.prs-cols { display: grid; gap: 0 2.2rem; margin: 0 0 1.8rem; }'
             '\n@media (min-width: 46rem) { .prs-cols { grid-template-columns: repeat(2, minmax(0, 1fr)); } }'
             '\n.prs { display: grid; row-gap: .55rem; }', src, flags=re.S)
src = src.replace('.prs-row { display: flex; justify-content: space-between; gap: 1rem; grid-column: 1 / -1; }',
                  '.prs-row { display: flex; justify-content: space-between; align-items: baseline; gap: 1rem; }')
src = src.replace('.prs-n i { font-style: normal; color: var(--line); margin-left: .3em; }',
                  '.prs-note { margin: 0; font-size: var(--step--1); line-height: 1.6; color: var(--ink-faint); }')
html.write_text(src)
print(f"{len(rows)} rows written")
