//! Dove additions to `run_steps` waits and checks (ROADMAP W3.2).
//!
//! Upstream `run_steps` already has `wait_for` and `expect` checks by
//! role/name/text and named targets that wait for their element to appear.
//! This module adds, without changing how those work:
//!
//! - `wait_for` / `expect` spellings models reach for: `query` (any row
//!   containing the text, like get_window_state's `query`), `timeout`, and a
//!   bare string (`"wait_for": "Saved"`);
//! - `expect` entries written as `verify_state` predicates
//!   (`{"element": {"selector": ...}}`, `{"window": {"exists": ...}}`), run
//!   through the registry's `verify_state` tool, so they are judged exactly
//!   as a direct verify_state call: stable samples, and `unknown` is not
//!   success;
//! - Playwright-style auto-wait before an action on a named target: the
//!   element exists, is enabled, is on screen (has area) and kept the same
//!   frame across two reads, within the step's find timeout. On timeout the
//!   step says which of these did not hold. A control that the tree shows
//!   only as a row without an index marked `(disabled)` (AT-SPI does this)
//!   is waited on as disabled, not reported as missing;
//! - when the end `observe` would read the window the batch last acted in
//!   and that window closed (the last step submitted its dialog), the app's
//!   frontmost window is read instead, so the end diff still shows the result.
//!
//! Everything here is reached from a handful of call sites in
//! `batch_tools.rs`, so the patch that carries it stacks with others.

use std::time::{Duration, Instant};

use serde_json::{json, Map, Value};

use super::locate::{self, ElementSpec, Found, Locator, Miss, Window, WindowSpec};
use crate::tool::ToolRegistry;

/// Step and batch field that turns auto-wait off.
pub(crate) const AUTO_WAIT_KEY: &str = "auto_wait";
/// Most verify_state predicates one step may carry (verify_state's own cap).
const MAX_VERIFY_PREDICATES: usize = 8;
/// Pause before reading a blocked target again.
const ACTIONABILITY_POLL: Duration = Duration::from_millis(100);
/// Pause before the second read that proves an actionable target is steady:
/// about two display frames, as Playwright waits two animation frames.
const STABILITY_GAP: Duration = Duration::from_millis(40);
/// Actions that need an enabled target. Hover and scroll do not.
const NEEDS_ENABLED: &[&str] = &[
    "click",
    "double_click",
    "right_click",
    "set_value",
    "type_text",
    "press_key",
    "hotkey",
];

/// Appended to the run_steps description.
pub(crate) const DESCRIPTION: &str = "\n\n\
    AUTO-WAIT: before acting on a target named by role/name, the batch waits (within the \
    step's timeout_ms, default 3000) until the element exists, is enabled, has an on-screen \
    frame and kept the same frame across two reads; if it does not, the step fails in phase \
    `find` with code not_actionable and says which (disabled, no on-screen area, still \
    moving). `\"auto_wait\":false` on a step or on run_steps acts as soon as the element \
    is found. Targets given by element_token or x,y act at once. \
    A wait_for/expect check may also be a bare string or use `query` (text shown anywhere in \
    the window) and `timeout` (ms). An expect entry may be a verify_state predicate, \
    {\"element\":{\"selector\":{\"role\"?,\"label_contains\"?},\"exists\"?,\"value_equals\"?,\
    \"enabled\"?,\"selected\"?}} or {\"window\":{\"exists\"?,\"bounds\"?}}, plus optional \
    timeout_ms and stable_samples; those run as one verify_state call on the step's window \
    and only `satisfied` passes.";

/// What one step adds to the upstream step fields.
#[derive(Clone, Debug, Default)]
pub(crate) struct StepWaits {
    /// The step's own `auto_wait`; None inherits the batch's.
    pub auto_wait: Option<bool>,
    /// `expect` entries written as verify_state predicates.
    pub verify: Option<Verify>,
}

impl StepWaits {
    pub fn auto_wait(&self) -> bool {
        self.auto_wait.unwrap_or(true)
    }
}

/// verify_state predicates checked after a step's action.
#[derive(Clone, Debug)]
pub(crate) struct Verify {
    pub predicates: Vec<Value>,
    pub timeout_ms: u64,
    pub stable_samples: Option<u64>,
    pub session: Option<String>,
}

/// The batch-level `auto_wait` (default true).
pub(crate) fn batch_auto_wait(object: &Map<String, Value>) -> Result<bool, String> {
    match object.get(AUTO_WAIT_KEY) {
        None | Some(Value::Null) => Ok(true),
        Some(Value::Bool(flag)) => Ok(*flag),
        Some(_) => Err(format!("`{AUTO_WAIT_KEY}` must be true or false")),
    }
}

/// Rewrite one raw step into the shape upstream's step parser reads, and
/// take out what this module handles: `auto_wait`, check aliases, and
/// verify_state-shaped `expect` entries.
pub(crate) fn normalize_step(
    raw: &Value,
    session: Option<&str>,
) -> Result<(Value, StepWaits), String> {
    let Some(object) = raw.as_object() else {
        // Upstream's parser names the problem.
        return Ok((raw.clone(), StepWaits::default()));
    };
    let mut object = object.clone();
    let mut waits = StepWaits::default();
    match object.remove(AUTO_WAIT_KEY) {
        None | Some(Value::Null) => {}
        Some(Value::Bool(flag)) => waits.auto_wait = Some(flag),
        Some(_) => return Err(format!("`{AUTO_WAIT_KEY}` must be true or false")),
    }
    if let Some(wait_for) = object.get_mut("wait_for") {
        normalize_check(wait_for).map_err(|message| format!("wait_for: {message}"))?;
    }
    if let Some(expect) = object.remove("expect").filter(|expect| !expect.is_null()) {
        let (items, single) = match expect {
            Value::Array(items) => (items, false),
            other => (vec![other], true),
        };
        let mut checks = Vec::new();
        let mut predicates = Vec::new();
        let mut timeout_ms: Option<u64> = None;
        let mut stable_samples: Option<u64> = None;
        for (nth, mut item) in items.into_iter().enumerate() {
            let label = if single {
                "expect".to_owned()
            } else {
                format!("expect {}", nth + 1)
            };
            if is_verify_predicate(&item) {
                let (predicate, timeout, samples) =
                    verify_predicate(item).map_err(|message| format!("{label}: {message}"))?;
                predicates.push(predicate);
                timeout_ms = max_option(timeout_ms, timeout);
                stable_samples = max_option(stable_samples, samples);
            } else {
                normalize_check(&mut item).map_err(|message| format!("{label}: {message}"))?;
                checks.push(item);
            }
        }
        if predicates.len() > MAX_VERIFY_PREDICATES {
            return Err(format!(
                "`expect` holds {} verify_state predicates; at most {MAX_VERIFY_PREDICATES}",
                predicates.len()
            ));
        }
        if !predicates.is_empty() {
            waits.verify = Some(Verify {
                predicates,
                timeout_ms: timeout_ms.unwrap_or(locate::DEFAULT_EXPECT_TIMEOUT_MS),
                stable_samples,
                session: session.map(str::to_owned),
            });
        }
        // Upstream's parser refuses an empty `expect` array, so only the
        // checks it reads are put back.
        if !checks.is_empty() || waits.verify.is_none() {
            let value = if single && checks.len() == 1 {
                checks.remove(0)
            } else {
                Value::Array(checks)
            };
            object.insert("expect".to_owned(), value);
        }
    }
    Ok((Value::Object(object), waits))
}

fn max_option(a: Option<u64>, b: Option<u64>) -> Option<u64> {
    match (a, b) {
        (Some(a), Some(b)) => Some(a.max(b)),
        (a, b) => a.or(b),
    }
}

/// A check in the upstream shape, from the spellings models also use:
/// a bare string is a text check, `query` means `text`, `timeout` means
/// `timeout_ms`.
fn normalize_check(check: &mut Value) -> Result<(), String> {
    if let Value::String(text) = check {
        if text.trim().is_empty() {
            return Err("must name what to wait for".to_owned());
        }
        *check = json!({ "text": text.trim() });
        return Ok(());
    }
    let Some(object) = check.as_object_mut() else {
        return Ok(());
    };
    for (alias, key) in [("query", "text"), ("timeout", "timeout_ms")] {
        if let Some(value) = object.remove(alias) {
            if object.contains_key(key) {
                return Err(format!("give `{alias}` or `{key}`, not both"));
            }
            object.insert(key.to_owned(), value);
        }
    }
    Ok(())
}

/// An `expect` entry in verify_state's predicate shape: an `element`
/// object, or a `window` object (a string `window` is the upstream title
/// filter).
fn is_verify_predicate(item: &Value) -> bool {
    item.get("element").is_some_and(Value::is_object)
        || item.get("window").is_some_and(Value::is_object)
}

/// Split a verify_state-shaped entry into the predicate and its options,
/// refusing what verify_state itself would refuse.
fn verify_predicate(item: Value) -> Result<(Value, Option<u64>, Option<u64>), String> {
    let Value::Object(mut object) = item else {
        unreachable!("is_verify_predicate only passes objects");
    };
    let mut timeout = None;
    for key in ["timeout_ms", "timeout"] {
        if let Some(value) = object.remove(key) {
            if timeout.is_some() {
                return Err("give `timeout` or `timeout_ms`, not both".to_owned());
            }
            timeout = Some(
                value
                    .as_u64()
                    .filter(|ms| *ms <= locate::MAX_CHECK_TIMEOUT_MS)
                    .ok_or_else(|| {
                        format!(
                            "`{key}` must be an integer 0 to {}",
                            locate::MAX_CHECK_TIMEOUT_MS
                        )
                    })?,
            );
        }
    }
    let samples = match object.remove("stable_samples") {
        None | Some(Value::Null) => None,
        Some(value) => Some(
            value
                .as_u64()
                .filter(|count| (1..=5).contains(count))
                .ok_or("`stable_samples` must be an integer 1 to 5")?,
        ),
    };
    let predicate = Value::Object(object);
    let parsed: cua_driver_contract::StatePredicate = serde_json::from_value(predicate.clone())
        .map_err(|error| format!("not a verify_state predicate: {error}"))?;
    match (&parsed.window, &parsed.element) {
        (Some(_), Some(_)) => {
            return Err("a predicate checks `window` or `element`, not both".to_owned())
        }
        (Some(window), None) if window.exists.is_none() && window.bounds.is_none() => {
            return Err("`window` needs `exists` or `bounds`".to_owned())
        }
        (None, Some(element)) => {
            if element.exists == Some(false) {
                return Err(
                    "element.exists=false is not supported (use {\"name\":…,\"gone\":true})"
                        .to_owned(),
                );
            }
            let blank =
                |value: &Option<String>| value.as_deref().is_some_and(|v| v.trim().is_empty());
            if (element.selector.role.is_none() && element.selector.label_contains.is_none())
                || blank(&element.selector.role)
                || blank(&element.selector.label_contains)
            {
                return Err(
                    "element.selector needs a non-empty `role` or `label_contains`".to_owned(),
                );
            }
        }
        _ => {}
    }
    if timeout == Some(0) && samples.is_some_and(|count| count > 1) {
        return Err("timeout_ms 0 allows only stable_samples 1".to_owned());
    }
    Ok((predicate, timeout, samples))
}

/// Find a named target and, with auto-wait, wait until it is actionable.
/// Adds `auto_wait` to the step report and a note when it had to wait.
pub(crate) async fn find_for_action(
    locator: &Locator<'_>,
    window: &WindowSpec,
    element: &ElementSpec,
    timeout: Duration,
    auto_wait: bool,
    report: &mut Value,
    notes: &mut Vec<String>,
) -> Result<Found, Miss> {
    if !auto_wait {
        return locator.find(window, element, timeout).await;
    }
    let tool = element.action.unwrap_or_default();
    let started = Instant::now();
    let deadline = started + timeout;
    let mut previous: Option<Sample> = None;
    let mut reads = 0u32;
    // The last reason that held the action back, other than the second
    // read stability needs anyway.
    let mut held_by: Option<Blocker> = None;
    loop {
        let remaining = deadline.saturating_duration_since(Instant::now());
        let found = match locator.find(window, element, remaining).await {
            Ok(found) => found,
            Err(miss) => {
                // AT-SPI shows a disabled control as a row without an index,
                // so the lookup misses it; wait on it as disabled instead.
                let Some(row) = disabled_row(locator, &miss, element).await else {
                    return Err(miss);
                };
                reads += 1;
                held_by = Some(Blocker::Disabled);
                if Instant::now() + ACTIONABILITY_POLL > deadline {
                    let waited = started.elapsed().as_millis() as u64;
                    report["auto_wait"] = json!({
                        "waited_ms": waited,
                        "reads": reads,
                        "blocked_by": Blocker::Disabled.code(),
                    });
                    let window = miss.window.expect("disabled_row needs the window");
                    return Err(Miss {
                        code: "not_actionable",
                        message: format!(
                            "{} in {} is shown as `{row}` and did not become actionable within \
                             {} ms: {}; it has no element index while disabled.",
                            element.describe(),
                            window.describe(),
                            timeout.as_millis(),
                            Blocker::Disabled.explain()
                        ),
                        window: Some(window),
                    });
                }
                previous = None;
                tokio::time::sleep(ACTIONABILITY_POLL).await;
                continue;
            }
        };
        reads += 1;
        let sample = Sample::of(&found);
        let blocker = sample.blocker(NEEDS_ENABLED.contains(&tool), previous.as_ref());
        let Some(blocker) = blocker else {
            if let Some(held) = &held_by {
                let waited = started.elapsed().as_millis() as u64;
                report["auto_wait"] = json!({
                    "waited_ms": waited,
                    "reads": reads,
                    "waited_for": held.wanted(),
                });
                notes.push(format!("auto-waited {waited} ms until {}", held.wanted()));
            }
            return Ok(found);
        };
        if !matches!(blocker, Blocker::Unproven) {
            held_by = Some(blocker.clone());
        }
        let pause = if matches!(blocker, Blocker::Unproven) {
            STABILITY_GAP
        } else {
            ACTIONABILITY_POLL
        };
        // Stability always gets its second read, even with timeout 0.
        if reads >= 2 && Instant::now() + pause > deadline {
            let blocker = held_by.unwrap_or(blocker);
            let waited = started.elapsed().as_millis() as u64;
            report["auto_wait"] = json!({
                "waited_ms": waited,
                "reads": reads,
                "blocked_by": blocker.code(),
            });
            return Err(Miss {
                code: "not_actionable",
                message: format!(
                    "{} in {} was found but did not become actionable within {} ms ({reads} \
                     reads): {}. Set \"auto_wait\":false on the step to act anyway.",
                    found.describe(),
                    found.window.describe(),
                    timeout.as_millis(),
                    blocker.explain()
                ),
                window: Some(found.window),
            });
        }
        previous = Some(sample);
        tokio::time::sleep(pause).await;
    }
}

/// After a lookup missed `element`, the row of its window that shows it as a
/// disabled control without an element index, such as AT-SPI's
/// `push button = "Submit" (disabled)`.
async fn disabled_row(locator: &Locator<'_>, miss: &Miss, element: &ElementSpec) -> Option<String> {
    if !matches!(miss.code, "not_found" | "not_addressable") || element.name.is_none() {
        return None;
    }
    let read = locator.read(miss.window.as_ref()?).await.ok()?;
    read.markdown.lines().find_map(|line| {
        disabled_row_matches(line, element).then(|| line.trim().trim_start_matches("- ").to_owned())
    })
}

fn disabled_row_matches(line: &str, element: &ElementSpec) -> bool {
    let Some(rest) = line.trim().strip_prefix("- ") else {
        return false;
    };
    let Some(rest) = rest.strip_suffix("(disabled)") else {
        return false;
    };
    if rest.starts_with('[') {
        return false;
    }
    let Some((role, quoted)) = rest.split_once('"') else {
        return false;
    };
    let role = role.trim().trim_end_matches('=').trim();
    let Some((label, _)) = quoted.split_once('"') else {
        return false;
    };
    let role_ok = element
        .role
        .as_deref()
        .is_none_or(|wanted| locate::role_family(wanted) == locate::role_family(role));
    let name_ok = element.name.as_deref().is_some_and(|name| {
        let (label, name) = (label.trim().to_lowercase(), name.trim().to_lowercase());
        !name.is_empty() && label.contains(&name)
    });
    role_ok && name_ok
}

/// What one read showed of the target.
#[derive(Clone, Debug, PartialEq)]
struct Sample {
    identity: (Option<String>, Option<String>),
    frame: Option<[f64; 4]>,
    enabled: Option<bool>,
}

impl Sample {
    fn of(found: &Found) -> Self {
        let element = &found.element;
        let text = |key: &str| element.get(key).and_then(Value::as_str).map(str::to_owned);
        let frame = element.get("frame").map(|frame| {
            let number = |a: &str, b: &str| {
                frame
                    .get(a)
                    .or_else(|| frame.get(b))
                    .and_then(Value::as_f64)
                    .unwrap_or(0.0)
            };
            [
                number("x", "x"),
                number("y", "y"),
                number("w", "width"),
                number("h", "height"),
            ]
        });
        Self {
            identity: (text("role"), text("label")),
            frame,
            enabled: element.get("enabled").and_then(Value::as_bool),
        }
    }

    /// Why the target is not actionable yet, if it is not.
    fn blocker(&self, needs_enabled: bool, previous: Option<&Sample>) -> Option<Blocker> {
        if let Some([_, _, w, h]) = self.frame {
            if w <= 0.0 || h <= 0.0 {
                return Some(Blocker::Hidden);
            }
        }
        if needs_enabled && self.enabled == Some(false) {
            return Some(Blocker::Disabled);
        }
        let Some(previous) = previous else {
            return Some(Blocker::Unproven);
        };
        if previous.identity != self.identity {
            return Some(Blocker::Unproven);
        }
        if previous.frame != self.frame {
            return Some(Blocker::Moving {
                before: previous.frame,
                after: self.frame,
            });
        }
        None
    }
}

#[derive(Clone, Debug, PartialEq)]
enum Blocker {
    /// One read so far: stability needs a second.
    Unproven,
    Hidden,
    Disabled,
    Moving {
        before: Option<[f64; 4]>,
        after: Option<[f64; 4]>,
    },
}

impl Blocker {
    fn code(&self) -> &'static str {
        match self {
            Blocker::Unproven => "stability_unproven",
            Blocker::Hidden => "not_visible",
            Blocker::Disabled => "disabled",
            Blocker::Moving { .. } => "not_stable",
        }
    }

    fn wanted(&self) -> &'static str {
        match self {
            Blocker::Unproven => "it was read twice",
            Blocker::Hidden => "it was on screen",
            Blocker::Disabled => "it was enabled",
            Blocker::Moving { .. } => "it stopped moving",
        }
    }

    fn explain(&self) -> String {
        let frame = |frame: &Option<[f64; 4]>| match frame {
            Some([x, y, w, h]) => format!("{x},{y} {w}x{h}"),
            None => "none".to_owned(),
        };
        match self {
            Blocker::Unproven => {
                "it changed between reads, so it could not be read the same twice".to_owned()
            }
            Blocker::Hidden => {
                "it has no on-screen area (zero-size frame), so it is hidden or collapsed"
                    .to_owned()
            }
            Blocker::Disabled => "it is disabled (enabled=false)".to_owned(),
            Blocker::Moving { before, after } => format!(
                "it kept moving (frame {} then {}), so it is animating or the layout is still changing",
                frame(before),
                frame(after)
            ),
        }
    }
}

/// When the end read of the window the batch last used failed because that
/// window has closed (the last step submitted the dialog it acted in), the
/// observation arguments for the app's frontmost window instead, with a note.
pub(crate) async fn observe_after_close(
    locator: &Locator<'_>,
    args: &Value,
    last: Option<&Window>,
) -> Option<(Value, String)> {
    let closed = last?;
    let windows = locator
        .listed_windows(&WindowSpec {
            pid: Some(closed.pid),
            ..Default::default()
        })
        .await
        .ok()?;
    if windows
        .iter()
        .any(|window| window.window_id == closed.window_id)
    {
        return None;
    }
    let open = windows.into_iter().next()?;
    let mut retry = args.clone();
    retry["pid"] = json!(open.pid);
    retry["window_id"] = json!(open.window_id);
    Some((
        retry,
        format!(
            "window {} closed during the batch; observing {} instead",
            closed.window_id,
            open.describe()
        ),
    ))
}

/// Run a step's verify_state predicates on the step's window, through the
/// registry, so they get the same session and approval checks as a direct
/// verify_state call. Adds `verify` to the report; Ok carries a note for the
/// step line, Err the failure code and message. Like upstream's `expect`, the window becomes the one
/// observed at the end after a failure, or after a step that only checks.
pub(crate) async fn run_verify(
    registry: &ToolRegistry,
    locator: &Locator<'_>,
    verify: &Verify,
    window: &WindowSpec,
    step_has_no_action: bool,
    last_window: &mut Option<Window>,
    report: &mut Value,
) -> Result<String, (&'static str, String)> {
    let resolved = if window.is_empty() {
        last_window.clone().ok_or((
            "no_window",
            "no window to verify in: give `app` (or pid and window_id) on this step or an earlier one"
                .to_owned(),
        ))?
    } else {
        locator
            .window(window)
            .await
            .map_err(|miss| (miss.code, miss.message))?
    };
    let mut args = json!({
        "pid": resolved.pid,
        "window_id": resolved.window_id,
        "expect": verify.predicates,
        "timeout_ms": verify.timeout_ms,
    });
    if let Some(samples) = verify.stable_samples {
        args["stable_samples"] = json!(samples);
    } else if verify.timeout_ms == 0 {
        args["stable_samples"] = json!(1);
    }
    if let Some(session) = &verify.session {
        args["session"] = json!(session);
    }
    let result = registry.invoke("verify_state", args).await;
    if result.is_error == Some(true) {
        let message = result
            .content
            .iter()
            .find_map(|content| match content {
                crate::protocol::Content::Text { text, .. } => Some(text.trim().to_owned()),
                _ => None,
            })
            .unwrap_or_else(|| "verify_state failed".to_owned());
        return Err(("verify_failed", format!("verify_state: {message}")));
    }
    let output = result.structured_content.unwrap_or(Value::Null);
    let status = output
        .get("status")
        .and_then(Value::as_str)
        .unwrap_or("unknown");
    let predicates = output
        .get("predicates")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    report["verify"] = json!({
        "status": status,
        "stable": output.get("stable"),
        "samples": output.get("samples"),
        "elapsed_ms": output.get("elapsed_ms"),
        "predicates": predicates,
    });
    if status == "satisfied" {
        if last_window.is_none() || step_has_no_action {
            *last_window = Some(resolved);
        }
        return Ok(format!(
            "{} verify_state predicate(s) satisfied",
            verify.predicates.len()
        ));
    }
    *last_window = Some(resolved.clone());
    let failed: Vec<String> = predicates
        .iter()
        .filter(|outcome| outcome.get("status").and_then(Value::as_str) != Some("satisfied"))
        .map(|outcome| {
            let index = outcome.get("index").and_then(Value::as_u64).unwrap_or(0) as usize;
            let what = verify
                .predicates
                .get(index)
                .map(|predicate| serde_json::to_string(predicate).unwrap_or_default())
                .unwrap_or_default();
            let mut line = format!(
                "{what} is {}",
                outcome
                    .get("status")
                    .and_then(Value::as_str)
                    .unwrap_or("unknown")
            );
            if let Some(reason) = outcome.get("unknown_reason").and_then(Value::as_str) {
                line.push_str(&format!(" ({reason})"));
            }
            if let Some(observed) = outcome.get("observed_json").and_then(Value::as_str) {
                let observed: String = observed.chars().take(200).collect();
                line.push_str(&format!("; observed {observed}"));
            }
            line
        })
        .collect();
    let code = if status == "unsatisfied" {
        "verify_unsatisfied"
    } else {
        "verify_unknown"
    };
    Err((
        code,
        format!(
            "verify_state {status} in {} after {} ms: {}",
            resolved.describe(),
            output
                .get("elapsed_ms")
                .and_then(Value::as_u64)
                .unwrap_or(0),
            failed.join("; ")
        ),
    ))
}

#[cfg(test)]
#[path = "waits_flow_tests.rs"]
mod flow_tests;

#[cfg(test)]
mod tests {
    use super::*;

    fn normalized(raw: Value) -> (Value, StepWaits) {
        normalize_step(&raw, Some("s1")).expect("normalizes")
    }

    #[test]
    fn query_timeout_and_bare_strings_become_upstream_check_keys() {
        let (step, _) = normalized(json!({
            "wait_for": {"query": "Ready", "gone": true, "timeout": 900},
            "expect": "Saved"
        }));
        assert_eq!(
            step["wait_for"],
            json!({"text": "Ready", "gone": true, "timeout_ms": 900})
        );
        assert_eq!(step["expect"], json!({"text": "Saved"}));
        let (step, _) = normalized(json!({"wait_for": "Loading"}));
        assert_eq!(step["wait_for"], json!({"text": "Loading"}));
    }

    #[test]
    fn an_alias_and_its_key_together_are_refused() {
        let error =
            normalize_step(&json!({"wait_for": {"query": "a", "text": "b"}}), None).unwrap_err();
        assert!(error.contains("`query` or `text`"), "{error}");
        let error = normalize_step(
            &json!({"expect": [{"name": "x", "timeout": 1, "timeout_ms": 2}]}),
            None,
        )
        .unwrap_err();
        assert!(error.starts_with("expect 1:"), "{error}");
    }

    #[test]
    fn verify_predicates_are_split_from_upstream_checks() {
        let (step, waits) = normalized(json!({
            "click": {"name": "OK"},
            "auto_wait": false,
            "expect": [
                {"text": "Done"},
                {"element": {"selector": {"role": "button", "label_contains": "Close"}, "enabled": true},
                 "timeout_ms": 1500},
                {"window": {"exists": true}, "stable_samples": 3}
            ]
        }));
        assert_eq!(step["expect"], json!([{"text": "Done"}]));
        assert!(step.get("auto_wait").is_none());
        assert_eq!(waits.auto_wait, Some(false));
        let verify = waits.verify.expect("verify predicates");
        assert_eq!(verify.predicates.len(), 2);
        assert_eq!(verify.timeout_ms, 1500);
        assert_eq!(verify.stable_samples, Some(3));
        assert_eq!(verify.session.as_deref(), Some("s1"));
        assert!(verify.predicates[0].get("timeout_ms").is_none());
    }

    #[test]
    fn a_step_of_only_verify_predicates_drops_expect() {
        let (step, waits) = normalized(json!({"expect": {"window": {"exists": false}}}));
        assert!(step.get("expect").is_none());
        assert_eq!(
            waits.verify.unwrap().timeout_ms,
            locate::DEFAULT_EXPECT_TIMEOUT_MS
        );
    }

    #[test]
    fn malformed_verify_predicates_are_refused_before_running() {
        for (raw, needle) in [
            (
                json!({"element": {"selector": {}}}),
                "non-empty `role` or `label_contains`",
            ),
            (
                json!({"element": {"selector": {"role": "button"}, "exists": false}}),
                "exists=false",
            ),
            (
                json!({"element": {"selector": {"role": "x"}, "colour": "red"}}),
                "not a verify_state predicate",
            ),
            (json!({"window": {}}), "`exists` or `bounds`"),
            (
                json!({"window": {"exists": true}, "stable_samples": 9}),
                "stable_samples",
            ),
            (
                json!({"window": {"exists": true}, "timeout_ms": 0, "stable_samples": 2}),
                "stable_samples 1",
            ),
        ] {
            let error = normalize_step(&json!({"expect": raw}), None).unwrap_err();
            assert!(error.contains(needle), "{raw}: {error}");
        }
    }

    #[test]
    fn a_disabled_row_without_an_index_is_recognised() {
        let submit = ElementSpec {
            role: Some("button".into()),
            name: Some("Submit".into()),
            ..Default::default()
        };
        assert!(disabled_row_matches(
            "    - push button = \"Submit\" (disabled)",
            &submit
        ));
        assert!(disabled_row_matches(
            "- button \"Submit form\" (disabled)",
            &submit
        ));
        // An indexed row, an enabled row, another role or name: no.
        assert!(!disabled_row_matches(
            "- [3] push button \"Submit\" (disabled)",
            &submit
        ));
        assert!(!disabled_row_matches("- push button = \"Submit\"", &submit));
        assert!(!disabled_row_matches(
            "- check box = \"Submit\" (disabled)",
            &submit
        ));
        assert!(!disabled_row_matches(
            "- push button = \"Close\" (disabled)",
            &submit
        ));
    }

    #[test]
    fn auto_wait_must_be_a_flag() {
        assert!(normalize_step(&json!({"auto_wait": "no"}), None).is_err());
        let batch = json!({"auto_wait": false});
        assert!(!batch_auto_wait(batch.as_object().unwrap()).unwrap());
        assert!(batch_auto_wait(&Map::new()).unwrap());
    }

    fn found(frame: Value, enabled: Option<bool>) -> Found {
        let mut element =
            json!({"role": "AXButton", "label": "Go", "element_token": "s1:1", "frame": frame});
        if let Some(enabled) = enabled {
            element["enabled"] = json!(enabled);
        }
        Found {
            window: Window {
                pid: 1,
                window_id: 2,
                app: None,
                title: None,
                on_screen: true,
            },
            element,
        }
    }

    #[test]
    fn actionability_needs_area_enablement_and_a_steady_frame() {
        let frame = json!({"x": 1, "y": 2, "w": 30, "h": 10});
        let first = Sample::of(&found(frame.clone(), Some(true)));
        assert_eq!(first.blocker(true, None), Some(Blocker::Unproven));
        let second = Sample::of(&found(frame.clone(), Some(true)));
        assert_eq!(second.blocker(true, Some(&first)), None);

        let disabled = Sample::of(&found(frame.clone(), Some(false)));
        assert_eq!(
            disabled.blocker(true, Some(&first)),
            Some(Blocker::Disabled)
        );
        // Hover and scroll do not need an enabled target.
        assert_eq!(disabled.blocker(false, Some(&first)), None);

        let hidden = Sample::of(&found(json!({"x": 0, "y": 0, "w": 0, "h": 0}), None));
        assert_eq!(hidden.blocker(false, Some(&first)), Some(Blocker::Hidden));

        let moved = Sample::of(&found(json!({"x": 9, "y": 2, "w": 30, "h": 10}), None));
        assert!(matches!(
            moved.blocker(true, Some(&first)),
            Some(Blocker::Moving { .. })
        ));
        assert!(Blocker::Moving {
            before: first.frame,
            after: moved.frame
        }
        .explain()
        .contains("1,2 30x10 then 9,2 30x10"));
    }
}
