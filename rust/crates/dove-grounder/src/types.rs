//! nexi-cua's normalized observation, action and decision types
//! (`nexi_cua/types.py`, `nexi_cua/actions.py`).

use serde_json::{Map, Value};
use std::fmt;

#[derive(Clone, Debug, PartialEq)]
pub struct Bounds {
    pub x: f64,
    pub y: f64,
    pub w: f64,
    pub h: f64,
}

/// One actionable or describable UI element, as every nexi perceiver emits it.
#[derive(Clone, Debug, PartialEq)]
pub struct Element {
    pub id: String,
    /// Normalized role: button, textfield, link, ...
    pub role: String,
    pub name: String,
    pub value: String,
    pub bounds: Option<Bounds>,
    pub enabled: bool,
    pub focused: bool,
    pub checked: Option<bool>,
    pub selected: bool,
    pub children_count: i64,
    pub source: String,
    pub depth: i64,
    pub extra: Map<String, Value>,
}

impl Default for Element {
    fn default() -> Self {
        Self {
            id: String::new(),
            role: String::new(),
            name: String::new(),
            value: String::new(),
            bounds: None,
            enabled: true,
            focused: false,
            checked: None,
            selected: false,
            children_count: 0,
            source: "a11y".into(),
            depth: 0,
            extra: Map::new(),
        }
    }
}

impl Element {
    /// `(bounds.y, bounds.x)`, or `(0, 0)` without bounds: nexi's reading order.
    pub fn reading_key(&self) -> (f64, f64) {
        match &self.bounds {
            Some(b) => (b.y, b.x),
            None => (0.0, 0.0),
        }
    }

    /// `el.extra.get("editable")` is truthy.
    pub fn editable(&self) -> bool {
        self.extra.get("editable").is_some_and(truthy)
    }
}

/// Python truthiness of a JSON value.
pub fn truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(b) => *b,
        Value::Number(n) => n.as_f64().is_some_and(|f| f != 0.0),
        Value::String(s) => !s.is_empty(),
        Value::Array(a) => !a.is_empty(),
        Value::Object(o) => !o.is_empty(),
    }
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct Tab {
    pub id: String,
    pub title: String,
}

#[derive(Clone, Debug, Default, PartialEq)]
pub struct BrowserState {
    pub url: String,
    pub title: String,
    pub tabs: Vec<Tab>,
}

/// The observation the policy reads (`NormalizedObservation`).
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Observation {
    pub goal: String,
    pub elements: Vec<Element>,
    pub browser: Option<BrowserState>,
    pub screen_w: i64,
    pub screen_h: i64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Verb {
    Click,
    DoubleClick,
    RightClick,
    Type,
    Keypress,
    Scroll,
    Drag,
    Select,
    Focus,
    Check,
    SwitchWindow,
    SwitchTab,
    Navigate,
    NewTab,
    CloseTab,
    Back,
    Forward,
    Refresh,
    Wait,
    Done,
    ClickXy,
    DoubleClickXy,
    RightClickXy,
    TypeText,
    KeypressKeys,
    DragXy,
    ScrollXy,
}

impl Verb {
    pub const ALL: [Verb; 27] = [
        Verb::Click,
        Verb::DoubleClick,
        Verb::RightClick,
        Verb::Type,
        Verb::Keypress,
        Verb::Scroll,
        Verb::Drag,
        Verb::Select,
        Verb::Focus,
        Verb::Check,
        Verb::SwitchWindow,
        Verb::SwitchTab,
        Verb::Navigate,
        Verb::NewTab,
        Verb::CloseTab,
        Verb::Back,
        Verb::Forward,
        Verb::Refresh,
        Verb::Wait,
        Verb::Done,
        Verb::ClickXy,
        Verb::DoubleClickXy,
        Verb::RightClickXy,
        Verb::TypeText,
        Verb::KeypressKeys,
        Verb::DragXy,
        Verb::ScrollXy,
    ];

    pub fn as_str(self) -> &'static str {
        match self {
            Verb::Click => "click",
            Verb::DoubleClick => "double_click",
            Verb::RightClick => "right_click",
            Verb::Type => "type",
            Verb::Keypress => "keypress",
            Verb::Scroll => "scroll",
            Verb::Drag => "drag",
            Verb::Select => "select",
            Verb::Focus => "focus",
            Verb::Check => "check",
            Verb::SwitchWindow => "switch_window",
            Verb::SwitchTab => "switch_tab",
            Verb::Navigate => "navigate",
            Verb::NewTab => "new_tab",
            Verb::CloseTab => "close_tab",
            Verb::Back => "back",
            Verb::Forward => "forward",
            Verb::Refresh => "refresh",
            Verb::Wait => "wait",
            Verb::Done => "done",
            Verb::ClickXy => "click_xy",
            Verb::DoubleClickXy => "double_click_xy",
            Verb::RightClickXy => "right_click_xy",
            Verb::TypeText => "type_text",
            Verb::KeypressKeys => "keypress_keys",
            Verb::DragXy => "drag_xy",
            Verb::ScrollXy => "scroll_xy",
        }
    }

    /// Index in nexi's `VERB_VOCAB` (the enum order).
    pub fn index(self) -> i64 {
        Verb::ALL.iter().position(|v| *v == self).unwrap() as i64
    }

    fn visual(self) -> bool {
        matches!(
            self,
            Verb::ClickXy | Verb::DoubleClickXy | Verb::RightClickXy | Verb::DragXy | Verb::ScrollXy
        )
    }
}

/// A typed action (`nexi_cua.actions.Action`).
#[derive(Clone, Debug, PartialEq)]
pub struct Action {
    pub verb: Verb,
    pub element_id: Option<String>,
    pub element_name: String,
    pub text: String,
    pub keys: Vec<String>,
    pub direction: String,
    pub amount: f64,
    pub x: f64,
    pub y: f64,
    pub x2: f64,
    pub y2: f64,
    pub window: String,
    pub tab: String,
    pub wait_ms: i64,
}

impl Action {
    pub fn new(verb: Verb) -> Self {
        Self {
            verb,
            element_id: None,
            element_name: String::new(),
            text: String::new(),
            keys: Vec::new(),
            direction: String::new(),
            amount: 3.0,
            x: 0.0,
            y: 0.0,
            x2: 0.0,
            y2: 0.0,
            window: String::new(),
            tab: String::new(),
            wait_ms: 0,
        }
    }

    /// An action on an element.
    pub fn on(verb: Verb, el: &Element) -> Self {
        Self {
            element_id: Some(el.id.clone()),
            element_name: el.name.clone(),
            ..Self::new(verb)
        }
    }

    pub fn with_text(mut self, text: impl Into<String>) -> Self {
        self.text = text.into();
        self
    }

    pub fn with_keys(mut self, keys: Vec<String>) -> Self {
        self.keys = keys;
        self
    }

    pub fn with_direction(mut self, direction: impl Into<String>) -> Self {
        self.direction = direction.into();
        self
    }

    /// The canonical candidate text the model reads (`Action.textual`).
    pub fn textual(&self) -> String {
        let mut parts = vec![self.verb.as_str().to_owned()];
        if !self.element_name.is_empty() {
            parts.push(format!("on \"{}\"", self.element_name));
        }
        if !self.text.is_empty() {
            parts.push(format!("\"{}\"", self.text));
        }
        if !self.keys.is_empty() {
            parts.push(format!("keys {}", self.keys.join("+")));
        }
        if !self.direction.is_empty() {
            parts.push(self.direction.clone());
        }
        if self.x != 0.0 || self.y != 0.0 {
            parts.push(format!("at {},{}", fmt0(self.x), fmt0(self.y)));
        }
        parts.join(" ")
    }

    fn target(&self) -> &str {
        [
            self.element_id.as_deref().unwrap_or(""),
            self.tab.as_str(),
            self.window.as_str(),
        ]
        .into_iter()
        .find(|s| !s.is_empty())
        .unwrap_or("-")
    }
}

/// Python's `f"{v:.0f}"`.
fn fmt0(v: f64) -> String {
    format!("{v:.0}")
}

/// Python's `f"{v:g}"` for the values nexi uses (whole numbers and short decimals).
fn fmt_g(v: f64) -> String {
    if v.fract() == 0.0 && v.abs() < 1e16 {
        format!("{}", v as i64)
    } else {
        let s = format!("{v:.6}");
        s.trim_end_matches('0').trim_end_matches('.').to_owned()
    }
}

/// `str(action)`: the form nexi's evals compare.
impl fmt::Display for Action {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        if self.verb.visual() {
            return match self.verb {
                Verb::DragXy => write!(
                    f,
                    "drag(({},{})->({},{}))",
                    fmt0(self.x),
                    fmt0(self.y),
                    fmt0(self.x2),
                    fmt0(self.y2)
                ),
                Verb::ScrollXy => write!(
                    f,
                    "scroll_xy({},{} @ {},{})",
                    self.direction,
                    fmt_g(self.amount),
                    fmt0(self.x),
                    fmt0(self.y)
                ),
                verb => write!(f, "{}({},{})", verb.as_str(), fmt0(self.x), fmt0(self.y)),
            };
        }
        let tgt = self.target();
        let nm = if self.element_name.is_empty() {
            String::new()
        } else {
            format!("\"{}\"", self.element_name)
        };
        match self.verb {
            Verb::Type => write!(f, "type({tgt} {nm}, \"{}\")", self.text),
            Verb::Keypress => write!(f, "keypress({})", self.keys.join("+")),
            Verb::Select => write!(f, "select({tgt} {nm}, \"{}\")", self.text),
            Verb::Scroll => write!(f, "scroll({},{})", self.direction, fmt_g(self.amount)),
            Verb::Drag => write!(f, "drag({tgt} {nm} -> {})", self.text),
            Verb::Navigate => write!(f, "navigate({})", self.text),
            Verb::SwitchTab | Verb::SwitchWindow => {
                write!(f, "{}({tgt} {nm})", self.verb.as_str())
            }
            Verb::Wait => write!(f, "wait({}ms)", self.wait_ms),
            Verb::Done => write!(f, "done()"),
            verb => write!(f, "{}({tgt} {nm})", verb.as_str()),
        }
    }
}

/// How a decision was reached.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DecidedBy {
    /// The deterministic resolver named the target.
    Resolver,
    /// NEXI-CUA-1 ranked the candidates.
    Ranker,
    /// Nothing to rank.
    NoCandidates,
}

/// The policy's output (`Decision`): an action, or an abstention.
#[derive(Clone, Debug)]
pub struct Decision {
    pub action: Option<Action>,
    pub probability: f64,
    pub confidence: f64,
    pub abstain: bool,
    pub reason: String,
    pub decided_by: DecidedBy,
    /// Best candidates by softmax probability (ranker decisions only), with
    /// their candidate index, as `(index, str(action), p)`.
    pub top_k: Vec<(usize, String, f64)>,
    /// Ranked candidates the top_k came from, for abstain reporting.
    pub candidates: Vec<Action>,
    pub latency_ms: f64,
}

impl Decision {
    /// `Decision.describe()` without the latency.
    pub fn summary(&self) -> String {
        match &self.action {
            Some(action) if !self.abstain => action.to_string(),
            _ => "ABSTAIN".to_owned(),
        }
    }
}
