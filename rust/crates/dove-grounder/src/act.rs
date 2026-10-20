//! From an intent to one driver call: read the snapshot rows, decide, and
//! name the tool and arguments that carry the decision out through the
//! chosen row's element token.
//!
//! The driver owns the reads and the call itself (cua-driver-core's
//! `grounder_tools`); this module is the pure part between them.

use crate::rows::{self, Row};
use crate::service::Grounder;
use crate::types::{Action, DecidedBy, Decision, Verb};
use serde_json::{json, Map, Value};
use std::collections::HashMap;
use std::sync::Arc;

/// Most candidate rows an abstention returns.
pub const MAX_CANDIDATES: usize = 5;

/// What the decision asks the driver to do.
#[derive(Clone, Debug, PartialEq)]
pub enum Plan {
    /// Call `tool` with `args` (pid, window_id and session still to add).
    Tool {
        tool: &'static str,
        args: Map<String, Value>,
    },
    /// Pause, then report.
    Wait { ms: u64 },
    /// The intent says the task is finished: nothing to do.
    Done,
    /// No action: the reason, with the candidate rows to choose from.
    Abstain { reason: String },
}

/// A grounded intent.
pub struct Grounding {
    pub decision: Decision,
    pub plan: Plan,
    /// The row acted on (`describe`d), if any.
    pub target: Option<Value>,
    /// Best-ranked candidates with their rows; filled on abstention.
    pub candidates: Vec<Value>,
}

impl Grounding {
    /// One line for the tool result: what was decided, and how.
    pub fn summary(&self) -> String {
        let how = match self.decision.decided_by {
            DecidedBy::Resolver => "resolver".to_owned(),
            DecidedBy::Ranker => format!(
                "NEXI-CUA-1 p={:.2} confidence={:.2}",
                self.decision.probability, self.decision.confidence
            ),
            DecidedBy::NoCandidates => "no candidates".to_owned(),
        };
        match &self.plan {
            Plan::Abstain { reason } => format!("abstained ({reason})"),
            _ => format!("{} ({how})", self.decision.summary()),
        }
    }
}

/// Decide `intent` over the snapshot `rows` and plan the call.
pub fn ground(grounder: &Arc<Grounder>, rows: &[Value], intent: &str) -> Grounding {
    let (obs, by_id) = rows::observation(rows, intent);
    let decision = grounder.decide(&obs, intent);
    plan_decision(decision, &by_id)
}

/// Turn a decision into a plan over the rows it was made on.
pub fn plan_decision(decision: Decision, by_id: &HashMap<String, Row>) -> Grounding {
    let abstain = |decision: Decision, reason: String| {
        let candidates = candidate_rows(&decision, by_id);
        Grounding {
            decision,
            plan: Plan::Abstain { reason },
            target: None,
            candidates,
        }
    };
    let action = match (&decision.action, decision.abstain) {
        (Some(action), false) => action.clone(),
        _ => {
            let reason = if decision.reason.is_empty() {
                "no confident action".to_owned()
            } else {
                decision.reason.clone()
            };
            return abstain(decision, reason);
        }
    };
    let row = action.element_id.as_deref().and_then(|id| by_id.get(id));
    match plan_action(&action, row) {
        Ok(plan) => Grounding {
            target: row.map(|r| describe(r)),
            decision,
            plan,
            candidates: Vec::new(),
        },
        Err(reason) => abstain(decision, reason),
    }
}

fn token_args(row: Option<&Row>) -> Result<Map<String, Value>, String> {
    let row = row.ok_or("the decision names no element")?;
    let token = row
        .token
        .as_deref()
        .ok_or_else(|| format!("row {} has no element_token", row.index))?;
    let mut args = Map::new();
    args.insert("element_token".into(), json!(token));
    Ok(args)
}

/// nexi writes shortcuts the macOS way; elsewhere `cmd` is Ctrl.
fn driver_key(key: &str) -> String {
    match key {
        "cmd" if !cfg!(target_os = "macos") => "ctrl".to_owned(),
        "esc" => "escape".to_owned(),
        "return" => "enter".to_owned(),
        other => other.to_owned(),
    }
}

/// The driver call for one nexi action.
pub fn plan_action(action: &Action, row: Option<&Row>) -> Result<Plan, String> {
    let tool = |tool: &'static str, args: Map<String, Value>| Ok(Plan::Tool { tool, args });
    match action.verb {
        // Focusing a field is a click into it; checking a box is a click.
        Verb::Click | Verb::Focus | Verb::Check => tool("click", token_args(row)?),
        Verb::DoubleClick => tool("double_click", token_args(row)?),
        Verb::RightClick => tool("right_click", token_args(row)?),
        Verb::Type | Verb::Select => {
            if action.text.is_empty() || action.text.starts_with('\u{0}') {
                return Err(format!(
                    "{} needs text: put it in quotes in the intent",
                    action.verb.as_str()
                ));
            }
            let mut args = token_args(row)?;
            args.insert("value".into(), json!(action.text));
            tool("set_value", args)
        }
        Verb::Scroll => {
            let mut args = if row.is_some() {
                token_args(row)?
            } else {
                Map::new()
            };
            let direction = if action.direction.is_empty() {
                "down"
            } else {
                action.direction.as_str()
            };
            args.insert("direction".into(), json!(direction));
            args.insert(
                "amount".into(),
                json!(action.amount.round().clamp(1.0, 50.0) as u64),
            );
            tool("scroll", args)
        }
        Verb::Keypress => {
            let keys: Vec<String> = action.keys.iter().map(|k| driver_key(k)).collect();
            let mut args = Map::new();
            match keys.as_slice() {
                [] => return Err("no key to press".into()),
                [key] if !key.starts_with('\u{0}') => {
                    args.insert("key".into(), json!(key));
                    tool("press_key", args)
                }
                _ if keys.iter().any(|k| k.starts_with('\u{0}')) => Err("no key to press".into()),
                _ => {
                    args.insert("keys".into(), json!(keys));
                    tool("hotkey", args)
                }
            }
        }
        Verb::Wait => Ok(Plan::Wait {
            ms: action.wait_ms.clamp(0, 10_000) as u64,
        }),
        Verb::Done => Ok(Plan::Done),
        Verb::Drag => Err("drag takes coordinates; act does not drag".into()),
        verb => Err(format!(
            "{} is a browser-session action; use the browser tools",
            verb.as_str()
        )),
    }
}

/// A row as the result shows it: index, token, role, label, value.
pub fn describe(row: &Row) -> Value {
    let mut out = Map::new();
    out.insert("element_index".into(), json!(row.index));
    if let Some(token) = &row.token {
        out.insert("element_token".into(), json!(token));
    }
    for key in ["role", "label", "value"] {
        if let Some(v) = row.raw.get(key).filter(|v| !v.is_null()) {
            out.insert(key.into(), v.clone());
        }
    }
    Value::Object(out)
}

/// The ranker's best candidates (top 5 by probability), each with its row.
/// Element candidates are kept once per row; global ones as plain actions.
pub fn candidate_rows(decision: &Decision, by_id: &HashMap<String, Row>) -> Vec<Value> {
    let mut seen = Vec::new();
    let mut out = Vec::new();
    for (index, text, p) in &decision.top_k {
        let Some(action) = decision.candidates.get(*index) else {
            continue;
        };
        let key = action.element_id.clone().unwrap_or_else(|| text.clone());
        if seen.contains(&key) {
            continue;
        }
        seen.push(key);
        let readable = text
            .replace("\u{0}ARG", "<text>")
            .replace("\u{0}DST", "<target>")
            .replace("\u{0}KEYS", "<keys>");
        let mut entry = json!({
            "action": readable,
            "verb": action.verb.as_str(),
            "p": (p * 1000.0).round() / 1000.0,
        });
        if let Some(row) = action.element_id.as_deref().and_then(|id| by_id.get(id)) {
            entry["row"] = describe(row);
        }
        out.push(entry);
        if out.len() >= MAX_CANDIDATES {
            break;
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::types::Element;

    fn row(index: u64) -> Row {
        Row {
            index,
            token: Some(format!("s1:{index}")),
            raw: json!({"element_index": index, "role": "Button", "label": "Save"}),
        }
    }

    fn el(id: &str) -> Element {
        Element {
            id: id.into(),
            name: "Save".into(),
            ..Default::default()
        }
    }

    #[test]
    fn actions_map_to_token_calls() {
        let r = row(3);
        let click = Action::on(Verb::Click, &el("3"));
        assert_eq!(
            plan_action(&click, Some(&r)).unwrap(),
            Plan::Tool {
                tool: "click",
                args: json!({"element_token": "s1:3"})
                    .as_object()
                    .unwrap()
                    .clone()
            }
        );
        let typed = Action::on(Verb::Type, &el("3")).with_text("hello");
        let Plan::Tool { tool, args } = plan_action(&typed, Some(&r)).unwrap() else {
            panic!()
        };
        assert_eq!((tool, &args["value"]), ("set_value", &json!("hello")));
        assert!(plan_action(&Action::on(Verb::Type, &el("3")), Some(&r)).is_err());
        let chord = Action::new(Verb::Keypress).with_keys(vec!["cmd".into(), "z".into()]);
        let Plan::Tool { tool, args } = plan_action(&chord, None).unwrap() else {
            panic!()
        };
        assert_eq!(tool, "hotkey");
        let expected = if cfg!(target_os = "macos") {
            "cmd"
        } else {
            "ctrl"
        };
        assert_eq!(args["keys"], json!([expected, "z"]));
        let enter = Action::new(Verb::Keypress).with_keys(vec!["enter".into()]);
        assert!(matches!(
            plan_action(&enter, None),
            Ok(Plan::Tool {
                tool: "press_key",
                ..
            })
        ));
        assert_eq!(plan_action(&Action::new(Verb::Done), None), Ok(Plan::Done));
        assert!(plan_action(&Action::new(Verb::Back), None).is_err());
    }

    #[test]
    fn abstentions_list_candidate_rows_once_each() {
        let mut by_id = HashMap::new();
        by_id.insert("3".to_owned(), row(3));
        let cands = vec![
            Action::on(Verb::Click, &el("3")),
            Action::on(Verb::DoubleClick, &el("3")),
            Action::new(Verb::Wait),
        ];
        let decision = Decision {
            action: None,
            probability: 0.4,
            confidence: 0.1,
            abstain: true,
            reason: "max correctness 0.10 < 0.52".into(),
            decided_by: DecidedBy::Ranker,
            top_k: vec![
                (0, cands[0].to_string(), 0.4),
                (1, cands[1].to_string(), 0.3),
                (2, cands[2].to_string(), 0.2),
            ],
            candidates: cands,
            latency_ms: 0.0,
        };
        let g = plan_decision(decision, &by_id);
        assert!(matches!(g.plan, Plan::Abstain { .. }));
        assert_eq!(g.candidates.len(), 2);
        assert_eq!(g.candidates[0]["row"]["element_token"], json!("s1:3"));
        assert_eq!(g.candidates[1]["verb"], json!("wait"));
    }
}
