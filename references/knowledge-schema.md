# Knowledge card schema

Knowledge cards are Markdown files with YAML-like frontmatter. The MVP parser intentionally supports only a small, predictable subset: top-level scalar fields and top-level lists. Do not use nested mappings in this version.

## Required frontmatter

| Field | Type | Rules |
|---|---|---|
| `title` | string | Human-readable, specific, and searchable |
| `date` | string | `YYYY-MM-DD` |
| `topic` | string | Stable lowercase slug used to group related cards |
| `source` | string or list | Concrete evidence references |
| `tags` | list | Registered domain, type, and status tags |
| `reusable` | boolean | `true` only when the knowledge can be applied elsewhere |

Optional fields:

- `project`: project or repository name.
- `environment`: operating system, service, or version context.
- `owner`: person or team responsible for keeping the card current.

## Required body sections

- `## Context`: the situation and observable problem.
- `## Reusable knowledge`: the durable conclusion or procedure.
- `## When not to use`: applicability boundaries.
- `## Verification`: commands, tests, observations, or links that support the conclusion.

## Extraction rules

Create one card per reusable idea. Prefer concrete observations over narrative. Keep error messages, versions, file paths, and commands that make the knowledge verifiable.

Do not:

- Combine unrelated decisions in one card.
- Present an inference as an observed fact.
- Omit a failed attempt when it prevents a repeat mistake.
- Copy secrets, access tokens, private keys, or personal data.
- Reuse an unregistered tag.

## Evidence quality

Strong evidence:

- Reproduced test or command output.
- Versioned file path and commit.
- Runbook result with a known success criterion.
- Two independent observations of the same behavior.

Weak evidence:

- A model's unsupported recollection.
- A single anecdote without verification.
- A copied claim without a source.
- “It worked” without context or a repeatable check.

