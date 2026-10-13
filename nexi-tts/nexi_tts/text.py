"""Bounded English frontend; the Kitten 0.8 symbol table and tokenization contract."""

from __future__ import annotations

import re
import unicodedata

from num2words import num2words

MAX_TEXT_CHARS = 20000
CHUNK_CHARS = 180
MAX_TOKENS = 510
SYMBOLS = (
    "$"
    ';:,.!?¡¿—…"«»"" '
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    "ɑɐɒæɓʙβɔɕçɗɖðʤəɘɚɛɜɝɞɟʄɡɠɢʛɦɧħɥʜɨɪʝɭɬɫɮʟɱɯɰŋɳɲɴøɵɸθœɶʘɹɺɾɻʀʁɽʂʃʈʧʉʊʋⱱʌɣɤʍχʎʏʑʐʒʔʡʕʢǀǁǂǃˈˌːˑʼʴʰʱʲʷˠˤ˞↓↑→↗↘'̩'ᵻ"
)
TOKEN_IDS = {char: index for index, char in enumerate(SYMBOLS)}


def normalize(text: str) -> str:
    if not text.strip():
        raise ValueError("Text must not be empty")
    if len(text) > MAX_TEXT_CHARS:
        raise ValueError(f"Text exceeds {MAX_TEXT_CHARS} characters")
    if any(unicodedata.category(char) == "Cc" and char not in "\n\r\t" for char in text):
        raise ValueError("Text contains control characters")
    text = unicodedata.normalize("NFKC", text).replace("’", "'").replace("“", '"').replace("”", '"')

    def expand(match: re.Match[str]) -> str:
        raw = match.group().replace(",", "")
        if len(raw) > 15:
            raise ValueError("Numbers longer than 15 characters must be spelled out")
        return str(num2words(raw, lang="en"))

    text = re.sub(r"(?<!\w)(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?!\w)", expand, text)
    return " ".join(text.split())


def chunk_text(text: str, limit: int = CHUNK_CHARS) -> list[str]:
    if limit < 2:
        raise ValueError("Chunk limit must be at least two")
    chunks: list[str] = []
    # Reserve one character for the punctuation required by the upstream model.
    for sentence in re.split(r"(?<=[.!?;])\s+", text):
        remaining = sentence.strip()
        while remaining:
            if len(remaining) <= limit - 1:
                piece, remaining = remaining, ""
            else:
                split = remaining.rfind(" ", 0, limit)
                if split <= 0:
                    split = limit - 1
                piece, remaining = remaining[:split], remaining[split:].lstrip()
            if piece[-1] not in ".!?,;:":
                piece += ","
            chunks.append(piece)
    return chunks


def tokenize(phonemes: str) -> list[int]:
    separated = " ".join(re.findall(r"\w+|[^\w\s]", phonemes))
    tokens = [TOKEN_IDS[char] for char in separated if char in TOKEN_IDS]
    if not tokens:
        raise ValueError("Input produced no supported phonemes")
    if len(tokens) + 2 > MAX_TOKENS:
        raise ValueError("Phoneme sequence too long; use shorter words or smaller chunks")
    return [0, *tokens, 0]
