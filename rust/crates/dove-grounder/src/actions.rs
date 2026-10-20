//! Role families and candidate enumeration (`nexi_cua/actions.py`).

use crate::features::{ascii_words, cmp_key, sort_by_reading};
use crate::pystr;
use crate::types::{Action, Element, Observation, Verb};
use std::cmp::Ordering;
use std::collections::HashSet;

pub const CLICKABLE_ROLES: &[&str] = &[
    "button", "link", "menuitem", "tab", "checkbox", "radio", "toggle", "listitem", "row",
    "option", "segmented", "tabitem", "imagebutton", "menubutton", "popupbutton", "cell",
    "treeitem", "heading", "image", "disclosure",
];
pub const DCLICK_ROLES: &[&str] = &["listitem", "treeitem", "row", "cell", "image", "heading", "option"];
pub const DRAGGABLE_ROLES: &[&str] = &[
    "listitem", "treeitem", "row", "cell", "image", "tab", "slider", "handle",
];
pub const TEXT_ROLES: &[&str] = &[
    "textfield", "textarea", "searchfield", "textbox", "combobox", "securetextfield", "webarea",
];
pub const SELECT_ROLES: &[&str] = &["combobox", "list", "popupbutton", "select", "dropdown", "radiogroup"];
pub const CHECKABLE_ROLES: &[&str] = &["checkbox", "radio", "toggle", "switch"];
pub const SCROLLABLE_ROLES: &[&str] = &["scrollarea", "webarea", "table", "list", "document"];

pub fn has(set: &[&str], role: &str) -> bool {
    set.contains(&role)
}

/// The union nexi uses for "any element a named goal can act on".
pub fn any_actionable(role: &str) -> bool {
    has(CLICKABLE_ROLES, role)
        || has(CHECKABLE_ROLES, role)
        || has(TEXT_ROLES, role)
        || has(SELECT_ROLES, role)
        || has(DCLICK_ROLES, role)
}

const GOAL_STOP: &[&str] = &[
    "a", "an", "and", "at", "click", "choose", "enable", "follow", "in", "into", "link", "on",
    "open", "page", "select", "the", "to", "type",
];
const ORDINALS: [(&str, usize); 3] = [("first", 0), ("second", 1), ("third", 2)];

fn goal_words(text: &str) -> HashSet<String> {
    ascii_words(text)
        .filter(|w| !GOAL_STOP.contains(&w.as_str()))
        .collect()
}

/// Score tuple of `_priority_elements` (compared descending).
#[derive(PartialEq, PartialOrd)]
struct Priority(u8, u8, f64, usize, u8, u8, f64, f64);

/// `_priority_elements`: keep goal-relevant and ordinal targets reachable on
/// dense screens.
fn priority_elements(obs: &Observation) -> Vec<&Element> {
    let elements: Vec<&Element> = obs.elements.iter().filter(|e| e.enabled).collect();
    let goal = pystr::lower(&obs.goal);
    if goal.is_empty() {
        return elements;
    }
    let raw_goal_words: HashSet<String> = ascii_words(&goal).collect();
    let gw = goal_words(&goal);
    let mut forced: HashSet<&str> = HashSet::new();
    let mut roles: Vec<&str> = Vec::new();
    for set in [CLICKABLE_ROLES, TEXT_ROLES, SELECT_ROLES, CHECKABLE_ROLES] {
        for role in set {
            if !roles.contains(role) {
                roles.push(role);
            }
        }
    }
    for role in roles {
        let plural = format!("{role}s");
        if !(raw_goal_words.contains(role) || raw_goal_words.contains(&plural)) {
            continue;
        }
        let mut ordered: Vec<&Element> = elements
            .iter()
            .copied()
            .filter(|el| pystr::lower(&el.role) == role && !el.name.is_empty())
            .collect();
        sort_by_reading(&mut ordered);
        for (ordinal, index) in ORDINALS {
            if goal.contains(ordinal) && index < ordered.len() {
                forced.insert(&ordered[index].id);
            }
        }
        if goal.contains("last") {
            if let Some(last) = ordered.last() {
                forced.insert(&last.id);
            }
        }
    }
    let has_named_match = elements
        .iter()
        .any(|el| !el.name.is_empty() && goal_words(&el.name).intersection(&gw).next().is_some());
    let has_role_match = elements
        .iter()
        .any(|el| raw_goal_words.contains(&pystr::lower(&el.role)));
    if forced.is_empty() && !has_named_match && !has_role_match {
        return elements;
    }
    let score = |el: &Element| {
        let name = pystr::strip(&pystr::lower(&el.name)).to_owned();
        let name_words = goal_words(&name);
        let overlap = gw.intersection(&name_words).count();
        let coverage = overlap as f64 / name_words.len().max(1) as f64;
        let exact_phrase = !name.is_empty() && goal.contains(&name);
        let role_mentioned = goal.contains(&pystr::lower(&el.role));
        let (y, x) = el.reading_key();
        Priority(
            forced.contains(el.id.as_str()) as u8,
            exact_phrase as u8,
            coverage,
            overlap,
            role_mentioned as u8,
            el.focused as u8,
            -y,
            -x,
        )
    };
    let mut scored: Vec<(Priority, &Element)> = elements.into_iter().map(|el| (score(el), el)).collect();
    // sorted(..., reverse=True) keeps equal keys in their original order.
    scored.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(Ordering::Equal));
    scored.into_iter().map(|(_, el)| el).collect()
}

pub const ARG: &str = "\u{0}ARG";
pub const DST: &str = "\u{0}DST";
pub const KEYS: &str = "\u{0}KEYS";

/// `candidate_actions(obs)`: the plausible actions the policy scores.
pub fn candidate_actions(obs: &Observation) -> Vec<Action> {
    const MAX_ELEMENT_CANDIDATES: usize = 100;
    let mut cands = Vec::new();
    for el in priority_elements(obs) {
        let role = pystr::lower(&el.role);
        let role = role.as_str();
        if has(CLICKABLE_ROLES, role) || has(CHECKABLE_ROLES, role) {
            cands.push(Action::on(Verb::Click, el));
        }
        if has(DCLICK_ROLES, role) {
            cands.push(Action::on(Verb::DoubleClick, el));
            cands.push(Action::on(Verb::RightClick, el));
        }
        if has(DRAGGABLE_ROLES, role) {
            cands.push(Action::on(Verb::Drag, el).with_text(DST));
        }
        if has(CHECKABLE_ROLES, role) {
            cands.push(Action::on(Verb::Check, el));
        }
        if has(TEXT_ROLES, role) || el.editable() {
            cands.push(Action::on(Verb::Focus, el));
            cands.push(Action::on(Verb::Type, el).with_text(ARG));
        }
        if has(SELECT_ROLES, role) {
            cands.push(Action::on(Verb::Click, el));
            cands.push(Action::on(Verb::Select, el).with_text(ARG));
        }
        if has(SCROLLABLE_ROLES, role) {
            cands.push(Action::on(Verb::Scroll, el).with_direction("down"));
            cands.push(Action::on(Verb::Scroll, el).with_direction("up"));
        }
        if cands.len() >= MAX_ELEMENT_CANDIDATES {
            break;
        }
    }
    cands.push(Action::new(Verb::Keypress).with_keys(vec![KEYS.to_owned()]));
    cands.push(Action {
        wait_ms: 1000,
        ..Action::new(Verb::Wait)
    });
    if let Some(browser) = &obs.browser {
        cands.push(Action::new(Verb::Navigate).with_text(ARG));
        for verb in [Verb::Back, Verb::Forward, Verb::Refresh, Verb::NewTab, Verb::CloseTab] {
            cands.push(Action::new(verb));
        }
        for tab in browser.tabs.iter().take(8) {
            cands.push(Action {
                tab: tab.id.clone(),
                element_name: tab.title.clone(),
                ..Action::new(Verb::SwitchTab)
            });
        }
    }
    cands.push(Action::new(Verb::Done));
    cands
}

/// Index of the first element with the smallest reading key (`min(..., key=_reading_key)`).
pub fn topmost<'a>(els: &[&'a Element]) -> Option<&'a Element> {
    let mut best: Option<&Element> = None;
    for el in els {
        if best.is_none_or(|b| cmp_key(el.reading_key(), b.reading_key()) == Ordering::Less) {
            best = Some(el);
        }
    }
    best
}
