#!/usr/bin/env bash
# Every repository I have contributed to, and what kind of work it was:
#
#   prs      pull requests authored and merged   (search, all time)
#   all      pull requests authored, any state
#   rev      pull requests reviewed
#   iss      issues opened
#   commits  commits authored on the default branch, counted exactly
#
# PRs, reviews and issues come from the search API (capped at 1000 per query, but
# those four queries stay under it). Commits cannot come from search — thousands
# of them need pagination that trips the search rate limit — so each repository is
# asked once and the total is read off the Link header: one request per repo.
#
# Sorted by owner, then repository, so an org's repos stay together.
# Usage: ./contrib.sh [login]
set -euo pipefail
exec python3 - "$@" <<'PY'
import json, re, subprocess, sys, collections
from concurrent.futures import ThreadPoolExecutor

me = sys.argv[1] if len(sys.argv) > 1 else json.loads(
    subprocess.run(["gh", "api", "user"], capture_output=True, text=True, check=True).stdout)["login"]

def gh(*args):
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=True).stdout

def per_repo(*search_args):
    out = gh("search", *search_args, "--limit", "1000", "--json", "repository")
    return collections.Counter(p["repository"]["nameWithOwner"] for p in json.loads(out))

prs    = per_repo("prs", "--author", me, "--merged")
allprs = per_repo("prs", "--author", me)
revs   = per_repo("prs", "--reviewed-by", me)
iss    = per_repo("issues", "--author", me)

def commits_in(repo):
    """Exact count of my commits on the default branch: read the last page number."""
    r = subprocess.run(["gh", "api", f"repos/{repo}/commits?author={me}&per_page=1", "--include"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return repo, 0
    for line in r.stdout.splitlines():
        if line.lower().startswith("link:"):
            for part in line.split(","):
                if 'rel="last"' in part:
                    n = re.search(r"[?&]page=(\d+)>", part)
                    if n:
                        return repo, int(n.group(1))
    body = r.stdout.split("\r\n\r\n", 1)[-1].split("\n\n", 1)[-1].strip()
    try:
        return repo, len(json.loads(body)) if body.startswith("[") else 0
    except json.JSONDecodeError:
        return repo, 0

def commit_repos():
    """Repos my commits live in, from contribution years — catches repos with no PR."""
    found, year, now = set(), 2020, 2026
    for y in range(year, now + 1):
        q = ('query($l:String!,$f:DateTime!,$t:DateTime!){user(login:$l){'
             'contributionsCollection(from:$f,to:$t){commitContributionsByRepository(maxRepositories:100)'
             '{repository{nameWithOwner}}}}}')
        r = subprocess.run(["gh", "api", "graphql", "-f", f"login={me}", "-f", f"query={q}",
                            "-f", f"f={y}-01-01T00:00:00Z", "-f", f"t={y}-12-31T23:59:59Z"],
                           capture_output=True, text=True)
        if r.returncode:
            continue
        d = json.loads(r.stdout)["data"]["user"]["contributionsCollection"]
        found |= {x["repository"]["nameWithOwner"] for x in d["commitContributionsByRepository"]}
    return found

repos = set(prs) | set(allprs) | set(revs) | set(iss) | commit_repos()
with ThreadPoolExecutor(max_workers=6) as pool:
    commits = dict(pool.map(commits_in, sorted(repos)))

rows = [(r, prs[r], allprs[r], revs[r], iss[r], commits.get(r, 0)) for r in repos]
rows.sort(key=lambda t: (t[0].lower().split("/")[0], t[0].lower()))

print(f"{'repository':46s} {'prs':>5s} {'all':>5s} {'rev':>4s} {'iss':>5s} {'commits':>8s}")
for r, p, a, v, i, c in rows:
    print(f"{r:46s} {p:5d} {a:5d} {v:4d} {i:5d} {c:8d}")
tot = [sum(x[k] for x in rows) for k in range(1, 6)]
print(f"{'TOTAL':46s} {tot[0]:5d} {tot[1]:5d} {tot[2]:4d} {tot[3]:5d} {tot[4]:8d}")

# GitHub's own all-repos commit count, for comparison with the per-repo columns
merged_total = json.loads(gh("api", "search/issues?q=author:%s+type:pr+is:merged&per_page=1" % me))["total_count"]
all_total = json.loads(gh("api", "search/issues?q=author:%s+type:pr&per_page=1" % me))["total_count"]
rev_total = json.loads(gh("api", "search/issues?q=reviewed-by:%s+type:pr&per_page=1" % me))["total_count"]
iss_total = json.loads(gh("api", "search/issues?q=author:%s+type:issue&per_page=1" % me))["total_count"]
com_total = json.loads(gh("api", "search/commits?q=author:%s&per_page=1" % me))["total_count"]
print(f"\n{len(rows)} repos with merged PRs, reviews, issues or commits")
print(f"GitHub search totals: {merged_total} merged PRs · {all_total} PRs authored · "
      f"{rev_total} reviews · {iss_total} issues · {com_total} commits")
PY
