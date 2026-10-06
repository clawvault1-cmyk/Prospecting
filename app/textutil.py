"""Small text helpers shared by validators and the fact-check gate."""

from __future__ import annotations

import re

WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*%?")
SENTENCE_SPLIT = re.compile(r"(?<=[.?!])\s+")
NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?%?")

STOP = {
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "with", "at", "by",
    "from", "that", "this", "it", "its", "as", "their", "they", "them", "his", "her",
    "not", "no", "do", "does", "did", "but", "if", "so", "than", "then", "into",
    "over", "after", "before", "about", "up", "out", "just", "also", "more", "most",
    "other", "such", "can", "will", "would", "should", "could", "may", "might",
    "saw", "put", "has", "have", "had", "per", "via", "across", "between", "within",
    "without", "under", "our", "ours", "we", "you", "your", "yours", "i", "im",
    "are", "was", "were", "been", "being", "be", "is", "am", "when", "while",
    "what", "which", "who", "how", "where", "there", "here", "still", "want",
    "happy", "useful", "open", "side", "note", "page", "one", "short", "look",
}


def words(text: str) -> list[str]:
    return WORD_RE.findall(text or "")


def word_count(text: str) -> int:
    return len(words(text))


_ABBR = re.compile(r"\b(St|Mr|Mrs|Ms|Dr|Jr|Sr|Inc|Co|U\.S)\.")


def iter_sentences(text: str) -> list[str]:
    chunks: list[str] = []
    for para in re.split(r"\n+", (text or "").strip()):
        para = para.strip()
        if not para:
            continue
        shielded = _ABBR.sub(lambda match: match.group(0).replace(".", "∯"), para)
        parts = SENTENCE_SPLIT.split(shielded)
        for part in parts:
            restored = part.replace("∯", ".").strip()
            if restored:
                chunks.append(restored)
    return chunks


def normalize_number(raw: str) -> str:
    return raw.replace(",", "").lower()


def numbers(text: str) -> list[str]:
    return [normalize_number(raw) for raw in NUMBER_RE.findall(text or "")]


def number_in(number: str, blob: str) -> bool:
    found = set(numbers(blob))
    if number in found:
        return True
    if number.endswith("%") and number[:-1] in found:
        return True
    if not number.endswith("%") and f"{number}%" in found:
        return True
    return False


def numbers_supported(claim: str, blob: str) -> bool:
    return all(number_in(number, blob) for number in numbers(claim))


def norm_ws(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def tokens(text: str) -> list[str]:
    out = []
    for word in words(text):
        low = word.lower().rstrip("%")
        if len(low) <= 3 or low in STOP:
            continue
        out.append(low)
    return out


def you_we_counts(text: str) -> tuple[int, int]:
    you = len(re.findall(r"\b(you|your|yours)\b", text or "", flags=re.I))
    we = len(re.findall(r"\b(we|our|ours|i|i'm|im|we're|we've)\b", text or "", flags=re.I))
    return you, we
