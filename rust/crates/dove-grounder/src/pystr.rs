//! Python `str` and `re` semantics the port has to reproduce exactly.
//!
//! nexi-cua's hashing, word sets and regexes run on Python strings, so the
//! decisions depend on Python's notion of whitespace (`str.isspace`, which
//! also counts U+001C..U+001F), `str.lower`, `str.strip`, `str.split()`, and
//! on `re` details: `$` also matches before a final newline, and `\s`/`\w`
//! follow `str.isspace`/`str.isalnum`.

use regex::Regex;

/// `str.isspace()` for one character.
pub fn is_space(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}

/// `str.strip()`.
pub fn strip(s: &str) -> &str {
    s.trim_matches(is_space)
}

/// `str.lower()`.
pub fn lower(s: &str) -> String {
    s.to_lowercase()
}

/// `str.split()` with no separator.
pub fn split(s: &str) -> impl Iterator<Item = &str> {
    s.split(is_space).filter(|part| !part.is_empty())
}

/// The first `n` code points (`s[:n]`).
pub fn prefix(s: &str, n: usize) -> &str {
    match s.char_indices().nth(n) {
        Some((at, _)) => &s[..at],
        None => s,
    }
}

/// `len(s)` in code points.
pub fn len(s: &str) -> usize {
    s.chars().count()
}

/// `str.casefold()` equality.
pub fn casefold_eq(a: &str, b: &str) -> bool {
    unicase::UniCase::unicode(a) == unicase::UniCase::unicode(b)
}

/// Compile a Python `re` pattern (str pattern, no MULTILINE/DOTALL) with the
/// same matching behaviour: `\s`, `\S` and `\w` use Python's classes and `$`
/// also matches before a trailing newline. `ignore_case` is `re.I`.
pub fn py_regex(pattern: &str, ignore_case: bool) -> Regex {
    let translated = translate(pattern);
    let full = if ignore_case {
        format!("(?i){translated}")
    } else {
        translated
    };
    Regex::new(&full).unwrap_or_else(|error| panic!("bad pattern {pattern:?}: {error}"))
}

/// `re.match`: anchored at the start.
pub fn py_regex_match(pattern: &str, ignore_case: bool) -> Regex {
    py_regex(&format!(r"\A(?:{pattern})"), ignore_case)
}

/// `re.fullmatch`: anchored at both ends.
pub fn py_regex_full(pattern: &str, ignore_case: bool) -> Regex {
    py_regex(&format!(r"\A(?:{pattern})\z"), ignore_case)
}

const SPACE_CLASS: &str = r"\s\x{1C}-\x{1F}";
const WORD_CLASS: &str = r"\p{L}\p{N}_";

fn translate(pattern: &str) -> String {
    let mut out = String::with_capacity(pattern.len() + 16);
    let mut in_class = false;
    let mut chars = pattern.chars().peekable();
    while let Some(c) = chars.next() {
        match c {
            '\\' => {
                let Some(next) = chars.next() else {
                    out.push('\\');
                    break;
                };
                match (next, in_class) {
                    ('s', false) => out.push_str(&format!("[{SPACE_CLASS}]")),
                    ('s', true) => out.push_str(SPACE_CLASS),
                    ('S', false) => out.push_str(&format!("[^{SPACE_CLASS}]")),
                    ('w', false) => out.push_str(&format!("[{WORD_CLASS}]")),
                    ('w', true) => out.push_str(WORD_CLASS),
                    ('S', true) => panic!("\\S inside a class is not translated"),
                    _ => {
                        out.push('\\');
                        out.push(next);
                    }
                }
            }
            '[' if !in_class => {
                in_class = true;
                out.push('[');
                // A leading `^` or `]` belongs to the class.
                if chars.peek() == Some(&'^') {
                    out.push(chars.next().unwrap());
                }
                if chars.peek() == Some(&']') {
                    out.push_str(r"\]");
                    chars.next();
                }
            }
            ']' if in_class => {
                in_class = false;
                out.push(']');
            }
            '[' if in_class => out.push_str(r"\["),
            '$' if !in_class => out.push_str(r"(?:\n?\z)"),
            _ => out.push(c),
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn python_whitespace_and_dollar() {
        assert_eq!(strip("\u{1c} a b \n"), "a b");
        assert_eq!(split(" a\u{1f}b  c ").collect::<Vec<_>>(), ["a", "b", "c"]);
        let re = py_regex(r"(.+)$", false);
        assert_eq!(&re.captures("abc\n").unwrap()[1], "abc");
        assert!(py_regex(r"a\sb", false).is_match("a\u{1d}b"));
        assert!(py_regex(r"[\w .-]+", false).is_match("é"));
        assert!(casefold_eq("STRASSE", "straße"));
        assert_eq!(prefix("héllo", 2), "hé");
    }
}
