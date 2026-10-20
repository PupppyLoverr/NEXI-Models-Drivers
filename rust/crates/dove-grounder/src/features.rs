//! Feature extraction (`nexi_cua/policy/features.py`): hashed character
//! trigrams plus word unigrams, L2 normalised, and the per-element numeric
//! block. Kept sparse here; the model's first layer is applied to the
//! non-zero buckets only, which is the same linear map.

use crate::pystr;
use crate::types::Element;
use blake2::digest::{Update, VariableOutput};
use blake2::Blake2bVar;
use regex::Regex;
use std::collections::HashSet;
use std::sync::LazyLock;

pub const TEXT_DIM: usize = 12288;
const WORD_BUCKETS: usize = 1024;
pub const NUMERIC_DIM: usize = 14;

pub const ROLE_VOCAB: [&str; 56] = [
    "button",
    "link",
    "textfield",
    "securetextfield",
    "searchfield",
    "textarea",
    "combobox",
    "popupbutton",
    "select",
    "checkbox",
    "radio",
    "switch",
    "toggle",
    "menuitem",
    "menu",
    "menubar",
    "tab",
    "tabgroup",
    "list",
    "listitem",
    "option",
    "table",
    "tree",
    "row",
    "cell",
    "treeitem",
    "slider",
    "stepper",
    "scrollarea",
    "webarea",
    "statictext",
    "heading",
    "image",
    "group",
    "toolbar",
    "dialog",
    "sheet",
    "progress",
    "scrollbar",
    "disclosure",
    "segmented",
    "radiogroup",
    "grid",
    "colorwell",
    "level",
    "value",
    "handle",
    "popover",
    "column",
    "menubutton",
    "window",
    "application",
    "busy",
    "splitter",
    "separator",
    "unknown",
];

/// `role_index`: position in ROLE_VOCAB, "unknown" otherwise.
pub fn role_index(role: &str) -> i64 {
    let role = pystr::lower(role);
    let position = ROLE_VOCAB
        .iter()
        .position(|r| *r == role)
        .unwrap_or(ROLE_VOCAB.len() - 1);
    position as i64
}

fn blake2b_u32(data: &[u8]) -> u32 {
    let mut hasher = Blake2bVar::new(4).expect("4-byte digest");
    hasher.update(data);
    let mut out = [0u8; 4];
    hasher.finalize_variable(&mut out).expect("4-byte digest");
    u32::from_le_bytes(out)
}

/// A sparse, L2-normalised text feature vector: sorted `(bucket, value)`.
pub type SparseText = Vec<(u32, f32)>;

/// `text_features(text)`, sparse.
pub fn text_features(text: &str) -> SparseText {
    if text.is_empty() {
        return Vec::new();
    }
    let mut counts: std::collections::BTreeMap<u32, f32> = Default::default();
    let tl = pystr::strip(&pystr::lower(text)).to_owned();
    // _ngrams lowers and strips again before adding the ^ $ markers.
    let marked: Vec<char> = format!("^{}$", pystr::strip(&pystr::lower(&tl)))
        .chars()
        .collect();
    let trigram_buckets = (TEXT_DIM - WORD_BUCKETS) as u32;
    let mut buf = String::new();
    for window in marked.windows(3) {
        buf.clear();
        buf.extend(window);
        let bucket = blake2b_u32(buf.as_bytes()) % trigram_buckets;
        *counts.entry(bucket).or_default() += 1.0;
    }
    for word in pystr::split(&tl).take(64) {
        let h = blake2b_u32(format!("w:{word}").as_bytes());
        let bucket = trigram_buckets + h % WORD_BUCKETS as u32;
        *counts.entry(bucket).or_default() += 1.0;
    }
    // Counts are small integers, so the f32 sum of squares is exact and the
    // norm and quotients round exactly as torch's do.
    let norm = counts.values().map(|c| c * c).sum::<f32>().sqrt();
    if norm > 0.0 {
        counts.into_iter().map(|(k, c)| (k, c / norm)).collect()
    } else {
        counts.into_iter().collect()
    }
}

const FEATURE_STOP: [&str; 16] = [
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "it", "is", "my", "your", "this",
    "that",
];

static ALNUM: LazyLock<Regex> = LazyLock::new(|| Regex::new("[a-z0-9]+").unwrap());

/// Lowercased `[a-z0-9]+` words of `text`.
pub fn ascii_words(text: &str) -> impl Iterator<Item = String> {
    let lowered = pystr::lower(text);
    ALNUM
        .find_iter(&lowered)
        .map(|m| m.as_str().to_owned())
        .collect::<Vec<_>>()
        .into_iter()
}

fn wordset(text: &str) -> HashSet<String> {
    ascii_words(text)
        .filter(|w| !FEATURE_STOP.contains(&w.as_str()))
        .collect()
}

/// Ordinal position among same-role named elements in reading order, 0..1.
fn role_rank(el: &Element, elements: &[Element]) -> f64 {
    let mut sibs: Vec<&Element> = elements
        .iter()
        .filter(|e| e.role == el.role && !e.name.is_empty())
        .collect();
    sort_by_reading(&mut sibs);
    if sibs.len() <= 1 {
        return 0.0;
    }
    let last = (sibs.len() - 1) as f64;
    // `sibs.index(el)` compares dataclasses by value; the fallback compares ids.
    if let Some(i) = sibs.iter().position(|e| *e == el) {
        return i as f64 / last;
    }
    if let Some(i) = sibs.iter().position(|e| e.id == el.id) {
        return i as f64 / last;
    }
    0.0
}

/// Stable sort by `(y, x)`.
pub fn sort_by_reading(els: &mut [&Element]) {
    els.sort_by(|a, b| cmp_key(a.reading_key(), b.reading_key()));
}

pub fn cmp_key(a: (f64, f64), b: (f64, f64)) -> std::cmp::Ordering {
    a.partial_cmp(&b).unwrap_or(std::cmp::Ordering::Equal)
}

/// `element_numeric(el, screen_w, screen_h, goal, elements)`.
pub fn element_numeric(
    el: &Element,
    screen_w: i64,
    screen_h: i64,
    goal: &str,
    elements: &[Element],
) -> [f32; NUMERIC_DIM] {
    let sw = if screen_w != 0 {
        screen_w as f64
    } else {
        1600.0
    };
    let sh = if screen_h != 0 {
        screen_h as f64
    } else {
        1200.0
    };
    let (nx, ny, nw, nh) = match &el.bounds {
        Some(b) => (b.x / sw, b.y / sh, b.w / sw, b.h / sh),
        None => (0.0, 0.0, 0.0, 0.0),
    };
    let name_w = wordset(&el.name);
    let goal_w = wordset(goal);
    let common = name_w.intersection(&goal_w).count() as f64;
    let name_in_goal = if name_w.is_empty() {
        0.0
    } else {
        common / name_w.len() as f64
    };
    let goal_in_name = if goal_w.is_empty() {
        0.0
    } else {
        common / goal_w.len() as f64
    };
    let checked = match el.checked {
        None => -1.0,
        Some(true) => 1.0,
        Some(false) => 0.0,
    };
    let flag = |b: bool| if b { 1.0 } else { 0.0 };
    let feats: [f64; NUMERIC_DIM] = [
        nx,
        ny,
        nw,
        nh,
        el.depth.min(12) as f64 / 12.0,
        flag(el.focused),
        (el.children_count as f64).ln_1p().min(5.0) / 5.0,
        flag(!el.name.is_empty()),
        flag(!el.value.is_empty()),
        flag(el.enabled),
        checked,
        name_in_goal,
        goal_in_name,
        if elements.is_empty() {
            0.0
        } else {
            role_rank(el, elements)
        },
    ];
    feats.map(|f| f as f32)
}

/// `element_text(el)`: role, name, the first 60 characters of the value and
/// the DOM tag, joined by spaces.
pub fn element_text(el: &Element) -> String {
    let mut parts: Vec<String> = vec![el.role.clone(), el.name.clone()];
    if !el.value.is_empty() {
        parts.push(pystr::prefix(&el.value, 60).to_owned());
    }
    if let Some(tag) = el.extra.get("tag").filter(|t| crate::types::truthy(t)) {
        parts.push(match tag {
            serde_json::Value::String(s) => s.clone(),
            other => other.to_string(),
        });
    }
    parts
        .into_iter()
        .filter(|p| !p.is_empty())
        .collect::<Vec<_>>()
        .join(" ")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn features_are_normalised() {
        let v = text_features("Save");
        let norm: f32 = v.iter().map(|(_, x)| x * x).sum();
        assert!((norm - 1.0).abs() < 1e-6);
        // ^sa sav ave ve$ + one word
        assert_eq!(v.len(), 5);
        assert!(text_features("").is_empty());
    }
}
