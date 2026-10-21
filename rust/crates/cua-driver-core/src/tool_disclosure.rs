//! Dove fork: lazy tool disclosure (ROADMAP W5).
//!
//! With `DOVE_TOOL_DISCLOSURE=lazy` (or `CUA_DRIVER_TOOL_DISCLOSURE=lazy`,
//! which `DOVE_DRIVER_TOOL_DISCLOSURE` aliases to), the MCP `tools/list`
//! result keeps the full input schema only for the core loop tools in
//! [`FULL_SCHEMA_TOOLS`] and [`DESCRIBE_TOOLS`]. Every other tool is listed
//! by name with a one-line description and the minimal valid schema
//! `{"type":"object"}`, so a harness sees a small tool list until it needs
//! more. `describe_tools {names}` returns the full entries on demand, a
//! withheld tool can still be called directly, and a call with bad arguments
//! gets that tool's input schema back in the error.
//!
//! Unset (or any other value), every function here is the identity and
//! `describe_tools` does not exist, so the default stays upstream's.
//!
//! The registry's own `tools_list()` stays complete: argument handling,
//! output-schema conformance and the proxy's cached daemon list all read the
//! full entries. Only what the MCP client is shown changes.

use serde_json::{json, Map, Value};

/// Variables that select the disclosure mode, in priority order.
pub const ENV_VARS: [&str; 2] = ["CUA_DRIVER_TOOL_DISCLOSURE", "DOVE_TOOL_DISCLOSURE"];

/// The on-demand schema tool. It exists only in lazy mode.
pub const DESCRIBE_TOOLS: &str = "describe_tools";

/// Tools whose full input schema stays in a lazy `tools/list`. `act` is
/// listed for when a build registers it (ROADMAP W9); a name the registry
/// does not have is simply absent.
pub const FULL_SCHEMA_TOOLS: [&str; 5] = [
    "list_windows",
    "get_window_state",
    "run_steps",
    "verify_state",
    "act",
];

/// Longest one-line description kept for a withheld tool, in characters.
const SHORT_DESCRIPTION_CHARS: usize = 100;

/// Error codes the dispatch seam uses for arguments the tool rejected.
const BAD_ARGUMENT_CODES: [&str; 2] = ["invalid_arguments", "invalid_args"];

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Disclosure {
    /// Upstream behaviour: every tool with its full entry.
    Eager,
    /// Full schemas for the core tools only; the rest on demand.
    Lazy,
}

impl Disclosure {
    /// The mode the environment selects. Anything but `lazy` is eager.
    pub fn from_env() -> Self {
        let value = ENV_VARS
            .iter()
            .find_map(|name| std::env::var(name).ok().filter(|v| !v.trim().is_empty()));
        Self::parse(value.as_deref())
    }

    pub fn parse(value: Option<&str>) -> Self {
        match value {
            Some(value) if value.trim().eq_ignore_ascii_case("lazy") => Self::Lazy,
            _ => Self::Eager,
        }
    }

    pub fn is_lazy(self) -> bool {
        self == Self::Lazy
    }

    /// The `tools/list` result shown to an MCP client, from the registry's
    /// complete one.
    pub fn advertised(self, full: Value) -> Value {
        if !self.is_lazy() {
            return full;
        }
        let Value::Object(mut result) = full else {
            return full;
        };
        let tools = result
            .remove("tools")
            .and_then(|tools| match tools {
                Value::Array(tools) => Some(tools),
                _ => None,
            })
            .unwrap_or_default();
        let mut listed: Vec<Value> = tools.iter().map(lazy_entry).collect();
        if !tools
            .iter()
            .any(|tool| tool_name(tool) == Some(DESCRIBE_TOOLS))
        {
            listed.push(describe_tools_entry());
        }
        result.insert("tools".to_owned(), Value::Array(listed));
        // The enforcement inventory documents every tool's adapters; it is
        // full-detail metadata like the withheld schemas.
        result.remove("enforcement_adapters");
        Value::Object(result)
    }

    /// [`crate::mcp_wire::validate_tool_call`] against the tools the client
    /// was shown: in lazy mode `describe_tools` is known even though the
    /// registry's own list does not have it.
    pub fn validate_tool_call(
        self,
        req: &crate::protocol::Request,
        id: Value,
        era: crate::mcp_wire::ProtocolEra,
        full: &Value,
    ) -> Result<(), crate::protocol::Response> {
        self.validate_tool_call_by(req, id, era, |name| {
            crate::mcp_wire::inventory_has_tool(full, name)
        })
    }

    /// [`Self::validate_tool_call`] against a name lookup, so a caller need
    /// not build the full tool list per call (Dove W4). Withheld tools stay
    /// callable: lazy mode only shortens what `tools/list` shows.
    pub fn validate_tool_call_by(
        self,
        req: &crate::protocol::Request,
        id: Value,
        era: crate::mcp_wire::ProtocolEra,
        has_tool: impl Fn(&str) -> bool,
    ) -> Result<(), crate::protocol::Response> {
        let lazy = self.is_lazy();
        crate::mcp_wire::validate_tool_call_by(req, id, era, |name| {
            (lazy && name == DESCRIBE_TOOLS) || has_tool(name)
        })
    }

    /// Answer a `describe_tools` call here, at the MCP boundary, when lazy
    /// mode owns that name. `None` means dispatch the call as usual.
    pub fn intercept_call(self, full: &Value, tool: &str, args: &Value) -> Option<Value> {
        self.owns_call(tool, |name| find_tool(full, name).is_some())
            .then(|| describe_tools(full, args))
    }

    /// Whether [`Self::intercept_call`] answers `tool`, from a name lookup,
    /// so the full list is built only for the call that needs it.
    pub fn owns_call(self, tool: &str, has_tool: impl Fn(&str) -> bool) -> bool {
        self.is_lazy() && tool == DESCRIBE_TOOLS && !has_tool(DESCRIBE_TOOLS)
    }

    /// Whether [`Self::annotate_result`] would add a schema to `result`, so
    /// the full list is built only for a bad-arguments error.
    pub fn annotates(self, result: &Value) -> bool {
        self.is_lazy() && is_bad_arguments(result)
    }

    /// Put the tool's input schema into a bad-arguments error, so a caller
    /// that never saw the schema can correct the call in one step.
    pub fn annotate_result(self, full: &Value, tool: &str, result: &mut Value) {
        if !self.annotates(result) {
            return;
        }
        let Some(schema) = find_tool(full, tool).and_then(|entry| entry.get("inputSchema")) else {
            return;
        };
        let schema = schema.clone();
        if let Some(Value::Array(content)) = result.get_mut("content") {
            content.push(json!({
                "type": "text",
                "text": format!(
                    "Input schema for `{tool}`: {}",
                    serde_json::to_string(&schema).unwrap_or_default()
                ),
            }));
        }
        let structured = result.as_object_mut().map(|result| {
            result
                .entry("structuredContent")
                .or_insert_with(|| Value::Object(Map::new()))
        });
        match structured {
            Some(Value::Object(structured)) => {
                structured.entry("input_schema").or_insert(schema);
            }
            Some(other @ Value::Null) => *other = json!({"input_schema": schema}),
            _ => {}
        }
    }
}

/// The `describe_tools` tool entry, with its full schema.
pub fn describe_tools_entry() -> Value {
    json!({
        "name": DESCRIBE_TOOLS,
        "description": "Return the full tools/list entries (input schema, annotations, output schema) for the named tools. tools/list shows most tools by name only; call this before a tool whose arguments you do not know. With no `names`, returns every tool.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Tool names, for example [\"click\", \"type_text\"]."
                }
            },
            "additionalProperties": false
        },
        "annotations": {
            "readOnlyHint": true,
            "destructiveHint": false,
            "idempotentHint": true,
            "openWorldHint": false
        }
    })
}

/// The `describe_tools` result: full entries for the requested tools, plus
/// the names that matched no tool.
pub fn describe_tools(full: &Value, args: &Value) -> Value {
    let tools = full["tools"]
        .as_array()
        .map(Vec::as_slice)
        .unwrap_or_default();
    let requested: Option<Vec<&str>> = match args.get("names") {
        None | Some(Value::Null) => None,
        Some(Value::Array(names)) => {
            let names: Option<Vec<&str>> = names.iter().map(Value::as_str).collect();
            match names {
                Some(names) => Some(names),
                None => return bad_describe_arguments(),
            }
        }
        Some(_) => return bad_describe_arguments(),
    };
    let (described, unknown): (Vec<Value>, Vec<Value>) = match requested {
        None => (tools.to_vec(), Vec::new()),
        Some(names) => {
            let mut described = Vec::new();
            let mut unknown = Vec::new();
            for name in names {
                if name == DESCRIBE_TOOLS {
                    described.push(describe_tools_entry());
                } else if let Some(entry) = find_tool(full, name) {
                    described.push(entry.clone());
                } else {
                    unknown.push(Value::String(name.to_owned()));
                }
            }
            (described, unknown)
        }
    };
    let mut structured = json!({ "tools": described });
    if !unknown.is_empty() {
        structured["unknown"] = Value::Array(unknown);
    }
    json!({
        "content": [{
            "type": "text",
            "text": serde_json::to_string(&structured).unwrap_or_default(),
        }],
        "isError": false,
        "structuredContent": structured,
    })
}

fn bad_describe_arguments() -> Value {
    let schema = describe_tools_entry()["inputSchema"].clone();
    json!({
        "content": [{
            "type": "text",
            "text": "describe_tools: invalid arguments: `names` must be an array of tool-name strings",
        }],
        "isError": true,
        "structuredContent": {
            "code": "invalid_arguments",
            "tool": DESCRIBE_TOOLS,
            "input_schema": schema,
        },
    })
}

/// The lazy line added to the MCP server instructions.
pub fn instructions_line() -> &'static str {
    "Most tools are listed by name only: call `describe_tools({names:[...]})` for their argument schemas before first use."
}

/// The lazy note added to the served SKILL.md, after the line that opens
/// its "Efficient loop" section.
pub fn skill_note() -> &'static str {
    "\nThis server lists most tools by name only. `list_windows`, `get_window_state`, `run_steps` and `verify_state` carry full schemas; call `describe_tools({names:[...]})` for any other tool's arguments before first use. Every listed tool can be called, and a call with bad arguments returns that tool's schema in the error.\n"
}

/// SKILL.md as served in lazy mode: [`skill_note`] after the first line of
/// the "Efficient loop" section, or at the end if upstream moved it.
pub fn lazy_skill(skill: &str) -> String {
    let anchor = skill
        .find("## Efficient loop\n\n")
        .and_then(|start| {
            let body = start + "## Efficient loop\n\n".len();
            skill[body..].find('\n').map(|end| body + end + 1)
        })
        .unwrap_or(skill.len());
    format!("{}{}{}", &skill[..anchor], skill_note(), &skill[anchor..])
}

fn lazy_entry(tool: &Value) -> Value {
    let name = tool_name(tool).unwrap_or_default();
    if FULL_SCHEMA_TOOLS.contains(&name) || name == DESCRIBE_TOOLS {
        let mut entry = Map::new();
        for key in ["name", "description", "inputSchema", "annotations"] {
            if let Some(value) = tool.get(key) {
                entry.insert(key.to_owned(), value.clone());
            }
        }
        return Value::Object(entry);
    }
    json!({
        "name": name,
        "description": one_line(tool["description"].as_str().unwrap_or_default()),
        "inputSchema": {"type": "object"},
    })
}

/// The first sentence of the first line, at most [`SHORT_DESCRIPTION_CHARS`].
fn one_line(description: &str) -> String {
    let line = description.trim().lines().next().unwrap_or_default().trim();
    let sentence = match line.find(". ") {
        Some(end) => &line[..=end],
        None => line,
    };
    let sentence = sentence.trim_end_matches(':').trim_end();
    if sentence.chars().count() <= SHORT_DESCRIPTION_CHARS {
        return sentence.to_owned();
    }
    let cut: String = sentence.chars().take(SHORT_DESCRIPTION_CHARS - 3).collect();
    let cut = match cut.rfind(' ') {
        Some(space) if space > SHORT_DESCRIPTION_CHARS / 2 => &cut[..space],
        _ => cut.as_str(),
    };
    format!("{}...", cut.trim_end_matches([',', ';', ' ']))
}

fn tool_name(tool: &Value) -> Option<&str> {
    tool.get("name").and_then(Value::as_str)
}

fn find_tool<'a>(full: &'a Value, name: &str) -> Option<&'a Value> {
    full["tools"]
        .as_array()?
        .iter()
        .find(|tool| tool_name(tool) == Some(name))
}

fn is_bad_arguments(result: &Value) -> bool {
    if result.get("isError").and_then(Value::as_bool) != Some(true) {
        return false;
    }
    // Tools report the code at the top of structuredContent; the dispatch
    // seam's refusals nest it under `refusal`.
    let bad_code = ["/structuredContent/code", "/structuredContent/refusal/code"]
        .iter()
        .filter_map(|pointer| result.pointer(pointer).and_then(Value::as_str))
        .any(|code| BAD_ARGUMENT_CODES.contains(&code));
    if bad_code {
        return true;
    }
    let text = result
        .pointer("/content/0/text")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_ascii_lowercase();
    text.contains("invalid arguments") || text.contains("missing required")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn full_list() -> Value {
        let big_schema = json!({
            "type": "object",
            "properties": {
                "pid": {"type": "integer", "description": "x".repeat(400)},
                "session": {"type": "string"}
            },
            "required": ["pid"],
            "additionalProperties": false
        });
        let tool = |name: &str| {
            json!({
                "name": name,
                "description": format!("Do {name} in the background. More detail follows.\n\nA long body."),
                "inputSchema": big_schema,
                "outputSchema": {"type": "object"},
                "annotations": {"readOnlyHint": false},
                "capabilities": ["x.y"],
                "risk": "low"
            })
        };
        json!({
            "tools": [tool("list_windows"), tool("get_window_state"), tool("click"), tool("type_text")],
            "capability_version": "1",
            "schema_version": "1",
            "enforcement_adapters": [{"a": 1}]
        })
    }

    #[test]
    fn eager_is_the_identity() {
        let full = full_list();
        assert_eq!(Disclosure::Eager.advertised(full.clone()), full);
        assert!(Disclosure::Eager
            .intercept_call(&full, DESCRIBE_TOOLS, &json!({}))
            .is_none());
        let mut error = json!({"isError": true, "content": [{"type":"text","text":"click: invalid arguments: x"}], "structuredContent": {"code": "invalid_arguments"}});
        let before = error.clone();
        Disclosure::Eager.annotate_result(&full, "click", &mut error);
        assert_eq!(error, before);
    }

    #[test]
    fn mode_parsing_accepts_only_lazy() {
        assert_eq!(Disclosure::parse(None), Disclosure::Eager);
        assert_eq!(Disclosure::parse(Some("")), Disclosure::Eager);
        assert_eq!(Disclosure::parse(Some("eager")), Disclosure::Eager);
        assert_eq!(Disclosure::parse(Some("lazy")), Disclosure::Lazy);
        assert_eq!(Disclosure::parse(Some(" LAZY ")), Disclosure::Lazy);
    }

    #[test]
    fn lazy_keeps_core_schemas_and_withholds_the_rest() {
        let listed = Disclosure::Lazy.advertised(full_list());
        let tools = listed["tools"].as_array().unwrap();
        let names: Vec<&str> = tools.iter().filter_map(tool_name).collect();
        assert_eq!(
            names,
            [
                "list_windows",
                "get_window_state",
                "click",
                "type_text",
                DESCRIBE_TOOLS
            ]
        );
        assert_eq!(
            tools[0]["inputSchema"],
            full_list()["tools"][0]["inputSchema"]
        );
        assert!(tools[0].get("outputSchema").is_none());
        assert_eq!(tools[2]["inputSchema"], json!({"type": "object"}));
        assert_eq!(tools[2]["description"], "Do click in the background.");
        assert_eq!(tools[4], describe_tools_entry());
        assert!(listed.get("enforcement_adapters").is_none());
        assert_eq!(listed["capability_version"], "1");
    }

    #[test]
    fn describe_tools_returns_full_entries_and_unknown_names() {
        let full = full_list();
        let result = Disclosure::Lazy
            .intercept_call(&full, DESCRIBE_TOOLS, &json!({"names": ["click", "nope"]}))
            .unwrap();
        assert_eq!(result["isError"], false);
        assert_eq!(result["structuredContent"]["tools"][0], full["tools"][2]);
        assert_eq!(result["structuredContent"]["unknown"], json!(["nope"]));
        let all = describe_tools(&full, &json!({}));
        assert_eq!(
            all["structuredContent"]["tools"].as_array().unwrap().len(),
            4
        );
        let bad = describe_tools(&full, &json!({"names": "click"}));
        assert_eq!(bad["isError"], true);
        assert_eq!(bad["structuredContent"]["code"], "invalid_arguments");
    }

    #[test]
    fn bad_arguments_carry_the_schema() {
        let full = full_list();
        let mut error = json!({
            "isError": true,
            "content": [{"type": "text", "text": "click: unknown argument `bogus`"}],
            "structuredContent": {"code": "invalid_arguments", "tool": "click"}
        });
        Disclosure::Lazy.annotate_result(&full, "click", &mut error);
        assert_eq!(
            error["structuredContent"]["input_schema"],
            full["tools"][2]["inputSchema"]
        );
        assert!(error["content"][1]["text"]
            .as_str()
            .unwrap()
            .starts_with("Input schema for `click`:"));

        let mut plain = json!({
            "isError": true,
            "content": [{"type": "text", "text": "Missing required parameter pid"}]
        });
        Disclosure::Lazy.annotate_result(&full, "type_text", &mut plain);
        assert_eq!(
            plain["structuredContent"]["input_schema"],
            full["tools"][3]["inputSchema"]
        );

        let mut refusal = json!({
            "isError": true,
            "content": [{"type": "text", "text": "click: unknown argument bogus; accepted: pid"}],
            "structuredContent": {
                "status": "refused",
                "refusal": {"code": "invalid_arguments", "message": "click: unknown argument bogus"}
            }
        });
        Disclosure::Lazy.annotate_result(&full, "click", &mut refusal);
        assert_eq!(
            refusal["structuredContent"]["input_schema"],
            full["tools"][2]["inputSchema"]
        );
        assert_eq!(refusal["structuredContent"]["status"], "refused");

        let mut other = json!({
            "isError": true,
            "content": [{"type": "text", "text": "element_token is stale"}],
            "structuredContent": {"code": "stale_element_token"}
        });
        let before = other.clone();
        Disclosure::Lazy.annotate_result(&full, "click", &mut other);
        assert_eq!(other, before);
    }

    #[test]
    fn name_lookup_admission_matches_the_full_list() {
        let full = full_list();
        let has_tool = |name: &str| crate::mcp_wire::inventory_has_tool(&full, name);
        let call = |name: &str| -> crate::protocol::Request {
            serde_json::from_value(json!({
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": name, "arguments": {}}
            }))
            .unwrap()
        };
        let era = crate::mcp_wire::ProtocolEra::Modern;
        for mode in [Disclosure::Eager, Disclosure::Lazy] {
            for name in ["click", "type_text", DESCRIBE_TOOLS, "nope"] {
                let by_list = mode
                    .validate_tool_call(&call(name), json!(1), era, &full)
                    .is_ok();
                let by_name = mode
                    .validate_tool_call_by(&call(name), json!(1), era, has_tool)
                    .is_ok();
                assert_eq!(by_list, by_name, "{mode:?} {name}");
            }
        }
        // Withheld tools stay callable; describe_tools exists only when lazy.
        assert!(Disclosure::Lazy
            .validate_tool_call_by(&call("type_text"), json!(1), era, has_tool)
            .is_ok());
        assert!(Disclosure::Lazy
            .validate_tool_call_by(&call(DESCRIBE_TOOLS), json!(1), era, has_tool)
            .is_ok());
        assert!(Disclosure::Eager
            .validate_tool_call_by(&call(DESCRIBE_TOOLS), json!(1), era, has_tool)
            .is_err());
        assert!(Disclosure::Lazy.owns_call(DESCRIBE_TOOLS, has_tool));
        assert!(!Disclosure::Lazy.owns_call("click", has_tool));
        assert!(!Disclosure::Lazy.owns_call(DESCRIBE_TOOLS, |_| true));
        assert!(!Disclosure::Eager.owns_call(DESCRIBE_TOOLS, has_tool));
        let bad = json!({"isError": true, "structuredContent": {"code": "invalid_arguments"}});
        assert!(Disclosure::Lazy.annotates(&bad));
        assert!(!Disclosure::Eager.annotates(&bad));
        assert!(!Disclosure::Lazy.annotates(&json!({"isError": false})));
    }

    #[test]
    fn one_line_descriptions_are_short() {
        assert_eq!(one_line("Short."), "Short.");
        assert_eq!(
            one_line("List apps with flags:\n\n- a"),
            "List apps with flags"
        );
        let long = one_line(&"word ".repeat(60));
        assert!(long.chars().count() <= SHORT_DESCRIPTION_CHARS);
        assert!(long.ends_with("..."));
    }
}
