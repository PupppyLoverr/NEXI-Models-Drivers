//! Dove (ROADMAP W6) on macOS: what a guarded action targets, for
//! `cua_driver_core::dove_safety`.
//!
//! - `AXSecureTextField` (subrole) or `AXSecureTextField` role → password.
//! - An editable field named like a card number, CVC or expiry → payment.
//! - The authorization and Touch ID / password agents (`SecurityAgent`,
//!   `coreautha`/`CoreAuthUI`, the LocalAuthentication UI agent) → credential
//!   prompt, for every action.
//!
//! Without an `element_token`, text and keys go to the app's
//! `AXFocusedUIElement`, so that element is inspected.
//!
//! Unverified until W7 CI: written against the upstream AX bindings, not
//! compiled or run on macOS in this change.

use std::sync::Arc;

use cua_driver_core::dove_safety::{
    is_payment_field_name, SecureKind, TargetInfo, TargetInspector,
};
use serde_json::Value;

use crate::ax::bindings::{copy_string_attr, focused_element_of_pid, AXUIElementRef};
use crate::ax::snapshot::Snapshots;

const PROMPT_BUNDLES: &[&str] = &[
    "com.apple.SecurityAgent",
    "com.apple.CoreAuthUI",
    "com.apple.LocalAuthentication.UIAgent",
    "com.apple.coreautha",
];

fn describe(element: AXUIElementRef, info: &mut TargetInfo) {
    unsafe {
        let role = copy_string_attr(element, "AXRole").unwrap_or_default();
        let subrole = copy_string_attr(element, "AXSubrole").unwrap_or_default();
        info.name = copy_string_attr(element, "AXTitle")
            .filter(|s| !s.trim().is_empty())
            .or_else(|| copy_string_attr(element, "AXDescription"))
            .or_else(|| copy_string_attr(element, "AXPlaceholderValue"))
            .unwrap_or_default();
        info.editable = matches!(
            role.as_str(),
            "AXTextField" | "AXTextArea" | "AXComboBox" | "AXSearchField"
        );
        if role == "AXSecureTextField" || subrole == "AXSecureTextField" {
            info.role = role;
            info.editable = true;
            info.secure = Some(SecureKind::Password);
            return;
        }
        let identifier = copy_string_attr(element, "AXIdentifier").unwrap_or_default();
        if info.editable
            && (is_payment_field_name(&info.name) || is_payment_field_name(&identifier))
        {
            info.secure = Some(SecureKind::Payment);
        }
        info.value = copy_string_attr(element, "AXValue").map(|v| v.chars().take(256).collect());
        info.role = role;
    }
}

fn inspect(snapshots: &Snapshots, tool: &str, args: &Value) -> Option<TargetInfo> {
    let mut info = TargetInfo::default();
    let pid = args
        .get("pid")
        .and_then(Value::as_i64)
        .and_then(|pid| i32::try_from(pid).ok())
        .or_else(|| snapshots.pid_for_token(args))?;
    if crate::apps::bundle_id_for_pid(pid)
        .is_some_and(|bundle| PROMPT_BUNDLES.contains(&bundle.as_str()))
    {
        info.secure = Some(SecureKind::CredentialPrompt);
        return Some(info);
    }
    if args.get("element_token").is_some() {
        if let Ok(cua_driver_core::element_token::ResolvedElement::Element { element, .. }) =
            snapshots.resolve(pid, args)
        {
            describe(element.as_ptr() as AXUIElementRef, &mut info);
        }
        return Some(info);
    }
    if matches!(
        tool,
        "type_text" | "type_text_chars" | "press_key" | "hotkey" | "set_value"
    ) {
        unsafe {
            if let Some(focused) = focused_element_of_pid(pid) {
                describe(focused, &mut info);
                core_foundation::base::CFRelease(focused as core_foundation::base::CFTypeRef);
            }
        }
    }
    Some(info)
}

/// The inspector `cua_driver_core::dove_safety` calls before a guarded action.
pub(crate) fn target_inspector(snapshots: Arc<Snapshots>) -> TargetInspector {
    Arc::new(move |tool, args| inspect(&snapshots, tool, args))
}
