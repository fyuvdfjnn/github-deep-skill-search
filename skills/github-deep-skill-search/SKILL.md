---
name: github-deep-skill-search
description: Deeply search, inspect, rank, and compare GitHub-hosted agent skills, Codex skills, Claude skills, skill collections, and topic-specific workflow repositories. Use when Codex needs to find high-quality skills for a domain, verify stars and maintenance, inspect README/SKILL.md content, identify installable skill paths, compare candidates, or create an evidence-backed shortlist from GitHub.
---

# GitHub Deep Skill Search

## Overview

Use this skill to move beyond shallow GitHub search. It discovers candidate repositories, inspects their metadata and skill files, scores relevance and quality, and returns an evidence-backed shortlist with links, installability notes, and caveats.

This skill was designed after reviewing `VoltAgent/awesome-agent-skills`: prefer curated/community-proven skills, clear descriptions, progressive disclosure, explicit skill paths, active maintenance, and real-world usage over bulk-generated or low-evidence repositories.

## Quick Start

Run the bundled search script first:

```bash
python3 ~/.codex/skills/github-deep-skill-search/scripts/github_deep_skill_search.py \
  --query "study abroad personal statement SOP admissions essay" \
  --seed-repo VoltAgent/awesome-agent-skills \
  --seed-file /private/tmp/awesome-agent-skills/README.md \
  --seed-only \
  --include "留学,文书,personal statement,SOP,study abroad,admissions essay" \
  --limit 12 \
  --seed-limit 60 \
  --out /tmp/github-skill-search.json
```

Then read `/tmp/github-skill-search.json`, open the strongest repositories if needed, and summarize:

- which candidates are standard skills versus agent docs or ordinary repos
- star/fork/update signals
- relevant files inspected
- install or conversion path
- risks such as low stars, stale repos, missing `SKILL.md`, or unclear license

If GitHub API limits are hit, retry with `GITHUB_TOKEN` exported by the user or fall back to targeted web search plus direct repository inspection.

## Workflow

1. Define the search frame.
   - Extract topic keywords, synonyms, languages, target platforms, and minimum quality constraints.
   - For domain searches, generate 3-6 queries instead of relying on one phrase.
   - For skill searches, include terms such as `skill`, `SKILL.md`, `Claude Code skill`, `Codex skill`, `agent skill`, `awesome`, and platform-specific names.

2. Discover candidates.
   - Prefer the bundled script for repeatable metadata and file inspection.
   - Search both repository metadata and likely file names: `SKILL.md`, `.claude/skills`, `.agents/skills`, `.github/skills`, `skills/`, `agents/`, `README.md`.
   - Include curated lists such as `awesome-agent-skills` as seed sources, but do not treat a list entry as proof of quality by itself.

3. Inspect deeply.
   - Read README summaries, `SKILL.md` files, manifests, and repository trees.
   - Verify whether a result is installable as a skill, a collection containing skill paths, or only raw reference material.
   - Prefer official/team-maintained skills and repositories with clear documentation.

4. Score and filter.
   - Prioritize relevance first, then proof of quality.
   - Treat star count as a signal, not a guarantee.
   - Downrank repos with missing docs, no skill file, unclear ownership, stale updates, or obvious SEO/spam content.

5. Report with evidence.
   - Provide links to each repository and any important `SKILL.md` or folder path.
   - Separate “directly installable”, “convertible to skill”, and “reference only”.
   - Include exact commands only after verifying the target path exists.

## Scoring Heuristic

Use this default weighting unless the user gives different priorities:

- Relevance to the requested domain: 0-40
- Skill compatibility and installability: 0-20
- Community signal: stars, forks, watchers, inclusion in curated lists: 0-15
- Maintenance: recent update, non-archived repo, active default branch: 0-10
- Documentation quality: clear README, examples, usage, constraints: 0-10
- Safety and trust: license, official owner, avoids spam or copied copyrighted material: 0-5

Call out uncertainty rather than overclaiming. For small or emerging domains, the best candidate may be low-star but precise.

## Script

Primary script:

```bash
python3 ~/.codex/skills/github-deep-skill-search/scripts/github_deep_skill_search.py --help
```

Useful options:

- `--query`: Main GitHub search phrase. Can be repeated.
- `--include`: Comma-separated terms that should boost relevance.
- `--exclude`: Comma-separated terms that should reduce relevance.
- `--core`: Comma-separated core domain terms that should dominate ranking, such as `study abroad,personal statement,SOP`.
- `--support`: Comma-separated auxiliary terms that should help but not dominate, such as `humanizer,research,writing`.
- `--limit`: Number of final candidates.
- `--per-query`: Repository search results to retrieve per query.
- `--out`: Write JSON report to a file.
- `--markdown`: Print a concise Markdown table.
- `--inspect-files`: Number of likely documentation/skill files to fetch per repo.
- `--seed-repo`: A repository whose README should be mined for GitHub links before scoring; repeatable. Use `VoltAgent/awesome-agent-skills` for broad skill discovery.
- `--seed-file`: A local Markdown/text file to mine for GitHub links; useful after cloning an index repo or when GitHub API limits are tight.
- `--seed-limit`: Maximum linked repositories to inspect from seed sources. Keep this modest for broad indexes.
- `--hydrate-seeds`: Fetch GitHub metadata for seed-file candidates. Leave off when rate-limited; the script will still emit repo links.
- `--seed-only`: Skip GitHub search entirely and rank only seed sources. Useful for validating a curated shortlist or working around rate limits.

The script uses `GITHUB_TOKEN` or `GH_TOKEN` when available. Without a token, it uses unauthenticated GitHub API requests and may hit lower rate limits.

For narrow domains, pass explicit `--core` and `--support` terms. The script sorts primary domain matches ahead of supporting tools, so a precise low-star PS/SOP skill can outrank a high-star generic writing helper.

Seed parsing supports GitHub repository links and `officialskills.sh/{owner}/skills/{skill}` listings. When using broad indexes, review the `Role` column first; tail results marked `weak or adjacent match` are usually only useful as context, not recommendations.

## References

- Read `references/search-strategy.md` when designing a complex query set or evaluating ambiguous results.
- Read `references/awesome-agent-skills-notes.md` when applying lessons from `VoltAgent/awesome-agent-skills`.
