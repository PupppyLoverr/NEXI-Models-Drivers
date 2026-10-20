//! `run_steps` auto-wait, query waits and verify_state expects against a
//! fake form app: a main window whose button opens a details dialog that
//! appears late, with fields that enable late and a Submit button that is
//! disabled until every field is filled and slides into place.

use std::sync::{Arc, Mutex};

use async_trait::async_trait;
use serde_json::{json, Value};

use crate::{
    expectation::{ToolObservationProvider, VerifyStateTool},
    protocol::{Content, ToolResult},
    tool::{Tool, ToolDef, ToolRegistry},
};

#[derive(Default)]
struct Ui {
    reads: u32,
    /// Read count at which the dialog was asked to open.
    opened_at: Option<u32>,
    /// Reads after opening before the dialog window is listed.
    dialog_delay: u32,
    /// Reads after the dialog shows before its fields enable.
    fields_delay: u32,
    /// Reads left during which Submit is still sliding in.
    submit_moves: u32,
    /// Reads left during which the "Slide" button moves.
    slide_moves: u32,
    /// Show disabled controls the AT-SPI way: a row without an index.
    passive_disabled: bool,
    fields: [String; 3],
    result: Option<String>,
    snapshot: u32,
    last_tokens: Vec<(String, String, bool)>,
    calls: Vec<(String, Value)>,
}

const FIELDS: [&str; 3] = ["Name", "Email", "Phone"];

struct Row {
    role: &'static str,
    label: String,
    value: Option<String>,
    enabled: bool,
    frame: (i64, i64, i64, i64),
}

fn row(role: &'static str, label: &str, enabled: bool, frame: (i64, i64, i64, i64)) -> Row {
    Row {
        role,
        label: label.to_owned(),
        value: None,
        enabled,
        frame,
    }
}

impl Ui {
    fn dialog_shown(&self) -> bool {
        self.opened_at
            .is_some_and(|at| self.reads >= at + self.dialog_delay)
    }

    fn fields_enabled(&self) -> bool {
        self.opened_at
            .is_some_and(|at| self.reads >= at + self.dialog_delay + self.fields_delay)
    }

    /// Rows of a window plus its display-only text rows.
    fn rows(&mut self, window_id: u64, advance: bool) -> (Vec<Row>, Vec<String>) {
        if window_id == 8 {
            let enabled = self.fields_enabled();
            let mut rows: Vec<Row> = FIELDS
                .iter()
                .enumerate()
                .map(|(nth, name)| Row {
                    value: Some(self.fields[nth].clone()).filter(|v| !v.is_empty()),
                    ..row("Edit", name, enabled, (110, 120 + 30 * nth as i64, 200, 24))
                })
                .collect();
            let filled = self.fields.iter().all(|field| !field.is_empty());
            let x = 110 + 10 * self.submit_moves as i64;
            if advance && self.submit_moves > 0 {
                self.submit_moves -= 1;
            }
            rows.push(row("Button", "Submit", filled, (x, 220, 80, 24)));
            rows.push(row("Button", "Close", true, (200, 220, 80, 24)));
            rows.push(row("Button", "Cancel", false, (290, 220, 80, 24)));
            return (rows, vec!["Fill in all fields".to_owned()]);
        }
        let x = 10 + 25 * self.slide_moves as i64;
        if advance && self.slide_moves > 0 {
            self.slide_moves -= 1;
        }
        let rows = vec![
            row("Button", "Open details", true, (10, 10, 120, 24)),
            row("Button", "Export", false, (140, 10, 80, 24)),
            row("Button", "Slide", true, (x, 40, 80, 24)),
            row("Button", "Ghost", true, (10, 70, 0, 0)),
        ];
        let text = format!(
            "Result: {}",
            self.result.clone().unwrap_or_else(|| "none".into())
        );
        (rows, vec![text])
    }
}

#[derive(Clone)]
struct Fake {
    def: ToolDef,
    ui: Arc<Mutex<Ui>>,
}

#[async_trait]
impl Tool for Fake {
    fn def(&self) -> &ToolDef {
        &self.def
    }

    async fn invoke(&self, args: Value) -> ToolResult {
        let mut ui = self.ui.lock().unwrap();
        let name = self.def.name.clone();
        ui.calls.push((name.clone(), args.clone()));
        match name.as_str() {
            "list_windows" => {
                let mut windows = vec![json!({
                    "pid": 42, "window_id": 7, "app_name": "Forms", "title": "Main",
                    "z_index": 1, "is_on_screen": true,
                    "bounds": {"x": 0.0, "y": 0.0, "width": 800.0, "height": 600.0}
                })];
                if ui.dialog_shown() {
                    windows.push(json!({
                        "pid": 42, "window_id": 8, "app_name": "Forms", "title": "Details",
                        "z_index": 2, "is_on_screen": true,
                        "bounds": {"x": 100.0, "y": 100.0, "width": 400.0, "height": 200.0}
                    }));
                }
                ToolResult::text("windows").with_structured(json!({ "windows": windows }))
            }
            "list_apps" => ToolResult::text("apps").with_structured(json!({
                "apps": [{"pid": 42, "name": "Forms", "running": true, "active": false}]
            })),
            "get_window_state" => {
                let window_id = args["window_id"].as_u64().unwrap_or(7);
                if window_id == 8 && !ui.dialog_shown() {
                    return ToolResult::error(
                        "Window target pid 42, window_id 8 is stale or no longer running",
                    );
                }
                // verify_state reads without refreshing the action tokens.
                let observation_only = args.get("_observation_only").is_some();
                ui.reads += 1;
                ui.snapshot += 1;
                let snapshot = ui.snapshot;
                let (rows, texts) = ui.rows(window_id, !observation_only);
                let mut markdown = String::from("- [0] Window \"Forms\"\n");
                let mut elements = Vec::new();
                let mut tokens = Vec::new();
                for (offset, row) in rows.iter().enumerate() {
                    let index = offset + 1;
                    if ui.passive_disabled && !row.enabled {
                        markdown.push_str(&format!(
                            "  - {} = \"{}\" (disabled)\n",
                            row.role, row.label
                        ));
                        continue;
                    }
                    let token = format!("s{snapshot:08x}:{index}");
                    markdown.push_str(&format!("  - [{index}] {} \"{}\"\n", row.role, row.label));
                    let (x, y, w, h) = row.frame;
                    let mut element = json!({
                        "element_index": index,
                        "element_token": token,
                        "role": row.role,
                        "depth": 1,
                        "label": row.label,
                        "enabled": row.enabled,
                        "frame": {"x": x, "y": y, "w": w, "h": h},
                    });
                    if let Some(value) = &row.value {
                        element["value"] = json!(value);
                    }
                    elements.push(element);
                    tokens.push((token, row.label.clone(), row.enabled));
                }
                for text in texts {
                    markdown.push_str(&format!("  - Text \"{text}\"\n"));
                }
                if !observation_only {
                    ui.last_tokens = tokens;
                }
                ToolResult::text(markdown.clone()).with_structured(json!({
                    "pid": 42,
                    "window_id": window_id,
                    "snapshot_id": format!("s{snapshot:08x}"),
                    "elements": elements,
                    "elements_complete": true,
                    "tree_markdown": markdown,
                }))
            }
            "click" | "set_value" => {
                let token = args["element_token"].as_str().unwrap_or_default();
                let Some((label, enabled)) = ui
                    .last_tokens
                    .iter()
                    .find(|(candidate, _, _)| candidate == token)
                    .map(|(_, label, enabled)| (label.clone(), *enabled))
                else {
                    return ToolResult::error(format!("{name}: stale element_token {token}"));
                };
                if !enabled {
                    return ToolResult::error(format!("{name}: \"{label}\" is disabled"));
                }
                match (name.as_str(), label.as_str()) {
                    ("click", "Open details") => ui.opened_at = Some(ui.reads),
                    ("click", "Close") => ui.opened_at = None,
                    ("click", "Submit") => {
                        ui.result = Some(format!("Saved {}", ui.fields.join(" / ")));
                        ui.opened_at = None;
                    }
                    ("set_value", field) => {
                        if let Some(nth) = FIELDS.iter().position(|name| *name == field) {
                            ui.fields[nth] = args["value"].as_str().unwrap_or_default().to_owned();
                        }
                    }
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
    ui: Arc<Mutex<Ui>>,
}

impl Harness {
    fn new(ui: Ui) -> Self {
        let ui = Arc::new(Mutex::new(ui));
        let fake = |name: &str| Fake {
            def: ToolDef {
                name: name.into(),
                description: "fake".into(),
                input_schema: json!({
                    "type": "object",
                    "properties": {
                        "pid": {"type": "integer"},
                        "window_id": {"type": "integer"},
                        "element_token": {"type": "string"},
                        "value": {"type": "string"},
                        "key": {"type": "string"},
                        "x": {"type": "number"},
                        "y": {"type": "number"}
                    }
                }),
                read_only: matches!(name, "get_window_state" | "list_windows" | "list_apps"),
                destructive: false,
                idempotent: false,
                open_world: false,
            },
            ui: ui.clone(),
        };
        let mut registry = ToolRegistry::new();
        for name in super::super::BATCHABLE_TOOLS.iter().copied().chain([
            "get_window_state",
            "list_windows",
            "list_apps",
        ]) {
            registry.register(Box::new(fake(name)));
        }
        // The real verify_state, observing the same fake app.
        registry.register(Box::new(VerifyStateTool::new(Arc::new(
            ToolObservationProvider::new(
                Arc::new(fake("list_windows")),
                Arc::new(fake("get_window_state")),
            ),
        ))));
        registry.register_session_tools();
        let registry = Arc::new(registry);
        registry.init_self_weak();
        Self { registry, ui }
    }

    async fn run(&self, args: Value) -> ToolResult {
        self.registry
            .invoke(super::super::RUN_STEPS_TOOL, args)
            .await
    }

    fn calls(&self, tool: &str) -> Vec<Value> {
        self.ui
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

/// ROADMAP W3 "done when": open dialog, fill three fields, submit, check
/// the result, in one run_steps call, with the dialog, its fields and its
/// Submit button all arriving late.
#[tokio::test]
async fn open_fill_submit_check_is_one_call() {
    let harness = Harness::new(Ui {
        dialog_delay: 2,
        fields_delay: 5,
        submit_moves: 2,
        ..Default::default()
    });
    let result = harness
        .run(json!({
            "app": "Forms",
            "steps": [
                {"click": {"role": "button", "name": "Open details"}},
                {"set_value": {"role": "textfield", "name": "Name", "value": "Ada"}},
                {"set_value": {"role": "textfield", "name": "Email", "value": "ada@example.com"}},
                {"set_value": {"role": "textfield", "name": "Phone", "value": "555"},
                 "expect": {"element": {"selector": {"role": "button", "label_contains": "Submit"}, "enabled": true}}},
                {"click": {"role": "button", "name": "Submit"},
                 "expect": [{"window": "Main", "query": "Result: Saved Ada"},
                            {"query": "Fill in all fields", "gone": true}]}
            ],
            "observe": {}
        }))
        .await;
    let report = text(&result);
    assert_ne!(result.is_error, Some(true), "{report}");
    let structured = result.structured_content.clone().unwrap();
    assert_eq!(structured["executed"], 5, "{report}");
    // The first field had to wait for the dialog and then for its fields
    // to enable; Submit was disabled until Phone was filled, then slid in.
    assert_eq!(
        structured["steps"][1]["auto_wait"]["waited_for"], "it was enabled",
        "{report}"
    );
    assert_eq!(structured["steps"][3]["verify"]["status"], "satisfied");
    assert_eq!(structured["steps"][1]["target"]["window"]["window_id"], 8);
    assert_eq!(
        harness.ui.lock().unwrap().result.as_deref(),
        Some("Saved Ada / ada@example.com / 555")
    );
    assert_eq!(harness.calls("click").len(), 2, "no click was refused");
    assert_eq!(harness.calls("set_value").len(), 3);
    // The observe diff still runs at the end. Submit closed the dialog the
    // batch last acted in, so the main window is read instead.
    assert_eq!(structured["observation"]["ok"], true, "{report}");
    assert!(
        report.contains("window 8 closed during the batch; observing Forms window 7"),
        "{report}"
    );
    let observed = harness.calls("get_window_state").last().unwrap().clone();
    assert_eq!(observed["since"], "latest");
    assert_eq!(observed["window_id"], 7);
}

/// The cost of auto-wait on a target that is ready: one more read of the
/// window than with auto_wait off, and no note in the report.
#[tokio::test]
async fn a_ready_target_costs_one_extra_read() {
    let harness = Harness::new(Ui::default());
    let step = json!({"click": {"app": "Forms", "role": "button", "name": "Open details"}});
    let result = harness.run(json!({"steps": [step.clone()]})).await;
    assert_ne!(result.is_error, Some(true), "{}", text(&result));
    let structured = result.structured_content.unwrap();
    assert!(structured["steps"][0].get("auto_wait").is_none());
    assert!(!text_of_steps(&structured).contains("auto-waited"));
    let with_auto_wait = harness.calls("get_window_state").len();
    assert_eq!(with_auto_wait, 2);

    let harness = Harness::new(Ui::default());
    harness
        .run(json!({"auto_wait": false, "steps": [step]}))
        .await;
    assert_eq!(harness.calls("get_window_state").len(), 1);
}

fn text_of_steps(structured: &Value) -> String {
    structured["steps"].to_string()
}

#[tokio::test]
async fn a_disabled_target_times_out_saying_why() {
    let harness = Harness::new(Ui::default());
    let started = std::time::Instant::now();
    let result = harness
        .run(json!({"steps": [
            {"click": {"app": "Forms", "role": "button", "name": "Export"}, "timeout_ms": 400},
            {"click": {"role": "button", "name": "Open details"}}
        ]}))
        .await;
    let report = text(&result);
    assert_eq!(result.is_error, Some(true));
    let structured = result.structured_content.clone().unwrap();
    assert_eq!(structured["failed_step"], 0);
    assert_eq!(structured["steps"][0]["phase"], "find");
    assert_eq!(structured["steps"][0]["code"], "not_actionable");
    assert_eq!(
        structured["steps"][0]["auto_wait"]["blocked_by"],
        "disabled"
    );
    assert!(report.contains("disabled (enabled=false)"), "{report}");
    assert!(report.contains("\"auto_wait\":false"), "{report}");
    assert!(
        harness.calls("click").is_empty(),
        "early stop: nothing clicked"
    );
    assert!(started.elapsed() >= std::time::Duration::from_millis(300));
}

/// Linux AT-SPI lists a disabled button as `push button = "Export"
/// (disabled)` with no index: auto-wait waits on it and says it is disabled.
#[tokio::test]
async fn a_disabled_row_without_an_index_times_out_as_disabled() {
    let harness = Harness::new(Ui {
        passive_disabled: true,
        ..Default::default()
    });
    let result = harness
        .run(json!({"steps": [
            {"click": {"app": "Forms", "role": "button", "name": "Export"}, "timeout_ms": 400}
        ]}))
        .await;
    let report = text(&result);
    let structured = result.structured_content.clone().unwrap();
    assert_eq!(structured["steps"][0]["code"], "not_actionable", "{report}");
    assert_eq!(
        structured["steps"][0]["auto_wait"]["blocked_by"],
        "disabled"
    );
    assert!(
        report.contains("`Button = \"Export\" (disabled)`"),
        "{report}"
    );
    assert!(harness.calls("click").is_empty());

    // With auto_wait off the upstream lookup takes the row for a control
    // with no accessibility actions and fails at once.
    let result = harness
        .run(json!({"auto_wait": false, "steps": [
            {"click": {"app": "Forms", "role": "button", "name": "Export"}, "timeout_ms": 0}
        ]}))
        .await;
    assert_eq!(
        result.structured_content.unwrap()["steps"][0]["code"],
        "not_addressable"
    );
}

#[tokio::test]
async fn auto_wait_false_acts_at_once() {
    let harness = Harness::new(Ui::default());
    let result = harness
        .run(json!({"auto_wait": false, "steps": [
            {"click": {"app": "Forms", "role": "button", "name": "Export"}}
        ]}))
        .await;
    assert_eq!(result.is_error, Some(true));
    let structured = result.structured_content.clone().unwrap();
    // The click ran and the app refused it.
    assert_eq!(structured["steps"][0]["phase"], "action");
    assert_eq!(harness.calls("click").len(), 1);

    // A step's own auto_wait wins over the batch's.
    let harness = Harness::new(Ui::default());
    let result = harness
        .run(json!({"auto_wait": true, "steps": [
            {"click": {"app": "Forms", "role": "button", "name": "Export"}, "auto_wait": false}
        ]}))
        .await;
    assert_eq!(
        result.structured_content.unwrap()["steps"][0]["phase"],
        "action"
    );
}

#[tokio::test]
async fn a_moving_target_is_clicked_once_it_settles() {
    let harness = Harness::new(Ui {
        slide_moves: 3,
        ..Default::default()
    });
    let result = harness
        .run(json!({"steps": [{"click": {"app": "Forms", "role": "button", "name": "Slide"}}]}))
        .await;
    let report = text(&result);
    assert_ne!(result.is_error, Some(true), "{report}");
    let structured = result.structured_content.unwrap();
    assert_eq!(
        structured["steps"][0]["auto_wait"]["waited_for"],
        "it stopped moving"
    );
    assert!(report.contains("auto-waited"), "{report}");
    assert_eq!(harness.ui.lock().unwrap().slide_moves, 0);
}

#[tokio::test]
async fn a_target_that_keeps_moving_or_has_no_area_fails_with_the_reason() {
    let harness = Harness::new(Ui {
        slide_moves: 100,
        ..Default::default()
    });
    let result = harness
        .run(json!({"steps": [{"click": {"app": "Forms", "role": "button", "name": "Slide"}, "timeout_ms": 300}]}))
        .await;
    let report = text(&result);
    let structured = result.structured_content.clone().unwrap();
    assert_eq!(
        structured["steps"][0]["auto_wait"]["blocked_by"],
        "not_stable"
    );
    assert!(report.contains("kept moving (frame"), "{report}");

    let result = harness
        .run(json!({"steps": [{"click": {"app": "Forms", "role": "button", "name": "Ghost"}, "timeout_ms": 0}]}))
        .await;
    let report = text(&result);
    let structured = result.structured_content.clone().unwrap();
    assert_eq!(
        structured["steps"][0]["auto_wait"]["blocked_by"],
        "not_visible"
    );
    assert!(report.contains("no on-screen area"), "{report}");
    assert!(harness.calls("click").is_empty());
}

#[tokio::test]
async fn wait_for_query_gone_and_timeout() {
    let harness = Harness::new(Ui {
        dialog_delay: 3,
        ..Default::default()
    });
    let result = harness
        .run(json!({"app": "Forms", "steps": [
            {"click": {"role": "button", "name": "Open details"}},
            {"wait_for": "Fill in all fields"},
            {"click": {"role": "button", "name": "Close"},
             "wait_for": {"query": "Fill in", "timeout": 2000}},
            {"wait_for": {"query": "Fill in all fields", "gone": true, "timeout": 2000}}
        ]}))
        .await;
    let report = text(&result);
    assert_ne!(result.is_error, Some(true), "{report}");
    assert_eq!(result.structured_content.unwrap()["executed"], 4);
    assert!(
        report.contains("with text \"Fill in all fields\""),
        "{report}"
    );

    // A wait that never holds fails in phase wait_for and stops the batch.
    let result = harness
        .run(json!({"app": "Forms", "steps": [
            {"wait_for": {"query": "Never shown", "timeout": 300}},
            {"click": {"role": "button", "name": "Open details"}}
        ]}))
        .await;
    let structured = result.structured_content.unwrap();
    assert_eq!(structured["steps"][0]["phase"], "wait_for");
    assert_eq!(structured["executed"], 1);
}

#[tokio::test]
async fn verify_predicates_fail_with_status_and_stop_the_batch() {
    let harness = Harness::new(Ui::default());
    let result = harness
        .run(json!({"app": "Forms", "steps": [
            {"expect": {"element": {"selector": {"role": "button", "label_contains": "Export"}, "enabled": true},
                        "timeout_ms": 300}},
            {"click": {"role": "button", "name": "Open details"}}
        ], "observe": {}}))
        .await;
    let report = text(&result);
    assert_eq!(result.is_error, Some(true));
    let structured = result.structured_content.clone().unwrap();
    assert_eq!(structured["steps"][0]["phase"], "expect");
    assert_eq!(structured["steps"][0]["code"], "verify_unsatisfied");
    assert_eq!(structured["steps"][0]["verify"]["status"], "unsatisfied");
    assert!(report.contains("\"enabled\":false"), "{report}");
    assert!(harness.calls("click").is_empty());
    // The failed batch is still observed.
    assert_eq!(structured["observation"]["ok"], true);

    // No element matches: verify_state says unknown, which is not success.
    let result = harness
        .run(json!({"app": "Forms", "steps": [
            {"expect": [{"element": {"selector": {"label_contains": "Nowhere"}}, "timeout_ms": 0}]}
        ]}))
        .await;
    let structured = result.structured_content.unwrap();
    assert_eq!(structured["steps"][0]["code"], "verify_unknown");
    assert!(structured["steps"][0]["message"]
        .as_str()
        .unwrap()
        .contains("target_missing"));

    // A window predicate holds.
    let result = harness
        .run(json!({"app": "Forms", "steps": [{"expect": {"window": {"exists": true}}}]}))
        .await;
    assert_ne!(result.is_error, Some(true), "{}", text(&result));
}

#[tokio::test]
async fn malformed_waits_are_rejected_before_anything_runs() {
    let harness = Harness::new(Ui::default());
    for (step, needle) in [
        (
            json!({"click": {"app": "Forms", "name": "Open details"}, "auto_wait": 1}),
            "`auto_wait` must be true or false",
        ),
        (
            json!({"expect": {"element": {"selector": {"role": "button"}, "exists": false}}}),
            "exists=false",
        ),
        (
            json!({"wait_for": {"query": "a", "text": "b"}}),
            "`query` or `text`",
        ),
    ] {
        let result = harness
            .run(json!({"steps": [{"click": {"app": "Forms", "name": "Open details"}}, step]}))
            .await;
        let message = text(&result);
        assert!(
            message.contains("rejected before running anything"),
            "{message}"
        );
        assert!(message.contains(needle), "{needle}: {message}");
    }
    let result = harness
        .run(json!({"auto_wait": "yes", "steps": [{"click": {"app": "Forms", "name": "Open details"}}]}))
        .await;
    assert!(text(&result).contains("`auto_wait` must be true or false"));
    assert!(harness.calls("click").is_empty());
}
