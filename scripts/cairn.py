#!/usr/bin/env python3
"""Skill Cairn: local, evidence-backed knowledge vault tooling."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable


SKILL_ROOT = Path(__file__).resolve().parent.parent
CONFIG_RELATIVE_PATH = Path("_config") / "skill-cairn.json"
TEMPLATE_RELATIVE_PATH = Path("_templates") / "knowledge-card.md"
DEFAULT_CONFIG_ASSET = SKILL_ROOT / "assets" / "config.default.json"
DEFAULT_TEMPLATE_ASSET = SKILL_ROOT / "assets" / "templates" / "knowledge-card.md"
REQUIRED_FIELDS = {"title", "date", "topic", "source", "tags", "reusable"}
REQUIRED_SECTIONS = (
    "Context",
    "Reusable knowledge",
    "When not to use",
    "Verification",
)
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TOPIC_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class CairnError(RuntimeError):
    """Raised when the command cannot safely continue."""


@dataclass
class Card:
    path: Path
    meta: dict[str, Any]
    body: str


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def write_new_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
    except FileExistsError as exc:
        raise CairnError(f"refusing to overwrite existing file: {path}") from exc


def parse_scalar(raw: str) -> Any:
    value = raw.strip()
    if value.startswith('"') and value.endswith('"'):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    lower = value.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    if lower in {"null", "none"}:
        return None
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [parse_scalar(item.strip()) for item in inner.split(",")]
    return value


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    normalized = text.replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        raise CairnError("missing opening frontmatter delimiter")
    end = normalized.find("\n---\n", 4)
    if end == -1:
        raise CairnError("missing closing frontmatter delimiter")

    raw_frontmatter = normalized[4:end]
    body = normalized[end + 5 :]
    meta: dict[str, Any] = {}
    current_key: str | None = None

    for line_number, line in enumerate(raw_frontmatter.splitlines(), start=2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith((" ", "\t")):
            stripped = line.strip()
            if stripped.startswith("- "):
                if current_key is None:
                    raise CairnError(
                        f"list item without a parent key at frontmatter line {line_number}"
                    )
                if not isinstance(meta.get(current_key), list):
                    meta[current_key] = []
                meta[current_key].append(parse_scalar(stripped[2:]))
                continue
            raise CairnError(
                f"nested mappings are not supported at frontmatter line {line_number}"
            )

        if ":" not in line:
            raise CairnError(
                f"invalid frontmatter field at line {line_number}: {line!r}"
            )
        key, raw_value = line.split(":", 1)
        current_key = key.strip()
        if not current_key:
            raise CairnError(f"empty frontmatter key at line {line_number}")
        if not raw_value.strip():
            meta[current_key] = []
        else:
            meta[current_key] = parse_scalar(raw_value)

    return meta, body


def load_config(vault: Path) -> dict[str, Any]:
    config_path = vault / CONFIG_RELATIVE_PATH
    if not config_path.is_file():
        raise CairnError(
            f"vault config not found: {config_path}. Run the init command first."
        )
    try:
        config = json.loads(read_text(config_path))
    except json.JSONDecodeError as exc:
        raise CairnError(f"invalid JSON config at {config_path}: {exc}") from exc
    validate_config(config, config_path)
    return config


def validate_config(config: dict[str, Any], config_path: Path) -> None:
    try:
        paths = config["paths"]
        tags = config["tags"]
        promotion = config["promotion"]
        domains = tags["domains"]
        types = tags["types"]
        statuses = tags["statuses"]
        max_per_card = tags["max_per_card"]
        verified_status = tags["verified_status"]
        config["promotion"]["min_cards"]
        config["promotion"]["min_verified_cards"]
        config["promotion"]["min_unique_sources"]
        config["promotion"]["require_reusable"]
        for key in ("inbox", "knowledge", "sop", "skill_candidates", "maps"):
            if not isinstance(paths[key], str) or not paths[key].strip():
                raise TypeError(f"paths.{key} must be a non-empty string")
    except (KeyError, TypeError) as exc:
        raise CairnError(f"invalid vault config at {config_path}: {exc}") from exc

    if not isinstance(max_per_card, int) or max_per_card < 3:
        raise CairnError(
            f"invalid vault config at {config_path}: tags.max_per_card must be >= 3"
        )
    if verified_status not in statuses:
        raise CairnError(
            f"invalid vault config at {config_path}: "
            "tags.verified_status must be one of tags.statuses"
        )
    for name, values in (
        ("domains", domains),
        ("types", types),
        ("statuses", statuses),
    ):
        if not isinstance(values, list) or not values or not all(
            isinstance(value, str) and value for value in values
        ):
            raise CairnError(
                f"invalid vault config at {config_path}: tags.{name} must be non-empty strings"
            )


def initialize_vault(vault: Path) -> dict[str, Any]:
    config_path = vault / CONFIG_RELATIVE_PATH
    if config_path.exists():
        raise CairnError(f"vault is already initialized: {config_path}")
    if not DEFAULT_CONFIG_ASSET.is_file() or not DEFAULT_TEMPLATE_ASSET.is_file():
        raise CairnError("skill assets are incomplete; expected config and template files")

    config = json.loads(read_text(DEFAULT_CONFIG_ASSET))
    validate_config(config, DEFAULT_CONFIG_ASSET)
    created: list[str] = []

    for relative in config["paths"].values():
        directory = vault / relative
        directory.mkdir(parents=True, exist_ok=True)
        created.append(str(directory))

    write_new_file(config_path, json.dumps(config, indent=2, ensure_ascii=False) + "\n")
    template_path = vault / TEMPLATE_RELATIVE_PATH
    write_new_file(template_path, read_text(DEFAULT_TEMPLATE_ASSET))
    created.extend([str(config_path), str(template_path)])

    return {"vault": str(vault.resolve()), "created": created}


def normalize_sources(value: Any) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = [item for item in value if isinstance(item, str)]
    else:
        return []
    return [item.strip() for item in values if item.strip()]


def heading_present(body: str, heading: str) -> bool:
    return bool(
        re.search(
            rf"^##\s+{re.escape(heading)}\s*$",
            body,
            flags=re.MULTILINE | re.IGNORECASE,
        )
    )


def validate_card(
    card: Card,
    config: dict[str, Any],
    vault: Path,
) -> list[str]:
    errors: list[str] = []
    relative = card.path.relative_to(vault).as_posix()
    missing = sorted(REQUIRED_FIELDS - card.meta.keys())
    if missing:
        errors.append(f"{relative}: missing required fields: {', '.join(missing)}")

    for field in ("title", "topic"):
        if not isinstance(card.meta.get(field), str) or not card.meta[field].strip():
            errors.append(f"{relative}: {field} must be a non-empty string")

    topic = card.meta.get("topic")
    if isinstance(topic, str) and topic.strip() and not TOPIC_PATTERN.fullmatch(
        topic.strip()
    ):
        errors.append(
            f"{relative}: topic must be a lowercase ASCII slug using hyphens"
        )

    card_date = card.meta.get("date")
    if not isinstance(card_date, str) or not DATE_PATTERN.fullmatch(card_date):
        errors.append(f"{relative}: date must use YYYY-MM-DD")
    else:
        try:
            date.fromisoformat(card_date)
        except ValueError:
            errors.append(f"{relative}: date is not a valid calendar date")

    if not normalize_sources(card.meta.get("source")):
        errors.append(f"{relative}: source must contain at least one evidence reference")

    if not isinstance(card.meta.get("reusable"), bool):
        errors.append(f"{relative}: reusable must be true or false")

    raw_tags = card.meta.get("tags")
    if not isinstance(raw_tags, list) or not all(
        isinstance(tag, str) and tag.strip() for tag in raw_tags
    ):
        errors.append(f"{relative}: tags must be a non-empty YAML list")
        return errors

    tags = [tag.strip() for tag in raw_tags]
    max_tags = config["tags"]["max_per_card"]
    if len(tags) > max_tags:
        errors.append(f"{relative}: {len(tags)} tags exceeds limit {max_tags}")
    if len(tags) != len(set(tags)):
        errors.append(f"{relative}: duplicate tags are not allowed")

    domains = set(config["tags"]["domains"])
    types = set(config["tags"]["types"])
    statuses = set(config["tags"]["statuses"])
    registered = domains | types | statuses

    unknown = sorted(set(tags) - registered)
    if unknown:
        errors.append(f"{relative}: unregistered tags: {', '.join(unknown)}")
    if not set(tags) & domains:
        errors.append(f"{relative}: at least one domain tag is required")
    type_count = len(set(tags) & types)
    status_count = len(set(tags) & statuses)
    if type_count != 1:
        errors.append(f"{relative}: exactly one type tag is required")
    if status_count != 1:
        errors.append(f"{relative}: exactly one status tag is required")

    if " " in card.path.stem:
        errors.append(f"{relative}: filename must not contain spaces")
    for section in REQUIRED_SECTIONS:
        if not heading_present(card.body, section):
            errors.append(f"{relative}: missing body section '## {section}'")

    return errors


def validate_vault(vault: Path) -> dict[str, Any]:
    config = load_config(vault)
    knowledge_dir = vault / config["paths"]["knowledge"]
    if not knowledge_dir.is_dir():
        raise CairnError(f"knowledge directory not found: {knowledge_dir}")

    errors: list[str] = []
    warnings: list[str] = []
    cards: list[Card] = []
    seen_titles: dict[str, str] = {}
    seen_stems: dict[str, str] = {}

    for path in sorted(knowledge_dir.rglob("*.md")):
        relative = path.relative_to(vault).as_posix()
        stem_key = path.stem.casefold()
        if stem_key in seen_stems:
            errors.append(
                f"{relative}: duplicate filename stem also used by {seen_stems[stem_key]}"
            )
        else:
            seen_stems[stem_key] = relative

        try:
            meta, body = parse_frontmatter(read_text(path))
        except CairnError as exc:
            errors.append(f"{relative}: {exc}")
            continue

        card = Card(path=path, meta=meta, body=body)
        card_errors = validate_card(card, config, vault)
        errors.extend(card_errors)
        if not card_errors:
            cards.append(card)

        title = meta.get("title")
        if isinstance(title, str) and title.strip():
            title_key = title.strip().casefold()
            if title_key in seen_titles:
                warnings.append(
                    f"{relative}: duplicate title also used by {seen_titles[title_key]}"
                )
            else:
                seen_titles[title_key] = relative

    return {
        "ok": not errors,
        "vault": str(vault.resolve()),
        "card_count": len(cards),
        "errors": errors,
        "warnings": warnings,
        "cards": cards,
    }


def topic_groups(cards: Iterable[Card]) -> dict[str, list[Card]]:
    groups: dict[str, list[Card]] = defaultdict(list)
    for card in cards:
        topic = card.meta.get("topic")
        if isinstance(topic, str) and topic.strip():
            groups[topic.strip()].append(card)
    return dict(sorted(groups.items()))


def card_sources(card: Card) -> list[str]:
    return normalize_sources(card.meta.get("source"))


def promotion_candidates(
    cards: Iterable[Card],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    gate = config["promotion"]
    verified_status = config["tags"]["verified_status"]
    results: list[dict[str, Any]] = []

    for topic, group in topic_groups(cards).items():
        sources = {
            source
            for card in group
            for source in card_sources(card)
        }
        verified = sum(
            verified_status in card.meta.get("tags", []) for card in group
        )
        reusable = sum(card.meta.get("reusable") is True for card in group)
        reasons: list[str] = []
        if len(group) < gate["min_cards"]:
            reasons.append(
                f"needs {gate['min_cards']} cards; found {len(group)}"
            )
        if verified < gate["min_verified_cards"]:
            reasons.append(
                f"needs {gate['min_verified_cards']} verified cards; found {verified}"
            )
        if len(sources) < gate["min_unique_sources"]:
            reasons.append(
                f"needs {gate['min_unique_sources']} unique sources; found {len(sources)}"
            )
        if gate["require_reusable"] and reusable < 1:
            reasons.append("needs at least one reusable card")

        results.append(
            {
                "topic": topic,
                "eligible": not reasons,
                "card_count": len(group),
                "verified_cards": verified,
                "reusable_cards": reusable,
                "unique_sources": len(sources),
                "sources": sorted(sources),
                "cards": [str(card.path) for card in group],
                "blocking_reasons": reasons,
            }
        )

    return results


def render_candidate_report(candidates: list[dict[str, Any]]) -> str:
    generated = date.today().isoformat()
    lines = [
        "# Promotion candidates",
        "",
        f"Generated: {generated}",
        "",
        "| Topic | Cards | Verified | Sources | Eligible |",
        "|---|---:|---:|---:|---|",
    ]
    if not candidates:
        lines.append("| _No topics found_ | 0 | 0 | 0 | no |")
    else:
        for candidate in candidates:
            lines.append(
                "| {topic} | {card_count} | {verified_cards} | {unique_sources} | {eligible} |".format(
                    topic=candidate["topic"],
                    card_count=candidate["card_count"],
                    verified_cards=candidate["verified_cards"],
                    unique_sources=candidate["unique_sources"],
                    eligible="yes" if candidate["eligible"] else "no",
                )
            )

    blocked = [item for item in candidates if not item["eligible"]]
    if blocked:
        lines.extend(["", "## Blocking reasons", ""])
        for item in blocked:
            lines.append(
                f"- `{item['topic']}`: {'; '.join(item['blocking_reasons'])}"
            )
    return "\n".join(lines) + "\n"


def extract_section(body: str, heading: str) -> str:
    pattern = re.compile(
        rf"^##\s+{re.escape(heading)}\s*$\n(.*?)(?=^##\s+|\Z)",
        flags=re.MULTILINE | re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(body)
    return match.group(1).strip() if match else ""


def unique_blocks(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = re.sub(r"\s+", " ", value).strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(value.strip())
    return result


def skill_name_from_topic(topic: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")
    if normalized and len(normalized) <= 64:
        return normalized
    digest = hashlib.sha1(topic.encode("utf-8")).hexdigest()[:10]
    return f"distilled-experience-{digest}"


def render_skill_draft(
    topic: str,
    group: list[Card],
    candidate: dict[str, Any],
) -> str:
    knowledge = unique_blocks(
        extract_section(card.body, "Reusable knowledge") for card in group
    )
    boundaries = unique_blocks(
        extract_section(card.body, "When not to use") for card in group
    )
    verification = unique_blocks(
        extract_section(card.body, "Verification") for card in group
    )
    sources = unique_blocks(
        source for card in group for source in card_sources(card)
    )
    skill_name = skill_name_from_topic(topic)

    lines = [
        "---",
        f'name: "{skill_name}"',
        (
            f'description: "Use when working on {topic} and applying previously '
            'verified project knowledge. This is a generated draft; review scope, '
            'actions, and boundaries before publishing."'
        ),
        "metadata:",
        '  generated_by: "skill-cairn"',
        '  source_topic: "%s"' % topic,
        "---",
        "",
        f"# {topic.replace('-', ' ').title()}",
        "",
        "> Generated from evidence-backed knowledge cards. Review every section before use.",
        "",
        "## When to use",
        "",
        f"Use this skill when the task matches `{topic}` and the evidence below applies to the current environment.",
        "",
        "## Evidence-backed knowledge",
        "",
    ]
    for item in knowledge:
        lines.extend([item, ""])

    lines.extend(["## Boundaries", ""])
    for item in boundaries:
        lines.extend([item, ""])

    lines.extend(["## Verification", ""])
    for item in verification:
        lines.extend([item, ""])

    lines.extend(["## Evidence sources", ""])
    lines.extend(f"- {source}" for source in sources)
    lines.extend(
        [
            "",
            "## Review checklist",
            "",
            "- Confirm the description triggers only for the intended task.",
            "- Test the workflow against a representative prompt.",
            "- Remove stale evidence and unverified claims.",
            "- Add explicit failure handling and authorization boundaries.",
            "- Do not publish this draft without user approval.",
            "",
            "## Promotion evidence",
            "",
            f"- Cards: {candidate['card_count']}",
            f"- Verified cards: {candidate['verified_cards']}",
            f"- Unique sources: {candidate['unique_sources']}",
        ]
    )
    return "\n".join(lines) + "\n"


def export_skill_draft(
    vault: Path,
    topic: str,
    output: Path | None,
) -> dict[str, Any]:
    validation = validate_vault(vault)
    if validation["errors"]:
        raise CairnError(
            "vault validation failed; fix card errors before exporting a Skill draft"
        )
    config = load_config(vault)
    cards = validation["cards"]
    candidates = promotion_candidates(cards, config)
    candidate = next(
        (item for item in candidates if item["topic"] == topic),
        None,
    )
    if candidate is None:
        raise CairnError(f"topic not found: {topic}")
    if not candidate["eligible"]:
        raise CairnError(
            f"topic {topic!r} does not pass the promotion gate: "
            + "; ".join(candidate["blocking_reasons"])
        )

    group = [card for card in cards if card.meta.get("topic") == topic]
    default_path = (
        vault
        / config["paths"]["skill_candidates"]
        / f"{skill_name_from_topic(topic)}.SKILL.md"
    )
    output_path = (output or default_path).resolve()
    content = render_skill_draft(topic, group, candidate)
    write_new_file(output_path, content)
    return {
        "topic": topic,
        "output": str(output_path),
        "card_count": candidate["card_count"],
        "verified_cards": candidate["verified_cards"],
        "unique_sources": candidate["unique_sources"],
    }


def command_init(args: argparse.Namespace) -> int:
    result = initialize_vault(Path(args.vault).expanduser())
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def command_validate(args: argparse.Namespace) -> int:
    result = validate_vault(Path(args.vault).expanduser())
    if args.json:
        payload = {key: value for key, value in result.items() if key != "cards"}
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(
            f"Validated {result['card_count']} card(s): "
            f"{'OK' if result['ok'] else 'FAILED'}"
        )
        for warning in result["warnings"]:
            print(f"warning: {warning}", file=sys.stderr)
        for error in result["errors"]:
            print(f"error: {error}", file=sys.stderr)
    return 0 if result["ok"] else 1


def command_candidates(args: argparse.Namespace) -> int:
    vault = Path(args.vault).expanduser()
    validation = validate_vault(vault)
    if validation["errors"]:
        print("Vault validation failed; candidate scan aborted.", file=sys.stderr)
        for error in validation["errors"]:
            print(f"error: {error}", file=sys.stderr)
        return 1

    config = load_config(vault)
    candidates = promotion_candidates(validation["cards"], config)
    if args.write:
        report_path = (
            vault
            / config["paths"]["skill_candidates"]
            / "promotion-report.md"
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            render_candidate_report(candidates),
            encoding="utf-8",
            newline="\n",
        )
        print(f"Wrote candidate report: {report_path.resolve()}")

    if args.json:
        print(json.dumps(candidates, indent=2, ensure_ascii=False))
    else:
        eligible = [item for item in candidates if item["eligible"]]
        print(
            f"Found {len(candidates)} topic(s); "
            f"{len(eligible)} passed the promotion gate."
        )
        for item in candidates:
            status = "ELIGIBLE" if item["eligible"] else "BLOCKED"
            print(
                f"[{status}] {item['topic']} "
                f"(cards={item['card_count']}, verified={item['verified_cards']}, "
                f"sources={item['unique_sources']})"
            )
            for reason in item["blocking_reasons"]:
                print(f"  - {reason}")
    return 0


def command_export(args: argparse.Namespace) -> int:
    result = export_skill_draft(
        Path(args.vault).expanduser(),
        args.topic,
        Path(args.output).expanduser() if args.output else None,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cairn",
        description="Create and maintain an evidence-backed knowledge vault.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="initialize a new vault")
    init_parser.add_argument("--vault", required=True, help="target vault path")
    init_parser.set_defaults(handler=command_init)

    validate_parser = subparsers.add_parser(
        "validate", help="validate cards and tags"
    )
    validate_parser.add_argument("--vault", required=True, help="vault path")
    validate_parser.add_argument("--json", action="store_true", help="print JSON")
    validate_parser.set_defaults(handler=command_validate)

    candidates_parser = subparsers.add_parser(
        "candidates", help="review topics against the promotion gate"
    )
    candidates_parser.add_argument("--vault", required=True, help="vault path")
    candidates_parser.add_argument(
        "--write",
        action="store_true",
        help="write the generated candidate report into the vault",
    )
    candidates_parser.add_argument("--json", action="store_true", help="print JSON")
    candidates_parser.set_defaults(handler=command_candidates)

    export_parser = subparsers.add_parser(
        "export-skill", help="export a Skill draft from qualifying cards"
    )
    export_parser.add_argument("--vault", required=True, help="vault path")
    export_parser.add_argument("--topic", required=True, help="topic slug")
    export_parser.add_argument(
        "--output",
        help="draft path; defaults to the configured skill candidate directory",
    )
    export_parser.set_defaults(handler=command_export)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except CairnError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

