#!/usr/bin/env python3
"""Skill Cairn: local, evidence-backed knowledge vault tooling."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from itertools import combinations
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
ASCII_TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9_+.#-]*")
CJK_RUN_PATTERN = re.compile(r"[\u3400-\u9fff]+")
DEFAULT_TAGGING = {
    "auto_apply_threshold": 0.85,
    "queue_threshold": 0.55,
    "dedupe_threshold": 0.62,
}
DIRECTORY_PATH_KEYS = ("inbox", "knowledge", "sop", "skill_candidates", "maps")


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

    tagging = config.get("tagging", {})
    if not isinstance(tagging, dict):
        raise CairnError(
            f"invalid vault config at {config_path}: tagging must be an object"
        )
    aliases = tagging.get("aliases", {})
    if not isinstance(aliases, dict):
        raise CairnError(
            f"invalid vault config at {config_path}: tagging.aliases must be an object"
        )
    registered = set(domains) | set(types) | set(statuses)
    for tag, terms in aliases.items():
        if tag not in registered:
            raise CairnError(
                f"invalid vault config at {config_path}: "
                f"tagging.aliases contains unregistered tag {tag!r}"
            )
        if not isinstance(terms, list) or not all(
            isinstance(term, str) and term.strip() for term in terms
        ):
            raise CairnError(
                f"invalid vault config at {config_path}: "
                f"tagging.aliases.{tag} must be a list of non-empty strings"
            )

    auto_threshold = tagging.get(
        "auto_apply_threshold", DEFAULT_TAGGING["auto_apply_threshold"]
    )
    queue_threshold = tagging.get(
        "queue_threshold", DEFAULT_TAGGING["queue_threshold"]
    )
    dedupe_threshold = tagging.get(
        "dedupe_threshold", DEFAULT_TAGGING["dedupe_threshold"]
    )
    for key, value in (
        ("auto_apply_threshold", auto_threshold),
        ("queue_threshold", queue_threshold),
        ("dedupe_threshold", dedupe_threshold),
    ):
        if not isinstance(value, (int, float)) or not 0 <= value <= 1:
            raise CairnError(
                f"invalid vault config at {config_path}: "
                f"tagging.{key} must be between 0 and 1"
            )
    if queue_threshold > auto_threshold:
        raise CairnError(
            f"invalid vault config at {config_path}: "
            "tagging.queue_threshold must not exceed auto_apply_threshold"
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

    for key in DIRECTORY_PATH_KEYS:
        relative = config["paths"][key]
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


def tokenize_text(text: str) -> Counter[str]:
    normalized = text.casefold()
    tokens = [
        token
        for token in ASCII_TOKEN_PATTERN.findall(normalized)
        if len(token) >= 2
    ]
    for run in CJK_RUN_PATTERN.findall(normalized):
        if len(run) <= 12:
            tokens.append(run)
        for size in (2, 3):
            tokens.extend(
                run[index : index + size]
                for index in range(max(0, len(run) - size + 1))
            )
    return Counter(tokens)


def cosine_similarity(left: Counter[str], right: Counter[str]) -> float:
    if not left or not right:
        return 0.0
    common = set(left) & set(right)
    numerator = sum(left[token] * right[token] for token in common)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


def term_present(text: str, term: str) -> bool:
    normalized_text = text.casefold()
    normalized_term = term.casefold().strip()
    if not normalized_term:
        return False
    if normalized_term.isascii():
        pieces = [re.escape(piece) for piece in normalized_term.split()]
        pattern = r"(?<![a-z0-9_])" + r"\s+".join(pieces) + r"(?![a-z0-9_])"
        return bool(re.search(pattern, normalized_text))
    return normalized_term in normalized_text


def card_search_text(card: Card) -> str:
    title = str(card.meta.get("title", ""))
    topic = str(card.meta.get("topic", ""))
    return "\n".join((title, topic, card.body))


def nearest_cards(
    text: str,
    cards: Iterable[Card],
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    input_tokens = tokenize_text(text)
    matches: list[dict[str, Any]] = []
    for card in cards:
        similarity = cosine_similarity(input_tokens, tokenize_text(card_search_text(card)))
        if similarity <= 0:
            continue
        matches.append(
            {
                "path": str(card.path),
                "title": card.meta.get("title", ""),
                "topic": card.meta.get("topic", ""),
                "similarity": round(similarity, 3),
            }
        )
    return sorted(
        matches,
        key=lambda item: (-item["similarity"], item["path"]),
    )[:limit]


def score_tags(
    text: str,
    tags: Iterable[str],
    aliases: dict[str, list[str]],
    cards: Iterable[Card],
) -> list[dict[str, Any]]:
    input_tokens = tokenize_text(text)
    card_vectors = [
        (card, tokenize_text(card_search_text(card))) for card in cards
    ]
    results: list[dict[str, Any]] = []
    for tag in sorted(tags):
        score = 0.0
        evidence: list[str] = []
        if term_present(text, tag):
            score += 2.0
            evidence.append(f"tag text: {tag}")
        for alias in aliases.get(tag, []):
            if term_present(text, alias):
                score += 1.0
                evidence.append(f"alias: {alias}")

        historical: list[str] = []
        for card, vector in card_vectors:
            if tag not in card.meta.get("tags", []):
                continue
            similarity = cosine_similarity(input_tokens, vector)
            if similarity >= 0.12:
                score += similarity * 3
                historical.append(f"{card.path.name} ({similarity:.2f})")
        if historical:
            evidence.append("similar tagged cards: " + ", ".join(historical[:3]))

        confidence = round(1 - math.exp(-score / 1.6), 3) if score else 0.0
        if confidence:
            results.append(
                {
                    "tag": tag,
                    "score": round(score, 3),
                    "confidence": min(confidence, 0.99),
                    "evidence": evidence,
                }
            )
    return sorted(results, key=lambda item: (-item["confidence"], item["tag"]))


def topic_from_input(text: str, topic_hint: str | None) -> str | None:
    if topic_hint:
        normalized = skill_name_from_topic(topic_hint)
        return normalized if TOPIC_PATTERN.fullmatch(normalized) else None

    if text.lstrip().startswith("---"):
        try:
            meta, _ = parse_frontmatter(text)
        except CairnError:
            meta = {}
        topic = meta.get("topic")
        if isinstance(topic, str) and TOPIC_PATTERN.fullmatch(topic.strip()):
            return topic.strip()

    heading = re.search(r"^#\s+(.+)$", text, flags=re.MULTILINE)
    source_text = heading.group(1) if heading else text
    ascii_words = [
        token
        for token in ASCII_TOKEN_PATTERN.findall(source_text.casefold())
        if len(token) >= 2
    ]
    if len(ascii_words) >= 2:
        candidate = "-".join(ascii_words[:5])
        if len(candidate) <= 64 and TOPIC_PATTERN.fullmatch(candidate):
            return candidate
    return None


def analyze_text(
    vault: Path,
    text: str,
    topic_hint: str | None = None,
) -> dict[str, Any]:
    config = load_config(vault)
    validation = validate_vault(vault)
    cards = validation["cards"]
    tagging = config.get("tagging", {})
    aliases = tagging.get("aliases", {})
    auto_threshold = float(
        tagging.get("auto_apply_threshold", DEFAULT_TAGGING["auto_apply_threshold"])
    )
    queue_threshold = float(
        tagging.get("queue_threshold", DEFAULT_TAGGING["queue_threshold"])
    )
    dedupe_threshold = float(
        tagging.get("dedupe_threshold", DEFAULT_TAGGING["dedupe_threshold"])
    )

    domain_scores = score_tags(
        text, config["tags"]["domains"], aliases, cards
    )
    type_scores = score_tags(text, config["tags"]["types"], aliases, cards)
    status_scores = score_tags(
        text, config["tags"]["statuses"], aliases, cards
    )
    nearest = nearest_cards(text, cards)
    topic = topic_from_input(text, topic_hint)

    best = {
        "domain": domain_scores[0] if domain_scores else None,
        "type": type_scores[0] if type_scores else None,
        "status": status_scores[0] if status_scores else None,
    }
    missing_required = [name for name, value in best.items() if value is None]
    lowest_confidence = min(
        (item["confidence"] for item in best.values() if item), default=0.0
    )
    can_auto_apply = not missing_required and topic is not None and lowest_confidence >= auto_threshold
    review_required = not can_auto_apply
    action = "auto_apply" if can_auto_apply else "review"
    if not can_auto_apply and lowest_confidence < queue_threshold:
        action = "suggest_only"

    return {
        "input_characters": len(text),
        "topic": topic,
        "suggestions": {
            "domains": domain_scores[:5],
            "types": type_scores[:5],
            "statuses": status_scores[:5],
        },
        "best": best,
        "nearest_cards": nearest,
        "thresholds": {
            "auto_apply": auto_threshold,
            "queue": queue_threshold,
            "dedupe": dedupe_threshold,
        },
        "can_auto_apply": can_auto_apply,
        "review_required": review_required,
        "recommended_action": action,
        "missing_required": missing_required,
        "card_validation_errors": validation["errors"],
    }


def find_duplicate_pairs(
    cards: Iterable[Card],
    *,
    threshold: float,
) -> list[dict[str, Any]]:
    vectors = {
        card.path: tokenize_text(card_search_text(card))
        for card in cards
    }
    results: list[dict[str, Any]] = []
    for left, right in combinations(sorted(vectors), 2):
        similarity = cosine_similarity(vectors[left], vectors[right])
        if similarity >= threshold:
            results.append(
                {
                    "left": str(left),
                    "right": str(right),
                    "similarity": round(similarity, 3),
                }
            )
    return sorted(
        results,
        key=lambda item: (-item["similarity"], item["left"], item["right"]),
    )


def read_review_queue(vault: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    relative = config.get("paths", {}).get(
        "review_queue", "00-Inbox/review-queue.jsonl"
    )
    path = vault / relative
    if not path.is_file():
        return []
    entries: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


def append_review_queue(
    vault: Path,
    config: dict[str, Any],
    input_path: str,
    text: str,
    analysis: dict[str, Any],
) -> tuple[Path, bool]:
    relative = config.get("paths", {}).get(
        "review_queue", "00-Inbox/review-queue.jsonl"
    )
    path = vault / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(
        (input_path + "\0" + text).encode("utf-8")
    ).hexdigest()
    existing = read_review_queue(vault, config)
    if any(entry.get("input_sha1") == digest for entry in existing):
        return path, False
    entry = {
        "created": date.today().isoformat(),
        "input": input_path,
        "input_sha1": digest,
        "analysis": analysis,
    }
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return path, True


def render_review_report(entries: Iterable[dict[str, Any]]) -> str:
    rows = list(entries)
    lines = [
        "# Review queue",
        "",
        f"Pending items: {len(rows)}",
        "",
    ]
    if not rows:
        lines.append("No pending automatic classifications.")
        return "\n".join(lines) + "\n"
    for index, entry in enumerate(rows, start=1):
        analysis = entry.get("analysis", {})
        best = analysis.get("best", {})
        lines.extend(
            [
                f"## {index}. {entry.get('input', 'unknown input')}",
                "",
                f"- Topic: `{analysis.get('topic') or 'unresolved'}`",
                f"- Suggested domain: `{(best.get('domain') or {}).get('tag', 'none')}`",
                f"- Suggested type: `{(best.get('type') or {}).get('tag', 'none')}`",
                f"- Suggested status: `{(best.get('status') or {}).get('tag', 'none')}`",
                f"- Recommended action: `{analysis.get('recommended_action', 'review')}`",
            ]
        )
        nearest = analysis.get("nearest_cards", [])
        if nearest:
            lines.append(
                "- Similar cards: "
                + ", ".join(
                    f"{item['path']} ({item['similarity']:.2f})"
                    for item in nearest[:3]
                )
            )
        lines.append("")
    return "\n".join(lines) + "\n"


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


def command_suggest(args: argparse.Namespace) -> int:
    vault = Path(args.vault).expanduser()
    if args.input == "-":
        text = sys.stdin.read()
        input_path = "stdin"
    else:
        source = Path(args.input).expanduser()
        if not source.is_file():
            raise CairnError(f"input file not found: {source}")
        text = read_text(source)
        input_path = str(source.resolve())

    analysis = analyze_text(vault, text, args.topic_hint)
    queued_path: Path | None = None
    queued = False
    if args.queue and analysis["review_required"]:
        config = load_config(vault)
        queued_path, queued = append_review_queue(
            vault, config, input_path, text, analysis
        )

    if args.json:
        payload = dict(analysis)
        payload["queued"] = queued
        payload["queue_path"] = str(queued_path) if queued_path else None
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    print(f"Action: {analysis['recommended_action']}")
    print(f"Topic: {analysis['topic'] or 'UNRESOLVED'}")
    for category in ("domain", "type", "status"):
        suggestion = analysis["best"].get(category)
        if suggestion:
            print(
                f"{category}: {suggestion['tag']} "
                f"({suggestion['confidence']:.3f})"
            )
        else:
            print(f"{category}: NONE")
    if analysis["nearest_cards"]:
        print("Nearest cards:")
        for item in analysis["nearest_cards"][:5]:
            print(f"  - {item['path']} ({item['similarity']:.3f})")
    if queued_path:
        print(f"Queued: {queued} ({queued_path})")
    return 0


def command_dedupe(args: argparse.Namespace) -> int:
    vault = Path(args.vault).expanduser()
    validation = validate_vault(vault)
    if validation["errors"]:
        print("Vault validation failed; duplicate scan aborted.", file=sys.stderr)
        for error in validation["errors"]:
            print(f"error: {error}", file=sys.stderr)
        return 1
    config = load_config(vault)
    threshold = args.threshold
    if threshold is None:
        threshold = float(
            config.get("tagging", {}).get(
                "dedupe_threshold", DEFAULT_TAGGING["dedupe_threshold"]
            )
        )
    if not 0 <= threshold <= 1:
        raise CairnError("dedupe threshold must be between 0 and 1")
    pairs = find_duplicate_pairs(validation["cards"], threshold=threshold)
    if args.json:
        print(
            json.dumps(
                {"threshold": threshold, "pairs": pairs},
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(f"Similar card pairs: {len(pairs)} (threshold={threshold:.2f})")
        for pair in pairs:
            print(
                f"[{pair['similarity']:.3f}] "
                f"{pair['left']} <-> {pair['right']}"
            )
    return 0


def command_review(args: argparse.Namespace) -> int:
    vault = Path(args.vault).expanduser()
    config = load_config(vault)
    entries = read_review_queue(vault, config)
    report = render_review_report(entries)
    if args.write:
        relative = config.get("paths", {}).get(
            "review_report", "00-Inbox/review-report.md"
        )
        output = vault / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report, encoding="utf-8", newline="\n")
        print(f"Wrote review report: {output.resolve()}")
    if args.json:
        print(json.dumps(entries, indent=2, ensure_ascii=False))
    elif not args.write:
        print(report, end="")
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

    suggest_parser = subparsers.add_parser(
        "suggest", help="suggest tags, status, topic, and related cards"
    )
    suggest_parser.add_argument("--vault", required=True, help="vault path")
    suggest_parser.add_argument(
        "--input", required=True, help="card or text path; use - for stdin"
    )
    suggest_parser.add_argument("--topic-hint", help="semantic topic slug")
    suggest_parser.add_argument(
        "--queue",
        action="store_true",
        help="queue uncertain suggestions for batch review",
    )
    suggest_parser.add_argument("--json", action="store_true", help="print JSON")
    suggest_parser.set_defaults(handler=command_suggest)

    dedupe_parser = subparsers.add_parser(
        "dedupe", help="find semantically similar card pairs"
    )
    dedupe_parser.add_argument("--vault", required=True, help="vault path")
    dedupe_parser.add_argument(
        "--threshold",
        type=float,
        help="similarity threshold between 0 and 1",
    )
    dedupe_parser.add_argument("--json", action="store_true", help="print JSON")
    dedupe_parser.set_defaults(handler=command_dedupe)

    review_parser = subparsers.add_parser(
        "review", help="show or write queued suggestions"
    )
    review_parser.add_argument("--vault", required=True, help="vault path")
    review_parser.add_argument(
        "--write",
        action="store_true",
        help="write the generated review report into the vault",
    )
    review_parser.add_argument("--json", action="store_true", help="print JSON")
    review_parser.set_defaults(handler=command_review)

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

