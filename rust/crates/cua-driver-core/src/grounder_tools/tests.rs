//! `act` and the `run_steps` intent step against a fake form. The grounder
//! is process-wide and needs its weights, so each test checks whichever
//! state this process is in: with `DOVE_DRIVER_GROUNDER_MODEL` set, the
//! intents run end to end; without it, the feature must be off.

use std::sync::{Arc, Mutex};

use async_trait::async_trait;
use serde_json::{json, Value};

use crate::{
    batch_tools::{BATCHABLE_TOOLS, RUN_STEPS_TOOL},
    protocol::{Content, ToolResult},
    tool::{Tool, ToolDef, ToolRegistry},
};

#[derive(Default)]
struct Form {
    email: String,
    saved: bool,
    snapshot: u32,
    calls: Vec<(String, Value)>,
}

const ROWS: [(&str, &str); 4] = [
    ("AXTextField", "Email"),
    ("AXButton", "Save"),
    ("AXButton", "Cancel"),
    ("AXCheckBox", "Remember me"),
];

struct Fake {
    def: ToolDef,
    form: Arc<Mutex<Form>>,
}

#[async_trait]
impl Tool for Fake {
    fn def(&self) -> &ToolDef {
        &self.def
    }

    async fn invoke(&self, args: Value) -> ToolResult {
        let mut form = self.form.lock().unwrap();
        let name = self.def.name.clone();
        form.calls.push((name.clone(), args.clone()));
        match name.as_str() {
            "get_window_state" => {
                form.snapshot += 1;
                let snapshot = form.snapshot;
                let mut elements = Vec::new();
                for (offset, (role, label)) in ROWS.iter().enumerate() {
                    let index = offset + 1;
                    let mut row = json!({
                        "element_index": index,
                        "element_token": format!("s{snapshot:08x}:{index}"),
                        "role": role,
                        "depth": 1,
                        "label": label,
                        "frame": {"x": 10, "y": 40 * index, "w": 120, "h": 24},
                    });
                    if *label == "Email" && !form.email.is_empty() {
                        row["value"] = json!(form.email);
                    }
                    elements.push(row);
                }
                let mut state = json!({
                    "pid": 42,
                    "window_id": 7,
                    "snapshot_id": format!("s{snapshot:08x}"),
                    "elements": elements,
                    "tree_markdown": "- [1] AXTextField \"Email\"",
                });
                if args.get("since").is_some() {
                    state["since_status"] = json!("diff");
                    state["diff_counts"] = json!({"added": 0, "changed": 1, "removed": 0});
                    state["tree_diff"] = json!("~ [1] AXTextField \"Email\"");
                }
                ToolResult::text("state").with_structured(state)
            }
            "click" | "set_value" => {
                let token = args["element_token"].as_str().unwrap_or_default();
                let index: usize = token
                    .rsplit(':')
                    .next()
                    .and_then(|i| i.parse().ok())
                    .unwrap_or(0);
                let Some((_, label)) = index.checked_sub(1).and_then(|i| ROWS.get(i)) else {
                    return ToolResult::error(format!("{name}: unknown element_token {token}"));
                };
                match (name.as_str(), *label) {
                    ("set_value", "Email") => {
                        form.email = args["value"].as_str().unwrap_or_default().to_owned()
                    }
                    ("click", "Save") => form.saved = true,
                    _ => {}
                }
                ToolResult::text(format!("{name} {label} done"))
            }
            other => ToolResult::text(format!("{other} done")),
        }
    }
}

struct Harness {
    registry: Arc<ToolRegistry>,
    form: Arc<Mutex<Form>>,
}

impl Harness {
    fn new() -> Self {
        let form = Arc::new(Mutex::new(Form::default()));
        let mut registry = ToolRegistry::new();
        for name in
            BATCHABLE_TOOLS
                .iter()
                .copied()
                .chain(["get_window_state", "list_windows", "list_apps"])
        {
            registry.register(Box::new(Fake {
                def: ToolDef {
                    name: name.into(),
                    description: "fake".into(),
                    input_schema: json!({"type": "object"}),
                    read_only: matches!(name, "get_window_state" | "list_windows" | "list_apps"),
                    destructive: false,
                    idempotent: false,
                    open_world: false,
                },
                form: form.clone(),
            }));
        }
        registry.register_session_tools();
        let registry = Arc::new(registry);
        registry.init_self_weak();
        Self { registry, form }
    }

    fn calls(&self, tool: &str) -> Vec<Value> {
        self.form
            .lock()
            .unwrap()
            .calls
            .iter()
            .filter(|(name, _)| name == tool)
            .map(|(_, args)| args.clone())
            .collect()
    }
}

fn text(result: &ToolResult) -> String {
    result
        .content
        .iter()
        .filter_map(|content| match content {
            Content::Text { text, .. } => Some(text.as_str()),
            _ => None,
        })
        .collect::<Vec<_>>()
        .join("\n")
}

#[tokio::test]
async fn act_is_offered_only_with_weights() {
    let harness = Harness::new();
    let offered = harness.registry.get_def(super::ACT_TOOL).is_some();
    assert_eq!(offered, super::enabled());
    let run_steps = harness.registry.get_def(RUN_STEPS_TOOL).unwrap();
    assert_eq!(
        run_steps.description.contains("INTENT STEPS"),
        super::enabled()
    );
}

#[tokio::test]
async fn an_intent_step_needs_the_grounder() {
    if super::enabled() {
        return;
    }
    let harness = Harness::new();
    let result = harness
        .registry
        .invoke(
            RUN_STEPS_TOOL,
            json!({"pid": 42, "window_id": 7, "steps": [{"intent": "click Save"}]}),
        )
        .await;
    assert_eq!(result.is_error, Some(true));
    assert!(
        text(&result).contains("local grounder, which is off"),
        "{}",
        text(&result)
    );
    assert!(harness.calls("click").is_empty());
}

#[tokio::test]
async fn intent_steps_act_through_element_tokens_and_report_the_diff() {
    if !super::enabled() {
        eprintln!("DOVE_DRIVER_GROUNDER_MODEL is not set: skipping");
        return;
    }
    let harness = Harness::new();
    let result = harness
        .registry
        .invoke(
            RUN_STEPS_TOOL,
            json!({
                "pid": 42,
                "window_id": 7,
                "steps": [
                    {"intent": "type \"a@example.com\" into the Email field"},
                    {"intent": "click Save"}
                ]
            }),
        )
        .await;
    assert_ne!(result.is_error, Some(true), "{}", text(&result));
    let set = harness.calls("set_value");
    assert_eq!(set.len(), 1);
    assert_eq!(set[0]["value"], json!("a@example.com"));
    assert!(set[0]["element_token"].as_str().unwrap().ends_with(":1"));
    let clicks = harness.calls("click");
    assert_eq!(clicks.len(), 1);
    assert!(clicks[0]["element_token"].as_str().unwrap().ends_with(":2"));
    assert!(harness.form.lock().unwrap().saved);
    let steps = &result.structured_content.as_ref().unwrap()["steps"];
    assert_eq!(steps[1]["tool"], json!("intent"));
    assert_eq!(
        steps[1]["grounding"]["decision"]["decided_by"],
        json!("resolver")
    );
    assert_eq!(steps[1]["grounding"]["diff"]["counts"]["changed"], json!(1));
}

#[tokio::test]
async fn act_abstains_with_candidate_rows_and_does_nothing() {
    if !super::enabled() {
        eprintln!("DOVE_DRIVER_GROUNDER_MODEL is not set: skipping");
        return;
    }
    let harness = Harness::new();
    let result = harness
        .registry
        .invoke(
            super::ACT_TOOL,
            json!({"pid": 42, "window_id": 7, "intent": "click the glowing purple button"}),
        )
        .await;
    assert_eq!(result.is_error, None, "{}", text(&result));
    let report = result.structured_content.unwrap();
    assert_eq!(report["code"], json!("abstained"));
    let candidates = report["candidates"].as_array().unwrap();
    assert!((1..=5).contains(&candidates.len()), "{candidates:?}");
    assert!(harness.calls("click").is_empty() && harness.calls("set_value").is_empty());

    let result = harness
        .registry
        .invoke(
            super::ACT_TOOL,
            json!({"pid": 42, "window_id": 7, "intent": "check Remember me"}),
        )
        .await;
    assert_ne!(result.is_error, Some(true), "{}", text(&result));
    let clicks = harness.calls("click");
    assert_eq!(clicks.len(), 1);
    assert!(clicks[0]["element_token"].as_str().unwrap().ends_with(":4"));
    assert!(
        text(&result).contains("changed: 0 added, 1 changed"),
        "{}",
        text(&result)
    );
}
