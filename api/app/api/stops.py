"""Stop resolution using the immutable bus snapshot."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from difflib import SequenceMatcher
import logging
from types import MappingProxyType
import re
import unicodedata

from api.app.schemas.snapshot import RoutingIndexes, StopId


# normalized district -> normalized stop name -> compact IDs
StopNameIndex = Mapping[str, Mapping[str, tuple[StopId, ...]]]
logger = logging.getLogger(__name__)


def normalize_text(value: str) -> str:
    """Normalize Turkish text for case/accent-insensitive name comparisons."""

    value = value.translate(str.maketrans({"I": "ı", "İ": "i"})).casefold()
    value = value.translate(
        str.maketrans({"ı": "i", "ğ": "g", "ü": "u", "ş": "s", "ö": "o", "ç": "c"})
    )
    value = "".join(
        character
        for character in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(character)
    )
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value).split())


def build_stop_name_index(indexes: RoutingIndexes) -> StopNameIndex:
    """Build an immutable index containing only stops used by active patterns.

    ``stop_id`` is the relational key throughout the snapshot.  Stops absent
    from ``routes_at_stop`` or mapped to an empty pattern set are excluded, so
    stale master-list entries cannot be returned by name resolution.
    """

    grouped: dict[str, dict[str, list[StopId]]] = defaultdict(lambda: defaultdict(list))
    for stop_id, stop in indexes.stops.items():
        active_patterns = indexes.routes_at_stop.get(stop_id, frozenset())
        if not active_patterns:
            continue
        district_key = normalize_text(stop.district)
        name_key = normalize_text(stop.name)
        if district_key and name_key:
            grouped[district_key][name_key].append(stop_id)
        # A city-wide index supports stops without district metadata.
        if name_key:
            grouped[""][name_key].append(stop_id)

    return MappingProxyType(
        {
            district: MappingProxyType(
                {name: tuple(sorted(ids)) for name, ids in names.items()}
            )
            for district, names in grouped.items()
        }
    )


def resolve_stop_ids(
    query: Mapping[str, str],
    stop_name_index: StopNameIndex,
    indexes: RoutingIndexes,
) -> tuple[StopId, ...]:
    """Return every best-matching active platform for a district/name query.

    All indexed IDs have active patterns. Matching is district-scoped, and
    equally good names return all matching stop IDs so the routing layer can
    evaluate directional platforms independently.
    """

    logger.info("Stop resolution requested: %s", dict(query))
    district_key = normalize_text(query.get("district", ""))
    name_query = normalize_text(query.get("name", ""))
    names_in_district = stop_name_index.get(district_key)
    fallback_names = stop_name_index.get("")
    if not name_query or (not names_in_district and not fallback_names):
        logger.warning(
            "No stop-name candidates for district=%r (normalized=%r), name=%r; "
            "district_index_found=%s",
            query.get("district", ""),
            district_key,
            query.get("name", ""),
            names_in_district is not None,
        )
        return ()

    best_score = 0.0
    scored_candidates: list[tuple[float, StopId]] = []
    # Prefer district-scoped matches, but do not make stations whose source
    # omits a district impossible to find.
    for names, district_bonus in ((names_in_district, 0.02), (fallback_names, 0.0)):
        if not names:
            continue
        for indexed_name, stop_ids in names.items():
            score = _name_similarity(name_query, indexed_name) + district_bonus
            best_score = max(best_score, score)
            scored_candidates.extend((score, stop_id) for stop_id in stop_ids)

    # Exact, substring, token overlap, and fuzzy matches receive descending
    # scores.  A weak match is reported as unresolved rather than guessed.
    if best_score < 0.70 or not scored_candidates:
        return ()

    # A broad place name such as "Umuttepe" can name several nearby platforms.
    # Retain near-best names so a short, poorly connected name cannot hide the
    # main interchange. Exact matches remain exact.
    threshold = best_score if best_score >= 0.999 else best_score - 0.03
    best_for_stop: dict[StopId, float] = {}
    for score, stop_id in scored_candidates:
        if score >= threshold:
            best_for_stop[stop_id] = max(score, best_for_stop.get(stop_id, 0.0))
    matches = tuple(
        sorted(
            best_for_stop,
            key=lambda stop_id: (
                -best_for_stop[stop_id],
                -len(indexes.routes_at_stop[stop_id]),
                int(stop_id),
            ),
        )[:16]
    )
    for selected_id in matches:
        selected_stop = indexes.stops[selected_id]
        active_patterns = len(indexes.routes_at_stop[selected_id])
        logger.info(
            "Active stop candidate: stop_id=%s gtfs_stop_id=%r name=%r district=%r "
            "name_score=%.3f active_patterns=%d",
            int(selected_id),
            selected_stop.gtfs_id,
            selected_stop.name,
            selected_stop.district,
            best_score,
            active_patterns,
        )
    logger.info(
        "Stop resolution returned %d active candidate(s) for district=%r "
        "name=%r best_name_score=%.3f",
        len(matches),
        query.get("district", ""),
        query.get("name", ""),
        best_score,
        )
    return matches


def resolve_stop_id(
    query: Mapping[str, str],
    stop_name_index: StopNameIndex,
    indexes: RoutingIndexes,
) -> StopId | None:
    """Compatibility helper returning the highest-coverage active candidate."""

    matches = resolve_stop_ids(query, stop_name_index, indexes)
    return matches[0] if matches else None


def _name_similarity(query: str, candidate: str) -> float:
    if query == candidate:
        return 1.0
    if query in candidate or candidate in query:
        return 0.9 + 0.09 * min(len(query), len(candidate)) / max(
            len(query), len(candidate)
        )
    query_tokens, candidate_tokens = set(query.split()), set(candidate.split())
    overlap = len(query_tokens & candidate_tokens) / max(
        len(query_tokens), len(candidate_tokens), 1
    )
    fuzzy = SequenceMatcher(a=query, b=candidate).ratio()
    return max(overlap * 0.88, fuzzy)
