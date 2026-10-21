//! Dove fork (ROADMAP W5): lazy tool disclosure over real MCP transports.
//!
//! `DOVE_TOOL_DISCLOSURE=lazy` shrinks `tools/list` to full schemas for the
//! core loop tools plus names and one-line descriptions for the rest;
//! `describe_tools` returns the withheld entries. Unset, the roster is
//! upstream's, which the `protocol_*` and `compatibility_contract_test`
//! suites pin. No test here sends input to any window.

#![cfg(any(target_os = "linux", target_os = "windows"))]

use cua_driver_core::mcp_wire::{
    CLIENT_CAPABILITIES_KEY, MODERN_PROTOCOL_VERSION, PROTOCOL_VERSION_KEY,
};
use cua_driver_core::tool_disclosure::{DESCRIBE_TOOLS, FULL_SCHEMA_TOOLS};
use cua_driver_testkit::RawDriver;
use serde_json::{json, Value};

/// Ceiling for the lazy `tools/list` result, serialized compactly: the
/// measured lazy size plus a small margin. Measured on Linux (66 tools):
/// 24,257 bytes lazy against 229,910 eager. About 15 KB of the lazy list is
/// the entries of `list_windows`, `get_window_state`, `run_steps`,
/// `verify_state` and `describe_tools` (full input schemas, descriptions cut
/// to their first paragraph); the other 62 tools take 9 KB. Every tool stays
/// listed (with a one-line description) so clients such as Claude Code,
/// which only call listed tools, can still call all of them; that rules out
/// the 3 KB first planned, since 59 bare `{name, inputSchema:{"type":"object"}}`
/// entries alone are 3.4 KB. The margin also covers Windows, not measured yet.
const LAZY_TOOLS_LIST_LIMIT_BYTES: usize = 26 * 1024;

fn tools_list(driver: &mut RawDriver) -> Value {
    driver.send(&json!({"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}));
    driver.recv();
    driver.send(&json!({"jsonrpc":"2.0","id":2,"method":"tools/list"}));
    driver.recv()["result"].take()
}

fn call(driver: &mut RawDriver, id: u64, name: &str, arguments: Value) -> Value {
    driver.send(&json!({
        "jsonrpc":"2.0","id":id,"method":"tools/call",
        "params":{"name":name,"arguments":arguments}
    }));
    driver.recv()["result"].take()
}

/// A per-request (modern) MCP call, which the stdio adapters check against
/// the tool inventory before dispatch. Returns the whole response.
fn modern_call(driver: &mut RawDriver, id: u64, name: &str, arguments: Value) -> Value {
    driver.send(&json!({
        "jsonrpc":"2.0","id":id,"method":"tools/call",
        "params":{
            "name":name,"arguments":arguments,
            "_meta":{PROTOCOL_VERSION_KEY: MODERN_PROTOCOL_VERSION, CLIENT_CAPABILITIES_KEY: {}}
        }
    }));
    driver.recv()
}

fn skill_text(driver: &mut RawDriver) -> String {
    driver.send(&json!({"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}));
    driver.recv();
    driver.send(&json!({
        "jsonrpc":"2.0","id":2,"method":"resources/read",
        "params":{"uri":"skill://cua-driver/SKILL.md"}
    }));
    driver.recv()["result"]["contents"][0]["text"]
        .as_str()
        .expect("SKILL.md text")
        .to_owned()
}

fn names(list: &Value) -> Vec<String> {
    list["tools"]
        .as_array()
        .expect("tools array")
        .iter()
        .filter_map(|tool| tool["name"].as_str().map(str::to_owned))
        .collect()
}

fn entry<'a>(list: &'a Value, name: &str) -> &'a Value {
    list["tools"]
        .as_array()
        .expect("tools array")
        .iter()
        .find(|tool| tool["name"] == name)
        .unwrap_or_else(|| panic!("{name} is not listed"))
}

fn compact_len(value: &Value) -> usize {
    serde_json::to_string(value).unwrap().len()
}

/// The eager (upstream) roster, from a driver started without the variable.
fn eager_list() -> Option<Value> {
    let mut driver = RawDriver::spawn_direct()?;
    Some(tools_list(&mut driver))
}

#[test]
fn default_tools_list_is_upstreams() {
    let Some(eager) = eager_list() else {
        return;
    };
    assert!(
        !names(&eager).iter().any(|name| name == DESCRIBE_TOOLS),
        "describe_tools must not exist unless lazy disclosure is on"
    );
    assert!(eager.get("enforcement_adapters").is_some());
    for tool in eager["tools"].as_array().unwrap() {
        assert_ne!(
            tool["inputSchema"],
            json!({"type": "object"}),
            "{} lost its schema in default mode",
            tool["name"]
        );
    }
}

#[test]
fn lazy_tools_list_is_small_and_keeps_core_schemas() {
    let Some(eager) = eager_list() else {
        return;
    };
    let Some(mut driver) = RawDriver::spawn_direct_with_env(&[("DOVE_TOOL_DISCLOSURE", "lazy")])
    else {
        return;
    };
    let lazy = tools_list(&mut driver);

    let eager_bytes = compact_len(&eager);
    let lazy_bytes = compact_len(&lazy);
    eprintln!(
        "tools/list: eager {eager_bytes} bytes / {} tools, lazy {lazy_bytes} bytes / {} tools",
        names(&eager).len(),
        names(&lazy).len()
    );
    assert!(
        lazy_bytes <= LAZY_TOOLS_LIST_LIMIT_BYTES,
        "lazy tools/list is {lazy_bytes} bytes, over the {LAZY_TOOLS_LIST_LIMIT_BYTES}-byte budget"
    );

    // Same roster, plus describe_tools.
    let mut expected = names(&eager);
    expected.push(DESCRIBE_TOOLS.to_owned());
    assert_eq!(names(&lazy), expected);

    for name in names(&eager) {
        let listed = entry(&lazy, &name);
        if FULL_SCHEMA_TOOLS.contains(&name.as_str()) {
            assert_eq!(
                listed["inputSchema"],
                entry(&eager, &name)["inputSchema"],
                "{name} must keep its full input schema"
            );
            let short = listed["description"].as_str().unwrap_or_default();
            let full = entry(&eager, &name)["description"]
                .as_str()
                .unwrap_or_default();
            assert!(
                !short.is_empty() && full.starts_with(short.trim_end_matches("...")),
                "{name}: the lazy description must open the full one, got {short:?}"
            );
        } else {
            assert_eq!(listed["inputSchema"], json!({"type": "object"}), "{name}");
            let description = listed["description"].as_str().unwrap_or_default();
            assert!(
                !description.is_empty() && !description.contains('\n'),
                "{name} needs a one-line description, got {description:?}"
            );
        }
    }
    assert!(entry(&lazy, DESCRIBE_TOOLS)["inputSchema"]["properties"]["names"].is_object());
}

#[test]
fn dove_driver_prefixed_variable_also_selects_lazy() {
    let Some(mut driver) =
        RawDriver::spawn_direct_with_env(&[("DOVE_DRIVER_TOOL_DISCLOSURE", "lazy")])
    else {
        return;
    };
    let lazy = tools_list(&mut driver);
    assert!(names(&lazy).iter().any(|name| name == DESCRIBE_TOOLS));
}

#[test]
fn describe_tools_returns_withheld_entries() {
    let Some(eager) = eager_list() else {
        return;
    };
    let Some(mut driver) = RawDriver::spawn_direct_with_env(&[("DOVE_TOOL_DISCLOSURE", "lazy")])
    else {
        return;
    };
    tools_list(&mut driver);
    let result = call(
        &mut driver,
        3,
        DESCRIBE_TOOLS,
        json!({"names": ["click", "get_config", "no_such_tool"]}),
    );
    assert_eq!(result["isError"], false, "{result}");
    let described = &result["structuredContent"];
    assert_eq!(described["tools"][0], *entry(&eager, "click"));
    assert_eq!(described["tools"][1], *entry(&eager, "get_config"));
    assert_eq!(described["unknown"], json!(["no_such_tool"]));
}

#[test]
fn withheld_tools_still_run_and_bad_calls_return_the_schema() {
    let Some(eager) = eager_list() else {
        return;
    };
    let Some(mut driver) = RawDriver::spawn_direct_with_env(&[("DOVE_TOOL_DISCLOSURE", "lazy")])
    else {
        return;
    };
    tools_list(&mut driver);

    // get_config is withheld and read-only.
    let ok = call(&mut driver, 3, "get_config", json!({}));
    assert_ne!(ok["isError"], true, "a withheld tool must still run: {ok}");

    let bad = call(&mut driver, 4, "get_config", json!({"no_such_argument": 1}));
    assert_eq!(bad["isError"], true, "{bad}");
    assert_eq!(
        bad["structuredContent"]["input_schema"],
        entry(&eager, "get_config")["inputSchema"],
        "a bad call must carry the tool's full schema: {bad}"
    );
    assert!(bad["content"]
        .as_array()
        .unwrap()
        .iter()
        .any(|part| part["text"]
            .as_str()
            .is_some_and(|text| text.starts_with("Input schema for `get_config`:"))));
}

#[test]
fn lazy_instructions_mention_describe_tools() {
    let Some(mut driver) = RawDriver::spawn_direct_with_env(&[("DOVE_TOOL_DISCLOSURE", "lazy")])
    else {
        return;
    };
    driver.send(&json!({"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}));
    let response = driver.recv();
    let instructions = response["result"]["instructions"]
        .as_str()
        .unwrap_or_default();
    assert!(instructions.contains("describe_tools"), "{instructions}");
}

#[test]
fn proxy_applies_lazy_disclosure_from_its_own_environment() {
    let Some(mut driver) = RawDriver::spawn_with_proxy_env(&[("DOVE_TOOL_DISCLOSURE", "lazy")])
    else {
        return;
    };
    let lazy = tools_list(&mut driver);
    assert!(compact_len(&lazy) <= LAZY_TOOLS_LIST_LIMIT_BYTES);
    assert_eq!(
        entry(&lazy, "click")["inputSchema"],
        json!({"type": "object"})
    );

    let result = call(&mut driver, 3, DESCRIBE_TOOLS, json!({"names": ["click"]}));
    assert_eq!(result["isError"], false, "{result}");
    assert!(result["structuredContent"]["tools"][0]["inputSchema"]["properties"].is_object());

    let bad = call(&mut driver, 4, "get_config", json!({"no_such_argument": 1}));
    assert_eq!(bad["isError"], true, "{bad}");
    assert!(
        bad["structuredContent"]["input_schema"].is_object(),
        "{bad}"
    );
}

fn assert_modern_describe_tools_is_admitted(driver: &mut RawDriver) {
    let response = modern_call(driver, 3, DESCRIBE_TOOLS, json!({"names": ["click"]}));
    assert!(response.get("error").is_none(), "{response}");
    assert_eq!(response["result"]["isError"], false, "{response}");
    assert_eq!(
        response["result"]["structuredContent"]["tools"][0]["name"], "click",
        "{response}"
    );
    // Names the client was never shown are still refused.
    let unknown = modern_call(driver, 4, "no_such_tool", json!({}));
    assert_eq!(unknown["error"]["code"], -32602, "{unknown}");
}

#[test]
fn modern_requests_admit_describe_tools_in_direct_mode() {
    let Some(mut driver) = RawDriver::spawn_direct_with_env(&[("DOVE_TOOL_DISCLOSURE", "lazy")])
    else {
        return;
    };
    assert_modern_describe_tools_is_admitted(&mut driver);
}

#[test]
fn modern_requests_admit_describe_tools_through_the_proxy() {
    let Some(mut driver) = RawDriver::spawn_with_proxy_env(&[("DOVE_TOOL_DISCLOSURE", "lazy")])
    else {
        return;
    };
    assert_modern_describe_tools_is_admitted(&mut driver);
}

#[test]
fn modern_requests_do_not_know_describe_tools_by_default() {
    let Some(mut driver) = RawDriver::spawn_direct() else {
        return;
    };
    let response = modern_call(&mut driver, 3, DESCRIBE_TOOLS, json!({}));
    assert_eq!(response["error"]["code"], -32602, "{response}");
}

#[test]
fn served_skill_describes_the_lazy_flow_only_in_lazy_mode() {
    let Some(mut eager) = RawDriver::spawn_direct() else {
        return;
    };
    let eager = skill_text(&mut eager);
    assert!(!eager.contains("describe_tools"));
    let Some(mut lazy) = RawDriver::spawn_direct_with_env(&[("DOVE_TOOL_DISCLOSURE", "lazy")])
    else {
        return;
    };
    let lazy = skill_text(&mut lazy);
    assert!(lazy.contains("`describe_tools({names:[...]})`"), "{lazy}");
    let Some(mut proxied) = RawDriver::spawn_with_proxy_env(&[("DOVE_TOOL_DISCLOSURE", "lazy")])
    else {
        return;
    };
    assert_eq!(skill_text(&mut proxied), lazy);
}
