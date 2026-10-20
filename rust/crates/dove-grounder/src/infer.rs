//! Runtime decision (`nexi_cua/policy/infer.py`): resolver first, then the
//! NEXI-CUA-1 ranker with calibrated abstention and the margin-rescue rule,
//! then argument resolution from the goal text.

use crate::actions::{self, candidate_actions};
use crate::features::{self, ascii_words};
use crate::model::{Batch, Model};
use crate::pystr::{self, py_regex};
use crate::resolver;
use crate::types::{Action, DecidedBy, Decision, Element, Observation, Verb};
use regex::Regex;
use std::collections::HashSet;
use std::sync::LazyLock;
use std::time::Instant;

pub const MAX_K: usize = 512;
pub const MAX_M: usize = 112;

static QUOTED: LazyLock<Regex> = LazyLock::new(|| py_regex("[\"“](.+?)[\"”]|'(.+?)'", false));
static TYPE_RE: LazyLock<Regex> = LazyLock::new(|| {
    py_regex(
        "(?:type|enter|write|fill(?:\\s+in)?|input)\\s(?:into|in|the|a|an|to|that|\\s)*(?:[\"“](.+?)[\"”]|'(.+?)'|([^.,]+?))(?:\\s+(?:into|in|to|inside|as)\\b|\\s*$)",
        true,
    )
});
static GOTO_RE: LazyLock<Regex> = LazyLock::new(|| {
    py_regex(
        r"(?:go to|navigate to|open|visit|browse to)\s+((?:https?://)?[\w.-]+\.[a-z]{2,}(?:/\S*)?|[\w.-]+(?::\d+))",
        true,
    )
});
static PRESS_RE: LazyLock<Regex> = LazyLock::new(|| {
    py_regex(
        r"(?:press|hit|type the)\s+((?:cmd|command|ctrl|alt|option|shift|fn|super)\s*\+\s*)*([a-z0-9]+|f\d{1,2}|enter|return|tab|space|escape|esc|backspace|delete|up|down|left|right|home|end|pageup|pagedown)",
        true,
    )
});
static MOD_RE: LazyLock<Regex> =
    LazyLock::new(|| py_regex(r"(cmd|command|ctrl|alt|option|shift|fn|super)", true));
static DIRECTION_RE: LazyLock<Regex> =
    LazyLock::new(|| py_regex(r"\b(up|down|left|right)\b", true));

fn first_group(caps: &regex::Captures<'_>) -> Option<String> {
    caps.iter()
        .skip(1)
        .flatten()
        .map(|g| g.as_str())
        .find(|g| !g.is_empty())
        .map(str::to_owned)
}

/// `_goal_text_arg`: the quoted text, or what follows "type/enter/fill".
pub fn goal_text_arg(goal: &str) -> String {
    if let Some(caps) = QUOTED.captures(goal) {
        return first_group(&caps).unwrap_or_default();
    }
    if let Some(caps) = TYPE_RE.captures(goal) {
        return pystr::strip(&first_group(&caps).unwrap_or_default()).to_owned();
    }
    String::new()
}

fn goal_url_arg(goal: &str) -> String {
    GOTO_RE
        .captures(goal)
        .map(|c| pystr::strip(&c[1]).to_owned())
        .unwrap_or_default()
}

fn goal_keys_arg(goal: &str) -> Vec<String> {
    let Some(m) = PRESS_RE.captures(goal) else {
        return Vec::new();
    };
    let mods_text = m.get(1).map(|g| g.as_str()).unwrap_or("");
    let mut keys: Vec<String> = MOD_RE
        .find_iter(mods_text)
        .map(|x| resolver::canonical_key(&pystr::lower(x.as_str())))
        .collect();
    keys.push(pystr::lower(&m[2]));
    keys
}

static SELECT_SET_TO_RE: LazyLock<Regex> = LazyLock::new(|| {
    py_regex(r"(?:set|change|switch)\s+(?:the\s+)?(.+?)\s+to\s+(.+)$", true)
});
static SELECT_CHOOSE_RE: LazyLock<Regex> = LazyLock::new(|| {
    py_regex(r"(?:choose|pick|select)\s+(.+?)\s+(?:for|in|from|on)\b", true)
});
static SELECT_FALLBACK_RE: LazyLock<Regex> =
    LazyLock::new(|| py_regex("(?:to|as|for)\\s+([\"']?[\\w .-]+[\"']?)\\s*$", true));
static SELECT_ROLE_SUFFIX_RE: LazyLock<Regex> = LazyLock::new(|| {
    py_regex(r"(?:\s+(?:dropdown|menu|field|list|option))+\s*$", true)
});
static ARTICLE_RE: LazyLock<Regex> = LazyLock::new(|| py_regex(r"^(?:the|a|an)\s+", true));
static ROLE_WORD_RE: LazyLock<Regex> =
    LazyLock::new(|| py_regex(r"\b(?:dropdown|menu|field|list|option)\b", true));

fn clean_select_arg(value: &str) -> String {
    let value = pystr::strip(value).trim_matches(|c| matches!(c, '"' | '\'' | '“' | '”'));
    let value = ARTICLE_RE.replace(value, "");
    pystr::strip(&SELECT_ROLE_SUFFIX_RE.replace_all(&value, "")).to_owned()
}

fn extract_goal_select_arg(goal: &str) -> String {
    if let Some(caps) = QUOTED.captures(goal) {
        return clean_select_arg(&first_group(&caps).unwrap_or_default());
    }
    if let Some(caps) = SELECT_SET_TO_RE.captures(goal) {
        return clean_select_arg(&caps[2]);
    }
    if let Some(caps) = SELECT_CHOOSE_RE.captures(goal) {
        return clean_select_arg(&caps[1]);
    }
    SELECT_FALLBACK_RE
        .captures(goal)
        .map(|caps| clean_select_arg(&caps[1]))
        .unwrap_or_default()
}

/// `_goal_select_arg(goal, target_name)`.
pub fn goal_select_arg(goal: &str, target_name: &str) -> String {
    let arg = extract_goal_select_arg(goal);
    if !target_name.is_empty()
        && pystr::casefold_eq(&arg, pystr::strip(target_name))
    {
        let name_re = Regex::new(&format!("(?i){}", regex::escape(target_name)))
            .expect("escaped literal");
        let without_target = name_re.replace_all(goal, " ");
        let without_target = ROLE_WORD_RE.replace_all(&without_target, " ");
        return extract_goal_select_arg(&without_target);
    }
    arg
}

/// `_drag_dst`: the element sharing the most goal words, other than the source.
fn drag_dst(goal: &str, src_id: Option<&str>, elements: &[Element]) -> String {
    let gw: HashSet<String> = ascii_words(goal).collect();
    let mut best = String::new();
    let mut best_s: i64 = -1;
    for e in elements {
        if Some(e.id.as_str()) == src_id || e.name.is_empty() {
            continue;
        }
        let nw: HashSet<String> = ascii_words(&e.name).collect();
        let s = gw.intersection(&nw).count() as i64;
        if s > best_s {
            best = e.id.clone();
            best_s = s;
        }
    }
    best
}

/// `SemanticPolicy._resolve_args`: fill the placeholders from the goal.
pub fn resolve_args(a: &Action, goal: &str, elements: &[Element]) -> Action {
    let mut a = a.clone();
    match a.verb {
        Verb::Type if a.text == actions::ARG => a.text = goal_text_arg(goal),
        Verb::Select if a.text == actions::ARG => {
            let text = goal_text_arg(goal);
            a.text = if text.is_empty() {
                goal_select_arg(goal, "")
            } else {
                text
            };
        }
        Verb::Navigate if a.text == actions::ARG => a.text = goal_url_arg(goal),
        Verb::Scroll => {
            if let Some(m) = DIRECTION_RE.captures(goal) {
                let dir = pystr::lower(&m[1]);
                if a.direction != dir {
                    a.direction = dir;
                }
            }
        }
        Verb::Keypress if a.keys == [actions::KEYS] => {
            let mut keys = goal_keys_arg(goal);
            if keys.is_empty() {
                keys = resolver::shortcut_keys(&pystr::lower(goal), false).unwrap_or_default();
            }
            if keys.is_empty() {
                keys = vec!["enter".to_owned()];
            }
            a.keys = keys;
        }
        Verb::Drag if a.text == actions::DST => {
            a.text = drag_dst(goal, a.element_id.as_deref(), elements);
        }
        _ => {}
    }
    a
}

static ELEMENT_GOAL_RE: LazyLock<Regex> = LazyLock::new(|| {
    py_regex(
        r"\b(click|tap|follow|select|choose|enable|disable|toggle|check|uncheck|drag|type|expand|collapse|hit the|press the|press a|press an|open the|open a|open an|double.?click|right.?click)\b",
        true,
    )
});
static GLOBAL_GOAL_RE: LazyLock<Regex> = LazyLock::new(|| {
    py_regex(
        r"\b(new tab|close (the )?tab|switch (to )?(the )?(first|second|third|\w+ )?tab|press (enter|return|escape|space|tab|backspace|delete|up|down|left|right|home|end|pageup|pagedown|arrow)|go back|go forward|refresh|reload|scroll (up|down|left|right)|wait|finish|done)\b",
        true,
    )
});

/// `_element_goal`: the goal names an element interaction.
fn element_goal(goal: &str) -> bool {
    ELEMENT_GOAL_RE.is_match(goal) && !GLOBAL_GOAL_RE.is_match(goal)
}

fn global_verb(v: Verb) -> bool {
    matches!(
        v,
        Verb::Wait
            | Verb::Done
            | Verb::Keypress
            | Verb::Back
            | Verb::Forward
            | Verb::Refresh
            | Verb::NewTab
            | Verb::CloseTab
            | Verb::SwitchTab
    )
}

fn never_rescue(v: Verb) -> bool {
    global_verb(v) && v != Verb::SwitchTab
}

/// Calibration from `nexi-cua-1.calib.json`.
#[derive(Clone, Copy, Debug)]
pub struct Calibration {
    pub temperature: f64,
    pub abstain_threshold: f64,
}

/// `SemanticPolicy._batch`: the elements the model sees (targets first),
/// as `(element, index)` pairs, plus each candidate's target index.
pub fn build_batch(obs: &Observation, cands: &[Action]) -> Batch {
    let m = cands.len().min(MAX_M);
    let target_ids: HashSet<&str> = cands[..m]
        .iter()
        .filter_map(|a| a.element_id.as_deref())
        .filter(|id| !id.is_empty())
        .collect();
    let mut selected: Vec<&Element> = obs
        .elements
        .iter()
        .filter(|e| target_ids.contains(e.id.as_str()))
        .collect();
    let selected_ids: HashSet<&str> = selected.iter().map(|e| e.id.as_str()).collect();
    selected.extend(obs.elements.iter().filter(|e| !selected_ids.contains(e.id.as_str())));
    selected.truncate(MAX_K);
    let mut batch = Batch::default();
    let mut eidx: std::collections::HashMap<&str, i64> = Default::default();
    for (j, e) in selected.iter().enumerate() {
        // A later element with the same id takes the index (dict assignment).
        eidx.insert(e.id.as_str(), j as i64);
        batch.role_idx.push(features::role_index(&e.role));
        batch.elem_text.push(features::text_features(&features::element_text(e)));
        batch.numeric.push(features::element_numeric(
            e,
            obs.screen_w,
            obs.screen_h,
            &obs.goal,
            &obs.elements,
        ));
    }
    for a in &cands[..m] {
        batch.verb_idx.push(a.verb.index());
        let target = a
            .element_id
            .as_deref()
            .filter(|id| !id.is_empty())
            .and_then(|id| eidx.get(id).copied())
            .unwrap_or(-1);
        batch.tgt_idx.push(target);
        batch.arg_text.push(features::text_features(&a.textual()));
    }
    batch.goal_text = features::text_features(&obs.goal);
    batch
}

/// `SemanticPolicy.decide(obs, goal)`. `model` is None for the resolver-only
/// path (`use_resolver` with no network), which abstains whenever the
/// resolver defers.
pub fn decide(
    model: Option<&Model>,
    calib: Calibration,
    obs: &Observation,
    goal: &str,
    use_resolver: bool,
) -> Decision {
    let t0 = Instant::now();
    let mut obs = obs.clone();
    if !goal.is_empty() {
        obs.goal = goal.to_owned();
    }
    let elapsed = |t0: Instant| t0.elapsed().as_secs_f64() * 1e3;
    let cands = candidate_actions(&obs);
    let mut decision = Decision {
        action: None,
        probability: 0.0,
        confidence: 0.0,
        abstain: true,
        reason: String::new(),
        decided_by: DecidedBy::NoCandidates,
        top_k: Vec::new(),
        candidates: Vec::new(),
        latency_ms: 0.0,
    };
    if cands.is_empty() {
        decision.reason = "no candidates".into();
        decision.latency_ms = elapsed(t0);
        return decision;
    }
    if use_resolver {
        if let Some(direct) = resolver::resolve(&obs, &obs.goal) {
            decision.action = Some(resolve_args(&direct, &obs.goal, &obs.elements));
            decision.probability = 1.0;
            decision.confidence = 1.0;
            decision.abstain = false;
            decision.reason = "resolved deterministically".into();
            decision.decided_by = DecidedBy::Resolver;
            decision.latency_ms = elapsed(t0);
            return decision;
        }
    }
    decision.decided_by = DecidedBy::Ranker;
    let Some(model) = model else {
        decision.reason = "the resolver could not name a target and the ranker is not loaded".into();
        decision.latency_ms = elapsed(t0);
        return decision;
    };
    let batch = build_batch(&obs, &cands);
    let (logits, corr) = match model.run(&batch) {
        Ok(out) => out,
        Err(error) => {
            decision.reason = format!("ranker failed: {error}");
            decision.latency_ms = elapsed(t0);
            return decision;
        }
    };
    let m = logits.len();
    let temperature = calib.temperature as f32;
    let scaled: Vec<f32> = logits.iter().map(|l| l / temperature).collect();
    let probs = softmax(&scaled);
    let corr_p: Vec<f32> = corr.iter().map(|c| 1.0 / (1.0 + (-c).exp())).collect();
    // torch.max: the first maximum.
    let mut top_i = 0;
    for (i, p) in probs.iter().enumerate() {
        if *p > probs[top_i] {
            top_i = i;
        }
    }
    let top_p = probs[top_i] as f64;
    let conf = corr_p[top_i] as f64 * (0.5 + 0.5 * top_p);
    let mut order: Vec<usize> = (0..m).collect();
    // torch.sort(descending=True) is not stable; ties only occur between
    // identical candidates, whose strings are equal too.
    order.sort_by(|a, b| probs[*b].partial_cmp(&probs[*a]).unwrap_or(std::cmp::Ordering::Equal));
    decision.top_k = order
        .iter()
        .take(5)
        .map(|i| (*i, cands[*i].to_string(), probs[*i] as f64))
        .collect();
    let second_p = if m > 1 { probs[order[1]] as f64 } else { 0.0 };
    let decisive = top_p >= 0.95 || (top_p >= 0.30 && top_p >= 1.5 * second_p);
    let top = &cands[top_i];
    let rescue = decisive && !never_rescue(top.verb) && resolver::name_support(top, &obs.goal);
    decision.probability = top_p;
    decision.confidence = conf;
    decision.candidates = cands[..m].to_vec();
    decision.latency_ms = elapsed(t0);
    if global_verb(top.verb) && element_goal(&obs.goal) {
        decision.reason = "goal names an element interaction; no confident element pick".into();
        return decision;
    }
    if conf < calib.abstain_threshold && !rescue {
        decision.reason = format!(
            "max correctness {conf:.2} < {:.2}",
            calib.abstain_threshold
        );
        return decision;
    }
    decision.abstain = false;
    decision.action = Some(resolve_args(top, &obs.goal, &obs.elements));
    decision.latency_ms = elapsed(t0);
    decision
}

/// torch's CPU softmax: max-shifted exp, then multiply by the reciprocal sum.
fn softmax(x: &[f32]) -> Vec<f32> {
    let max = x.iter().copied().fold(f32::NEG_INFINITY, f32::max);
    let exps: Vec<f32> = x.iter().map(|v| (v - max).exp()).collect();
    let sum: f32 = exps.iter().sum();
    let inv = 1.0 / sum;
    exps.into_iter().map(|e| e * inv).collect()
}

/// Decision summary used by the gate: `str(action)` or `ABSTAIN`.
pub fn decision_key(decision: &Decision) -> String {
    decision.summary()
}

#[allow(dead_code)]
fn _unused(_: &[String]) -> usize {
    ascii_words("").count()
}
