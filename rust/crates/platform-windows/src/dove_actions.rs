//! Dove (ROADMAP W2 + W6) on Windows.
//!
//! - [`probed`] wraps the action tools. Before the action it records the
//!   target element's value and a fingerprint of the target window (its UIA
//!   control-view tree, read in one cached call, plus the pid's visible
//!   top-level windows). After the action it reads them again, polling
//!   briefly, and reports `change: changed | unchanged | unverifiable`. A
//!   click, key or scroll whose window changed becomes `effect: confirmed`
//!   with `window_change` evidence; a `set_value` whose element reads back the
//!   requested value becomes `confirmed` with `value_readback` evidence.
//!   Text typed with `type_text` keeps upstream's effect (the insertion point
//!   is unknown) and only gains `change`.
//! - [`target_inspector`] tells `cua_driver_core::dove_safety` what an action
//!   targets: the element's role, name and value, UIA `IsPassword`, a
//!   payment-card field, the UAC (`consent.exe`) prompt, the secure desktop
//!   and the Windows Security credential dialog.
//!
//! Chromium/Electron windows and LibreOffice (SAL) windows are not
//! fingerprinted: their trees are large or hang under a subtree cache, and a
//! Chromium UIA write is echoed back without reaching the page. They report
//! `unverifiable` unless the element value says otherwise.

use std::collections::HashMap;
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, Instant};

use async_trait::async_trait;
use cua_driver_core::action_record::{ActionEffect, ActionEvidence, EvidenceKind, ObservedChange};
use cua_driver_core::dove_safety::{
    is_payment_field_name, SecureKind, TargetInfo, TargetInspector,
};
use cua_driver_core::protocol::ToolResult;
use cua_driver_core::tool::{Tool, ToolDef};
use serde_json::{json, Value};
use windows::core::Interface;
use windows::Win32::Foundation::HWND;
use windows::Win32::System::Com::{
    CoCreateInstance, CoInitializeEx, CLSCTX_INPROC_SERVER, COINIT_MULTITHREADED,
};
use windows::Win32::UI::Accessibility::*;

use crate::uia::snapshot::{RetainedElement, UiaSnapshot};

// ── UIA helpers ──────────────────────────────────────────────────────────────

fn automation() -> Option<IUIAutomation> {
    unsafe {
        let _ = CoInitializeEx(None, COINIT_MULTITHREADED);
        CoCreateInstance(&CUIAutomation, None, CLSCTX_INPROC_SERVER).ok()
    }
}

fn role_name(control_type: i32) -> String {
    match control_type {
        50000 => "Button",
        50002 => "CheckBox",
        50003 => "ComboBox",
        50004 => "Edit",
        50005 => "Hyperlink",
        50007 => "ListItem",
        50008 => "List",
        50011 => "MenuItem",
        50013 => "RadioButton",
        50015 => "Slider",
        50019 => "TabItem",
        50020 => "Text",
        50024 => "TreeItem",
        50030 => "Document",
        50031 => "SplitButton",
        50032 => "Window",
        _ => return format!("ControlType{control_type}"),
    }
    .to_owned()
}

fn is_editable_role(control_type: i32) -> bool {
    matches!(control_type, 50004 | 50030)
}

/// The value of a live element: ValuePattern, then RangeValuePattern, then
/// the TextPattern document.
fn element_value(element: &IUIAutomationElement) -> Option<String> {
    unsafe {
        if let Some(value) = element
            .GetCurrentPattern(UIA_ValuePatternId)
            .ok()
            .and_then(|p| p.cast::<IUIAutomationValuePattern>().ok())
            .and_then(|p| p.CurrentValue().ok())
        {
            return Some(value.to_string());
        }
        if let Some(value) = element
            .GetCurrentPattern(UIA_RangeValuePatternId)
            .ok()
            .and_then(|p| p.cast::<IUIAutomationRangeValuePattern>().ok())
            .and_then(|p| p.CurrentValue().ok())
        {
            return Some(format_number(value));
        }
        if let Some(state) = element
            .GetCurrentPattern(UIA_TogglePatternId)
            .ok()
            .and_then(|p| p.cast::<IUIAutomationTogglePattern>().ok())
            .and_then(|p| p.CurrentToggleState().ok())
        {
            return Some(toggle_word(state).to_owned());
        }
        if let Some(selected) = element
            .GetCurrentPattern(UIA_SelectionItemPatternId)
            .ok()
            .and_then(|p| p.cast::<IUIAutomationSelectionItemPattern>().ok())
            .and_then(|p| p.CurrentIsSelected().ok())
        {
            return Some(
                if selected.as_bool() {
                    "selected"
                } else {
                    "unselected"
                }
                .to_owned(),
            );
        }
        if let Some(names) = element
            .GetCurrentPattern(UIA_SelectionPatternId)
            .ok()
            .and_then(|p| p.cast::<IUIAutomationSelectionPattern>().ok())
            .and_then(|p| p.GetCurrentSelection().ok())
            .map(|items| {
                let count = items.Length().unwrap_or(0);
                (0..count)
                    .filter_map(|i| items.GetElement(i).ok())
                    .filter_map(|item| item.CurrentName().ok().map(|n| n.to_string()))
                    .collect::<Vec<_>>()
            })
            .filter(|names| !names.is_empty())
        {
            return Some(names.join(", "));
        }
        element
            .GetCurrentPattern(UIA_TextPatternId)
            .ok()
            .and_then(|p| p.cast::<IUIAutomationTextPattern>().ok())
            .and_then(|p| p.DocumentRange().ok())
            .and_then(|r| r.GetText(4096).ok())
            .map(|text| text.to_string())
    }
}

fn toggle_word(state: ToggleState) -> &'static str {
    match state.0 {
        0 => "off",
        1 => "on",
        _ => "mixed",
    }
}

/// A requested on/off/selected value in one spelling.
fn canonical_state(value: &str) -> Option<&'static str> {
    match value.trim().to_ascii_lowercase().as_str() {
        "on" | "true" | "checked" | "yes" | "1" | "selected" => Some("on"),
        "off" | "false" | "unchecked" | "no" | "0" | "unselected" | "not selected" => Some("off"),
        "mixed" | "indeterminate" => Some("mixed"),
        _ => None,
    }
}

/// Dove (W2.3): `set_value` on an element without Value/RangeValue: set a
/// check box through TogglePattern, or select a radio button or list item
/// through SelectionItemPattern, until its state reads back as requested.
/// `Ok(None)` when the element has neither pattern or `value` is not a
/// state word.
pub(crate) fn set_state_value(
    element: &IUIAutomationElement,
    hwnd: u64,
    value: &str,
) -> anyhow::Result<Option<&'static str>> {
    let Some(want) = canonical_state(value) else {
        return Ok(None);
    };
    unsafe {
        if let Some(toggle) = element
            .GetCurrentPattern(UIA_TogglePatternId)
            .ok()
            .and_then(|p| p.cast::<IUIAutomationTogglePattern>().ok())
        {
            for _ in 0..3 {
                if toggle.CurrentToggleState().map(toggle_word).ok() == Some(want) {
                    return Ok(Some("TogglePattern"));
                }
                crate::uia::fg_bypass::run_with_uwp_bypass(hwnd as isize, || toggle.Toggle())?;
            }
            if toggle.CurrentToggleState().map(toggle_word).ok() == Some(want) {
                return Ok(Some("TogglePattern"));
            }
            anyhow::bail!("set_value: the toggle did not reach '{want}' after three toggles");
        }
        if let Some(item) = element
            .GetCurrentPattern(UIA_SelectionItemPatternId)
            .ok()
            .and_then(|p| p.cast::<IUIAutomationSelectionItemPattern>().ok())
        {
            let selected = || {
                item.CurrentIsSelected()
                    .map(|b| b.as_bool())
                    .unwrap_or(false)
            };
            match want {
                "on" => {
                    if selected() {
                        return Ok(Some("SelectionItemPattern"));
                    }
                    crate::uia::fg_bypass::run_with_uwp_bypass(hwnd as isize, || item.Select())?;
                    // Some providers (WinForms radio buttons) accept Select
                    // without selecting; their Invoke is the click.
                    if !selected() {
                        if let Some(invoke) = element
                            .GetCurrentPattern(UIA_InvokePatternId)
                            .ok()
                            .and_then(|p| p.cast::<IUIAutomationInvokePattern>().ok())
                        {
                            crate::uia::fg_bypass::run_with_uwp_bypass(hwnd as isize, || {
                                invoke.Invoke()
                            })?;
                            return Ok(Some("InvokePattern"));
                        }
                    }
                }
                "off" => crate::uia::fg_bypass::run_with_uwp_bypass(hwnd as isize, || {
                    item.RemoveFromSelection()
                })?,
                _ => return Ok(None),
            }
            return Ok(Some("SelectionItemPattern"));
        }
    }
    Ok(None)
}

/// Dove (W2.3): pick the item named `value` in a UIA combo box (not a native
/// Win32 one): ExpandCollapse to publish the items, SelectionItem.Select on
/// the match, collapse again. `Ok(None)` when no item has that name, so the
/// caller can fall back to a ValuePattern write.
pub(crate) fn select_combo_item(
    element: &IUIAutomationElement,
    hwnd: u64,
    value: &str,
) -> anyhow::Result<Option<&'static str>> {
    let Some(automation) = automation() else {
        return Ok(None);
    };
    unsafe {
        let expand = element
            .GetCurrentPattern(UIA_ExpandCollapsePatternId)
            .ok()
            .and_then(|p| p.cast::<IUIAutomationExpandCollapsePattern>().ok());
        let was_collapsed = expand
            .as_ref()
            .and_then(|p| p.CurrentExpandCollapseState().ok())
            .is_some_and(|state| state == ExpandCollapseState_Collapsed);
        if let (Some(expand), true) = (expand.as_ref(), was_collapsed) {
            let _ = crate::uia::fg_bypass::run_with_uwp_bypass(hwnd as isize, || expand.Expand());
        }
        let condition = automation.CreatePropertyCondition(
            UIA_ControlTypePropertyId,
            &windows::core::VARIANT::from(UIA_ListItemControlTypeId.0),
        )?;
        let mut found = None;
        if let Ok(items) = element.FindAll(TreeScope_Descendants, &condition) {
            for i in 0..items.Length().unwrap_or(0) {
                let Ok(item) = items.GetElement(i) else {
                    continue;
                };
                let name = item
                    .CurrentName()
                    .map(|n| n.to_string())
                    .unwrap_or_default();
                if name.trim().eq_ignore_ascii_case(value.trim()) {
                    found = Some(item);
                    break;
                }
            }
        }
        let selected = match found
            .as_ref()
            .and_then(|item| item.GetCurrentPattern(UIA_SelectionItemPatternId).ok())
            .and_then(|p| p.cast::<IUIAutomationSelectionItemPattern>().ok())
        {
            Some(pattern) => {
                crate::uia::fg_bypass::run_with_uwp_bypass(hwnd as isize, || pattern.Select())?;
                true
            }
            None => false,
        };
        if let (Some(expand), true) = (expand.as_ref(), was_collapsed) {
            let _ = crate::uia::fg_bypass::run_with_uwp_bypass(hwnd as isize, || expand.Collapse());
        }
        Ok(selected.then_some("SelectionItemPattern"))
    }
}

fn format_number(value: f64) -> String {
    if value.fract() == 0.0 && value.abs() < 1e15 {
        format!("{}", value as i64)
    } else {
        format!("{value}")
    }
}

/// Borrow the COM element a retained snapshot row holds, without releasing it.
fn with_retained<T>(
    retained: &RetainedElement,
    f: impl FnOnce(&IUIAutomationElement) -> T,
) -> Option<T> {
    if !retained.is_uia() || retained.as_ptr() == 0 {
        return None;
    }
    let element = std::mem::ManuallyDrop::new(unsafe {
        IUIAutomationElement::from_raw(retained.as_ptr() as *mut _)
    });
    Some(f(&element))
}

// ── Window fingerprint ───────────────────────────────────────────────────────

/// Rows longer than this are cut, so a large document does not dominate.
const ROW_TEXT_LIMIT: usize = 160;
const MAX_ROWS: usize = 4000;
/// A window whose fingerprint takes longer than this is not probed again for
/// a while: the probe would cost more than it tells.
const SLOW_FINGERPRINT: Duration = Duration::from_millis(400);
const SLOW_RETRY_AFTER: Duration = Duration::from_secs(120);

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct WindowFingerprint {
    rows: Vec<String>,
    windows: Vec<String>,
}

fn slow_windows() -> &'static Mutex<HashMap<u64, Instant>> {
    static SLOW: OnceLock<Mutex<HashMap<u64, Instant>>> = OnceLock::new();
    SLOW.get_or_init(Default::default)
}

fn window_class(hwnd: u64) -> String {
    use windows::Win32::UI::WindowsAndMessaging::GetClassNameW;
    let mut buf = [0u16; 128];
    let n = unsafe { GetClassNameW(HWND(hwnd as *mut _), &mut buf) };
    if n <= 0 {
        return String::new();
    }
    String::from_utf16_lossy(&buf[..n as usize])
}

fn window_title(hwnd: u64) -> String {
    use windows::Win32::UI::WindowsAndMessaging::GetWindowTextW;
    let mut buf = [0u16; 256];
    let n = unsafe { GetWindowTextW(HWND(hwnd as *mut _), &mut buf) };
    if n <= 0 {
        return String::new();
    }
    String::from_utf16_lossy(&buf[..n as usize])
}

fn fingerprintable(hwnd: u64) -> bool {
    if hwnd == 0
        || crate::input::is_chromium_target_window(hwnd)
        || window_class(hwnd).starts_with("SAL")
    {
        return false;
    }
    let mut slow = slow_windows().lock().unwrap_or_else(|e| e.into_inner());
    slow.retain(|_, since| since.elapsed() < SLOW_RETRY_AFTER);
    !slow.contains_key(&hwnd)
}

fn cached_text(element: &IUIAutomationElement, property: UIA_PROPERTY_ID) -> String {
    unsafe { element.GetCachedPropertyValue(property) }
        .map(|value| value.to_string())
        .unwrap_or_default()
}

/// `before` is the check ahead of an action: it skips windows known to be
/// slow. The checks after an action always run once the first one did.
fn fingerprint(hwnd: u64, pid: u32, before: bool) -> Option<WindowFingerprint> {
    if before && !fingerprintable(hwnd) {
        return None;
    }
    let started = Instant::now();
    let automation = automation()?;
    let rows = unsafe {
        let cache = automation.CreateCacheRequest().ok()?;
        for property in [
            UIA_ControlTypePropertyId,
            UIA_NamePropertyId,
            UIA_AutomationIdPropertyId,
            UIA_IsEnabledPropertyId,
            UIA_ValueValuePropertyId,
            UIA_ToggleToggleStatePropertyId,
            UIA_SelectionItemIsSelectedPropertyId,
            UIA_ExpandCollapseExpandCollapseStatePropertyId,
            UIA_RangeValueValuePropertyId,
            UIA_IsPasswordPropertyId,
        ] {
            let _ = cache.AddProperty(property);
        }
        let _ = cache.SetTreeScope(TreeScope_Subtree);
        if let Ok(condition) = automation.ControlViewCondition() {
            let _ = cache.SetTreeFilter(&condition);
        }
        let root = match automation
            .ElementFromHandle(HWND(hwnd as *mut _))
            .and_then(|element| element.BuildUpdatedCache(&cache))
        {
            Ok(root) => root,
            Err(error) => {
                tracing::debug!(target: "dove_actions", "fingerprint 0x{hwnd:x}: {error}");
                return None;
            }
        };
        let mut rows = Vec::new();
        collect_rows(&root, 0, &mut rows);
        rows
    };
    let windows = crate::win32::list_windows_via_win32(Some(pid))
        .into_iter()
        .filter(|window| window.is_on_screen)
        .map(|window| format!("{:x}|{}", window.hwnd, window.title))
        .collect();
    if started.elapsed() > SLOW_FINGERPRINT {
        slow_windows()
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .insert(hwnd, Instant::now());
    }
    Some(WindowFingerprint { rows, windows })
}

unsafe fn collect_rows(element: &IUIAutomationElement, depth: usize, rows: &mut Vec<String>) {
    if rows.len() >= MAX_ROWS || depth > 64 {
        return;
    }
    let control_type = element.CachedControlType().map(|c| c.0).unwrap_or(0);
    let password = element
        .GetCachedPropertyValue(UIA_IsPasswordPropertyId)
        .ok()
        .and_then(|v| bool::try_from(&v).ok())
        .unwrap_or(false);
    // A password field's value is never read into the fingerprint; its
    // length still shows that it changed.
    let value = cached_text(element, UIA_ValueValuePropertyId);
    let value = if password {
        format!("<{} chars>", value.chars().count())
    } else {
        value.chars().take(ROW_TEXT_LIMIT).collect()
    };
    rows.push(format!(
        "{depth}|{}|{}|{}|{}|{value}|{}|{}|{}|{}",
        role_name(control_type),
        cached_text(element, UIA_AutomationIdPropertyId),
        cached_text(element, UIA_NamePropertyId)
            .chars()
            .take(ROW_TEXT_LIMIT)
            .collect::<String>(),
        cached_text(element, UIA_IsEnabledPropertyId),
        cached_text(element, UIA_ToggleToggleStatePropertyId),
        cached_text(element, UIA_SelectionItemIsSelectedPropertyId),
        cached_text(element, UIA_ExpandCollapseExpandCollapseStatePropertyId),
        cached_text(element, UIA_RangeValueValuePropertyId),
    ));
    let Ok(children) = element.GetCachedChildren() else {
        return;
    };
    let count = children.Length().unwrap_or(0);
    for index in 0..count {
        if let Ok(child) = children.GetElement(index) {
            collect_rows(&child, depth + 1, rows);
        }
    }
}

/// What differs between two fingerprints, in a few words, or `None` when
/// nothing does.
fn describe_difference(before: &WindowFingerprint, after: &WindowFingerprint) -> Option<String> {
    if before == after {
        return None;
    }
    let mut parts = Vec::new();
    let opened: Vec<&String> = after
        .windows
        .iter()
        .filter(|w| !before.windows.contains(w))
        .collect();
    let closed: Vec<&String> = before
        .windows
        .iter()
        .filter(|w| !after.windows.contains(w))
        .collect();
    let title = |w: &String| {
        w.split_once('|')
            .map(|(_, t)| t.to_owned())
            .unwrap_or_default()
    };
    if !opened.is_empty() {
        parts.push(format!(
            "window opened: {}",
            opened
                .iter()
                .map(|w| format!("'{}'", title(w)))
                .collect::<Vec<_>>()
                .join(", ")
        ));
    }
    if !closed.is_empty() {
        parts.push(format!(
            "window closed: {}",
            closed
                .iter()
                .map(|w| format!("'{}'", title(w)))
                .collect::<Vec<_>>()
                .join(", ")
        ));
    }
    let mut remaining: HashMap<&str, usize> = HashMap::new();
    for row in &before.rows {
        *remaining.entry(row.as_str()).or_default() += 1;
    }
    let mut new_rows = Vec::new();
    for row in &after.rows {
        match remaining.get_mut(row.as_str()) {
            Some(count) if *count > 0 => *count -= 1,
            _ => new_rows.push(row),
        }
    }
    let gone = remaining.values().sum::<usize>();
    if !new_rows.is_empty() || gone > 0 {
        let shown: Vec<String> = new_rows
            .iter()
            .take(3)
            .map(|row| {
                let fields: Vec<&str> = row.split('|').collect();
                let role = fields.get(1).copied().unwrap_or_default();
                let name = fields.get(3).copied().unwrap_or_default();
                let value = fields.get(5).copied().unwrap_or_default();
                match (name.is_empty(), value.is_empty()) {
                    (false, false) => format!("{role} '{name}' = '{value}'"),
                    (false, true) => format!("{role} '{name}'"),
                    (true, false) => format!("{role} = '{value}'"),
                    (true, true) => role.to_owned(),
                }
            })
            .collect();
        parts.push(format!(
            "{} element(s) changed or appeared, {gone} changed or gone{}",
            new_rows.len(),
            if shown.is_empty() {
                String::new()
            } else {
                format!(" (now: {})", shown.join("; "))
            }
        ));
    }
    Some(parts.join("; "))
}

// ── Before/after probe ───────────────────────────────────────────────────────

/// Tools whose effect is probed.
fn probed_tool(tool: &str) -> bool {
    matches!(
        tool,
        "click"
            | "double_click"
            | "right_click"
            | "set_value"
            | "type_text"
            | "press_key"
            | "hotkey"
            | "scroll"
            | "drag"
    )
}

/// Tools whose window change may upgrade an unverifiable effect to
/// `confirmed`.
fn window_change_confirms(tool: &str) -> bool {
    matches!(
        tool,
        "click" | "double_click" | "right_click" | "press_key" | "hotkey" | "scroll" | "drag"
    )
}

#[derive(Clone)]
struct ProbeTarget {
    pid: u32,
    hwnd: u64,
    element: Option<RetainedElement>,
}

#[derive(Default)]
struct Observation {
    window: Option<WindowFingerprint>,
    value: Option<String>,
}

fn observe(
    target: &ProbeTarget,
    read_value: bool,
    fingerprint_window: bool,
    before: bool,
) -> Observation {
    let value = if read_value {
        target
            .element
            .as_ref()
            .and_then(|element| {
                with_retained(element, |e| {
                    // Never read a password field's value.
                    let password = unsafe { e.CurrentIsPassword() }
                        .map(|b| b.as_bool())
                        .unwrap_or(false);
                    if password {
                        None
                    } else {
                        element_value(e)
                    }
                })
            })
            .flatten()
    } else {
        None
    };
    let window = if fingerprint_window {
        fingerprint(target.hwnd, target.pid, before)
    } else {
        None
    };
    Observation { window, value }
}

/// How long the probe waits for a change after the action, in steps.
const AFTER_POLL_MS: [u64; 5] = [0, 40, 60, 100, 150];

/// Two read-backs of one element are the same value ("42" and "42.0" are).
fn same_value(a: &str, b: &str) -> bool {
    a == b
        || matches!(
            (a.trim().parse::<f64>(), b.trim().parse::<f64>()),
            (Ok(x), Ok(y)) if (x - y).abs() < 1e-9
        )
}

fn requested_value_matches(requested: &str, seen: &str) -> bool {
    if requested == seen || requested.trim().eq_ignore_ascii_case(seen.trim()) {
        return true;
    }
    if let (Some(a), Some(b)) = (canonical_state(requested), canonical_state(seen)) {
        return a == b;
    }
    match (requested.trim().parse::<f64>(), seen.trim().parse::<f64>()) {
        (Ok(a), Ok(b)) => (a - b).abs() < 1e-9,
        _ => false,
    }
}

struct Verdict {
    change: ObservedChange,
    evidence: Option<ActionEvidence>,
}

fn verdict(
    tool: &str,
    args: &Value,
    before: &Observation,
    after: &Observation,
    chromium: bool,
) -> Verdict {
    let value_tool = matches!(tool, "set_value" | "type_text");
    let window_diff = match (&before.window, &after.window) {
        (Some(b), Some(a)) => Some(describe_difference(b, a)),
        _ => None,
    };
    let change = match (&before.value, &after.value) {
        (Some(b), Some(a)) if value_tool => {
            if !same_value(a, b) {
                ObservedChange::Changed
            } else {
                ObservedChange::Unchanged
            }
        }
        _ => match &window_diff {
            Some(Some(_)) => ObservedChange::Changed,
            Some(None) => ObservedChange::Unchanged,
            None => ObservedChange::Unverifiable,
        },
    };
    let evidence = if tool == "set_value" && !chromium {
        let requested = args
            .get("value")
            .and_then(Value::as_str)
            .unwrap_or_default();
        after
            .value
            .as_deref()
            .filter(|seen| requested_value_matches(requested, seen))
            .map(|seen| ActionEvidence {
                kind: EvidenceKind::ValueReadback,
                detail: format!(
                    "the element reads back '{}'",
                    seen.chars().take(ROW_TEXT_LIMIT).collect::<String>()
                ),
            })
    } else if window_change_confirms(tool) && change == ObservedChange::Changed && !chromium {
        window_diff.flatten().map(|detail| ActionEvidence {
            kind: EvidenceKind::WindowChange,
            detail,
        })
    } else {
        None
    };
    Verdict { change, evidence }
}

fn evidence_kind_name(kind: EvidenceKind) -> &'static str {
    match kind {
        EvidenceKind::ValueReadback => "value_readback",
        EvidenceKind::WindowChange => "window_change",
        _ => "accessibility_readback",
    }
}

/// Write the verdict into the result, in its record or its legacy payload.
fn apply_verdict(result: &mut ToolResult, verdict: Verdict) {
    if result.is_error == Some(true) {
        return;
    }
    if let Some(record) = result.action_record.as_mut() {
        if record.effect == ActionEffect::Refused {
            return;
        }
        record.observed_change = Some(verdict.change);
        if let Some(evidence) = verdict.evidence {
            if matches!(
                record.effect,
                ActionEffect::Unverifiable | ActionEffect::SuspectedNoop
            ) {
                record.effect = ActionEffect::Confirmed;
                record.escalation = None;
            }
            if !record.evidence.iter().any(|e| e.kind == evidence.kind) {
                record.evidence.push(evidence);
            }
        }
        return;
    }
    let structured = result.structured_content.get_or_insert_with(|| json!({}));
    let Some(object) = structured.as_object_mut() else {
        return;
    };
    if object.get("effect").and_then(Value::as_str) == Some("refused")
        || object.get("status").and_then(Value::as_str) == Some("refused")
    {
        return;
    }
    object.insert("change".into(), verdict.change.as_str().into());
    if let Some(evidence) = verdict.evidence {
        if !matches!(
            object.get("effect").and_then(Value::as_str),
            Some("confirmed" | "partial")
        ) {
            object.insert("effect".into(), "confirmed".into());
            object.remove("escalation");
        }
        let item = json!({ "kind": evidence_kind_name(evidence.kind), "detail": evidence.detail });
        match object.get_mut("evidence").and_then(Value::as_array_mut) {
            Some(items) => items.push(item),
            None => {
                object.insert("evidence".into(), json!([item]));
            }
        }
    }
}

fn resolve_probe_target(args: &Value) -> Option<ProbeTarget> {
    if args.get("scope").and_then(Value::as_str) == Some("desktop") {
        return None;
    }
    let snapshots = cua_driver_core::snapshot_store::current_runtime_store::<UiaSnapshot>()
        .or_else(latest_snapshots);
    let pid = args
        .get("pid")
        .and_then(Value::as_u64)
        .and_then(|pid| u32::try_from(pid).ok())
        .or_else(|| {
            snapshots
                .as_ref()
                .and_then(|s| s.pid_for_token(args))
                .and_then(|pid| u32::try_from(pid).ok())
        })?;
    let (window, element) = match snapshots.as_ref().map(|s| s.resolve(pid as i32, args)) {
        Some(Ok(resolved)) => {
            let (_, window, element) =
                resolved.into_parts(args.get("window_id").and_then(Value::as_u64));
            (window, element)
        }
        // A stale token: the tool refuses it, nothing to probe.
        Some(Err(_)) => return None,
        None => (args.get("window_id").and_then(Value::as_u64), None),
    };
    let hwnd = match window {
        Some(hwnd) => hwnd,
        None => {
            crate::win32::list_windows_via_win32(Some(pid))
                .first()?
                .hwnd
        }
    };
    Some(ProbeTarget { pid, hwnd, element })
}

/// Wrap an action tool with the before/after probe.
pub(crate) fn probed(inner: Box<dyn Tool>) -> Box<dyn Tool> {
    Box::new(DoveActionProbe { inner })
}

struct DoveActionProbe {
    inner: Box<dyn Tool>,
}

#[async_trait]
impl Tool for DoveActionProbe {
    fn def(&self) -> &ToolDef {
        self.inner.def()
    }

    fn has_independent_input_lane(&self, args: &Value) -> bool {
        self.inner.has_independent_input_lane(args)
    }

    async fn protected_resource_ownership(
        &self,
        adapter_id: &str,
        args: &Value,
    ) -> cua_driver_core::tool::ProtectedResourceOwnership {
        self.inner
            .protected_resource_ownership(adapter_id, args)
            .await
    }

    async fn protected_resource_scope(
        &self,
        adapter_id: &str,
        args: &Value,
    ) -> Result<Option<Value>, String> {
        self.inner.protected_resource_scope(adapter_id, args).await
    }

    async fn validate_protected_resource_scope(
        &self,
        adapter_id: &str,
        args: &Value,
        approved_scope: &Value,
    ) -> Result<(), String> {
        self.inner
            .validate_protected_resource_scope(adapter_id, args, approved_scope)
            .await
    }

    async fn invoke(&self, args: Value) -> ToolResult {
        let tool = self.inner.def().name.clone();
        if !probed_tool(&tool) {
            return self.inner.invoke(args).await;
        }
        let Some(target) = resolve_probe_target(&args) else {
            tracing::debug!(target: "dove_actions", "{tool}: no probe target");
            return self.inner.invoke(args).await;
        };
        let read_value =
            matches!(tool.as_str(), "set_value" | "type_text") && target.element.is_some();
        let chromium = crate::input::is_chromium_target_window(target.hwnd);
        let before_target = target.clone();
        let before =
            tokio::task::spawn_blocking(move || observe(&before_target, read_value, true, true))
                .await
                .unwrap_or_default();
        tracing::debug!(
            target: "dove_actions",
            "{tool}: hwnd=0x{:x} pid={} fingerprint={} value={}",
            target.hwnd,
            target.pid,
            before.window.as_ref().map_or(0, |w| w.rows.len()),
            before.value.is_some()
        );
        if before.window.is_none() && before.value.is_none() {
            return self.inner.invoke(args).await;
        }
        let fingerprint_window = before.window.is_some();
        let mut result = self.inner.invoke(args.clone()).await;
        if result.is_error == Some(true) {
            return result;
        }
        let tool_for_task = tool.clone();
        let args_for_task = args.clone();
        let verdict = tokio::task::spawn_blocking(move || {
            let mut last = Observation::default();
            for wait in AFTER_POLL_MS {
                std::thread::sleep(Duration::from_millis(wait));
                last = observe(&target, read_value, fingerprint_window, false);
                let verdict = verdict(&tool_for_task, &args_for_task, &before, &last, chromium);
                if verdict.change == ObservedChange::Changed
                    && (tool_for_task != "set_value" || verdict.evidence.is_some())
                {
                    return verdict;
                }
            }
            verdict(&tool_for_task, &args_for_task, &before, &last, chromium)
        })
        .await;
        if let Ok(verdict) = verdict {
            tracing::debug!(target: "dove_actions", "{tool}: change={}", verdict.change.as_str());
            apply_verdict(&mut result, verdict);
        }
        result
    }
}

// ── Target inspector (W6) ────────────────────────────────────────────────────

fn process_file_name(pid: u32) -> String {
    crate::history::process_executable_path(pid)
        .and_then(|path| path.file_name().map(|n| n.to_string_lossy().to_lowercase()))
        .unwrap_or_default()
}

/// The OS prompt a window belongs to, if any.
pub(crate) fn prompt_kind(process: &str, class: &str, title: &str) -> Option<SecureKind> {
    match process {
        "consent.exe" => return Some(SecureKind::ElevationPrompt),
        "credentialuibroker.exe" | "logonui.exe" => return Some(SecureKind::CredentialPrompt),
        _ => {}
    }
    if class == "Credential Dialog Xaml Host"
        || (title == "Windows Security"
            && matches!(class, "#32770" | "Credential Dialog Xaml Host"))
    {
        return Some(SecureKind::CredentialPrompt);
    }
    None
}

fn window_prompt_kind(hwnd: u64) -> Option<SecureKind> {
    let pid = crate::win32::window_owner_pid(hwnd)?;
    prompt_kind(
        &process_file_name(pid),
        &window_class(hwnd),
        &window_title(hwnd),
    )
}

/// The input desktop is not `Default`: the UAC secure desktop or the lock
/// screen. A process on `Default` cannot open `Winlogon`, so access denied in
/// an interactive session means the same.
fn secure_desktop_active() -> bool {
    use windows::Win32::System::RemoteDesktop::ProcessIdToSessionId;
    use windows::Win32::System::StationsAndDesktops::{
        CloseDesktop, GetUserObjectInformationW, OpenInputDesktop, DESKTOP_ACCESS_FLAGS,
        DESKTOP_CONTROL_FLAGS, UOI_NAME,
    };
    unsafe {
        match OpenInputDesktop(
            DESKTOP_CONTROL_FLAGS(0),
            windows::Win32::Foundation::BOOL::from(false),
            DESKTOP_ACCESS_FLAGS(0),
        ) {
            Ok(desktop) => {
                let mut buf = [0u16; 64];
                let mut needed = 0u32;
                let ok = GetUserObjectInformationW(
                    windows::Win32::Foundation::HANDLE(desktop.0),
                    UOI_NAME,
                    Some(buf.as_mut_ptr().cast()),
                    (buf.len() * 2) as u32,
                    Some(&mut needed as *mut u32),
                )
                .is_ok();
                let _ = CloseDesktop(desktop);
                if !ok {
                    return false;
                }
                let len = buf.iter().position(|&c| c == 0).unwrap_or(buf.len());
                let name = String::from_utf16_lossy(&buf[..len]);
                !name.is_empty() && !name.eq_ignore_ascii_case("Default")
            }
            Err(error) => {
                let mut session = 0u32;
                let interactive =
                    ProcessIdToSessionId(std::process::id(), &mut session).is_ok() && session != 0;
                interactive && error.code() == windows::Win32::Foundation::E_ACCESSDENIED
            }
        }
    }
}

fn describe_element(element: &IUIAutomationElement, info: &mut TargetInfo) {
    unsafe {
        let control_type = element.CurrentControlType().map(|c| c.0).unwrap_or(0);
        info.role = role_name(control_type);
        info.name = element
            .CurrentName()
            .map(|n| n.to_string())
            .unwrap_or_default();
        info.editable = is_editable_role(control_type);
        let password = element
            .CurrentIsPassword()
            .map(|b| b.as_bool())
            .unwrap_or(false);
        if password {
            info.secure = Some(SecureKind::Password);
            return;
        }
        let automation_id = element
            .CurrentAutomationId()
            .map(|n| n.to_string())
            .unwrap_or_default();
        if info.editable
            && (is_payment_field_name(&info.name) || is_payment_field_name(&automation_id))
        {
            info.secure = Some(SecureKind::Payment);
        }
        info.value = element
            .GetCurrentPattern(UIA_ValuePatternId)
            .ok()
            .and_then(|p| p.cast::<IUIAutomationValuePattern>().ok())
            .and_then(|p| p.CurrentValue().ok())
            .map(|v| v.to_string().chars().take(256).collect());
    }
}

/// A focused Win32 edit with `ES_PASSWORD` or a password character.
fn win32_password_edit(hwnd: u64) -> bool {
    use windows::Win32::UI::WindowsAndMessaging::{
        GetWindowLongW, SendMessageTimeoutW, GWL_STYLE, SMTO_ABORTIFHUNG,
    };
    const ES_PASSWORD: i32 = 0x0020;
    const EM_GETPASSWORDCHAR: u32 = 0x00D2;
    let window = HWND(hwnd as *mut _);
    let class = window_class(hwnd).to_ascii_lowercase();
    if !(class == "edit" || class.contains("edit")) {
        return false;
    }
    unsafe {
        if GetWindowLongW(window, GWL_STYLE) & ES_PASSWORD != 0 {
            return true;
        }
        let mut result = 0usize;
        let sent = SendMessageTimeoutW(
            window,
            EM_GETPASSWORDCHAR,
            windows::Win32::Foundation::WPARAM(0),
            windows::Win32::Foundation::LPARAM(0),
            SMTO_ABORTIFHUNG,
            200,
            Some(&mut result as *mut usize),
        );
        sent.0 != 0 && result != 0
    }
}

fn inspect(
    snapshots: &crate::uia::snapshot::Snapshots,
    tool: &str,
    args: &Value,
) -> Option<TargetInfo> {
    let mut info = TargetInfo::default();
    if secure_desktop_active() {
        info.secure = Some(SecureKind::ElevationPrompt);
        return Some(info);
    }
    let has_token = args.get("element_token").is_some();
    let pid = args
        .get("pid")
        .and_then(Value::as_u64)
        .and_then(|pid| u32::try_from(pid).ok())
        .or_else(|| {
            snapshots
                .pid_for_token(args)
                .and_then(|pid| u32::try_from(pid).ok())
        });
    let desktop_scope = args.get("scope").and_then(Value::as_str) == Some("desktop")
        || (pid.is_none() && args.get("window_id").is_none() && !has_token);
    let mut element: Option<RetainedElement> = None;
    let mut window = args.get("window_id").and_then(Value::as_u64);
    if let (Some(pid), true) = (pid, has_token) {
        if let Ok(resolved) = snapshots.resolve(pid as i32, args) {
            let (_, token_window, retained) = resolved.into_parts(window);
            window = token_window;
            element = retained;
        }
    }
    let hwnd = match (window, pid) {
        (Some(hwnd), _) => Some(hwnd),
        _ if desktop_scope => crate::input::mouse::foreground_window().ok(),
        (None, Some(pid)) => crate::win32::list_windows_via_win32(Some(pid))
            .first()
            .map(|w| w.hwnd),
        (None, None) => None,
    };
    if let Some(kind) = hwnd.and_then(window_prompt_kind) {
        info.secure = Some(kind);
        return Some(info);
    }
    if let Some(pid) = pid {
        if let Some(kind) = prompt_kind(&process_file_name(pid), "", "") {
            info.secure = Some(kind);
            return Some(info);
        }
    }
    if let Some(retained) = element.as_ref() {
        with_retained(retained, |e| describe_element(e, &mut info));
        return Some(info);
    }
    // No element token: text and keys go to the window's focused control.
    let keyboard = matches!(
        tool,
        "type_text" | "type_text_chars" | "press_key" | "hotkey" | "set_value"
    );
    if keyboard {
        if let Some(focus) = hwnd.and_then(|hwnd| {
            crate::input::keyboard::wait_for_focused_descendant(hwnd, Duration::ZERO)
        }) {
            if win32_password_edit(focus) {
                info.role = "Edit".into();
                info.editable = true;
                info.secure = Some(SecureKind::Password);
                return Some(info);
            }
            if let Some(automation) = automation() {
                if let Ok(element) = unsafe { automation.ElementFromHandle(HWND(focus as *mut _)) }
                {
                    describe_element(&element, &mut info);
                }
            }
            return Some(info);
        }
    }
    hwnd.map(|_| info)
}

fn latest_slot() -> &'static Mutex<Option<Arc<crate::uia::snapshot::Snapshots>>> {
    static LATEST: OnceLock<Mutex<Option<Arc<crate::uia::snapshot::Snapshots>>>> = OnceLock::new();
    LATEST.get_or_init(Default::default)
}

/// The snapshot store of the registry built last, for a dispatch that runs
/// outside a runtime scope.
fn latest_snapshots() -> Option<Arc<crate::uia::snapshot::Snapshots>> {
    latest_slot()
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .clone()
}

/// The inspector `cua_driver_core::dove_safety` calls before a guarded action.
pub(crate) fn target_inspector(snapshots: Arc<crate::uia::snapshot::Snapshots>) -> TargetInspector {
    *latest_slot().lock().unwrap_or_else(|e| e.into_inner()) = Some(snapshots.clone());
    Arc::new(move |tool, args| inspect(&snapshots, tool, args))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn print(rows: &[&str], windows: &[&str]) -> WindowFingerprint {
        WindowFingerprint {
            rows: rows.iter().map(|r| r.to_string()).collect(),
            windows: windows.iter().map(|w| w.to_string()).collect(),
        }
    }

    #[test]
    fn identical_fingerprints_have_no_difference() {
        let a = print(&["0|Window||Form|True|||||"], &["1|Form"]);
        assert_eq!(describe_difference(&a, &a.clone()), None);
    }

    #[test]
    fn a_changed_label_is_described() {
        let before = print(
            &["0|Window||Form|True|||||", "1|Text|status|Ready|True|||||"],
            &["1|Form"],
        );
        let after = print(
            &[
                "0|Window||Form|True|||||",
                "1|Text|status|Clicked|True|||||",
            ],
            &["1|Form"],
        );
        let detail = describe_difference(&before, &after).unwrap();
        assert!(detail.contains("Text 'Clicked'"), "{detail}");
    }

    #[test]
    fn a_new_window_is_described() {
        let before = print(&["0|Window||Form|True|||||"], &["1|Form"]);
        let after = print(&["0|Window||Form|True|||||"], &["1|Form", "2|Save As"]);
        assert!(describe_difference(&before, &after)
            .unwrap()
            .contains("window opened: 'Save As'"));
    }

    #[test]
    fn prompts_are_recognised() {
        assert_eq!(
            prompt_kind("consent.exe", "", ""),
            Some(SecureKind::ElevationPrompt)
        );
        assert_eq!(
            prompt_kind("credentialuibroker.exe", "", ""),
            Some(SecureKind::CredentialPrompt)
        );
        assert_eq!(
            prompt_kind("app.exe", "#32770", "Windows Security"),
            Some(SecureKind::CredentialPrompt)
        );
        assert_eq!(prompt_kind("app.exe", "#32770", "Save As"), None);
    }

    fn observed(window: Option<WindowFingerprint>, value: Option<&str>) -> Observation {
        Observation {
            window,
            value: value.map(str::to_owned),
        }
    }

    #[test]
    fn click_window_change_confirms() {
        let a = print(&["1|Text|s|Ready|True|||||"], &[]);
        let b = print(&["1|Text|s|Done|True|||||"], &[]);
        let v = verdict(
            "click",
            &json!({}),
            &observed(Some(a.clone()), None),
            &observed(Some(b), None),
            false,
        );
        assert_eq!(v.change, ObservedChange::Changed);
        assert_eq!(v.evidence.unwrap().kind, EvidenceKind::WindowChange);
        let v = verdict(
            "click",
            &json!({}),
            &observed(Some(a.clone()), None),
            &observed(Some(a.clone()), None),
            false,
        );
        assert_eq!(v.change, ObservedChange::Unchanged);
        assert!(v.evidence.is_none());
        // Chromium echoes: never confirm from its tree.
        let b = print(&["1|Text|s|Done|True|||||"], &[]);
        let v = verdict(
            "click",
            &json!({}),
            &observed(Some(a), None),
            &observed(Some(b), None),
            true,
        );
        assert!(v.evidence.is_none());
    }

    #[test]
    fn set_value_readback_confirms_even_when_unchanged() {
        let args = json!({"value": "42"});
        let v = verdict(
            "set_value",
            &args,
            &observed(None, Some("42")),
            &observed(None, Some("42.0")),
            false,
        );
        assert_eq!(v.change, ObservedChange::Unchanged);
        assert_eq!(v.evidence.unwrap().kind, EvidenceKind::ValueReadback);
        let v = verdict(
            "set_value",
            &args,
            &observed(None, Some("1")),
            &observed(None, Some("2")),
            false,
        );
        assert_eq!(v.change, ObservedChange::Changed);
        assert!(v.evidence.is_none());
    }

    #[test]
    fn state_words_match_across_spellings() {
        assert!(requested_value_matches("true", "on"));
        assert!(requested_value_matches("checked", "on"));
        assert!(requested_value_matches("selected", "on"));
        assert!(requested_value_matches("Banana", "banana"));
        assert!(!requested_value_matches("on", "off"));
        assert!(!requested_value_matches("Apple", "Banana"));
    }

    #[test]
    fn verdict_updates_legacy_and_record_results() {
        let mut legacy = ToolResult::text("ok").with_structured(json!({
            "path": "ax", "effect": "unverifiable",
            "escalation": {"recommended": "foreground"}
        }));
        apply_verdict(
            &mut legacy,
            Verdict {
                change: ObservedChange::Changed,
                evidence: Some(ActionEvidence {
                    kind: EvidenceKind::WindowChange,
                    detail: "x".into(),
                }),
            },
        );
        let s = legacy.structured_content.unwrap();
        assert_eq!(s["effect"], "confirmed");
        assert_eq!(s["change"], "changed");
        assert_eq!(s["evidence"][0]["kind"], "window_change");
        assert!(s.get("escalation").is_none());

        use cua_driver_core::action_record::{
            ActionExecutionRecord, ActionTransport, ActualDelivery, RequestedDelivery,
        };
        let mut record = ActionExecutionRecord::new(
            ActionEffect::Unverifiable,
            ActionTransport::WindowsUiaInvoke,
            RequestedDelivery::Background,
        );
        record.actual_delivery = Some(ActualDelivery::Background);
        let mut with_record = ToolResult::text("ok").with_action_record(record);
        apply_verdict(
            &mut with_record,
            Verdict {
                change: ObservedChange::Changed,
                evidence: Some(ActionEvidence {
                    kind: EvidenceKind::WindowChange,
                    detail: "label".into(),
                }),
            },
        );
        let record = with_record.action_record.unwrap();
        assert_eq!(record.effect, ActionEffect::Confirmed);
        let public = serde_json::to_value(record.public_result().unwrap()).unwrap();
        assert_eq!(public["change"], "changed");
        assert_eq!(public["via"], "uia_invoke");
        assert_eq!(public["delivery"]["mode"], "background");
    }
}
