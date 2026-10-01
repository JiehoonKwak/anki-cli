from __future__ import annotations

import html
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from .ankiconnect import AnkiConnectClient

GENERIC_TAGS = {
    "llm_generated",
    "agent::codex",
    "flashcards",
    "obsidian",
    "marked",
    "leech",
}

ENGLISH_STOPWORDS = {
    "about",
    "after",
    "again",
    "also",
    "anki",
    "answer",
    "because",
    "before",
    "between",
    "card",
    "cards",
    "context",
    "could",
    "does",
    "front",
    "from",
    "have",
    "into",
    "like",
    "more",
    "note",
    "question",
    "should",
    "source",
    "that",
    "their",
    "there",
    "these",
    "this",
    "what",
    "when",
    "where",
    "which",
    "with",
    "would",
}

KOREAN_STOPWORDS = {
    "것은",
    "것이",
    "것을",
    "있는",
    "없는",
    "무엇인가",
    "어떻게",
    "어떤",
    "왜",
    "핵심",
    "차이",
    "의미",
    "용도",
    "정의",
    "설명",
    "카드",
}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def strip_html(value: str) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def truncate(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    text = strip_html(text)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _field_value(fields: dict[str, Any], name: str) -> str:
    value = fields.get(name)
    if isinstance(value, dict):
        return str(value.get("value", "") or "")
    if value is None:
        return ""
    return str(value)


def field_value(fields: dict[str, Any], *names: str) -> str:
    lower_map = {str(key).lower(): key for key in fields}
    for name in names:
        direct = _field_value(fields, name)
        if direct:
            return direct
        key = lower_map.get(name.lower())
        if key is not None:
            indirect = _field_value(fields, str(key))
            if indirect:
                return indirect
    return ""


def front_back_from_fields(fields: dict[str, Any]) -> tuple[str, str]:
    front = field_value(fields, "Front", "Text", "Question", "Expression")
    back = field_value(fields, "Back", "Meaning", "Answer", "Definition")
    if front or back:
        return front, back
    values = [_field_value(fields, str(key)) for key in fields]
    values = [value for value in values if value]
    if not values:
        return "", ""
    if len(values) == 1:
        return values[0], ""
    return values[0], values[1]


def review_timestamp_ms(review: dict[str, Any]) -> int:
    try:
        return int(review.get("id", 0) or 0)
    except (TypeError, ValueError):
        return 0


def review_ease(review: dict[str, Any]) -> int:
    try:
        return int(review.get("ease", 0) or 0)
    except (TypeError, ValueError):
        return 0


def review_type(review: dict[str, Any]) -> int:
    try:
        return int(review.get("type", 0) or 0)
    except (TypeError, ValueError):
        return 0


def is_review_hard(review: dict[str, Any]) -> bool:
    # In learning/relearning reviews, button 2 is often "Good", not "Hard".
    # Count Hard only for normal/filtered review events where 4-button review semantics apply.
    return review_ease(review) == 2 and review_type(review) in {1, 3}


def review_time_ms(review: dict[str, Any]) -> int:
    try:
        return int(review.get("time", 0) or 0)
    except (TypeError, ValueError):
        return 0


def review_stats(
    reviews: list[dict[str, Any]],
    *,
    now: datetime,
    days: int,
    recent_days: int,
) -> dict[str, Any]:
    now_ms = int(now.timestamp() * 1000)
    window_cutoff = now_ms - days * 24 * 60 * 60 * 1000
    recent_cutoff = now_ms - recent_days * 24 * 60 * 60 * 1000
    window = [review for review in reviews if review_timestamp_ms(review) >= window_cutoff]
    recent = [review for review in reviews if review_timestamp_ms(review) >= recent_cutoff]

    def count_again(items: list[dict[str, Any]]) -> int:
        return sum(1 for item in items if review_ease(item) == 1)

    def count_hard(items: list[dict[str, Any]]) -> int:
        return sum(1 for item in items if is_review_hard(item))

    def count_ease(items: list[dict[str, Any]], ease: int) -> int:
        return sum(1 for item in items if review_ease(item) == ease)

    time_values = [review_time_ms(review) for review in window if review_time_ms(review) > 0]
    avg_time_ms = round(sum(time_values) / len(time_values)) if time_values else 0
    max_time_ms = max(time_values) if time_values else 0
    last_review_ms = max((review_timestamp_ms(review) for review in reviews), default=0)
    return {
        "total": len(reviews),
        "window_days": days,
        "recent_days": recent_days,
        "window_total": len(window),
        "recent_total": len(recent),
        "again_window": count_again(window),
        "hard_window": count_hard(window),
        "good_window": count_ease(window, 3),
        "easy_window": count_ease(window, 4),
        "again_recent": count_again(recent),
        "hard_recent": count_hard(recent),
        "avg_time_ms_window": avg_time_ms,
        "max_time_ms_window": max_time_ms,
        "last_review_ms": last_review_ms,
    }


def int_info(info: dict[str, Any], key: str, default: int = 0) -> int:
    try:
        value = info.get(key, default)
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def maturity(info: dict[str, Any], *, min_reps: int, min_interval: int) -> dict[str, Any]:
    reps = int_info(info, "reps")
    interval = int_info(info, "interval")
    lapses = int_info(info, "lapses")
    queue = int_info(info, "queue")
    card_type = int_info(info, "type")
    is_mature = reps >= min_reps or interval >= min_interval
    return {
        "reps": reps,
        "interval": interval,
        "lapses": lapses,
        "queue": queue,
        "type": card_type,
        "mature": is_mature,
        "thresholds": {"min_reps": min_reps, "min_interval": min_interval},
    }


def content_signals(front: str, back: str) -> list[str]:
    front_text = strip_html(front)
    back_text = strip_html(back)
    signals: list[str] = []
    if len(front_text) > 180:
        signals.append("long_front")
    if len(back_text) > 700:
        signals.append("long_back")
    if any(marker in front_text for marker in ["이 논문", "이 영상", "위 글", "본문", "Fig.", "Figure"]):
        signals.append("source_dependent_front")
    if ">>>" in front or ">>>" in back or "&gt;&gt;&gt;" in front or "&gt;&gt;&gt;" in back:
        signals.append("delimiter_fragment")
    if re.search(r"</?p>|</?div>|</?span>", front + back, flags=re.IGNORECASE):
        signals.append("html_fragment")
    return signals


def friction_score(stats: dict[str, Any], mat: dict[str, Any], source_reasons: set[str]) -> float:
    score = 0.0
    score += stats["again_recent"] * 10
    score += stats["again_window"] * 6
    score += stats["hard_recent"] * 5
    score += stats["hard_window"] * 2
    score += min(mat["lapses"], 5) * 8
    if "leech" in source_reasons:
        score += 10
    if mat["mature"]:
        score += 4
    score += min(mat["reps"], 20) * 0.2
    return round(score, 2)


def eligible_for_gap_brief(stats: dict[str, Any], mat: dict[str, Any], source_reasons: set[str]) -> bool:
    if mat["lapses"] > 0 or "leech" in source_reasons:
        return True
    repeated_friction = (
        stats["again_window"] >= 2
        or stats["hard_window"] >= 3
        or (stats["again_window"] >= 1 and stats["hard_window"] >= 1)
    )
    mature_friction = mat["mature"] and (stats["again_window"] >= 1 or stats["hard_window"] >= 2)
    return repeated_friction or mature_friction


def reason_codes(stats: dict[str, Any], mat: dict[str, Any], source_reasons: set[str], content: list[str]) -> list[str]:
    reasons = sorted(source_reasons)
    if mat["mature"]:
        reasons.append("mature_card")
    if mat["lapses"] > 0:
        reasons.append("lapses>0")
    if stats["again_recent"]:
        reasons.append(f"again_{stats['recent_days']}d:{stats['again_recent']}")
    if stats["hard_recent"]:
        reasons.append(f"hard_{stats['recent_days']}d:{stats['hard_recent']}")
    if stats["again_window"]:
        reasons.append(f"again_{stats['window_days']}d:{stats['again_window']}")
    if stats["hard_window"]:
        reasons.append(f"hard_{stats['window_days']}d:{stats['hard_window']}")
    reasons.extend(content)
    return list(dict.fromkeys(reasons))


def tokenize(text: str) -> set[str]:
    stripped = strip_html(text).lower()
    tokens = re.findall(r"[a-z][a-z0-9_:+\-/]{2,}|[가-힣]{2,}", stripped)
    result: set[str] = set()
    for token in tokens:
        if token in ENGLISH_STOPWORDS or token in KOREAN_STOPWORDS:
            continue
        if token.isdigit():
            continue
        result.add(token)
    return result


def _cluster_summary(label: str, candidates: list[dict[str, Any]], *, kind: str, max_fronts: int = 5) -> dict[str, Any]:
    score = round(sum(float(item.get("score", 0)) for item in candidates), 2)
    fronts = [item.get("text", {}).get("front", "") for item in candidates if item.get("text", {}).get("front")]
    reason_counter: Counter[str] = Counter()
    for item in candidates:
        reason_counter.update(item.get("reason_codes", []))
    return {
        "kind": kind,
        "label": label,
        "count": len(candidates),
        "score": score,
        "card_ids": [item["card_id"] for item in candidates],
        "top_fronts": fronts[:max_fronts],
        "top_reasons": [reason for reason, _count in reason_counter.most_common(8)],
    }


def build_clusters(candidates: list[dict[str, Any]], *, max_clusters: int = 20) -> list[dict[str, Any]]:
    clusters: list[dict[str, Any]] = []

    def add_group_clusters(kind: str, grouped: dict[str, list[dict[str, Any]]], min_count: int = 2) -> None:
        for label, items in grouped.items():
            if label and len(items) >= min_count:
                clusters.append(_cluster_summary(label, items, kind=kind))

    by_deck: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_tag: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_token: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for item in candidates:
        by_deck[item.get("deck", "")].append(item)
        source = item.get("source") or {}
        source_label = source.get("title") or source.get("uri") or ""
        if source_label:
            by_source[source_label].append(item)
        for tag in item.get("tags", []):
            if tag not in GENERIC_TAGS and not tag.startswith("agent::"):
                by_tag[tag].append(item)
        text = item.get("text", {})
        for token in tokenize(f"{text.get('front', '')} {text.get('back', '')}"):
            by_token[token].append(item)

    add_group_clusters("deck", by_deck, min_count=2)
    add_group_clusters("source", by_source, min_count=2)
    add_group_clusters("tag", by_tag, min_count=2)
    add_group_clusters("term", by_token, min_count=2)

    # Similar-pair candidates are intentionally lightweight; the LLM makes the final judgment.
    for i, left in enumerate(candidates[:80]):
        left_tokens = tokenize(f"{left.get('text', {}).get('front', '')} {left.get('text', {}).get('back', '')}")
        if len(left_tokens) < 3:
            continue
        for right in candidates[i + 1 : 80]:
            right_tokens = tokenize(f"{right.get('text', {}).get('front', '')} {right.get('text', {}).get('back', '')}")
            if len(right_tokens) < 3:
                continue
            overlap = left_tokens & right_tokens
            union = left_tokens | right_tokens
            jaccard = len(overlap) / len(union) if union else 0.0
            if len(overlap) >= 3 and jaccard >= 0.22:
                label = ", ".join(sorted(overlap)[:6])
                pair = _cluster_summary(label, [left, right], kind="similar_pair", max_fronts=2)
                pair["similarity"] = round(jaccard, 3)
                clusters.append(pair)

    clusters.sort(key=lambda item: (float(item["score"]), int(item["count"])), reverse=True)
    return clusters[:max_clusters]


def scoped_query(base: str, *, decks: list[str] | None = None, extra_query: str | None = None) -> list[str]:
    scopes = decks or [None]
    queries = []
    for deck in scopes:
        parts: list[str] = []
        if deck:
            parts.append(f'deck:"{deck}"')
        if extra_query:
            parts.append(extra_query)
        parts.append(base)
        queries.append(" ".join(parts))
    return queries


def find_cards_for(client: AnkiConnectClient, base: str, *, decks: list[str] | None, extra_query: str | None) -> list[int]:
    found: list[int] = []
    for query in scoped_query(base, decks=decks, extra_query=extra_query):
        found.extend(client.find_cards(query))
    return sorted(set(found))


def note_by_id(client: AnkiConnectClient, note_ids: list[int]) -> dict[int, dict[str, Any]]:
    if not note_ids:
        return {}
    infos = client.notes_info(notes=sorted(set(note_ids)))
    return {int(info["noteId"]): info for info in infos if "noteId" in info}


def card_text_payload(
    card_info: dict[str, Any],
    note_info: dict[str, Any] | None,
    *,
    include_text: str,
    max_field_chars: int,
) -> dict[str, str]:
    if include_text == "none":
        return {}
    fields = (note_info or {}).get("fields") or card_info.get("fields") or {}
    front, back = front_back_from_fields(fields)
    if include_text == "full":
        return {"front": strip_html(front), "back": strip_html(back)}
    return {"front": truncate(front, max_field_chars), "back": truncate(back, max_field_chars)}


def source_payload(card_info: dict[str, Any], note_info: dict[str, Any] | None) -> dict[str, str]:
    fields = (note_info or {}).get("fields") or card_info.get("fields") or {}
    return {
        "title": strip_html(field_value(fields, "SourceTitle")),
        "uri": strip_html(field_value(fields, "SourceURI")),
        "locator": strip_html(field_value(fields, "SourceLocator")),
    }


def build_gap_export(
    client: AnkiConnectClient,
    *,
    days: int = 30,
    recent_days: int = 7,
    limit: int = 80,
    max_pool: int = 500,
    include_text: str = "preview",
    max_field_chars: int = 700,
    min_reps: int = 3,
    min_interval: int = 7,
    decks: list[str] | None = None,
    extra_query: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if days < 1 or recent_days < 1:
        raise ValueError("days and recent_days must be positive")
    if recent_days > days:
        raise ValueError("recent_days must be <= days")
    if include_text not in {"none", "preview", "full"}:
        raise ValueError("include_text must be one of: none, preview, full")

    now = now or now_utc()
    query_specs = {
        "again_recent": f"rated:{recent_days}:1",
        "hard_recent": f"rated:{recent_days}:2",
        "again_window": f"rated:{days}:1",
        "hard_window": f"rated:{days}:2",
        "lapsed": "prop:lapses>0",
        "leech": "tag:leech",
    }
    query_counts: dict[str, int] = {}
    reason_by_card: dict[int, set[str]] = defaultdict(set)
    for reason, base_query in query_specs.items():
        card_ids = find_cards_for(client, base_query, decks=decks, extra_query=extra_query)
        query_counts[reason] = len(card_ids)
        for card_id in card_ids[:max_pool]:
            reason_by_card[card_id].add(reason)

    pool_ids = sorted(reason_by_card.keys())[:max_pool]
    card_infos = client.cards_info(pool_ids) if pool_ids else []
    note_infos = note_by_id(client, [int_info(info, "note") for info in card_infos])
    reviews_by_card = client.get_reviews_of_cards([int(info["cardId"]) for info in card_infos]) if card_infos else {}

    candidates: list[dict[str, Any]] = []
    excluded_counts: Counter[str] = Counter()
    for info in card_infos:
        card_id = int(info["cardId"])
        note_id = int_info(info, "note")
        note_info = note_infos.get(note_id)
        stats = review_stats(list(reviews_by_card.get(str(card_id), reviews_by_card.get(card_id, []))), now=now, days=days, recent_days=recent_days)
        mat = maturity(info, min_reps=min_reps, min_interval=min_interval)
        reasons = reason_by_card.get(card_id, set())
        text = card_text_payload(info, note_info, include_text=include_text, max_field_chars=max_field_chars)
        content = content_signals(text.get("front", ""), text.get("back", ""))
        if not eligible_for_gap_brief(stats, mat, reasons):
            excluded_counts["low_signal_or_normal_learning_noise"] += 1
            continue
        note_tags = list((note_info or {}).get("tags", []))
        score = friction_score(stats, mat, reasons)
        candidates.append(
            {
                "card_id": card_id,
                "note_id": note_id,
                "deck": str(info.get("deckName", "")),
                "model": str(info.get("modelName", "")),
                "maturity": mat,
                "review_stats": stats,
                "source": source_payload(info, note_info),
                "tags": note_tags,
                "reason_codes": reason_codes(stats, mat, reasons, content),
                "score": score,
                "text": text,
            }
        )

    candidates.sort(key=lambda item: float(item["score"]), reverse=True)
    candidates = candidates[:limit]

    state_counts = {
        "due": len(find_cards_for(client, "is:due", decks=decks, extra_query=extra_query)),
        "learning": len(find_cards_for(client, "is:learn", decks=decks, extra_query=extra_query)),
        "new": len(find_cards_for(client, "is:new", decks=decks, extra_query=extra_query)),
    }
    return {
        "schema_version": 1,
        "kind": "anki_gap_export",
        "generated_at": now.isoformat(),
        "scope": {
            "days": days,
            "recent_days": recent_days,
            "limit": limit,
            "max_pool": max_pool,
            "include_text": include_text,
            "max_field_chars": max_field_chars,
            "min_reps": min_reps,
            "min_interval": min_interval,
            "decks": decks or [],
            "query": extra_query or "",
            "explicit_user_signals_excluded": ["tag:marked", "flag:1"],
        },
        "counts": {
            **state_counts,
            **query_counts,
            "candidate_pool": len(pool_ids),
            "candidates": len(candidates),
            "excluded": dict(excluded_counts),
        },
        "candidates": candidates,
        "clusters": build_clusters(candidates),
    }
