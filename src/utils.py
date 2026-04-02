import hashlib
import html
import re
import unicodedata
from difflib import get_close_matches
from typing import Any
from .config import SEARCH_ALPHABET

def url_join(base: str, *paths: Any):

    for path in paths:
        base = f"{base.rstrip('/')}/{str(path).lstrip('/')}"

    return base

def normalize_search_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = ''.join(char if char in SEARCH_ALPHABET else " " for char in normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def search_terms(query: str) -> list[str]:
    return [term for term in normalize_search_text(query).split(" ") if term]


def search_score(query: str, text: str) -> int:
    normalized_query = normalize_search_text(query)
    normalized_text = normalize_search_text(text)

    if not normalized_query or not normalized_text:
        return 0

    query_terms = search_terms(normalized_query)
    text_words = normalized_text.split(" ")
    text_word_set = set(text_words)

    score = 0
    matches = 0

    if normalized_text == normalized_query:
        score += 400

    full_query_index = normalized_text.find(normalized_query)
    if full_query_index != -1:
        score += 240 - min(full_query_index, 40)
        matches += len(query_terms)

    for term in query_terms:
        if term in text_word_set:
            score += 90
            matches += 1
            continue

        if term in normalized_text:
            score += 60
            matches += 1
            continue

        close_match = get_close_matches(term, text_word_set, n=1, cutoff=0.78)
        if close_match:
            score += 36
            matches += 1
            continue

        compact_text = normalized_text.replace(" ", "")
        if _is_subsequence(term, compact_text):
            score += 12

    if matches == 0:
        return 0

    if matches >= len(query_terms):
        score += 80

    score += min(len(normalized_text), 240) // 12
    return score


def _is_subsequence(needle: str, haystack: str) -> bool:
    if not needle:
        return True

    needle_index = 0
    for char in haystack:
        if char == needle[needle_index]:
            needle_index += 1
            if needle_index == len(needle):
                return True

    return False


def highlight_matches(text: str, query: str) -> str:
    terms = sorted(set(search_terms(query)), key=len, reverse=True)
    if not text or not terms:
        return html.escape(text or "")

    escaped_text = html.escape(text)
    for term in terms:
        if not term:
            continue

        pattern = re.compile(rf"({re.escape(term)})", re.IGNORECASE)
        escaped_text = pattern.sub(r"<mark>\1</mark>", escaped_text)

    return escaped_text


def make_excerpt(text: str, query: str, radius: int = 92) -> str:
    stripped_text = " ".join(text.split())
    if not stripped_text:
        return ""

    normalized_text = normalize_search_text(stripped_text)
    normalized_query = normalize_search_text(query)

    excerpt = stripped_text
    if normalized_query and normalized_text:
        source_index = _find_excerpt_start(stripped_text, query)
        if source_index > radius:
            excerpt = "..." + stripped_text[source_index - radius:source_index + radius]
        else:
            excerpt = stripped_text[: radius * 2]

        if source_index + radius < len(stripped_text):
            excerpt = excerpt.rstrip() + "..."

    return highlight_matches(excerpt, query)


def _find_excerpt_start(text: str, query: str) -> int:
    lowered_text = text.casefold()

    for term in search_terms(query):
        index = lowered_text.find(term)
        if index != -1:
            return index

    return 0


def stable_slug(value: str, prefix: str = "item") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    slug = slug or prefix
    digest = hashlib.sha1(value.encode("utf8")).hexdigest()[:8]
    return f"{slug}-{digest}"
