# Promotion gate

The promotion gate reduces Skill sprawl by requiring evidence before an experience becomes a Skill candidate.

## Default gate

- At least 3 cards share the same `topic`.
- At least 2 of those cards have the configured verified status.
- At least 2 unique sources appear across the cards.
- At least 1 card has `reusable: true`.

All checks must pass unless the user explicitly changes the configuration.

## Why these checks

Repetition alone is not quality. A repeated mistake can create repeated bad advice. Verification and independent sources reduce that risk.

The gate answers four questions:

1. Is this pattern recurring?
2. Is it supported by evidence?
3. Can it be applied outside the original incident?
4. Is there enough context to define boundaries?

## What the gate does not prove

The gate cannot prove that a Skill will improve Agent output. A generated draft must still be tested with representative prompts and reviewed by the user.

Any later generation, evaluation, or optimization is outside this project's runtime boundary. Keep new evidence and lessons in the same knowledge vault so future promotion decisions are better informed.

## Manual override

Do not silently bypass the gate. If the user explicitly overrides it, record:

- Who requested the override.
- Why the evidence threshold is inappropriate.
- Which checks are missing.
- What test will compensate for the missing evidence.

