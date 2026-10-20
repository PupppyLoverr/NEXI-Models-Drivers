//! Dove (ROADMAP W6): stop and hand off at secure fields and system prompts,
//! and gate actions through the confirm/block classes of nexi-cua.
//!
//! Three checks run at the canonical dispatch seam, after the reviewed
//! authorization ladder and before the platform tool runs:
//!
//! 1. **Hand-off.** Text never goes into a password or payment field, and no
//!    action targets an elevation (UAC) prompt, the secure desktop or an OS
//!    credential dialog. The call is refused with `code: "handoff_required"`
//!    in every permission mode, so the agent asks the user to finish that
//!    step. The platform reports what the target is through a
//!    [`TargetInspector`] (UIA `IsPassword`, `AXSecureTextField`, AT-SPI
//!    `ROLE_PASSWORD_TEXT`, the owning process of the target window).
//! 2. **Blocked classes** (`code: "safety_blocked"`): never executed by the
//!    agent, in any mode.
//! 3. **Confirm classes** (`code: "confirmation_required"`): in `standard`
//!    mode the refusal carries a `confirm_token`. The agent asks the user, and
//!    after a yes repeats the call with `confirm: "<token>"`; the grant then
//!    covers that verb and class for the rest of the session, as nexi-cua's
//!    `SafetyGate.confirm` does. In `bounded` mode nobody is there to ask, so
//!    the call is refused without a token. `unrestricted` mode runs it.
//!
//! The classes are matched against the target element (its role, name and,
//! for non-editable elements, its value), the optional `intent` argument and
//! an `invoke_menu` path. They are a port of `nexi_cua/safety.py` from
//! PupppyLoverr/NEXI-Models-Drivers (Apache-2.0); see NOTICE.md.
//!
//! `DOVE_DRIVER_SAFETY_CLASSES=off` in the daemon's environment turns the
//! confirm/block classes off. The hand-off check cannot be turned off.

use std::collections::{HashMap, HashSet};
use std::sync::{Arc, Mutex, OnceLock, RwLock};
use std::time::{Duration, Instant};

use serde_json::{json, Map, Value};

use crate::authorization::PermissionMode;
use crate::protocol::ToolResult;

/// Daemon environment switch for the confirm/block classes.
pub const SAFETY_CLASSES_ENV: &str = "DOVE_DRIVER_SAFETY_CLASSES";

/// Why a target needs the user instead of the agent.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SecureKind {
    /// UIA `IsPassword`, `AXSecureTextField`, AT-SPI `ROLE_PASSWORD_TEXT`,
    /// `input[type=password]`.
    Password,
    /// A payment-card field (`autocomplete="cc-*"`, a card-number, CVC or
    /// expiry field).
    Payment,
    /// An OS credential dialog (Windows Security, a keychain or polkit
    /// password prompt).
    CredentialPrompt,
    /// An elevation prompt (UAC `consent.exe`) or the secure desktop.
    ElevationPrompt,
}

impl SecureKind {
    pub const fn reason(self) -> &'static str {
        match self {
            Self::Password => "password_field",
            Self::Payment => "payment_field",
            Self::CredentialPrompt => "credential_prompt",
            Self::ElevationPrompt => "elevation_prompt",
        }
    }

    /// Whether the kind stops every action, not only text entry.
    const fn blocks_every_action(self) -> bool {
        matches!(self, Self::CredentialPrompt | Self::ElevationPrompt)
    }

    fn hint(self) -> &'static str {
        match self {
            Self::Password => {
                "This is a password field. Do not type secrets: stop and ask the user to enter \
                 the password themselves, then continue after they say it is done."
            }
            Self::Payment => {
                "This is a payment-card field. Stop and ask the user to enter the card details \
                 themselves, then continue after they say it is done."
            }
            Self::CredentialPrompt => {
                "An OS credential dialog is showing. Stop and ask the user to answer it \
                 themselves, then continue after they say it is done."
            }
            Self::ElevationPrompt => {
                "An administrator (UAC) prompt or the secure desktop is active. Stop and ask the \
                 user to answer it themselves, then continue after they say it is done."
            }
        }
    }
}

/// What the platform knows about an action's target before it runs.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct TargetInfo {
    /// Accessibility role, for example `Button`, `AXButton`, `push button`.
    pub role: String,
    /// Accessible name (label).
    pub name: String,
    /// Current value, when the element has one.
    pub value: Option<String>,
    /// The element holds user text (edit, document, terminal). Its value is
    /// content, not a label, so it is left out of the class match.
    pub editable: bool,
    /// Set when the target must be handed to the user.
    pub secure: Option<SecureKind>,
}

/// Platform hook that describes the target of an action call. It runs on a
/// blocking thread and must return quickly; `None` means unknown.
pub type TargetInspector = Arc<dyn Fn(&str, &Value) -> Option<TargetInfo> + Send + Sync>;

/// Inspectors by dispatch runtime scope, plus the latest one.
type InspectorSlots = (HashMap<String, TargetInspector>, Option<TargetInspector>);

fn inspector_slots() -> &'static RwLock<InspectorSlots> {
    static SLOTS: OnceLock<RwLock<InspectorSlots>> = OnceLock::new();
    SLOTS.get_or_init(|| RwLock::new((HashMap::new(), None)))
}

fn runtime_scope() -> String {
    crate::tool::current_dispatch_runtime_scope().unwrap_or_else(|| "legacy".into())
}

/// Install the platform's target inspector for the runtime being built.
pub fn register_target_inspector(inspector: TargetInspector) {
    let mut slots = inspector_slots().write().unwrap_or_else(|e| e.into_inner());
    slots.0.insert(runtime_scope(), inspector.clone());
    slots.1 = Some(inspector);
}

fn current_inspector() -> Option<TargetInspector> {
    let slots = inspector_slots().read().unwrap_or_else(|e| e.into_inner());
    slots
        .0
        .get(&runtime_scope())
        .cloned()
        .or_else(|| slots.1.clone())
}

/// Tools the safety layer checks.
pub fn is_guarded_tool(tool: &str) -> bool {
    matches!(
        tool,
        "click"
            | "double_click"
            | "right_click"
            | "type_text"
            | "type_text_chars"
            | "set_value"
            | "press_key"
            | "hotkey"
            | "invoke_menu"
            | "drag"
            | "browser_click"
            | "browser_type"
    )
}

fn is_text_entry_tool(tool: &str) -> bool {
    matches!(
        tool,
        "type_text" | "type_text_chars" | "set_value" | "browser_type"
    )
}

/// Add the `intent` and `confirm` arguments to a guarded tool's advertised
/// schema.
pub fn advertise(tool: &str, properties: &mut Map<String, Value>) {
    if !is_guarded_tool(tool) {
        return;
    }
    properties.entry("intent").or_insert_with(|| {
        json!({
            "type": "string",
            "maxLength": 500,
            "description": "Optional: what this action is for, in a few words (the user's goal). \
                Checked against the safety classes together with the target element."
        })
    });
    properties.entry("confirm").or_insert_with(|| {
        json!({
            "type": "string",
            "description": "The confirm_token from a confirmation_required refusal. Pass it only \
                after the user said yes to that action."
        })
    });
}

/// The safety arguments of one call, removed from the platform arguments.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct SafetyArgs {
    pub intent: Option<String>,
    pub confirm: Option<String>,
}

/// Remove `intent` and `confirm` so platform tools never see them.
pub fn take_safety_args(tool: &str, args: &mut Value) -> SafetyArgs {
    if !is_guarded_tool(tool) {
        return SafetyArgs::default();
    }
    let Some(object) = args.as_object_mut() else {
        return SafetyArgs::default();
    };
    let take = |object: &mut Map<String, Value>, key: &str| {
        object
            .remove(key)
            .and_then(|value| value.as_str().map(str::to_owned))
            .filter(|value| !value.trim().is_empty())
    };
    SafetyArgs {
        intent: take(object, "intent"),
        confirm: take(object, "confirm"),
    }
}

fn classes_enabled() -> bool {
    !matches!(
        std::env::var(SAFETY_CLASSES_ENV)
            .ok()
            .map(|value| value.trim().to_ascii_lowercase())
            .as_deref(),
        Some("0" | "off" | "false" | "no")
    )
}

/// Risk of an action under the nexi-cua classes.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Risk {
    Safe,
    Confirm(&'static str),
    Blocked(&'static str),
}

fn words(haystack: &str) -> Vec<String> {
    haystack
        .to_lowercase()
        .split(|c: char| !c.is_alphanumeric())
        .filter(|word| !word.is_empty())
        .map(str::to_owned)
        .collect()
}

fn normalized(haystack: &str) -> String {
    haystack
        .to_lowercase()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

/// `first ... second` in word order, as nexi-cua's `\b(a)\b.*\b(b)\b`.
fn word_then_word(words: &[String], first: &[&str], second: &[&str]) -> bool {
    words
        .iter()
        .position(|word| first.contains(&word.as_str()))
        .is_some_and(|start| {
            words[start + 1..]
                .iter()
                .any(|word| second.contains(&word.as_str()))
        })
}

fn any_word(words: &[String], set: &[&str]) -> bool {
    words.iter().any(|word| set.contains(&word.as_str()))
}

/// Two adjacent words, also written as one (`sign in`, `signin`).
fn phrase(words: &[String], first: &str, second: &str) -> bool {
    let joined = format!("{first}{second}");
    words.iter().any(|word| *word == joined)
        || words
            .windows(2)
            .any(|pair| pair[0] == first && pair[1] == second)
}

/// Classify `haystack` (target role, name and value, intent, menu path).
/// `keys` are the keys of a `press_key`/`hotkey` call; `typing` is set for
/// text-entry tools. The order and the classes follow `nexi_cua.safety`:
/// blocked classes first, then confirm classes, then the key and
/// credential-field rules.
pub fn assess(haystack: &str, keys: &[String], typing: bool) -> Risk {
    let w = words(haystack);
    let flat = normalized(haystack);

    // Blocked classes.
    if any_word(&w, &["sudo", "mkfs"])
        || flat.contains("rm -rf /")
        || flat.contains("dd if=")
        || flat.contains(":(){ :|:& };:")
    {
        return Risk::Blocked("destructive shell");
    }
    // `steal` and `malware` match whole words only, as in nexi-cua; the
    // other stems also match their inflections (`exfiltrate`, `phishing`).
    if any_word(&w, &["steal", "malware"])
        || w.iter().any(|word| {
            ["exfiltrat", "keylog", "phish", "ransom"]
                .iter()
                .any(|stem| word.starts_with(stem))
        })
    {
        return Risk::Blocked("malicious intent");
    }
    if word_then_word(
        &w,
        &["bypass", "evade", "disable"],
        &["safety", "guardrail", "detection", "audit"],
    ) || (any_word(&w, &["bypass", "evade", "disable"]) && flat.contains("security control"))
    {
        return Risk::Blocked("safety-control bypass");
    }

    // Confirm classes.
    if any_word(
        &w,
        &[
            "delete", "remove", "trash", "erase", "wipe", "format", "unlink",
        ],
    ) || flat.contains("rm -rf")
    {
        return Risk::Confirm("file/data deletion");
    }
    if any_word(
        &w,
        &[
            "buy",
            "purchase",
            "checkout",
            "pay",
            "order",
            "subscribe",
            "billing",
            "transfer",
            "wire",
            "crypto",
        ],
    ) || phrase(&w, "card", "number")
        || phrase(&w, "send", "money")
    {
        return Risk::Confirm("purchase/payment/financial transfer");
    }
    if any_word(
        &w,
        &[
            "send", "post", "tweet", "publish", "reply", "comment", "submit",
        ],
    ) {
        return Risk::Confirm("sending/submitting content");
    }
    if any_word(
        &w,
        &[
            "password",
            "credential",
            "2fa",
            "totp",
            "security",
            "privacy",
            "permission",
        ],
    ) || phrase(&w, "sign", "in")
        || phrase(&w, "log", "in")
    {
        return Risk::Confirm("account/security settings");
    }
    if any_word(
        &w,
        &[
            "overwrite",
            "replace",
            "reset",
            "factory",
            "uninstall",
            "revoke",
            "deactivate",
        ],
    ) {
        return Risk::Confirm("irreversible change");
    }
    if any_word(
        &w,
        &["share", "invite", "grant", "authorize", "allow", "approve"],
    ) {
        return Risk::Confirm("granting access");
    }
    if word_then_word(
        &w,
        &[
            "install",
            "uninstall",
            "download",
            "run",
            "execute",
            "launch",
        ],
        &[
            "app",
            "application",
            "package",
            "installer",
            "executable",
            "script",
            "extension",
        ],
    ) {
        return Risk::Confirm("software installation/execution");
    }
    let config_verb =
        any_word(&w, &["change", "modify", "disable", "enable"]) || phrase(&w, "turn", "off");
    if config_verb
        && (word_then_word(
            &w,
            &["change", "modify", "disable", "enable", "off"],
            &[
                "firewall",
                "antivirus",
                "security",
                "permission",
                "encryption",
            ],
        ) || flat.contains("system setting"))
    {
        return Risk::Confirm("system/security configuration");
    }

    let lowered: HashSet<String> = keys.iter().map(|key| key.to_lowercase()).collect();
    for combo in [&["cmd", "backspace"][..], &["ctrl", "alt", "delete"][..]] {
        if combo.iter().all(|key| lowered.contains(*key)) {
            return Risk::Confirm("destructive key combo");
        }
    }
    if typing
        && w.iter().any(|word| {
            ["password", "passwd", "secret", "token", "apikey"].contains(&word.as_str())
        })
        || typing && (phrase(&w, "api", "key"))
    {
        return Risk::Confirm("typing into a credential field");
    }
    Risk::Safe
}

/// A run of 13 to 19 digits (spaces and dashes allowed) that passes the Luhn
/// check: a payment-card number.
pub fn contains_card_number(text: &str) -> bool {
    let mut digits: Vec<u32> = Vec::new();
    let flush = |digits: &mut Vec<u32>| -> bool {
        let found = (13..=19).contains(&digits.len()) && luhn(digits);
        digits.clear();
        found
    };
    for c in text.chars() {
        if let Some(d) = c.to_digit(10) {
            digits.push(d);
        } else if c == ' ' || c == '-' {
            continue;
        } else if flush(&mut digits) {
            return true;
        }
    }
    flush(&mut digits)
}

fn luhn(digits: &[u32]) -> bool {
    let sum: u32 = digits
        .iter()
        .rev()
        .enumerate()
        .map(|(i, &d)| {
            if i % 2 == 1 {
                let doubled = d * 2;
                if doubled > 9 {
                    doubled - 9
                } else {
                    doubled
                }
            } else {
                d
            }
        })
        .sum();
    sum % 10 == 0
}

/// Field names that mark a payment-card field when the platform exposes no
/// `autocomplete` attribute (native toolkits, UIA over a web page).
pub fn is_payment_field_name(name: &str) -> bool {
    let w = words(name);
    let flat = normalized(name);
    phrase(&w, "card", "number")
        || any_word(&w, &["cvv", "cvc", "cvv2", "cc", "ccv"])
        || flat.contains("credit card")
        || flat.contains("security code")
        || flat.contains("cc-number")
        || flat.contains("cc-csc")
        || flat.contains("cc-exp")
        || (flat.contains("expir") && (flat.contains("card") || flat.contains("mm")))
}

/// Keys of a `press_key` (`key`) or `hotkey` (`keys`) call.
fn call_keys(args: &Value) -> Vec<String> {
    let mut keys = Vec::new();
    if let Some(key) = args.get("key").and_then(Value::as_str) {
        keys.extend(key.split('+').map(|k| k.trim().to_owned()));
    }
    if let Some(list) = args.get("keys").and_then(Value::as_array) {
        keys.extend(
            list.iter()
                .filter_map(Value::as_str)
                .map(|k| k.trim().to_owned()),
        );
    }
    if let Some(modifiers) = args.get("modifiers").and_then(Value::as_array) {
        keys.extend(
            modifiers
                .iter()
                .filter_map(Value::as_str)
                .map(|k| k.trim().to_owned()),
        );
    }
    keys
}

/// Whether a key call would put text into the focused field: a single
/// printable key, or paste (`ctrl+v`, `cmd+v`, `shift+insert`).
fn key_call_enters_text(tool: &str, args: &Value) -> bool {
    let keys: Vec<String> = call_keys(args).iter().map(|k| k.to_lowercase()).collect();
    let modifiers = [
        "ctrl", "control", "cmd", "command", "meta", "win", "super", "alt", "option",
    ];
    let has = |name: &str| keys.iter().any(|key| key == name);
    let paste = (has("v") && keys.iter().any(|k| modifiers[..7].contains(&k.as_str())))
        || (has("shift") && has("insert"));
    let printable = tool == "press_key"
        && keys.len() == 1
        && keys[0].chars().count() == 1
        && !keys.iter().any(|k| modifiers.contains(&k.as_str()));
    paste || printable
}

fn typed_text(tool: &str, args: &Value) -> Option<String> {
    match tool {
        "type_text" | "type_text_chars" | "browser_type" => {
            args.get("text").and_then(Value::as_str).map(str::to_owned)
        }
        "set_value" => args.get("value").and_then(Value::as_str).map(str::to_owned),
        _ => None,
    }
}

const VALUE_MATCH_LIMIT: usize = 200;

/// The text the classes are matched against.
pub fn haystack(
    tool: &str,
    args: &Value,
    target: Option<&TargetInfo>,
    safety: &SafetyArgs,
) -> String {
    let mut parts: Vec<String> = Vec::new();
    if let Some(target) = target {
        parts.push(target.name.clone());
        if !target.editable {
            if let Some(value) = target.value.as_deref() {
                parts.push(value.chars().take(VALUE_MATCH_LIMIT).collect());
            }
        }
    }
    if tool == "invoke_menu" {
        if let Some(path) = args.get("path").and_then(Value::as_array) {
            parts.extend(path.iter().filter_map(Value::as_str).map(str::to_owned));
        }
    }
    if let Some(intent) = safety.intent.as_deref() {
        parts.push(intent.to_owned());
    }
    parts.retain(|part| !part.trim().is_empty());
    parts.join(" ")
}

/// Session grants for confirmed classes, and tokens waiting for the user.
#[derive(Default)]
struct ConfirmState {
    /// token → (session key, grant key, issued at)
    pending: HashMap<String, (String, String, Instant)>,
    /// (session key, grant key)
    granted: HashSet<(String, String)>,
}

const TOKEN_TTL: Duration = Duration::from_secs(10 * 60);

fn confirm_state() -> &'static Mutex<ConfirmState> {
    static STATE: OnceLock<Mutex<ConfirmState>> = OnceLock::new();
    STATE.get_or_init(Default::default)
}

fn verb(tool: &str) -> &str {
    match tool {
        "type_text_chars" => "type_text",
        other => other,
    }
}

/// Outcome of the confirm-class gate for one call.
enum ConfirmGate {
    Allowed,
    NeedsUser { token: String },
}

fn confirm_gate(session: &str, tool: &str, class: &str, presented: Option<&str>) -> ConfirmGate {
    let grant = format!("{}:{class}", verb(tool));
    let mut state = confirm_state().lock().unwrap_or_else(|e| e.into_inner());
    state
        .pending
        .retain(|_, (_, _, issued)| issued.elapsed() < TOKEN_TTL);
    if state.granted.contains(&(session.to_owned(), grant.clone())) {
        return ConfirmGate::Allowed;
    }
    if let Some(token) = presented {
        if let Some((token_session, token_grant, _)) = state.pending.get(token) {
            if token_session == session && *token_grant == grant {
                state.pending.remove(token);
                state.granted.insert((session.to_owned(), grant));
                return ConfirmGate::Allowed;
            }
        }
    }
    let token = format!("cf-{}", &uuid::Uuid::new_v4().simple().to_string()[..12]);
    state
        .pending
        .insert(token.clone(), (session.to_owned(), grant, Instant::now()));
    ConfirmGate::NeedsUser { token }
}

/// Forget the grants of a session (for example at `end_session`).
pub fn forget_session(session: &str) {
    let mut state = confirm_state().lock().unwrap_or_else(|e| e.into_inner());
    state.granted.retain(|(owner, _)| owner != session);
    state.pending.retain(|_, (owner, _, _)| owner != session);
}

/// Page function (`Runtime.callFunctionOn` on the target node) that names a
/// secure browser field: `"password"` for `input[type=password]` and
/// password autocomplete tokens, `"payment"` for `autocomplete="cc-*"` and
/// inputs inside a known hosted payment-field frame, `""` otherwise.
pub const BROWSER_SECURE_FIELD_CHECK: &str = r#"function() {
  const el = this;
  if (!el || el.nodeType !== 1) return "";
  const type = String(el.type || el.getAttribute("type") || "").toLowerCase();
  if (type === "password") return "password";
  const ac = String(el.getAttribute("autocomplete") || "").toLowerCase().split(/\s+/);
  if (ac.includes("current-password") || ac.includes("new-password")) return "password";
  if (ac.some(t => t.startsWith("cc-"))) return "payment";
  let host = "";
  try { host = String(el.ownerDocument.location.hostname || "").toLowerCase(); } catch (e) {}
  const payHosts = ["js.stripe.com", "m.stripe.network", "assets.braintreegateway.com",
    "checkoutshopper-live.adyen.com", "checkoutshopper-test.adyen.com",
    "secure.checkout.com", "flex.cybersource.com", "pay.google.com", "www.paypal.com"];
  if (payHosts.some(h => host === h || host.endsWith("." + h))) return "payment";
  return "";
}"#;

/// The hand-off kind for a [`BROWSER_SECURE_FIELD_CHECK`] answer.
pub fn browser_secure_kind(answer: &str) -> Option<SecureKind> {
    match answer {
        "password" => Some(SecureKind::Password),
        "payment" => Some(SecureKind::Payment),
        _ => None,
    }
}

/// The `handoff_required` refusal for `kind`.
pub fn handoff_refusal(kind: SecureKind, tool: &str) -> ToolResult {
    handoff_result(kind, tool)
}

fn handoff_result(kind: SecureKind, tool: &str) -> ToolResult {
    ToolResult::error(format!(
        "{tool} refused: {}. Hand this step to the user.",
        kind.hint()
    ))
    .with_structured(json!({
        "code": "handoff_required",
        "effect": "refused",
        "reason": kind.reason(),
        "handoff": { "to": "user", "reason": kind.reason() },
        "hint": kind.hint(),
    }))
}

fn describe_target(target: Option<&TargetInfo>) -> String {
    match target {
        Some(target) if !target.name.trim().is_empty() => {
            format!(" on {} \"{}\"", target.role, target.name.trim())
        }
        Some(target) if !target.role.is_empty() => format!(" on a {}", target.role),
        _ => String::new(),
    }
}

/// Decide a call against the secure-target hand-off and the safety classes.
/// Pure: the caller supplies what the platform reported about the target.
pub fn decide(
    tool: &str,
    args: &Value,
    target: Option<&TargetInfo>,
    safety: &SafetyArgs,
    mode: PermissionMode,
    session: &str,
    classes: bool,
) -> Option<ToolResult> {
    if !is_guarded_tool(tool) {
        return None;
    }
    let text_entry = is_text_entry_tool(tool)
        || (matches!(tool, "press_key" | "hotkey") && key_call_enters_text(tool, args));
    if let Some(kind) = target.and_then(|target| target.secure) {
        if kind.blocks_every_action() || text_entry {
            return Some(handoff_result(kind, tool));
        }
    }
    if let Some(text) = typed_text(tool, args) {
        if contains_card_number(&text) {
            return Some(handoff_result(SecureKind::Payment, tool));
        }
    }
    if !classes {
        return None;
    }
    let haystack = haystack(tool, args, target, safety);
    let typing = is_text_entry_tool(tool);
    match assess(&haystack, &call_keys(args), typing) {
        Risk::Safe => None,
        Risk::Blocked(class) => Some(
            ToolResult::error(format!(
                "{tool} refused: the action{} falls in the blocked class \"{class}\", which the \
                 agent never runs. Tell the user what you were about to do and stop.",
                describe_target(target)
            ))
            .with_structured(json!({
                "code": "safety_blocked",
                "effect": "refused",
                "class": class,
                "hint": "Blocked actions are never run by the agent. Explain the step to the \
                         user and let them do it, or choose another approach.",
            })),
        ),
        Risk::Confirm(class) => match mode {
            PermissionMode::Unrestricted => None,
            PermissionMode::Bounded => Some(
                ToolResult::error(format!(
                    "{tool} refused: the action{} is in the guarded class \"{class}\", which \
                     needs the user's confirmation, and bounded mode runs without one. Hand \
                     this step to the user.",
                    describe_target(target)
                ))
                .with_structured(json!({
                    "code": "confirmation_required",
                    "effect": "refused",
                    "class": class,
                    "handoff": { "to": "user", "reason": "confirmation_required" },
                    "hint": "Bounded mode cannot confirm guarded actions. Hand this step to the \
                             user.",
                })),
            ),
            PermissionMode::Standard => {
                match confirm_gate(session, tool, class, safety.confirm.as_deref()) {
                    ConfirmGate::Allowed => None,
                    ConfirmGate::NeedsUser { token } => Some(
                        ToolResult::error(format!(
                            "{tool} needs the user's confirmation: the action{} is in the \
                             guarded class \"{class}\". Ask the user; if they say yes, repeat \
                             the same call with confirm:\"{token}\".",
                            describe_target(target)
                        ))
                        .with_structured(json!({
                            "code": "confirmation_required",
                            "effect": "refused",
                            "class": class,
                            "confirm_token": token,
                            "hint": format!(
                                "Ask the user to confirm this {class} action. Only after a yes, \
                                 repeat the same call with confirm:\"{token}\"."
                            ),
                        })),
                    ),
                }
            }
        },
    }
}

const INSPECT_TIMEOUT: Duration = Duration::from_millis(1500);

/// Check one call at the dispatch seam. Returns the refusal to send instead
/// of running the tool, or `None` to run it.
pub async fn guard_call(
    tool: &str,
    args: &Value,
    safety: &SafetyArgs,
    mode: PermissionMode,
    session: &str,
) -> Option<ToolResult> {
    if !is_guarded_tool(tool) {
        return None;
    }
    let target = match current_inspector() {
        Some(inspector) => {
            let tool_owned = tool.to_owned();
            let args_owned = args.clone();
            let task = tokio::task::spawn_blocking(move || inspector(&tool_owned, &args_owned));
            match tokio::time::timeout(INSPECT_TIMEOUT, task).await {
                Ok(Ok(info)) => info,
                _ => None,
            }
        }
        None => None,
    };
    decide(
        tool,
        args,
        target.as_ref(),
        safety,
        mode,
        session,
        classes_enabled(),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn target(role: &str, name: &str) -> TargetInfo {
        TargetInfo {
            role: role.into(),
            name: name.into(),
            ..Default::default()
        }
    }

    #[test]
    fn nexi_classes_port() {
        assert_eq!(
            assess("Delete file", &[], false),
            Risk::Confirm("file/data deletion")
        );
        assert_eq!(
            assess("Place your order", &[], false),
            Risk::Confirm("purchase/payment/financial transfer")
        );
        assert_eq!(
            assess("Card Number", &[], false),
            Risk::Confirm("purchase/payment/financial transfer")
        );
        assert_eq!(
            assess("Submit", &[], false),
            Risk::Confirm("sending/submitting content")
        );
        assert_eq!(
            assess("Sign in", &[], false),
            Risk::Confirm("account/security settings")
        );
        assert_eq!(
            assess("Login", &[], false),
            Risk::Confirm("account/security settings")
        );
        assert_eq!(
            assess("Reset", &[], false),
            Risk::Confirm("irreversible change")
        );
        assert_eq!(
            assess("Share", &[], false),
            Risk::Confirm("granting access")
        );
        assert_eq!(
            assess("download the installer", &[], false),
            Risk::Confirm("software installation/execution")
        );
        assert_eq!(
            assess("turn off firewall", &[], false),
            Risk::Confirm("system/security configuration")
        );
        assert_eq!(
            assess("sudo reboot", &[], false),
            Risk::Blocked("destructive shell")
        );
        assert_eq!(
            assess("phishing kit", &[], false),
            Risk::Blocked("malicious intent")
        );
        assert_eq!(
            assess("disable the audit log", &[], false),
            Risk::Blocked("safety-control bypass")
        );
        assert_eq!(assess("OK", &[], false), Risk::Safe);
        assert_eq!(assess("Formatting toolbar", &[], false), Risk::Safe);
        assert_eq!(
            assess("", &["ctrl".into(), "alt".into(), "delete".into()], false),
            Risk::Confirm("destructive key combo")
        );
        assert_eq!(
            assess("API key", &[], true),
            Risk::Confirm("typing into a credential field")
        );
        assert_eq!(assess("API key", &[], false), Risk::Safe);
    }

    #[test]
    fn card_numbers_are_luhn_checked() {
        assert!(contains_card_number("4111 1111 1111 1111"));
        assert!(contains_card_number("pay with 4242-4242-4242-4242 now"));
        assert!(!contains_card_number("4111 1111 1111 1112"));
        assert!(!contains_card_number("call 555 1234"));
    }

    #[test]
    fn password_target_hands_off_text_but_not_clicks() {
        let mut field = target("Edit", "Password");
        field.secure = Some(SecureKind::Password);
        field.editable = true;
        let refused = decide(
            "type_text",
            &json!({"text": "hunter2"}),
            Some(&field),
            &SafetyArgs::default(),
            PermissionMode::Unrestricted,
            "s",
            true,
        )
        .unwrap();
        let structured = refused.structured_content.unwrap();
        assert_eq!(structured["code"], "handoff_required");
        assert_eq!(structured["reason"], "password_field");
        // Clicking into it to hand focus to the user is allowed by the
        // hand-off rule (the name still meets the account class).
        let click = decide(
            "click",
            &json!({}),
            Some(&field),
            &SafetyArgs::default(),
            PermissionMode::Unrestricted,
            "s",
            true,
        );
        assert!(click.is_none());
        // A paste into it is text entry.
        assert!(decide(
            "hotkey",
            &json!({"keys": ["ctrl", "v"]}),
            Some(&field),
            &SafetyArgs::default(),
            PermissionMode::Unrestricted,
            "s",
            false,
        )
        .is_some());
        // Enter is not.
        assert!(decide(
            "press_key",
            &json!({"key": "return"}),
            Some(&field),
            &SafetyArgs::default(),
            PermissionMode::Unrestricted,
            "s",
            false,
        )
        .is_none());
    }

    #[test]
    fn elevation_prompt_stops_every_action_in_every_mode() {
        let mut prompt = target("Button", "Yes");
        prompt.secure = Some(SecureKind::ElevationPrompt);
        for mode in [
            PermissionMode::Standard,
            PermissionMode::Bounded,
            PermissionMode::Unrestricted,
        ] {
            let refused = decide(
                "click",
                &json!({}),
                Some(&prompt),
                &SafetyArgs::default(),
                mode,
                "s",
                false,
            )
            .unwrap();
            assert_eq!(
                refused.structured_content.unwrap()["reason"],
                "elevation_prompt"
            );
        }
    }

    #[test]
    fn confirm_class_by_mode_and_token() {
        let button = target("Button", "Delete account");
        let args = json!({"element_token": "s00000001:3"});
        assert!(decide(
            "click",
            &args,
            Some(&button),
            &SafetyArgs::default(),
            PermissionMode::Unrestricted,
            "sess-a",
            true
        )
        .is_none());
        let bounded = decide(
            "click",
            &args,
            Some(&button),
            &SafetyArgs::default(),
            PermissionMode::Bounded,
            "sess-a",
            true,
        )
        .unwrap()
        .structured_content
        .unwrap();
        assert_eq!(bounded["code"], "confirmation_required");
        assert!(bounded.get("confirm_token").is_none());

        let first = decide(
            "click",
            &args,
            Some(&button),
            &SafetyArgs::default(),
            PermissionMode::Standard,
            "sess-a",
            true,
        )
        .unwrap()
        .structured_content
        .unwrap();
        let token = first["confirm_token"].as_str().unwrap().to_owned();
        // A token from another session does not confirm.
        let other = SafetyArgs {
            intent: None,
            confirm: Some(token.clone()),
        };
        assert!(decide(
            "click",
            &args,
            Some(&button),
            &other,
            PermissionMode::Standard,
            "sess-b",
            true
        )
        .is_some());
        assert!(decide(
            "click",
            &args,
            Some(&button),
            &other,
            PermissionMode::Standard,
            "sess-a",
            true
        )
        .is_none());
        // The grant covers the class for the rest of the session.
        assert!(decide(
            "click",
            &args,
            Some(&target("Button", "Remove item")),
            &SafetyArgs::default(),
            PermissionMode::Standard,
            "sess-a",
            true
        )
        .is_none());
        forget_session("sess-a");
    }

    #[test]
    fn intent_is_checked_and_editable_values_are_not() {
        let mut doc = target("Document", "Editor");
        doc.editable = true;
        doc.value = Some("please delete this paragraph".into());
        assert!(decide(
            "type_text",
            &json!({"text": "hello"}),
            Some(&doc),
            &SafetyArgs::default(),
            PermissionMode::Bounded,
            "s",
            true
        )
        .is_none());
        let intent = SafetyArgs {
            intent: Some("buy the cheapest flight".into()),
            confirm: None,
        };
        assert!(decide(
            "click",
            &json!({}),
            None,
            &intent,
            PermissionMode::Bounded,
            "s",
            true
        )
        .is_some());
    }

    #[test]
    fn typed_card_number_hands_off_without_target_info() {
        let refused = decide(
            "type_text",
            &json!({"text": "4111111111111111"}),
            None,
            &SafetyArgs::default(),
            PermissionMode::Unrestricted,
            "s",
            false,
        )
        .unwrap();
        assert_eq!(
            refused.structured_content.unwrap()["reason"],
            "payment_field"
        );
    }

    #[test]
    fn safety_args_are_removed_from_guarded_calls_only() {
        let mut args = json!({"pid": 1, "intent": "pay rent", "confirm": "cf-1"});
        let taken = take_safety_args("click", &mut args);
        assert_eq!(taken.intent.as_deref(), Some("pay rent"));
        assert_eq!(taken.confirm.as_deref(), Some("cf-1"));
        assert_eq!(args, json!({"pid": 1}));
        let mut read = json!({"intent": "x"});
        assert_eq!(
            take_safety_args("get_window_state", &mut read),
            SafetyArgs::default()
        );
        assert_eq!(read, json!({"intent": "x"}));
    }

    #[test]
    fn payment_field_names() {
        assert!(is_payment_field_name("Card number"));
        assert!(is_payment_field_name("CVV"));
        assert!(is_payment_field_name("Expiration date (MM/YY)"));
        assert!(!is_payment_field_name("User name"));
    }
}
