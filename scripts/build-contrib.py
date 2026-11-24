"""Collect every repo 0xClandestine has contributed to and cache it as JSON.

Sources, unioned so nothing hides:
  search: PRs merged / PRs opened / PRs reviewed / issues opened
  contributionsCollection (one call per year): repos with commits
  REST: exact commit count per repo, read off the Link header

Cached so a rerun does not re-hit the search rate limit.
"""
import json, re, subprocess, sys, collections, pathlib
from concurrent.futures import ThreadPoolExecutor

me = "0xClandestine"
cache = pathlib.Path("/tmp/contrib-cache.json")
years = range(2020, 2027)

def gh(*a):
    r = subprocess.run(["gh", *a], capture_output=True, text=True)
    if r.returncode:
        print(f"warn: {a[0]} {a[1][:40]} -> {r.stderr.splitlines()[0][:80]}", file=sys.stderr)
        return ""
    return r.stdout

data = json.loads(cache.read_text()) if cache.exists() else {}

def search(name, *args):
    if name in data:
        return data[name]
    out = gh("search", *args, "--limit", "1000", "--json", "repository")
    c = dict(collections.Counter(p["repository"]["nameWithOwner"] for p in json.loads(out or "[]")))
    if c:                      # never cache a rate-limited empty answer
        data[name] = c
        cache.write_text(json.dumps(data))
    return c

prs    = search("prs", "prs", "--author", me, "--merged")
allprs = search("all", "prs", "--author", me)
revs   = search("rev", "prs", "--reviewed-by", me)
iss    = search("iss", "issues", "--author", me)

if "contrib" not in data:
    acc = collections.Counter()
    q = ('query($l:String!,$f:DateTime!,$t:DateTime!){user(login:$l){'
         'contributionsCollection(from:$f,to:$t){commitContributionsByRepository('
         'maxRepositories:100){repository{nameWithOwner} contributions{totalCount}}}}}')
    for y in years:
        out = gh("api", "graphql", "-f", f"l={me}", "-f", f"query={q}",
                 "-f", f"f={y}-01-01T00:00:00Z", "-f", f"t={y}-12-31T23:59:59Z")
        if not out:
            continue
        d = json.loads(out)["data"]["user"]["contributionsCollection"]
        for x in d["commitContributionsByRepository"]:
            acc[x["repository"]["nameWithOwner"]] += x["contributions"]["totalCount"]
    data["contrib"] = dict(acc)

repos = set(prs) | set(allprs) | set(revs) | set(iss) | set(data["contrib"])
commits = data.get("commits", {})

def count_commits(repo):
    out = gh("api", f"repos/{repo}/commits?author={me}&per_page=1", "--include")
    for line in out.splitlines():
        if line.lower().startswith("link:"):
            m = re.search(r'[?&]page=(\d+)>;\s*rel="last"', line)
            if m:
                return repo, int(m.group(1))
    return repo, 0

todo = sorted(r for r in repos if r not in commits)
if todo:
    with ThreadPoolExecutor(max_workers=8) as pool:
        for repo, n in pool.map(count_commits, todo):
            commits[repo] = n
    data["commits"] = commits
cache.write_text(json.dumps(data))

rows = [(r, prs.get(r, 0), allprs.get(r, 0), revs.get(r, 0), iss.get(r, 0),
         max(commits.get(r, 0), data["contrib"].get(r, 0))) for r in repos]
rows.sort(key=lambda t: (t[0].split("/")[0].lower(), t[0].lower()))
json.dump(rows, open("/tmp/contrib-rows.json", "w"))
print(f"{len(rows)} repos")
print(f"prs {sum(r[1] for r in rows)} · opened {sum(r[2] for r in rows)} · "
      f"reviews {sum(r[3] for r in rows)} · issues {sum(r[4] for r in rows)} · "
      f"commits {sum(r[5] for r in rows)}")
