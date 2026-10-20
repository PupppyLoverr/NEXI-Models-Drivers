//! Dove fork (ROADMAP W5): lazy tool disclosure over real MCP transports.
//!
//! `DOVE_TOOL_DISCLOSURE=lazy` shrinks `tools/list` to full schemas for the
//! core loop tools plus names and one-line descriptions for the rest;
//! `describe_tools` returns the withheld entries. Unset, the roster is
//! upstream's, which the `protocol_*` and `compatibility_contract_test`
//! suites pin. No test here sends input to any window.

#![cfg(any(target_os = "linux", target_os = "windows"))]

use cua_driver_core::tool_disclosure::{DESCRIBE_TOOLS, FULL_SCHEMA_TOOLS};
use cua_driver_testkit::RawDriver;
use serde_json::{json, Value};

/// Ceiling for the lazy `tools/list` result, serialized compactly: the
/// measured lazy size plus a small margin. Every tool stays listed (with a
/// one-line description) so clients such as Claude Code, which only call
/// listed tools, can still call all of them; that rules out the 3 KB first
/// planned, since 59 bare `{name, inputSchema:{"type":"object"}}` entries
/// alone are 3.4 KB. The eager list is about 226 KB.
const LAZY_TOOLS_LIST_LIMIT_BYTES: usize = 24 * 1024;

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
    let instructions = response["result"]["instructions"].as_str().unwrap_or_default();
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
    assert_eq!(entry(&lazy, "click")["inputSchema"], json!({"type": "object"}));

    let result = call(&mut driver, 3, DESCRIBE_TOOLS, json!({"names": ["click"]}));
    assert_eq!(result["isError"], false, "{result}");
    assert!(result["structuredContent"]["tools"][0]["inputSchema"]["properties"].is_object());

    let bad = call(&mut driver, 4, "get_config", json!({"no_such_argument": 1}));
    assert_eq!(bad["isError"], true, "{bad}");
    assert!(bad["structuredContent"]["input_schema"].is_object(), "{bad}");
}
