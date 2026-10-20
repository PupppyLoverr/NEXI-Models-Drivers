//! dove-driver snapshot rows -> nexi observation.
//!
//! `get_window_state` returns one JSON row per addressable element:
//! `element_index`, `element_token`, `role` (AX, UIA or AT-SPI spelling),
//! `label`, `value`, `enabled`, `selected`, `depth`, `parent_index` and a
//! screen `frame`. nexi's perceivers normalise roles with their own tables
//! (`perceive/macos.py`, `windows.py`, `linux.py`, `browser/cdp.py`); the
//! same tables are applied here to the driver's role names. Element ids are
//! the rows' `element_index`, so a decision names the row it acts on.

use crate::types::{Bounds, Element, Observation};
use serde_json::{Map, Value};
use std::collections::HashMap;

/// nexi's normalised role for a driver role name.
pub fn nexi_role(role: &str) -> &'static str {
    if let Some(ax) = role.strip_prefix("AX") {
        return ax_role(ax);
    }
    let folded: String = role
        .chars()
        .filter(|c| c.is_ascii_alphanumeric())
        .map(|c| c.to_ascii_lowercase())
        .collect();
    match folded.as_str() {
        // UIA control types (`Button`, `Edit`, ...) and AT-SPI role names
        // (`push button`, `entry`, ...), folded to lowercase without spaces.
        "button" | "pushbutton" | "splitbutton" => "button",
        "togglebutton" => "toggle",
        "checkbox" | "checkbutton" => "checkbox",
        "radiobutton" | "radio" => "radio",
        "hyperlink" | "link" => "link",
        "edit" | "entry" | "text" | "textbox" => "textfield",
        "passwordtext" => "securetextfield",
        "textarea" => "textarea",
        "searchbox" | "searchfield" => "searchfield",
        "combobox" => "combobox",
        "list" | "listbox" => "list",
        "listitem" => "listitem",
        "option" => "option",
        "menu" => "menu",
        "menuitem" | "menuitemcheckbox" | "menuitemradio" | "checkmenuitem" | "radiomenuitem" => {
            "menuitem"
        }
        "menubar" => "menubar",
        "tabitem" | "pagetab" | "tab" => "tab",
        "pagetablist" | "tablist" => "tabgroup",
        "table" | "datagrid" => "table",
        "tablerow" | "row" | "dataitem" => "row",
        "tablecell" | "cell" | "gridcell" | "columnheader" | "rowheader" | "headeritem" => "cell",
        "tree" => "tree",
        "treeitem" => "treeitem",
        "scrollpane" | "scrollarea" => "scrollarea",
        "slider" => "slider",
        "spinbutton" | "spinner" => "stepper",
        "dialog" | "alert" | "alertdialog" => "dialog",
        "frame" | "window" => "window",
        "label" | "static" | "paragraph" | "statictext" | "tooltip" => "statictext",
        "heading" => "heading",
        "image" | "icon" | "img" => "image",
        "toolbar" | "statusbar" | "appbar" => "toolbar",
        "progressbar" => "progress",
        "scrollbar" => "scrollbar",
        "splitpane" => "splitter",
        "webarea" | "documentweb" | "documentframe" => "webarea",
        "separator" => "separator",
        "switch" => "switch",
        "thumb" => "handle",
        "grid" => "grid",
        _ => "group",
    }
}

fn ax_role(ax: &str) -> &'static str {
    match ax {
        "Button" => "button",
        "PopUpButton" => "popupbutton",
        "RadioButton" => "radio",
        "CheckBox" => "checkbox",
        "TextField" => "textfield",
        "SecureTextField" => "securetextfield",
        "TextArea" => "textarea",
        "ComboBox" => "combobox",
        "Link" => "link",
        "MenuItem" | "MenuBarItem" => "menuitem",
        "Tab" => "tab",
        "TabGroup" => "tabgroup",
        "List" => "list",
        "Row" => "row",
        "Cell" => "cell",
        "Table" => "table",
        "Outline" => "tree",
        "OutlineRow" => "treeitem",
        "ScrollArea" => "scrollarea",
        "Slider" => "slider",
        "Incrementor" | "Stepper" => "stepper",
        "WebArea" => "webarea",
        "Group" | "LayoutArea" | "LayoutItem" => "group",
        "Image" => "image",
        "StaticText" => "statictext",
        "Heading" => "heading",
        "Window" => "window",
        "Toolbar" => "toolbar",
        "Menu" => "menu",
        "MenuBar" => "menubar",
        "Application" => "application",
        "Sheet" => "sheet",
        "Dialog" => "dialog",
        "ProgressIndicator" => "progress",
        "BusyIndicator" => "busy",
        "Splitter" => "splitter",
        "ScrollBar" => "scrollbar",
        "DisclosureTriangle" => "disclosure",
        "ValueIndicator" => "value",
        "SegmentedControl" => "segmented",
        "RadioGroup" => "radiogroup",
        "Column" => "column",
        "Grid" => "grid",
        "Popover" => "popover",
        "Handle" => "handle",
        "ColorWell" => "colorwell",
        "Switch" => "switch",
        "SearchField" => "searchfield",
        "LevelIndicator" => "level",
        // nexi's macOS perceiver: unknown AX roles lose the prefix.
        _ => "unknown",
    }
}

fn frame(row: &Value) -> Option<Bounds> {
    let f = row.get("frame")?;
    let get = |a: &str, b: &str| f.get(a).or_else(|| f.get(b)).and_then(Value::as_f64);
    Some(Bounds {
        x: get("x", "left")?,
        y: get("y", "top")?,
        w: get("w", "width")?,
        h: get("h", "height")?,
    })
}

/// A checkable control's state from its value ("1"/"0", "true"/"false",
/// "on"/"off"), else its `selected` flag.
fn checked(role: &str, row: &Value) -> Option<bool> {
    if !matches!(role, "checkbox" | "radio" | "switch" | "toggle") {
        return None;
    }
    let from_value = row.get("value").and_then(Value::as_str).and_then(|v| {
        match v.trim().to_ascii_lowercase().as_str() {
            "1" | "true" | "on" | "checked" => Some(true),
            "0" | "false" | "off" | "unchecked" => Some(false),
            _ => None,
        }
    });
    from_value.or_else(|| row.get("selected").and_then(Value::as_bool))
}

/// One snapshot row as a nexi element, plus its token.
pub struct Row {
    pub index: u64,
    pub token: Option<String>,
    pub raw: Value,
}

/// The observation nexi's policy reads, built from snapshot rows. Bounds
/// are made window-relative (the rows' bounding box), which is what nexi's
/// numeric features expect of a screen.
pub fn observation(rows: &[Value], goal: &str) -> (Observation, HashMap<String, Row>) {
    let mut children: HashMap<u64, i64> = HashMap::new();
    for row in rows {
        if let Some(parent) = row.get("parent_index").and_then(Value::as_u64) {
            *children.entry(parent).or_default() += 1;
        }
    }
    let frames: Vec<Bounds> = rows
        .iter()
        .filter_map(frame)
        .filter(|b| b.w > 0.0 && b.h > 0.0)
        .collect();
    let (x0, y0, x1, y1) = frames.iter().fold(
        (
            f64::INFINITY,
            f64::INFINITY,
            f64::NEG_INFINITY,
            f64::NEG_INFINITY,
        ),
        |(a, b, c, d), f| (a.min(f.x), b.min(f.y), c.max(f.x + f.w), d.max(f.y + f.h)),
    );
    let has_extent = x1 > x0 && y1 > y0;
    let mut elements = Vec::with_capacity(rows.len());
    let mut by_id = HashMap::new();
    for row in rows {
        let Some(index) = row.get("element_index").and_then(Value::as_u64) else {
            continue;
        };
        let raw_role = row.get("role").and_then(Value::as_str).unwrap_or("");
        let role = nexi_role(raw_role);
        let text = |key: &str| {
            row.get(key)
                .and_then(Value::as_str)
                .map(|s| s.trim().to_owned())
                .unwrap_or_default()
        };
        let mut extra = Map::new();
        if row.get("in_web_content").and_then(Value::as_bool) == Some(true) {
            extra.insert("web".into(), Value::Bool(true));
        }
        let id = index.to_string();
        elements.push(Element {
            id: id.clone(),
            role: role.to_owned(),
            name: text("label"),
            value: text("value"),
            bounds: frame(row).map(|b| {
                if has_extent {
                    Bounds {
                        x: b.x - x0,
                        y: b.y - y0,
                        ..b
                    }
                } else {
                    b
                }
            }),
            enabled: row.get("enabled").and_then(Value::as_bool).unwrap_or(true),
            focused: row.get("focused").and_then(Value::as_bool).unwrap_or(false),
            checked: checked(role, row),
            selected: row
                .get("selected")
                .and_then(Value::as_bool)
                .unwrap_or(false),
            children_count: children.get(&index).copied().unwrap_or(0),
            source: "a11y".into(),
            depth: row.get("depth").and_then(Value::as_i64).unwrap_or(0),
            extra,
        });
        by_id.insert(
            id,
            Row {
                index,
                token: row
                    .get("element_token")
                    .and_then(Value::as_str)
                    .map(str::to_owned),
                raw: row.clone(),
            },
        );
    }
    let (screen_w, screen_h) = if has_extent {
        ((x1 - x0).round() as i64, (y1 - y0).round() as i64)
    } else {
        (0, 0)
    };
    (
        Observation {
            goal: goal.to_owned(),
            elements,
            browser: None,
            screen_w,
            screen_h,
        },
        by_id,
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn roles_from_every_platform_fold_to_nexi_roles() {
        assert_eq!(nexi_role("AXButton"), "button");
        assert_eq!(nexi_role("AXPopUpButton"), "popupbutton");
        assert_eq!(nexi_role("Edit"), "textfield");
        assert_eq!(nexi_role("Hyperlink"), "link");
        assert_eq!(nexi_role("TabItem"), "tab");
        assert_eq!(nexi_role("push button"), "button");
        assert_eq!(nexi_role("check box"), "checkbox");
        assert_eq!(nexi_role("page tab"), "tab");
        assert_eq!(nexi_role("password text"), "securetextfield");
        assert_eq!(nexi_role("Pane"), "group");
    }

    #[test]
    fn rows_become_window_relative_elements() {
        let rows = vec![
            json!({"element_index": 0, "element_token": "s1:0", "role": "Window", "depth": 0,
                   "frame": {"x": 100, "y": 50, "w": 400, "h": 300}}),
            json!({"element_index": 1, "element_token": "s1:1", "role": "Button", "label": " Save ",
                   "depth": 1, "parent_index": 0, "frame": {"x": 120, "y": 70, "w": 60, "h": 20}}),
            json!({"element_index": 2, "role": "CheckBox", "label": "Wrap", "value": "1",
                   "enabled": false, "parent_index": 0, "frame": {"x": 120, "y": 100, "w": 60, "h": 20}}),
        ];
        let (obs, by_id) = observation(&rows, "click Save");
        assert_eq!((obs.screen_w, obs.screen_h), (400, 300));
        assert_eq!(obs.elements[0].children_count, 2);
        let save = &obs.elements[1];
        assert_eq!((save.role.as_str(), save.name.as_str()), ("button", "Save"));
        assert_eq!(save.bounds.as_ref().map(|b| (b.x, b.y)), Some((20.0, 20.0)));
        assert_eq!(obs.elements[2].checked, Some(true));
        assert!(!obs.elements[2].enabled);
        assert_eq!(by_id["1"].token.as_deref(), Some("s1:1"));
        assert_eq!(by_id["2"].token, None);
    }
}
