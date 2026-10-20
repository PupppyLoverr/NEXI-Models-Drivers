//! Deterministic semantic resolver (`nexi_cua/policy/resolver.py`): the
//! first decision stage. It fires only when the goal itself names its action
//! unambiguously (the full accessible name, an ordinal, a key chord or a
//! session command) and otherwise defers to the ranker.

use crate::actions::{self, any_actionable, has, CHECKABLE_ROLES, CLICKABLE_ROLES, DCLICK_ROLES,
    SCROLLABLE_ROLES, SELECT_ROLES, TEXT_ROLES};
use crate::features::{ascii_words, cmp_key, sort_by_reading};
use crate::infer;
use crate::pystr::{self, py_regex, py_regex_full, py_regex_match};
use crate::types::{Action, Element, Observation, Verb};
use regex::Regex;
use std::cmp::Ordering;
use std::collections::HashSet;
use std::sync::LazyLock;

const STOP: &[&str] = &[
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does", "for", "go", "i", "in",
    "into", "is", "it", "its", "me", "my", "of", "on", "or", "our", "please", "that", "the",
    "their", "then", "this", "to", "us", "was", "we", "with", "you", "your",
];

const VERB_WORDS: &[&str] = &[
    "activate", "check", "choose", "click", "close", "collapse", "disable", "double", "drag",
    "enable", "enter", "expand", "fill", "follow", "hit", "input", "mark", "open", "pick", "press",
    "right", "scroll", "search", "select", "submit", "switch", "tap", "toggle", "type", "uncheck",
    "visit", "write",
];

const ORDINAL_WORDS: [(&str, i64); 10] = [
    ("1st", 0),
    ("first", 0),
    ("2nd", 1),
    ("second", 1),
    ("3rd", 2),
    ("third", 2),
    ("4th", 3),
    ("fourth", 3),
    ("5th", 4),
    ("fifth", 4),
];

const BUTTONS: &[&str] = &["button", "imagebutton", "menubutton", "popupbutton"];
const RESULTS: &[&str] = &["listitem", "link", "row", "cell", "option"];

/// `_ROLE_ALIAS`, in its dict order. An empty set means "do not restrict".
const ROLE_ALIAS: &[(&str, &[&str])] = &[
    ("link", &["link"]),
    ("links", &["link"]),
    ("button", BUTTONS),
    ("buttons", BUTTONS),
    ("pane", &["tab", "tabitem"]),
    ("field", TEXT_ROLES),
    ("input", TEXT_ROLES),
    ("box", TEXT_ROLES),
    ("text", TEXT_ROLES),
    ("area", TEXT_ROLES),
    ("entry", TEXT_ROLES),
    ("checkbox", &["checkbox"]),
    ("check", &["checkbox"]),
    ("radio", &["radio"]),
    ("switch", &["switch", "toggle"]),
    ("toggle", &["switch", "toggle"]),
    ("option", &["option"]),
    ("item", &["listitem", "treeitem", "menuitem"]),
    ("row", &["row", "treeitem"]),
    ("cell", &["cell"]),
    ("image", &["image", "imagebutton"]),
    ("icon", &["image", "imagebutton"]),
    ("menu", &["menuitem", "menubutton", "menu"]),
    ("menuitem", &["menuitem"]),
    ("heading", &["heading"]),
    ("title", &["heading"]),
    ("select", SELECT_ROLES),
    ("dropdown", SELECT_ROLES),
    ("combobox", SELECT_ROLES),
    ("list", &["list", "listitem"]),
    ("slider", &["slider"]),
    ("widget", &[]),
    ("control", &[]),
    ("element", &[]),
    ("result", RESULTS),
    ("results", RESULTS),
];

fn alias(word: &str) -> Option<&'static [&'static str]> {
    ROLE_ALIAS.iter().find(|(w, _)| *w == word).map(|(_, set)| *set)
}

/// `_words`: lowercased `[a-z0-9]+` words minus the stop list.
pub fn words(text: &str) -> HashSet<String> {
    ascii_words(text)
        .filter(|w| !STOP.contains(&w.as_str()))
        .collect()
}

/// `_words` in first-appearance order, for the one place set order matters.
fn ordered_words(text: &str) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    for w in ascii_words(text) {
        if !STOP.contains(&w.as_str()) && !out.contains(&w) {
            out.push(w);
        }
    }
    out
}

fn subset(a: &HashSet<String>, b: &HashSet<String>) -> bool {
    a.iter().all(|w| b.contains(w))
}

struct VerbRe(Regex, Verb);

static ELEMENT_VERB_RES: LazyLock<Vec<VerbRe>> = LazyLock::new(|| {
    let r = |p: &str, v| VerbRe(py_regex(p, false), v);
    vec![
        r(r"\b(?:double[ -]?click|two[ -]?click)\w*", Verb::DoubleClick),
        r(
            r"\b(?:right[ -]?click|secondary[ -]?click|context[ -]?click)\b",
            Verb::RightClick,
        ),
        r(r"\b(?:type|enter|write|fill|search\s+for|look\s+for)\b", Verb::Type),
        r(r"\b(?:drag|move)\b.*\b(?:onto|to|into|over)\b", Verb::Drag),
        r(
            r"\bfocus(?:\s+(?:on|onto|the))?\b|\bput\s+(?:the\s+)?cursor\s+(?:in|into|on)\b",
            Verb::Focus,
        ),
        r(r"\b(?:select|choose|pick)\b", Verb::Select),
        r(r"\b(?:check|mark|tick|uncheck|unmark)\b", Verb::Check),
        r(
            r"\b(?:click|press|tap|follow|open|hit|activate|expand|collapse|visit|enable|disable|toggle|turn\s+(?:on|off)|switch\s+(?:on|off))\b",
            Verb::Click,
        ),
    ]
});

fn intent(goal: &str) -> Option<Verb> {
    ELEMENT_VERB_RES
        .iter()
        .find(|VerbRe(re, _)| re.is_match(goal))
        .map(|VerbRe(_, v)| *v)
}

/// `_role_restriction`: the role set named by the goal's longest role word.
///
/// Python sorts `(len(word), alias_set)` pairs in reverse, so between two
/// role words of the same length a superset wins and otherwise the outcome
/// follows the iteration order of a `set` of strings, which Python
/// randomises per process. This port takes words in their order in the
/// goal: one of the outcomes Python can produce.
fn role_restriction(goal: &str) -> Option<&'static [&'static str]> {
    let mut hits: Vec<(usize, &'static [&'static str])> = Vec::new();
    for w in ordered_words(goal) {
        if let Some(set) = alias(&w).filter(|set| !set.is_empty()) {
            hits.push((w.len(), set));
        }
    }
    let longest = hits.iter().map(|(n, _)| *n).max()?;
    let tied: Vec<&'static [&'static str]> = hits
        .iter()
        .filter(|(n, _)| *n == longest)
        .map(|(_, s)| *s)
        .collect();
    let is_subset = |a: &[&str], b: &[&str]| a.iter().all(|r| b.contains(r));
    // A set no tied set strictly contains, first in goal order.
    tied.iter()
        .copied()
        .find(|a| {
            !tied
                .iter()
                .any(|b| is_subset(a, b) && !is_subset(b, a))
        })
        .or_else(|| tied.first().copied())
}

static ORDINAL_RE: LazyLock<Regex> = LazyLock::new(|| {
    let ord = r"1st|first|2nd|second|3rd|third|4th|fourth|5th|fifth|last|\d+(?:st|nd|rd|th)";
    // sorted(_ROLE_ALIAS, key=len, reverse=True): stable, so dict order breaks ties.
    let mut names: Vec<&str> = ROLE_ALIAS.iter().map(|(w, _)| *w).collect();
    names.sort_by_key(|w| std::cmp::Reverse(w.len()));
    py_regex(
        &format!(r"\b({ord})\s+(?:[a-z0-9]+\s+){{0,2}}({})\b", names.join("|")),
        false,
    )
});
static NUM_ORD_RE: LazyLock<Regex> = LazyLock::new(|| py_regex(r"^\d+(?:st|nd|rd|th)$", false));

/// `_ordinal_index`: an ordinal only when a role word follows within ~3 words.
fn ordinal_index(goal: &str, els: &[&Element]) -> Option<i64> {
    let m = ORDINAL_RE.captures(goal)?;
    let (g1, g2) = (m.get(1).unwrap(), m.get(2).unwrap());
    let ordinal_phrase = pystr::lower(pystr::strip(&goal[g1.start()..g2.start()]));
    if pystr::split(&ordinal_phrase).count() > 1
        && els
            .iter()
            .any(|el| pystr::lower(&el.name).contains(&ordinal_phrase))
    {
        return None;
    }
    let w = g1.as_str();
    if w == "last" {
        return Some(-1);
    }
    if let Some((_, i)) = ORDINAL_WORDS.iter().find(|(word, _)| *word == w) {
        return Some(*i);
    }
    if NUM_ORD_RE.is_match(w) {
        let digits = &w[..w.len() - 2];
        // Python's int() also reads non-ASCII digits; an overflow here is an
        // index past any pool, which Python also resolves to no target.
        return digits.parse::<i64>().ok().map(|n| n - 1);
    }
    None
}

fn score_key(el: &Element, nw_len: usize) -> (usize, f64, f64) {
    let (y, x) = el.reading_key();
    (nw_len, -y, -x)
}

/// `_best_named`: the element whose whole name word set is inside the goal;
/// the longest name wins, reading order breaks ties.
fn best_named<'a>(pool: &[&'a Element], goal_words: &HashSet<String>) -> Option<&'a Element> {
    let mut best: Option<(&Element, (usize, f64, f64))> = None;
    for el in pool {
        let nw = words(&el.name);
        if nw.is_empty() || !subset(&nw, goal_words) {
            continue;
        }
        let score = score_key(el, nw.len());
        let better = match &best {
            None => true,
            Some((_, b)) => score.partial_cmp(b) == Some(Ordering::Greater),
        };
        if better {
            best = Some((el, score));
        }
    }
    best.map(|(el, _)| el)
}

fn ordinal_target<'a>(pool: &[&'a Element], idx: i64) -> Option<&'a Element> {
    let mut ordered: Vec<&Element> = pool.iter().copied().filter(|e| !e.name.is_empty()).collect();
    if ordered.is_empty() {
        return None;
    }
    sort_by_reading(&mut ordered);
    let i = if idx >= 0 { idx } else { ordered.len() as i64 - 1 };
    if 0 <= i && (i as usize) < ordered.len() {
        Some(ordered[i as usize])
    } else {
        None
    }
}

const PURE_DONE: &[&str] = &[
    "done", "finish", "finished", "complete", "completed", "task", "up", "all", "set", "nothing",
    "else", "wrap", "are", "now", "im", "the", "is", "it", "this", "that", "you", "your", "we", "i",
    "am",
];
const DONE_MARKERS: &[&str] = &["done", "finish", "finished", "complete", "completed", "wrap"];
const PURE_WAIT: &[&str] = &[
    "wait", "pause", "hold", "on", "briefly", "moment", "second", "bit", "a", "the", "for",
    "please",
];
const WAIT_MARKERS: &[&str] = &["wait", "pause", "hold"];

static TAB_RE: LazyLock<Regex> = LazyLock::new(|| {
    py_regex(
        r"\b(?:switch\s+(?:to\s+)?|go\s+to\s+|open\s+|bring\s+up\s+)(?:the\s+)?(.+?)\s+tab\b|\btab\s+([a-z0-9][\w .-]*)$",
        false,
    )
});

fn tab_action(obs: &Observation, goal_l: &str) -> Option<Action> {
    let browser = obs.browser.as_ref()?;
    if browser.tabs.is_empty() {
        return None;
    }
    let m = TAB_RE.captures(goal_l)?;
    let phrase = m
        .get(1)
        .or_else(|| m.get(2))
        .map(|g| g.as_str())
        .unwrap_or("");
    let want = words(phrase);
    if want.is_empty() {
        return None;
    }
    for tab in &browser.tabs {
        let tw = words(&tab.title);
        if !tw.is_empty() && (subset(&tw, &want) || subset(&want, &tw)) {
            return Some(Action {
                tab: tab.id.clone(),
                element_name: tab.title.clone(),
                ..Action::new(Verb::SwitchTab)
            });
        }
    }
    None
}

static DRAG_RE: LazyLock<Regex> = LazyLock::new(|| {
    py_regex(
        r"(?:drag|move|reorder)\s+(?:the\s+)?(.+?)\s+(?:onto|into|to|over|before|after|on)\s+(?:the\s+)?(.+)$",
        false,
    )
});

fn drag_pair(els: &[&Element], goal_l: &str) -> Option<Action> {
    let m = DRAG_RE.captures(goal_l)?;
    let (sw, dw) = (words(&m[1]), words(&m[2]));
    let mut src: Option<&Element> = None;
    let mut dst: Option<&Element> = None;
    for el in els {
        let nw = words(&el.name);
        if !nw.is_empty()
            && subset(&nw, &sw)
            && src.is_none_or(|s| nw.len() > words(&s.name).len())
        {
            src = Some(el);
        }
        if !nw.is_empty()
            && subset(&nw, &dw)
            && dst.is_none_or(|d| nw.len() > words(&d.name).len())
        {
            dst = Some(el);
        }
    }
    let (src, dst) = (src?, dst?);
    if src.id == dst.id {
        return None;
    }
    Some(Action::on(Verb::Drag, src).with_text(dst.id.clone()))
}

fn keys(list: &[&str]) -> Vec<String> {
    list.iter().map(|k| (*k).to_owned()).collect()
}

static SHORTCUT_RES: LazyLock<Vec<(Regex, Vec<String>)>> = LazyLock::new(|| {
    let r = |p: &str, k: &[&str]| (py_regex(p, false), keys(k));
    vec![
        r(r"^(?:please\s+)?undo\s+(?:the\s+)?last\s+action(?:\s+now)?$", &["cmd", "z"]),
        r(r"^(?:please\s+)?copy\s+(?:the\s+)?selection(?:\s+now)?$", &["cmd", "c"]),
        r(r"^(?:please\s+)?paste\s+(?:the\s+)?clipboard(?:\s+now)?$", &["cmd", "v"]),
        r(r"^(?:please\s+)?select\s+all(?:\s+text)?(?:\s+now)?$", &["cmd", "a"]),
        r(r"^(?:please\s+)?open\s+spotlight(?:\s+search)?(?:\s+now)?$", &["cmd", "space"]),
        r(r"^(?:please\s+)?quit\s+(?:the\s+)?app(?:\s+now)?$", &["cmd", "q"]),
        r(r"^(?:please\s+)?find\s+on\s+page(?:\s+now)?$", &["cmd", "f"]),
        r(r"^(?:please\s+)?save\s+with\s+keyboard(?:\s+now)?$", &["cmd", "s"]),
        r(r"^(?:please\s+)?print(?:\s+now)?$", &["cmd", "p"]),
        r(r"^(?:please\s+)?page\s+down(?:\s+now)?$", &["pagedown"]),
        r(r"^(?:please\s+)?page\s+up(?:\s+now)?$", &["pageup"]),
        r(r"^(?:please\s+)?scroll\s+to\s+top(?:\s+now)?$", &["home"]),
        r(r"^(?:please\s+)?scroll\s+to\s+bottom(?:\s+now)?$", &["end"]),
    ]
});
static SESSION_SHORTCUT_RES: LazyLock<Vec<(Regex, Vec<String>)>> = LazyLock::new(|| {
    let r = |p: &str, k: &[&str]| (py_regex(p, false), keys(k));
    vec![
        r(r"^(?:please\s+)?new\s+tab(?:\s+now)?$", &["cmd", "t"]),
        r(r"^(?:please\s+)?close\s+(?:(?:the|this|current)\s+)?tab(?:\s+now)?$", &["cmd", "w"]),
        r(r"^(?:please\s+)?(?:go\s+)?back(?:\s+now)?$", &["alt", "left"]),
    ]
});
static SCROLLING_PAGE_RE: LazyLock<Regex> =
    LazyLock::new(|| py_regex(r"\bscroll\s+(?:(?:the\s+)?(?:page|list)\s+)?(?:up|down)\b", false));

/// `shortcut_keys(goal_l, obs)`; `in_browser` is `obs.browser is not None`.
pub fn shortcut_keys(goal_l: &str, in_browser: bool) -> Option<Vec<String>> {
    let scrolling_page = SCROLLING_PAGE_RE.is_match(goal_l);
    for (re, k) in SHORTCUT_RES.iter() {
        if scrolling_page && (k == &["pageup"] || k == &["pagedown"]) {
            continue;
        }
        if re.is_match(goal_l) {
            return Some(k.clone());
        }
    }
    if !in_browser {
        for (re, k) in SESSION_SHORTCUT_RES.iter() {
            if re.is_match(goal_l) {
                return Some(k.clone());
            }
        }
    }
    None
}

static CHORD_RE: LazyLock<Regex> = LazyLock::new(|| {
    py_regex(r"\b(?:press|hit)\s+(?:the\s+)?([\w +]+?)\s*(?:keys?|arrow keys?)?$", false)
});
static PLUS_RE: LazyLock<Regex> = LazyLock::new(|| py_regex(r"\s*\+\s*", false));
static FKEY_RE: LazyLock<Regex> = LazyLock::new(|| py_regex_full(r"f\d{1,2}", false));
static NEW_TAB_FULL: LazyLock<Regex> =
    LazyLock::new(|| py_regex_full(r"(?:please\s+)?(?:open\s+)?(?:a\s+)?new\s+tab", false));
static CLOSE_TAB_FULL: LazyLock<Regex> = LazyLock::new(|| {
    py_regex_full(r"(?:please\s+)?close\s+(?:(?:the|this|current)\s+)?tab", false)
});
static BACK_FULL: LazyLock<Regex> = LazyLock::new(|| {
    py_regex_full(
        r"(?:please\s+)?(?:go\s+)?back|(?:please\s+)?(?:previous page|navigate back)",
        false,
    )
});
static QUOTES_RE: LazyLock<Regex> =
    LazyLock::new(|| py_regex("\"[^\"]*\"|“[^”]*”|'[^']*'", false));
static CLICK_INTO_RE: LazyLock<Regex> = LazyLock::new(|| py_regex(r"\bclick (?:in)?to\b", false));
static SEMANTIC_RE: LazyLock<Regex> = LazyLock::new(|| {
    py_regex_match(r"^(?:please\s+)?(save|confirm|cancel|send|open|delete|undo)\b", false)
});
static SCROLL_RE: LazyLock<Regex> = LazyLock::new(|| {
    py_regex(r"\bscroll\s+(?:(?:the\s+)?(?:page|list)\s+)?(up|down|left|right)\b", false)
});
static PAGE_RE: LazyLock<Regex> = LazyLock::new(|| {
    py_regex(r"\b(?:scroll(?:\s+(?:the\s+)?(?:page|list))?|page|go)\s+(up|down)\b", false)
});
static NEW_TAB_RE: LazyLock<Regex> = LazyLock::new(|| py_regex(r"\bnew tab\b", false));
static CLOSE_TAB_RE: LazyLock<Regex> =
    LazyLock::new(|| py_regex(r"\bclose (?:the |this |current )?tab\b", false));
static BACK_RE: LazyLock<Regex> = LazyLock::new(|| py_regex(r"\b(?:go )?back\b", false));
static FORWARD_RE: LazyLock<Regex> =
    LazyLock::new(|| py_regex(r"\b(?:go )?forward\b|\bnext page\b", false));
static REFRESH_RE: LazyLock<Regex> = LazyLock::new(|| py_regex(r"\b(?:refresh|reload)\b", false));

const SAVE_NAMES: &[&str] = &[
    "Save", "Save…", "Save Document", "Save File", "Done", "Apply", "Keep", "Save As…",
    "Save Changes", "✓ Save",
];
const CANCEL_NAMES: &[&str] = &[
    "Cancel", "Close", "Dismiss", "No", "Don't Save", "Discard", "Not Now", "Later", "Skip", "Back",
];
const OK_NAMES: &[&str] = &[
    "OK", "Confirm", "Yes", "Continue", "Accept", "Allow", "Agree", "Next", "Proceed", "Got It",
    "I Understand",
];
const OPEN_NAMES: &[&str] = &[
    "Open…", "Open File", "Browse…", "Choose File", "Import…", "Upload", "Attach", "Select File",
    "Add Files",
];
const SEND_NAMES: &[&str] = &[
    "Send", "Submit", "Post", "Share", "Publish", "Reply", "Send Message", "Submit Form",
];
const DELETE_NAMES: &[&str] = &[
    "Delete", "Remove", "Trash", "Move to Trash", "Erase", "Delete Permanently", "Remove Item",
];
const UNDO_NAMES: &[&str] = &["Undo", "Revert", "Restore", "Back", "Go Back"];

fn is_mod(k: &str) -> bool {
    matches!(
        k,
        "cmd" | "command" | "ctrl" | "control" | "alt" | "option" | "shift" | "fn" | "super"
    )
}

fn is_named_key(k: &str) -> bool {
    matches!(
        k,
        "enter" | "return" | "tab" | "space" | "escape" | "esc" | "backspace" | "delete" | "up"
            | "down" | "left" | "right" | "home" | "end" | "pageup" | "pagedown"
    )
}

/// The canonical spelling of a modifier.
pub fn canonical_key(k: &str) -> String {
    match k {
        "command" => "cmd",
        "option" => "alt",
        "control" => "ctrl",
        other => other,
    }
    .to_owned()
}

fn emit(el: &Element, verb: Verb, goal: &str, goal_l: &str) -> Action {
    let role = pystr::lower(&el.role);
    let role = role.as_str();
    let mut v = verb;
    if v == Verb::Check {
        v = if has(CHECKABLE_ROLES, role) { Verb::Check } else { Verb::Click };
    }
    if v == Verb::Select && !has(SELECT_ROLES, role) {
        v = Verb::Click;
    }
    if v == Verb::Click && CLICK_INTO_RE.is_match(goal_l) && (has(TEXT_ROLES, role) || el.editable()) {
        v = Verb::Focus;
    }
    if matches!(v, Verb::DoubleClick | Verb::RightClick)
        && !(has(CLICKABLE_ROLES, role) || has(DCLICK_ROLES, role) || has(CHECKABLE_ROLES, role))
    {
        v = Verb::Click;
    }
    match v {
        Verb::Focus => Action::on(Verb::Focus, el),
        Verb::Select => Action::on(Verb::Select, el).with_text(infer::goal_select_arg(goal, &el.name)),
        Verb::Type => Action::on(Verb::Type, el).with_text(infer::goal_text_arg(goal)),
        Verb::Drag => Action::on(Verb::Drag, el).with_text(actions::DST),
        v => Action::on(v, el),
    }
}

/// `resolve(obs, goal)`: the action the goal names unambiguously, or None
/// to defer to the ranker.
pub fn resolve(obs: &Observation, goal: &str) -> Option<Action> {
    let goal_l = pystr::lower(pystr::strip(goal));
    let goal_l = goal_l.as_str();
    if goal_l.is_empty() {
        return None;
    }
    let ws = words(goal_l);
    let els: Vec<&Element> = obs.elements.iter().filter(|e| e.enabled).collect();
    let in_browser = obs.browser.is_some();
    let in_set = |set: &[&str]| ws.iter().all(|w| set.contains(&w.as_str()));
    let meets = |set: &[&str]| ws.iter().any(|w| set.contains(&w.as_str()));

    // Pure completion / idle phrases.
    if !ws.is_empty() && in_set(PURE_DONE) && meets(DONE_MARKERS) {
        return Some(Action::new(Verb::Done));
    }
    if !ws.is_empty() && in_set(PURE_WAIT) && meets(WAIT_MARKERS) {
        return Some(Action {
            wait_ms: 1000,
            ..Action::new(Verb::Wait)
        });
    }

    // Explicit key chords.
    if let Some(m) = CHORD_RE.captures(goal_l) {
        let joined = PLUS_RE.replace_all(&m[1], "+");
        let raw: Vec<String> = joined
            .split('+')
            .map(pystr::strip)
            .filter(|k| !k.is_empty())
            .map(|k| match k {
                "left arrow" => "left",
                "right arrow" => "right",
                "up arrow" => "up",
                "down arrow" => "down",
                other => other,
            })
            .map(str::to_owned)
            .collect();
        if !raw.is_empty()
            && raw.iter().all(|k| {
                is_mod(k) || is_named_key(k) || pystr::len(k) == 1 || FKEY_RE.is_match(k)
            })
        {
            return Some(
                Action::new(Verb::Keypress).with_keys(raw.iter().map(|k| canonical_key(k)).collect()),
            );
        }
    }

    if let Some(k) = shortcut_keys(goal_l, in_browser) {
        return Some(Action::new(Verb::Keypress).with_keys(k));
    }

    if in_browser {
        if NEW_TAB_FULL.is_match(goal_l) {
            return Some(Action::new(Verb::NewTab));
        }
        if CLOSE_TAB_FULL.is_match(goal_l) {
            return Some(Action::new(Verb::CloseTab));
        }
        if BACK_FULL.is_match(goal_l) {
            return Some(Action::new(Verb::Back));
        }
    }

    // Browser-tab intents.
    if let Some(action) = tab_action(obs, goal_l) {
        return Some(action);
    }

    let mut intent_goal = QUOTES_RE.replace_all(goal_l, " ").into_owned();
    if let Some(named) = best_named(&els, &words(&intent_goal)) {
        if !named.name.is_empty() {
            let name_re = Regex::new(&format!("(?i){}", regex::escape(&named.name)))
                .expect("escaped literal");
            if let Some(last) = name_re.find_iter(&intent_goal).last() {
                intent_goal = format!(
                    "{} {}",
                    &intent_goal[..last.start()],
                    &intent_goal[last.end()..]
                );
            }
        }
    }
    if let Some(verb) = intent(&intent_goal) {
        if verb == Verb::Drag {
            if let Some(pair) = drag_pair(&els, goal_l) {
                return Some(pair);
            }
        }

        // Ordinal targets.
        let role_set = role_restriction(goal_l);
        let pool: Vec<&Element> = match role_set {
            None => els.iter().copied().filter(|e| !e.name.is_empty()).collect(),
            Some(set) => els
                .iter()
                .copied()
                .filter(|e| set.contains(&pystr::lower(&e.role).as_str()) && !e.name.is_empty())
                .collect(),
        };
        if let Some(idx) = ordinal_index(goal_l, &els) {
            if let Some(el) = ordinal_target(&pool, idx) {
                return Some(emit(el, verb, goal, goal_l));
            }
        }

        // Named element targets.
        let named_pool: Vec<&Element> = if verb == Verb::RightClick {
            els.iter()
                .copied()
                .filter(|e| !e.name.is_empty() && has(DCLICK_ROLES, &pystr::lower(&e.role)))
                .collect()
        } else if matches!(verb, Verb::Type | Verb::Focus) {
            els.iter()
                .copied()
                .filter(|e| has(TEXT_ROLES, &pystr::lower(&e.role)) || e.editable())
                .collect()
        } else if role_set.is_none() {
            els.iter()
                .copied()
                .filter(|e| !e.name.is_empty() && any_actionable(&pystr::lower(&e.role)))
                .collect()
        } else {
            pool.clone()
        };
        let mut el = best_named(&named_pool, &ws);
        if role_set.is_some() && !matches!(verb, Verb::Type | Verb::Focus) {
            let unrestricted_pool: Vec<&Element> = els
                .iter()
                .copied()
                .filter(|e| !e.name.is_empty() && any_actionable(&pystr::lower(&e.role)))
                .collect();
            let unrestricted = best_named(&unrestricted_pool, &ws);
            let replace = match (el, unrestricted) {
                (None, _) => true,
                (Some(e), Some(u)) => words(&u.name).len() > words(&e.name).len(),
                (Some(_), None) => false,
            };
            if replace {
                el = unrestricted;
            }
        }
        if verb == Verb::Type {
            if el.is_none() {
                let arg_words = words(&infer::goal_text_arg(goal));
                let leftover = ws.iter().any(|w| {
                    !arg_words.contains(w)
                        && !VERB_WORDS.contains(&w.as_str())
                        && alias(w).is_none()
                        && !ORDINAL_WORDS.iter().any(|(o, _)| o == w)
                        && !matches!(w.as_str(), "last" | "key" | "keys")
                });
                if !leftover && !named_pool.is_empty() {
                    el = actions::topmost(&named_pool);
                }
            }
            if let Some(el) = el {
                return Some(emit(el, verb, goal, goal_l));
            }
        } else if let Some(el) = el {
            return Some(emit(el, verb, goal, goal_l));
        }
    }

    if let Some(m) = SEMANTIC_RE.captures(goal_l) {
        let names = match &m[1] {
            "save" => SAVE_NAMES,
            "confirm" => OK_NAMES,
            "cancel" => CANCEL_NAMES,
            "send" => SEND_NAMES,
            "open" => OPEN_NAMES,
            "delete" => DELETE_NAMES,
            _ => UNDO_NAMES,
        };
        // A dict keyed by id: a later element with the same id replaces it.
        let mut matches: Vec<&Element> = Vec::new();
        for el in &els {
            let name = pystr::strip(&el.name);
            if has(CLICKABLE_ROLES, &pystr::lower(&el.role))
                && names.iter().any(|n| pystr::casefold_eq(name, n))
            {
                match matches.iter_mut().find(|m| m.id == el.id) {
                    Some(slot) => *slot = el,
                    None => matches.push(el),
                }
            }
        }
        if matches.len() == 1 {
            return Some(Action::on(Verb::Click, matches[0]));
        }
    }

    // Session-level commands.
    let has_scrollable = els
        .iter()
        .any(|e| has(SCROLLABLE_ROLES, &pystr::lower(&e.role)));
    if let Some(m) = SCROLL_RE.captures(goal_l) {
        if has_scrollable {
            return Some(Action::new(Verb::Scroll).with_direction(&m[1]));
        }
    }
    if let Some(m) = PAGE_RE.captures(goal_l) {
        if !has_scrollable {
            let key = if &m[1] == "up" { "pageup" } else { "pagedown" };
            return Some(Action::new(Verb::Keypress).with_keys(vec![key.to_owned()]));
        }
    }
    if in_browser {
        if NEW_TAB_RE.is_match(goal_l) && !ws.contains("close") {
            return Some(Action::new(Verb::NewTab));
        }
        if CLOSE_TAB_RE.is_match(goal_l) {
            return Some(Action::new(Verb::CloseTab));
        }
        if BACK_RE.is_match(goal_l) {
            return Some(Action::new(Verb::Back));
        }
        if FORWARD_RE.is_match(goal_l) {
            return Some(Action::new(Verb::Forward));
        }
        if REFRESH_RE.is_match(goal_l) {
            return Some(Action::new(Verb::Refresh));
        }
    }
    None
}

/// `name_support`: the candidate's target shares a content word with the goal.
pub fn name_support(action: &Action, goal: &str) -> bool {
    let nw = words(&action.element_name);
    if nw.is_empty() {
        return false;
    }
    let gw = words(goal);
    nw.iter().any(|w| gw.contains(w))
}

#[allow(dead_code)]
fn _cmp(a: &Element, b: &Element) -> Ordering {
    cmp_key(a.reading_key(), b.reading_key())
}
