# Automation and review policy

Skill Cairn separates deterministic automation from decisions that materially change the knowledge base or publish artifacts.

## Processing pipeline

1. Split the source into atomic knowledge units.
2. Run `suggest` with a semantic topic hint.
3. Apply high-confidence registered tags and status directly.
4. Queue uncertain results for batch review.
5. Check similar cards before writing a new file.
6. Validate the completed card.

The scripts do not rewrite cards, create new taxonomy tags, or publish artifacts.

## Confidence levels

Thresholds live in `tagging` in `_config/skill-cairn.json`.

| Result | Default | Action |
|---|---:|---|
| `auto_apply` | lowest required confidence ≥ 0.85 | Use the suggested registered tags and status |
| `review` | lowest required confidence ≥ 0.55 | Queue the analysis for batch review |
| `suggest_only` | below 0.55 | Keep the suggestion; do not create a finalized card |

One high score does not override a missing category. Domain, type, status, and topic must all be present for automatic application.

## Tag signals

Suggestions can use:

- exact registered tag names;
- configured aliases and Chinese synonyms;
- tokens and CJK n-grams in the title and body;
- tags on lexically similar historical cards.

Every suggestion includes evidence so it can be reviewed without rerunning the analysis.

## Status rules

Suggested status is a classification hint, not proof:

- `verified` requires explicit verification language, test evidence, or user confirmation.
- absence of evidence defaults toward `unverified` when that tag is registered.
- a status conflict must be resolved by retaining the safer status and noting the missing evidence.

The Agent must not treat a high confidence score as a substitute for actual evidence.

## Related cards and duplicates

`suggest` returns the nearest cards by cosine similarity. `dedupe` scans the whole vault for pairs above the configured threshold.

Similarity is supporting evidence, not a merge instruction:

- inspect the actual conclusions before merging;
- keep conflicting cards separate and record the conflict;
- never overwrite or delete a card automatically.

## Review queue

Queued records are appended to `00-Inbox/review-queue.jsonl`. Duplicate queue entries for the same input content are suppressed by a SHA-1 content key.

Use:

```bash
python scripts/cairn.py review --vault <vault-path>
python scripts/cairn.py review --vault <vault-path> --write
```

The report is a batch-working surface. Review several items at once instead of asking the user to approve every card in separate turns.

## Still requires immediate confirmation

- Creating a new domain or tag in the configuration.
- Overwriting, deleting, or bulk-rewriting cards.
- Marking a card verified against contradictory or absent evidence.
- Installing a generated Skill.
- Creating or pushing a remote repository.

