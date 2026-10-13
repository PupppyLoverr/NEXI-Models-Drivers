"""Bounded English frontend; the Kitten 0.8 symbol table and tokenization contract."""

from __future__ import annotations

import re
import unicodedata

from num2words import num2words

MAX_TEXT_CHARS = 20000
CHUNK_CHARS = 128
MAX_TOKENS = 510
SYMBOLS = (
    "$"
    ';:,.!?¡¿—…"«»"" '
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    "ɑɐɒæɓʙβɔɕçɗɖðʤəɘɚɛɜɝɞɟʄɡɠɢʛɦɧħɥʜɨɪʝɭɬɫɮʟɱɯɰŋɳɲɴøɵɸθœɶʘɹɺɾɻʀʁɽʂʃʈʧʉʊʋⱱʌɣɤʍχʎʏʑʐʒʔʡʕʢǀǁǂǃˈˌːˑʼʴʰʱʲʷˠˤ˞↓↑→↗↘'̩'ᵻ"
)
TOKEN_IDS = {char: index for index, char in enumerate(SYMBOLS)}
NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
UNITS = {
    "kg": ("kilogram", "kilograms"),
    "km": ("kilometer", "kilometers"),
    "cm": ("centimeter", "centimeters"),
    "mm": ("millimeter", "millimeters"),
    "mL": ("milliliter", "milliliters"),
    "MB": ("megabyte", "megabytes"),
    "GB": ("gigabyte", "gigabytes"),
    "Hz": ("hertz", "hertz"),
    "kHz": ("kilohertz", "kilohertz"),
}


def number_words(raw: str) -> str:
    raw = raw.replace(",", "")
    if sum(char.isdigit() for char in raw) > 15:
        raise ValueError("Numbers longer than 15 digits must be spelled out")
    sign = "minus " if raw.startswith("-") else "plus " if raw.startswith("+") else ""
    integer, separator, fraction = raw.lstrip("+-").partition(".")
    words = str(num2words(integer, lang="en"))
    if separator:
        words += " point " + " ".join(str(num2words(digit, lang="en")) for digit in fraction)
    return sign + words


def money_words(match: re.Match[str]) -> str:
    sign, symbol, raw = match.groups()
    major, _, minor = raw.replace(",", "").partition(".")
    if len(minor) > 2:
        raise ValueError("Currency amounts support at most two decimal places")
    major_units, minor_units = {
        "$": (("dollar", "dollars"), ("cent", "cents")),
        "£": (("pound", "pounds"), ("penny", "pence")),
        "€": (("euro", "euros"), ("cent", "cents")),
    }[symbol]
    words = number_words(major) + " " + major_units[int(int(major) != 1)]
    cents = int(minor.ljust(2, "0") or "0")
    if cents:
        words += " and " + number_words(str(cents)) + " " + minor_units[int(cents != 1)]
    return ("minus " if sign == "-" else "plus " if sign == "+" else "") + words


def normalize(text: str) -> str:
    if not text.strip():
        raise ValueError("Text must not be empty")
    if len(text) > MAX_TEXT_CHARS:
        raise ValueError(f"Text exceeds {MAX_TEXT_CHARS} characters")
    if any(unicodedata.category(char) == "Cc" and char not in "\n\r\t" for char in text):
        raise ValueError("Text contains control characters")
    text = unicodedata.normalize("NFKC", text).replace("’", "'").replace("“", '"').replace("”", '"')

    text = re.sub(rf"(?<!\w)([-+]?)([$£€])\s*({NUMBER})(?!\w|\.\d)", money_words, text)
    text = re.sub(
        r"(?<!\w)(\d{1,12})(?:st|nd|rd|th)(?!\w)",
        lambda match: str(num2words(match[1], lang="en", to="ordinal")),
        text,
        flags=re.IGNORECASE,
    )

    def unit_words(match: re.Match[str]) -> str:
        raw, unit = match.groups()
        singular, plural = UNITS[unit]
        return (
            number_words(raw)
            + " "
            + (singular if abs(float(raw.replace(",", ""))) == 1 else plural)
        )

    text = re.sub(
        rf"(?<![\w.])([-+]?{NUMBER})\s*({'|'.join(UNITS)})(?!\w)",
        unit_words,
        text,
    )
    text = re.sub(
        rf"(?<![\w.])([-+]?{NUMBER})\s*%(?!\w)",
        lambda match: number_words(match[1]) + " percent",
        text,
    )
    text = re.sub(
        r"\b(Mr|Mrs|Ms|Dr|Prof)\.(?=\s+[A-Z])",
        lambda match: {
            "Mr": "Mister",
            "Mrs": "Missus",
            "Ms": "Ms",
            "Dr": "Doctor",
            "Prof": "Professor",
        }[match[1]],
        text,
    )
    text = re.sub(
        rf"(?<![\w.])[-+]?{NUMBER}(?!\w|\.\d)",
        lambda match: number_words(match.group()),
        text,
    )
    text = " ".join(text.split())
    if len(text) > MAX_TEXT_CHARS:
        raise ValueError(f"Expanded text exceeds {MAX_TEXT_CHARS} characters")
    return text


def chunk_text(
    text: str, limit: int = CHUNK_CHARS, *, first_chunk_chars: int | None = None
) -> list[str]:
    if limit < 2:
        raise ValueError("Chunk limit must be at least two")
    if first_chunk_chars is not None and not 2 <= first_chunk_chars <= limit:
        raise ValueError(f"First chunk limit must be between two and {limit}")
    chunks: list[str] = []
    # Reserve one character for the punctuation required by the upstream model.
    for sentence in re.split(r"(?<=[.!?;])\s+", text):
        remaining = sentence.strip()
        while remaining:
            active_limit = first_chunk_chars if not chunks and first_chunk_chars else limit
            if len(remaining) <= active_limit - 1:
                piece, remaining = remaining, ""
            else:
                split = remaining.rfind(" ", 0, active_limit)
                if split <= 0:
                    split = active_limit - 1
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
