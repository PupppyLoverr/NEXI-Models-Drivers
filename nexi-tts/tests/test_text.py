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
