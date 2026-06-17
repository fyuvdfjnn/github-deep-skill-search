#!/usr/bin/env python3
"""Search GitHub for agent skills and inspect likely skill files."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


API = "https://api.github.com"
LIKELY_DOC_NAMES = (
    "SKILL.md",
    "README.md",
    "skill.md",
    "AGENT.md",
    "agents.md",
    "CLAUDE.md",
)
LIKELY_PATH_MARKERS = (
    "SKILL.md",
    "/skills/",
    ".claude/skills",
    ".agents/skills",
    ".github/skills",
    ".cursor/skills",
    ".gemini/skills",
    "officialskills.sh",
)
GITHUB_RE = re.compile(r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(?:/(?:tree|blob)/([^\s)#]+))?")
OFFICIAL_SKILL_RE = re.compile(r"https://officialskills\.sh/([A-Za-z0-9_.-]+)/skills/([A-Za-z0-9_.-]+)")


@dataclass
class Candidate:
    full_name: str
    html_url: str
    description: str = ""
    stars: int = 0
    forks: int = 0
    watchers: int = 0
    language: str | None = None
    topics: list[str] = field(default_factory=list)
    updated_at: str = ""
    pushed_at: str = ""
    archived: bool = False
    disabled: bool = False
    license: str | None = None
    default_branch: str = "main"
    score: int = 0
    score_breakdown: dict[str, int] = field(default_factory=dict)
    match_reasons: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    inspected_files: list[dict[str, Any]] = field(default_factory=list)
    likely_skill_paths: list[str] = field(default_factory=list)
    type: str = "unknown"
    role: str = "unknown"


def request_json(url: str, token: str | None, quiet: bool = False) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "github-deep-skill-search",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if not quiet:
            print(f"warning: GitHub request failed {exc.code}: {url}\n{body[:300]}", file=sys.stderr)
        if exc.code == 429:
            time.sleep(1.5)
        return None
    except Exception as exc:
        if not quiet:
            print(f"warning: request failed: {url}: {exc}", file=sys.stderr)
        return None


def search_repositories(query: str, per_query: int, token: str | None) -> list[dict[str, Any]]:
    q = urllib.parse.quote(query)
    url = f"{API}/search/repositories?q={q}&sort=stars&order=desc&per_page={per_query}"
    data = request_json(url, token)
    if not data:
        return []
    return data.get("items", [])


def get_repo(full_name: str, token: str | None) -> dict[str, Any] | None:
    return request_json(f"{API}/repos/{full_name}", token, quiet=True)


def repo_tree(full_name: str, branch: str, token: str | None) -> list[dict[str, Any]]:
    url = f"{API}/repos/{full_name}/git/trees/{urllib.parse.quote(branch)}?recursive=1"
    data = request_json(url, token, quiet=True)
    if not data:
        return []
    return data.get("tree", [])


def get_content(full_name: str, path: str, branch: str, token: str | None) -> str | None:
    encoded_path = "/".join(urllib.parse.quote(part) for part in path.split("/"))
    encoded_ref = urllib.parse.quote(branch)
    url = f"{API}/repos/{full_name}/contents/{encoded_path}?ref={encoded_ref}"
    data = request_json(url, token, quiet=True)
    if not data or isinstance(data, list):
        return None
    content = data.get("content")
    if not content:
        return None
    if data.get("encoding") == "base64":
        try:
            return base64.b64decode(content).decode("utf-8", errors="replace")
        except Exception:
            return None
    return content


def extract_github_repos_from_text(text: str) -> dict[str, list[str]]:
    repos: dict[str, list[str]] = {}
    for match in GITHUB_RE.finditer(text):
        repo = match.group(1).rstrip(".")
        path = match.group(2) or ""
        if repo.lower().startswith("user-attachments/") or repo.lower().endswith((".png", ".svg", ".jpg", ".jpeg", ".gif")):
            continue
        repos.setdefault(repo, [])
        if path:
            repos[repo].append(path)
    return repos


def looks_like_noise_repo(repo: str) -> bool:
    lower = repo.lower()
    return lower.startswith("user-attachments/") or lower in {"github/user-attachments"}


def parse_seed_stars(fragment: str) -> int | None:
    match = re.search(r"Stars[:：]\s*(?:约\s*)?([0-9]+(?:\.[0-9]+)?)([kK]?)", fragment)
    if not match:
        return None
    value = float(match.group(1))
    if match.group(2):
        value *= 1000
    return int(value)


def seed_context_for_match(text: str, start: int, end: int) -> str:
    """Return the nearest Markdown-ish section or local window for one repo link."""
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    if line_end == -1:
        line_end = len(text)
    line = text[line_start:line_end]
    if line.lstrip().startswith(("-", "*", "|")) and len(line) < 1200:
        return line
    before = text.rfind("\n##", 0, start)
    after_match = re.search(r"\n##+\s+", text[end:])
    after = end + after_match.start() if after_match else -1
    if before != -1 and after != -1 and after > before and after - before < 2500:
        return text[before:after]
    if before != -1 and len(text) - before < 2500:
        return text[before:]
    return text[max(0, start - 300) : min(len(text), end + 700)]


def extract_seed_candidates_from_text(text: str) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for match in GITHUB_RE.finditer(text):
        repo = match.group(1).rstrip(".")
        if looks_like_noise_repo(repo):
            continue
        path = match.group(2) or ""
        context = seed_context_for_match(text, match.start(), match.end())
        seed = found.setdefault(repo, {"paths": [], "stars": None, "context": ""})
        if path:
            seed["paths"].append(path)
        parsed_stars = parse_seed_stars(context)
        if parsed_stars is not None:
            seed["stars"] = parsed_stars
        if len(context) > len(seed.get("context") or ""):
            seed["context"] = context
    for match in OFFICIAL_SKILL_RE.finditer(text):
        owner = match.group(1)
        skill = match.group(2)
        key = f"officialskills.sh/{owner}/{skill}"
        context = seed_context_for_match(text, match.start(), match.end())
        seed = found.setdefault(key, {"paths": [], "stars": None, "context": "", "official_url": match.group(0)})
        seed["paths"].append(f"officialskills.sh/{owner}/skills/{skill}")
        seed["official_url"] = match.group(0)
        parsed_stars = parse_seed_stars(context)
        if parsed_stars is not None:
            seed["stars"] = parsed_stars
        if len(context) > len(seed.get("context") or ""):
            seed["context"] = context
    return found


def high_value_terms(include: list[str]) -> list[str]:
    generic = {"skill", "skills", "skill.md", "agent", "agents", "github", "research", "writing"}
    return [term for term in include if term and term.lower() not in generic and len(term) >= 3]


def seed_repositories(seed_repo: str, token: str | None, include: list[str], seed_limit: int) -> dict[str, dict[str, Any]]:
    repo_meta = get_repo(seed_repo, token)
    if not repo_meta:
        return {}
    branch = repo_meta.get("default_branch") or "main"
    readme = get_content(seed_repo, "README.md", branch, token) or ""
    lower = readme.lower()
    chunks: list[str] = []
    for term in high_value_terms(include):
        idx = lower.find(term.lower())
        if idx != -1:
            chunks.append(readme[max(0, idx - 2500) : idx + 2500])
    if not chunks:
        chunks = [readme[:20000]]
    found: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        for full_name, seed in extract_seed_candidates_from_text(chunk).items():
            if len(found) >= seed_limit:
                return found
            if full_name.startswith("officialskills.sh/"):
                parts = full_name.split("/")
                owner, skill = parts[1], parts[2]
                meta = {
                    "full_name": full_name,
                    "html_url": seed.get("official_url") or f"https://officialskills.sh/{owner}/skills/{skill}",
                    "description": "",
                    "stargazers_count": 0,
                    "forks_count": 0,
                    "watchers_count": 0,
                    "topics": [],
                    "default_branch": "main",
                }
            else:
                meta = get_repo(full_name, token)
            if not meta:
                continue
            meta["_seed_paths"] = sorted(set(seed.get("paths") or []))
            if seed.get("stars") is not None:
                meta["stargazers_count"] = seed["stars"]
            if seed.get("context"):
                meta["_seed_context"] = seed["context"]
            meta["_seeded_from"] = seed_repo
            found[full_name] = meta
    return found


def seed_repositories_from_text(
    text: str,
    source: str,
    token: str | None,
    include: list[str],
    seed_limit: int,
    hydrate: bool,
) -> dict[str, dict[str, Any]]:
    lower = text.lower()
    chunks: list[str] = []
    for term in high_value_terms(include):
        idx = lower.find(term.lower())
        if idx != -1:
            chunks.append(text[max(0, idx - 2500) : idx + 2500])
    if not chunks:
        chunks = [text[:20000]]
    found: dict[str, dict[str, Any]] = {}
    for chunk in chunks:
        for full_name, seed in extract_seed_candidates_from_text(chunk).items():
            if len(found) >= seed_limit:
                return found
            if full_name.startswith("officialskills.sh/"):
                parts = full_name.split("/")
                owner, skill = parts[1], parts[2]
                meta = {
                    "full_name": full_name,
                    "html_url": seed.get("official_url") or f"https://officialskills.sh/{owner}/skills/{skill}",
                    "description": "",
                    "stargazers_count": 0,
                    "forks_count": 0,
                    "watchers_count": 0,
                    "topics": [],
                    "default_branch": "main",
                }
            else:
                meta = get_repo(full_name, token) if hydrate else None
            meta = meta or {
                "full_name": full_name,
                "html_url": f"https://github.com/{full_name}",
                "description": "",
                "stargazers_count": 0,
                "forks_count": 0,
                "watchers_count": 0,
                "topics": [],
                "default_branch": "main",
            }
            meta["_seed_paths"] = sorted(set(seed.get("paths") or []))
            if seed.get("stars") is not None:
                meta["stargazers_count"] = seed["stars"]
            if seed.get("context"):
                meta["_seed_context"] = seed["context"]
                if not meta.get("description"):
                    meta["description"] = re.sub(r"\s+", " ", seed["context"]).strip()[:500]
            meta["_seeded_from"] = source
            found[full_name] = meta
    return found


def normalize_terms(value: str | None) -> list[str]:
    if not value:
        return []
    return [term.strip().lower() for term in re.split(r"[,|]", value) if term.strip()]


def text_score(
    text: str,
    include: list[str],
    exclude: list[str],
    core_terms: list[str],
    support_terms: list[str],
) -> tuple[int, list[str], list[str], dict[str, int]]:
    lower = text.lower()
    reasons: list[str] = []
    risks: list[str] = []
    score = 0
    metrics = {
        "core_matches": 0,
        "support_matches": 0,
        "include_matches": 0,
        "skill_marker_matches": 0,
    }
    for term in core_terms:
        if term and term in lower:
            score += 8
            metrics["core_matches"] += 1
            reasons.append(f"core match: {term}")
    for term in support_terms:
        if term and term in lower:
            score += 2
            metrics["support_matches"] += 1
            reasons.append(f"support match: {term}")
    residual_terms = [term for term in include if term not in core_terms and term not in support_terms]
    for term in residual_terms:
        if term and term in lower:
            score += 3
            metrics["include_matches"] += 1
            reasons.append(f"matches term: {term}")
    for term in exclude:
        if term and term in lower:
            score -= 6
            risks.append(f"contains excluded term: {term}")
    for marker in LIKELY_PATH_MARKERS:
        if marker.lower() in lower:
            score += 3
            metrics["skill_marker_matches"] += 1
            reasons.append(f"skill marker: {marker}")
    return score, reasons, risks, metrics


def derive_core_terms(queries: list[str], include: list[str]) -> list[str]:
    support_like = {"skill", "skills", "skill.md", "agent", "agents", "github", "humanizer", "research", "writing"}
    core: list[str] = []
    for term in include:
        if term.lower() not in support_like:
            core.append(term)
    for query in queries:
        lower = query.lower()
        for phrase in (
            "study abroad",
            "personal statement",
            "statement of purpose",
            "admissions essay",
            "admissions essays",
            "motivation letter",
            "graduate admissions",
            "留学",
            "文书",
            "sop",
        ):
            if phrase in lower:
                core.append(phrase)
    seen: set[str] = set()
    return [term for term in core if not (term in seen or seen.add(term))]


def derive_support_terms(include: list[str], explicit_support: list[str]) -> list[str]:
    support_like = {"humanizer", "research", "writing", "polish", "rewrite", "论文", "润色"}
    support = list(explicit_support)
    for term in include:
        if term.lower() in support_like:
            support.append(term)
    seen: set[str] = set()
    return [term for term in support if not (term in seen or seen.add(term))]


def days_since(value: str) -> int | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).days
    except ValueError:
        return None


def classify(candidate: Candidate) -> str:
    paths = "\n".join(candidate.likely_skill_paths).lower()
    file_names = "\n".join(f["path"].lower() for f in candidate.inspected_files if not f["path"].startswith("seed:"))
    text = (paths + "\n" + file_names).lower()
    if candidate.full_name.startswith("officialskills.sh/"):
        return "official skill listing"
    if "skill.md" in text:
        return "directly installable or path-verifiable skill"
    if "/skills/" in text or ".claude/skills" in text or ".agents/skills" in text or ".github/skills" in text:
        return "skill collection"
    if "awesome" in candidate.full_name.lower() or "awesome" in candidate.description.lower():
        return "curated index"
    if "skill" in candidate.full_name.lower() or "skill" in candidate.description.lower():
        return "unverified skill candidate"
    return "convertible reference or ordinary repository"


def classify_role(metrics: dict[str, int], candidate: Candidate) -> str:
    repo_name = candidate.full_name.lower()
    text = " ".join(
        [
            candidate.full_name,
            candidate.description or "",
            " ".join(f.get("snippet", "") for f in candidate.inspected_files),
        ]
    ).lower()
    if "awesome" in repo_name:
        return "discovery index"

    primary_repo_markers = (
        "personal-statement",
        "personal_statement",
        "statement-of-purpose",
        "study-abroad",
        "admissions",
        "grad-essays",
        "taught-master",
        "application",
        "advisor",
    )
    support_repo_markers = (
        "humanizer",
        "research-paper",
        "writing-skills",
        "论文",
        "润色",
    )
    support_cues = (
        "not responsible for",
        "not a general",
        "不是留学专用",
        "不是通用留学申请",
        "不负责选校",
        "最终润色",
        "去 ai",
        "偏科研论文",
        "supporting tool",
        "辅助",
    )

    has_primary_repo_marker = any(marker in repo_name for marker in primary_repo_markers)
    has_support_repo_marker = any(marker in repo_name for marker in support_repo_markers)
    has_support_cue = any(cue in text for cue in support_cues)

    if has_primary_repo_marker and metrics["core_matches"] >= 1:
        return "primary match"
    if has_support_repo_marker or has_support_cue:
        return "supporting tool"
    if metrics["core_matches"] >= 2:
        return "primary match"
    if metrics["support_matches"] > 0 and metrics["core_matches"] <= 1:
        return "supporting tool"
    return "weak or adjacent match"


def score_candidate(candidate: Candidate, include: list[str], exclude: list[str], core_terms: list[str], support_terms: list[str]) -> None:
    combined = " ".join(
        [
            candidate.full_name,
            candidate.description or "",
            " ".join(candidate.topics),
            " ".join(f.get("path", "") + " " + f.get("snippet", "") for f in candidate.inspected_files),
            " ".join(candidate.likely_skill_paths),
        ]
    )
    relevance, reasons, risks, metrics = text_score(combined, include, exclude, core_terms, support_terms)
    role_preview = classify_role(metrics, candidate)
    if role_preview == "supporting tool":
        relevance = max(0, relevance - 8)
        risks.append("supporting or auxiliary resource rather than a primary domain skill")
    elif role_preview == "discovery index":
        relevance = max(0, relevance - 4)
        risks.append("curated index, not a direct skill")
    elif metrics["core_matches"] >= 2:
        relevance += 10
        reasons.append("multiple core terms matched")
    elif metrics["core_matches"] == 0 and metrics["support_matches"] > 0:
        relevance = max(0, relevance - 8)
        risks.append("supporting terms matched but no core topic terms")
    relevance = max(0, min(40, relevance))
    if not candidate.likely_skill_paths and candidate.stars < 50:
        relevance = max(0, relevance - 6)
        risks.append("no skill files or path markers found")

    installability = 0
    if any("skill.md" in p.lower() for p in candidate.likely_skill_paths):
        installability = 20
    elif any("/skills/" in p.lower() or ".claude/skills" in p.lower() or ".agents/skills" in p.lower() for p in candidate.likely_skill_paths):
        installability = 12
    elif candidate.inspected_files:
        installability = 5

    community = min(15, int(candidate.stars ** 0.5))
    maintenance = 0
    age = days_since(candidate.pushed_at or candidate.updated_at)
    if candidate.archived or candidate.disabled:
        risks.append("repository is archived or disabled")
    elif age is None:
        maintenance = 3
    elif age <= 180:
        maintenance = 10
    elif age <= 730:
        maintenance = 7
    else:
        maintenance = 3
        risks.append("repository appears stale")

    docs = 0
    real_inspected_files = [f for f in candidate.inspected_files if not f["path"].startswith("seed:")]
    if any(f["path"].lower().endswith("readme.md") for f in real_inspected_files):
        docs += 5
    if any(f["path"].lower().endswith("skill.md") for f in real_inspected_files):
        docs += 5
    docs = min(10, docs)

    trust = 0
    if candidate.license:
        trust += 2
    if candidate.stars >= 1000:
        trust += 2
    if not candidate.archived:
        trust += 1
    trust = min(5, trust)

    if candidate.stars == 0:
        risks.append("no GitHub stars")
    if not candidate.inspected_files:
        risks.append("no README/SKILL file inspected")

    candidate.score_breakdown = {
        "relevance": relevance,
        "installability": installability,
        "community": community,
        "maintenance": maintenance,
        "documentation": docs,
        "trust": trust,
    }
    candidate.score = sum(candidate.score_breakdown.values())
    candidate.match_reasons = sorted(set(reasons))[:12]
    candidate.risks = sorted(set(risks))[:12]
    candidate.type = classify(candidate)
    candidate.role = role_preview


def repo_to_candidate(repo: dict[str, Any]) -> Candidate:
    license_obj = repo.get("license") or {}
    c = Candidate(
        full_name=repo.get("full_name", ""),
        html_url=repo.get("html_url", ""),
        description=repo.get("description") or "",
        stars=repo.get("stargazers_count") or 0,
        forks=repo.get("forks_count") or 0,
        watchers=repo.get("watchers_count") or 0,
        language=repo.get("language"),
        topics=repo.get("topics") or [],
        updated_at=repo.get("updated_at") or "",
        pushed_at=repo.get("pushed_at") or "",
        archived=bool(repo.get("archived")),
        disabled=bool(repo.get("disabled")),
        license=license_obj.get("spdx_id") if isinstance(license_obj, dict) else None,
        default_branch=repo.get("default_branch") or "main",
    )
    seed_paths = repo.get("_seed_paths") or []
    if seed_paths:
        c.likely_skill_paths = list(seed_paths)
        c.match_reasons.append(f"seeded from {repo.get('_seeded_from')}")
    if repo.get("_seed_context"):
        c.inspected_files.append(
            {
                "path": f"seed:{repo.get('_seeded_from')}",
                "url": repo.get("html_url", ""),
                "snippet": re.sub(r"\s+", " ", repo["_seed_context"]).strip()[:1400],
            }
        )
    return c


def inspect_candidate(candidate: Candidate, token: str | None, inspect_files: int) -> None:
    if candidate.full_name.startswith("officialskills.sh/"):
        return
    tree = repo_tree(candidate.full_name, candidate.default_branch, token)
    likely_paths: list[str] = list(candidate.likely_skill_paths)
    for item in tree:
        path = item.get("path", "")
        if item.get("type") != "blob":
            continue
        lower = path.lower()
        if lower.endswith("skill.md") or any(marker.lower().strip("/") in lower for marker in LIKELY_PATH_MARKERS if marker != "officialskills.sh"):
            likely_paths.append(path)
        elif os.path.basename(path) in LIKELY_DOC_NAMES:
            likely_paths.append(path)
    candidate.likely_skill_paths = sorted(set(likely_paths))[:50]

    docs: list[str] = []
    priority = ["SKILL.md", "README.md"]
    for name in priority:
        for path in candidate.likely_skill_paths:
            if path.lower().endswith(name.lower()) and path not in docs:
                docs.append(path)
    for path in candidate.likely_skill_paths:
        if path not in docs:
            docs.append(path)
    for path in docs[:inspect_files]:
        content = get_content(candidate.full_name, path, candidate.default_branch, token)
        if not content:
            continue
        snippet = re.sub(r"\s+", " ", content[:1400]).strip()
        candidate.inspected_files.append(
            {
                "path": path,
                "url": f"{candidate.html_url}/blob/{candidate.default_branch}/{path}",
                "snippet": snippet,
            }
        )


def render_markdown(candidates: list[Candidate]) -> str:
    lines = [
        "| Score | R/I/C | Stars | Repo | Role | Type | Updated | Signals |",
        "|---:|---|---:|---|---|---|---|---|",
    ]
    for c in candidates:
        signals = "; ".join((c.match_reasons or c.risks or ["inspected"])[:3])
        updated = (c.pushed_at or c.updated_at or "")[:10]
        breakdown = c.score_breakdown or {}
        ric = f"{breakdown.get('relevance', 0)}/{breakdown.get('installability', 0)}/{breakdown.get('community', 0)}"
        lines.append(
            f"| {c.score} | {ric} | {c.stars} | [{c.full_name}]({c.html_url}) | {c.role} | {c.type} | {updated} | {signals} |"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", action="append", required=True, help="GitHub repository search query. Repeat for multiple searches.")
    parser.add_argument("--include", help="Comma-separated relevance terms to boost.")
    parser.add_argument("--exclude", help="Comma-separated terms to downrank.")
    parser.add_argument("--core", help="Comma-separated core domain terms to weight heavily.")
    parser.add_argument("--support", help="Comma-separated auxiliary terms to weight lightly.")
    parser.add_argument("--limit", type=int, default=10, help="Final candidate count.")
    parser.add_argument("--per-query", type=int, default=20, help="GitHub results per query.")
    parser.add_argument("--inspect-files", type=int, default=4, help="Likely docs/skill files to fetch per repo.")
    parser.add_argument("--seed-repo", action="append", help="Repository whose README should be mined for GitHub links before scoring. Repeatable.")
    parser.add_argument("--seed-file", action="append", help="Local Markdown/text file whose GitHub links should be mined. Repeatable.")
    parser.add_argument("--seed-limit", type=int, default=60, help="Maximum repositories to inspect from seed sources.")
    parser.add_argument("--hydrate-seeds", action="store_true", help="Fetch GitHub metadata for repositories discovered from seed files.")
    parser.add_argument("--seed-only", action="store_true", help="Skip GitHub search and rank only seed sources.")
    parser.add_argument("--out", help="Write JSON report to this path.")
    parser.add_argument("--markdown", action="store_true", help="Print Markdown summary.")
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    include = normalize_terms(args.include)
    exclude = normalize_terms(args.exclude)
    core_terms = normalize_terms(args.core) or derive_core_terms(args.query, include)
    support_terms = derive_support_terms(include, normalize_terms(args.support))

    repos: dict[str, dict[str, Any]] = {}
    expanded_queries: list[str] = []
    for query in args.query:
        expanded_queries.append(query)
        if "skill" not in query.lower():
            expanded_queries.extend(
                [
                    f'{query} skill',
                    f'{query} "SKILL.md"',
                    f'{query} "agent skill"',
                ]
            )

    if not args.seed_only:
        for query in expanded_queries:
            for repo in search_repositories(query, args.per_query, token):
                full_name = repo.get("full_name")
                if full_name and full_name not in repos:
                    repos[full_name] = repo

    for seed_repo in args.seed_repo or []:
        for full_name, repo in seed_repositories(seed_repo, token, include, args.seed_limit).items():
            if full_name not in repos:
                repos[full_name] = repo

    for seed_file in args.seed_file or []:
        try:
            with open(seed_file, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError as exc:
            print(f"warning: could not read seed file {seed_file}: {exc}", file=sys.stderr)
            continue
        for full_name, repo in seed_repositories_from_text(text, seed_file, token, include, args.seed_limit, args.hydrate_seeds).items():
            if full_name not in repos:
                repos[full_name] = repo

    candidates = [repo_to_candidate(repo) for repo in repos.values()]
    for candidate in candidates:
        inspect_candidate(candidate, token, args.inspect_files)
        score_candidate(candidate, include, exclude, core_terms, support_terms)

    role_order = {"primary match": 3, "discovery index": 2, "supporting tool": 1, "weak or adjacent match": 0}
    candidates.sort(key=lambda c: (role_order.get(c.role, 0), c.score, c.stars, c.forks), reverse=True)
    selected = candidates[: args.limit]

    report = {
        "queries": expanded_queries,
        "seed_repos": args.seed_repo or [],
        "seed_files": args.seed_file or [],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "token_used": bool(token),
        "core_terms": core_terms,
        "support_terms": support_terms,
        "candidate_count": len(candidates),
        "results": [c.__dict__ for c in selected],
    }

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2)

    if args.markdown:
        print(render_markdown(selected))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
