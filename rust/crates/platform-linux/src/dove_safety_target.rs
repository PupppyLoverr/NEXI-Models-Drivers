//! Dove (ROADMAP W6) on Linux: what a guarded action targets, for
//! `cua_driver_core::dove_safety`.
//!
//! - An element whose AT-SPI role is `password text` (`ROLE_PASSWORD_TEXT`)
//!   → password. The role comes from the snapshot row the `element_token`
//!   names, so no D-Bus call is made.
//! - A target process that is a polkit authentication agent, the GNOME
//!   keyring prompter (`gcr-prompter`), `pinentry` or the KDE wallet daemon →
//!   credential prompt, for every action.
//!
//! The element's accessible name is not in the snapshot row, so the
//! confirm/block classes see only the role and the call's `intent`.
//!
//! Unverified until W7 CI: written against the upstream AT-SPI snapshot
//! types, not compiled or run on Linux in this change.

use std::sync::Arc;

use cua_driver_core::dove_safety::{SecureKind, TargetInfo, TargetInspector};
use serde_json::Value;

use crate::atspi::snapshot::Snapshots;

/// A credential prompt process, by its `/proc/<pid>/comm` name.
pub(crate) fn is_prompt_process(comm: &str) -> bool {
    comm.starts_with("polkit-") && comm.contains("agent")
        || comm == "polkit-agent-helper-1"
        || comm == "gcr-prompter"
        || comm.starts_with("pinentry")
        || comm.starts_with("kwalletd")
        || comm == "ksecretd"
}

fn editable_role(role: &str) -> bool {
    matches!(
        role,
        "text" | "entry" | "terminal" | "document text" | "paragraph" | "editbar" | "password text"
    )
}

fn inspect(snapshots: &Snapshots, _tool: &str, args: &Value) -> Option<TargetInfo> {
    let mut info = TargetInfo::default();
    let pid = args
        .get("pid")
        .and_then(Value::as_i64)
        .and_then(|pid| i32::try_from(pid).ok())
        .or_else(|| snapshots.pid_for_token(args))?;
    let comm = std::fs::read_to_string(format!("/proc/{pid}/comm")).unwrap_or_default();
    if is_prompt_process(comm.trim()) {
        info.secure = Some(SecureKind::CredentialPrompt);
        return Some(info);
    }
    if let Ok(cua_driver_core::element_token::ResolvedElement::Element { element, .. }) =
        snapshots.resolve(pid, args)
    {
        let role = element.role.to_lowercase();
        info.editable = editable_role(&role);
        if role == "password text" {
            info.secure = Some(SecureKind::Password);
        }
        info.role = element.role.clone();
    }
    Some(info)
}

/// The inspector `cua_driver_core::dove_safety` calls before a guarded action.
pub(crate) fn target_inspector(snapshots: Arc<Snapshots>) -> TargetInspector {
    Arc::new(move |tool, args| inspect(&snapshots, tool, args))
}

#[cfg(test)]
mod tests {
    #[test]
    fn prompt_processes() {
        assert!(super::is_prompt_process(
            "polkit-gnome-authentication-agent-1"
        ));
        assert!(super::is_prompt_process("gcr-prompter"));
        assert!(super::is_prompt_process("pinentry-gnome3"));
        assert!(!super::is_prompt_process("gedit"));
    }
}
