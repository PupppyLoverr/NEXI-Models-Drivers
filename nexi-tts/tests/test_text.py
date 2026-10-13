from __future__ import annotations

import unittest

from nexi_tts.text import CHUNK_CHARS, MAX_TEXT_CHARS, TOKEN_IDS, chunk_text, normalize, tokenize


class TextTests(unittest.TestCase):
    def test_empty_and_controls_rejected(self) -> None:
        for text in ("", "  \n\t ", "hello\x00world", "hello\x1bworld"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                normalize(text)

    def test_text_limit(self) -> None:
        with self.assertRaises(ValueError):
            normalize("a" * (MAX_TEXT_CHARS + 1))

    def test_normalization(self) -> None:
        self.assertEqual(normalize("  “Hello”\nthere’s  42. "), '"Hello" there\'s forty-two.')
        self.assertEqual(normalize("123.5"), "one hundred and twenty-three point five")
        self.assertEqual(normalize("1,000"), "one thousand")
        self.assertEqual(normalize("1,2,3"), "one,two,three")

    def test_large_numbers_rejected(self) -> None:
        with self.assertRaises(ValueError):
            normalize("1234567890123456")

    def test_currency_and_pluralization(self) -> None:
        cases = {
            "$1.01": "one dollar and one cent",
            "$1,234.50": "one thousand, two hundred and thirty-four dollars and fifty cents",
            "£2.01": "two pounds and one penny",
            "€0.50": "zero euros and fifty cents",
            "-$5.00": "minus five dollars",
            "+$2": "plus two dollars",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(normalize(text), expected)
        with self.assertRaises(ValueError):
            normalize("$1.999")

    def test_ordinals_percent_units_and_decimal_digits(self) -> None:
        cases = {
            "1st, 2nd, 3rd, 11th, 21st": "first, second, third, eleventh, twenty-first",
            "-3.04, +1.20": "minus three point zero four, plus one point two zero",
            "12.5%": "twelve point five percent",
            "1kg and 2.5 kg": "one kilogram and two point five kilograms",
            "24kHz, 2 GB": "twenty-four kilohertz, two gigabytes",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(normalize(text), expected)

    def test_versions_and_addresses_are_not_partially_expanded(self) -> None:
        for text in ("v2.0", "1.2.3", "192.168.1.1", "B2B", "abc123", "1Mb"):
            with self.subTest(text=text):
                self.assertEqual(normalize(text), text)

    def test_titles_do_not_create_sentence_breaks(self) -> None:
        self.assertEqual(
            chunk_text(normalize("Dr. Smith met Mr. Jones.")),
            ["Doctor Smith met Mister Jones."],
        )

    def test_expansion_is_bounded(self) -> None:
        with self.assertRaisesRegex(ValueError, "Expanded"):
            normalize("999 " * 4000)

    def test_first_chunk_is_short_without_losing_words(self) -> None:
        text = " ".join(["hello"] * 50)
        chunks = chunk_text(text, first_chunk_chars=80)
        self.assertLessEqual(len(chunks[0]), 80)
        self.assertTrue(any(len(chunk) > 80 for chunk in chunks[1:]))
        self.assertEqual(" ".join(chunk.rstrip(",") for chunk in chunks), text)
        for limit in (1, 181):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                chunk_text(text, first_chunk_chars=limit)

    def test_punctuation_preserved(self) -> None:
        self.assertEqual(chunk_text("Hello! What? Yes."), ["Hello!", "What?", "Yes."])

    def test_chunks_bounded_including_added_punctuation(self) -> None:
        for text in ("a" * 1000, "hello world " * 100, "hello"):
            chunks = chunk_text(text)
            self.assertTrue(chunks)
            self.assertTrue(all(0 < len(c) <= CHUNK_CHARS for c in chunks))
            self.assertTrue(all(c[-1] in ".!?,;:" for c in chunks))

    def test_chunk_parameter_validation(self) -> None:
        with self.assertRaises(ValueError):
            chunk_text("hello", limit=1)
        self.assertEqual(chunk_text(""), [])

    def test_token_contract(self) -> None:
        self.assertEqual(tokenize("hi"), [0, TOKEN_IDS["h"], TOKEN_IDS["i"], 0])
        self.assertEqual(
            tokenize("hˈi"),
            [0, TOKEN_IDS["h"], TOKEN_IDS["ˈ"], TOKEN_IDS["i"], 0],
        )

    def test_unsupported_and_overlong_tokens_rejected(self) -> None:
        for phonemes in ("", "☃", "x" * 1000):
            with self.subTest(phonemes=phonemes), self.assertRaises(ValueError):
                tokenize(phonemes)
