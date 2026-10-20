//! Dove: the Local Grounder (`dove-grounder`, ROADMAP W9) as driver tools.
//!
//! `act {pid, window_id, intent}` and the `{"intent": ...}` step of
//! `run_steps` both read the window's snapshot rows, let the grounder pick
//! one action locally (nexi-cua's resolver, then the NEXI-CUA-1 ranker),
//! carry it out through the chosen row's element token, and read what
//! changed. When the grounder abstains they act on nothing and return its
//! best candidate rows instead.
//!
//! Like `run_steps`, every read and action goes through [`ToolRegistry`]
//! with the caller's session, so it passes the same policy, permission and
//! recording checks as a direct call. The grounder only exists when its
//! weights are installed (`DOVE_DRIVER_GROUNDER_MODEL`); `act` is not
//! registered otherwise.

use std::sync::OnceLock;
use std::time::Duration;

use async_trait::async_trait;
use dove_grounder::act::{self, Plan};
use dove_grounder::service::Grounder;
use serde_json::{json, Map, Value};

use crate::{
    protocol::{Content, ToolResult},
    recording_tools::ReplayRegistrySlot,
    tool::{Tool, ToolDef, ToolRegistry},
};

pub const ACT_TOOL: &str = "act";
/// Rows the grounder reads: the same budget as a plain get_window_state, so
/// its read is also the baseline the caller's next `since:"latest"` diffs.
const READ_MAX_ELEMENTS: usize = crate::window_state_view::DEFAULT_MAX_ELEMENTS;
/// Longest tree_diff text a result carries.
const DIFF_TEXT_LIMIT: usize = 2_000;

/// Whether the grounder's weights are installed.
pub fn enabled() -> bool {
    Grounder::from_env().is_some()
}

/// What a grounded intent did.
pub(crate) struct Grounded {
    pub ok: bool,
    /// Stable reason when not ok: grounder_off, read_failed, abstained,
    /// action_failed.
    pub code: &'static str,
    /// One line for the text result.
    pub line: String,
    pub report: Value,
}

impl Grounded {
    fn failed(code: &'static str, message: String, mut report: Value) -> Self {
        report["ok"] = json!(false);
        report["code"] = json!(code);
        report["message"] = json!(message);
        Self {
            ok: false,
            code,
            line: message,
            report,
        }
    }
}

fn with_session(mut args: Value, session: Option<&str>) -> Value {
    if let Some(session) = session {
        args["session"] = json!(session);
    }
    args
}

fn first_text(result: &ToolResult) -> String {
    let text = result
        .content
        .iter()
        .find_map(|content| match content {
            Content::Text { text, .. } => Some(text.trim()),
            _ => None,
        })
        .unwrap_or("failed");
    text.lines()
        .next()
        .unwrap_or(text)
        .chars()
        .take(300)
        .collect()
}

/// Ground `intent` in window `pid`/`window_id` and act on it.
pub(crate) async fn ground_and_act(
    registry: &ToolRegistry,
    pid: i64,
    window_id: u64,
    intent: &str,
    session: Option<&str>,
) -> Grounded {
    let mut report = json!({ "intent": intent, "pid": pid, "window_id": window_id });
    let Some(grounder) = Grounder::from_env() else {
        return Grounded::failed(
            "grounder_off",
            "the local grounder is off: its weights are not installed (DOVE_DRIVER_GROUNDER_MODEL)"
                .into(),
            report,
        );
    };

    let read = registry
        .invoke(
            "get_window_state",
            with_session(
                json!({
                    "pid": pid,
                    "window_id": window_id,
                    "tree_format": "elements",
                    "max_elements": READ_MAX_ELEMENTS,
                    "include_screenshot": false,
                }),
                session,
            ),
        )
        .await;
    if read.is_error == Some(true) {
        return Grounded::failed(
            "read_failed",
            format!("get_window_state: {}", first_text(&read)),
            report,
        );
    }
    let rows: Vec<Value> = read
        .structured_content
        .as_ref()
        .and_then(|state| state.get("elements"))
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let owned_intent = intent.to_owned();
    let grounding =
        match tokio::task::spawn_blocking(move || act::ground(&grounder, &rows, &owned_intent))
            .await
        {
            Ok(grounding) => grounding,
            Err(error) => {
                return Grounded::failed(
                    "grounder_failed",
                    format!("the grounder stopped: {error}"),
                    report,
                )
            }
        };
    let decision = &grounding.decision;
    report["decision"] = json!({
        "action": decision.summary(),
        "decided_by": format!("{:?}", decision.decided_by).to_lowercase(),
        "probability": (decision.probability * 1000.0).round() / 1000.0,
        "confidence": (decision.confidence * 1000.0).round() / 1000.0,
        "latency_ms": (decision.latency_ms * 10.0).round() / 10.0,
    });
    if let Some(target) = &grounding.target {
        report["target"] = target.clone();
    }
    let summary = grounding.summary();

    let acted = match grounding.plan {
        Plan::Abstain { reason } => {
            report["candidates"] = Value::Array(grounding.candidates);
            report["abstained"] = json!(true);
            return Grounded::failed(
                "abstained",
                format!(
                    "the grounder abstained on \"{intent}\": {reason}; nothing was done. \
                     Its best candidates are in `candidates` (act on one by element_token)"
                ),
                report,
            );
        }
        Plan::Done => format!("{summary}: nothing to do"),
        Plan::Wait { ms } => {
            tokio::time::sleep(Duration::from_millis(ms)).await;
            format!("{summary}: waited {ms} ms")
        }
        Plan::Tool { tool, args } => {
            let mut args = Value::Object(args);
            args["pid"] = json!(pid);
            args["window_id"] = json!(window_id);
            report["tool"] = json!(tool);
            report["args"] = args.clone();
            let result = registry.invoke(tool, with_session(args, session)).await;
            let message = first_text(&result);
            if result.is_error == Some(true) {
                return Grounded::failed(
                    "action_failed",
                    format!("{summary}, but {tool} failed: {message}"),
                    report,
                );
            }
            format!("{summary} via {tool}: {message}")
        }
    };

    // What changed: a diff against the read the grounder made.
    let after = registry
        .invoke(
            "get_window_state",
            with_session(
                json!({
                    "pid": pid,
                    "window_id": window_id,
                    "since": crate::window_state_view::SINCE_LATEST,
                    "max_elements": READ_MAX_ELEMENTS,
                    "include_screenshot": false,
                }),
                session,
            ),
        )
        .await;
    let mut line = acted;
    if after.is_error == Some(true) {
        report["diff"] = json!({ "error": first_text(&after) });
    } else if let Some(state) = after.structured_content.as_ref() {
        let status = state
            .get("since_status")
            .and_then(Value::as_str)
            .unwrap_or("full_read");
        let mut diff = Map::new();
        diff.insert("status".into(), json!(status));
        if let Some(counts) = state.get("diff_counts") {
            diff.insert("counts".into(), counts.clone());
            line.push_str(&format!(
                "; changed: {} added, {} changed, {} removed",
                counts["added"].as_u64().unwrap_or(0),
                counts["changed"].as_u64().unwrap_or(0),
                counts["removed"].as_u64().unwrap_or(0)
            ));
        } else if status == "no_change" {
            line.push_str("; no change in the window");
        }
        if let Some(text) = state.get("tree_diff").and_then(Value::as_str) {
            let clipped: String = text.chars().take(DIFF_TEXT_LIMIT).collect();
            diff.insert("tree_diff".into(), json!(clipped));
        }
        if let Some(focus) = state.get("focused_element") {
            diff.insert("focused_element".into(), focus.clone());
        }
        report["diff"] = Value::Object(diff);
    }
    report["ok"] = json!(true);
    report["message"] = json!(line);
    Grounded {
        ok: true,
        code: "ok",
        line,
        report,
    }
}

/// `act {pid, window_id, intent}`.
pub struct ActTool {
    registry: ReplayRegistrySlot,
}

impl ActTool {
    pub fn new(registry: ReplayRegistrySlot) -> Self {
        Self { registry }
    }
}

static DEF: OnceLock<ToolDef> = OnceLock::new();

#[async_trait]
impl Tool for ActTool {
    fn def(&self) -> &ToolDef {
        DEF.get_or_init(|| ToolDef {
            name: ACT_TOOL.into(),
            description: "Do one explicit sub-goal in a window without choosing the element \
                yourself: `intent` is a short instruction such as \"click Save\", \"type \
                'hello' into the search field\", \"check Wrap lines\", \"press ctrl+s\". A \
                local model (0 LLM tokens) reads the window's elements, picks one action, \
                does it through that element's token, and returns what it did plus what \
                changed (`diff`). When it is not confident it abstains, does nothing, and \
                returns its best candidate rows (element_token, role, label) for you to act \
                on. Use it for one obvious step; read the window yourself for anything \
                ambiguous."
                .into(),
            input_schema: json!({
                "type": "object",
                "required": ["pid", "window_id", "intent"],
                "properties": {
                    "pid": {"type": "integer", "description": "Process id of the window's app."},
                    "window_id": {"type": "integer", "description": "Window to act in (from list_windows or get_window_state)."},
                    "intent": {"type": "string", "minLength": 1, "description": "One explicit action in plain words, naming its target as the window labels it. Quote text to type."}
                },
                "additionalProperties": false
            }),
            read_only: false,
            destructive: true,
            idempotent: false,
            open_world: true,
        })
    }

    async fn invoke(&self, args: Value) -> ToolResult {
        let Some(registry) = self.registry.lock().unwrap().upgrade() else {
            return ToolResult::error("act is not available: registry not initialised yet.");
        };
        let pid = args.get("pid").and_then(Value::as_i64);
        let window_id = args.get("window_id").and_then(Value::as_u64);
        let intent = args
            .get("intent")
            .and_then(Value::as_str)
            .map(str::trim)
            .filter(|s| !s.is_empty());
        let (Some(pid), Some(window_id), Some(intent)) = (pid, window_id, intent) else {
            return ToolResult::error("act needs `pid`, `window_id` and a non-empty `intent`");
        };
        let session = args.get("_public_session_label").and_then(Value::as_str);
        let grounded = ground_and_act(&registry, pid, window_id, intent, session).await;
        let text = if grounded.ok {
            format!("act: {}", grounded.line)
        } else {
            let mut text = format!("act ({}): {}", grounded.code, grounded.line);
            if let Some(candidates) = grounded.report.get("candidates").and_then(Value::as_array) {
                for c in candidates {
                    text.push_str(&format!("\n- {}", candidate_line(c)));
                }
            }
            text
        };
        // An abstention is an answer, not a failure of the call.
        let is_error = (!grounded.ok && grounded.code != "abstained").then_some(true);
        ToolResult {
            content: vec![Content::text(text)],
            is_error,
            structured_content: Some(grounded.report),
            ..Default::default()
        }
    }
}

/// `p=0.42 click on [12] Button "Save" (s0000002a:12)`.
pub(crate) fn candidate_line(candidate: &Value) -> String {
    let p = candidate["p"].as_f64().unwrap_or(0.0);
    let verb = candidate["verb"].as_str().unwrap_or("?");
    match candidate.get("row") {
        Some(row) => format!(
            "p={p:.2} {verb} on [{}] {} \"{}\" ({})",
            row["element_index"],
            row["role"].as_str().unwrap_or(""),
            row["label"].as_str().unwrap_or(""),
            row["element_token"].as_str().unwrap_or("no token"),
        ),
        None => format!("p={p:.2} {}", candidate["action"].as_str().unwrap_or(verb)),
    }
}

#[cfg(test)]
mod tests;
