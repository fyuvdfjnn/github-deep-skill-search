# GitHub Deep Skill Search

Find, inspect, and rank GitHub agent skills by evidence, not just stars.

`github-deep-skill-search` is a Codex skill for discovering high-quality agent skills from GitHub repositories, awesome lists, and `officialskills.sh` listings. It separates primary matches from supporting tools, curated indexes, and weak adjacent results so you can decide what is actually worth installing or adapting.

## Why

GitHub search is noisy. Awesome lists are useful, but shallow. Star counts help, but they do not tell you whether a repository has a real `SKILL.md`, whether it is installable, or whether it only mentions your topic in passing.

This skill helps Codex:

- search and rank GitHub skill repositories
- parse local seed files, awesome lists, and `officialskills.sh` links
- inspect README and `SKILL.md` evidence when API access is available
- classify results as primary matches, supporting tools, discovery indexes, or weak matches
- score candidates by relevance, installability, community signal, maintenance, docs, and trust
- keep working in rate-limited environments through offline seed-file mode

## Repository Layout

```text
skills/
  github-deep-skill-search/
    SKILL.md
    agents/openai.yaml
    references/
    scripts/github_deep_skill_search.py
```

## Install

Copy the skill folder into your Codex skills directory:

```bash
cp -R skills/github-deep-skill-search ~/.codex/skills/
```

Then restart Codex so the skill is discovered.

## Quick Demo

Search a local copy of an awesome list:

```bash
python3 skills/github-deep-skill-search/scripts/github_deep_skill_search.py \
  --query "PDF document extraction editing forms skill" \
  --seed-file /path/to/awesome-agent-skills/README.md \
  --seed-only \
  --include "pdf,document,form,extract,edit,skill,docx,pptx,xlsx" \
  --core "pdf,forms,extract,edit,document" \
  --support "docx,pptx,xlsx,office" \
  --limit 10 \
  --markdown
```

Example output:

```text
| Score | R/I/C | Stars | Repo | Role | Type |
|---:|---|---:|---|---|---|
| 56 | 40/12/0 | 0 | officialskills.sh/anthropics/pdf | primary match | official skill listing |
| 53 | 37/12/0 | 0 | officialskills.sh/anthropics/docx | primary match | official skill listing |
| 27 | 11/12/0 | 0 | officialskills.sh/anthropics/pptx | supporting tool | official skill listing |
```

`R/I/C` means relevance / installability / community signal.

## More Examples

### Study Abroad / SOP Skills

```bash
python3 skills/github-deep-skill-search/scripts/github_deep_skill_search.py \
  --query "study abroad personal statement SOP admissions essay" \
  --include "study abroad,personal statement,SOP,statement of purpose,admissions essay,留学,文书,advisor,humanizer,research" \
  --core "study abroad,personal statement,SOP,statement of purpose,admissions essay,留学,文书,advisor" \
  --support "humanizer,research,writing" \
  --markdown
```

### Playwright / Browser Testing Skills

```bash
python3 skills/github-deep-skill-search/scripts/github_deep_skill_search.py \
  --query "playwright testing skill browser automation" \
  --seed-file /path/to/awesome-agent-skills/README.md \
  --seed-only \
  --include "playwright,testing,browser,automation,e2e,skill" \
  --core "playwright,testing,browser automation,e2e" \
  --support "browser,automation" \
  --markdown
```

## Output Roles

- `primary match`: directly relevant to the requested domain
- `supporting tool`: useful helper, but not the main answer
- `discovery index`: curated list or index for further search
- `weak or adjacent match`: tangential result; review only if needed

## Rate Limits

The script uses `GITHUB_TOKEN` or `GH_TOKEN` when available. Without a token, GitHub API access may be rate-limited. Use `--seed-file --seed-only` to rank local indexes without relying on GitHub API calls.

## License

MIT
