//! W9 gate, live: the dove-driver daemon with the grounder stays under
//! 250 MB peak RSS, and the grounder adds under 30 MB to it, while `act`
//! and `run_steps` intent steps drive a real GTK3 window through AT-SPI.
//!
//! Runs when all of these are set, and skips otherwise:
//! - `DOVE_DRIVER_GROUNDER_MODEL`: the ONNX asset;
//! - `DOVE_DRIVER_BIN`: a built `dove-driver` (use a release build);
//! - `DISPLAY` with an AT-SPI session bus, e.g.
//!   `xvfb-run -a dbus-run-session -- cargo test --release --test daemon`;
//! - optionally `DOVE_GROUNDER_DEMO_PYTHON`: a Python with PyGObject and
//!   GTK 3 (default `python3`), which runs `tests/fixtures/grounder_demo.py`.
//!
//! The daemon is started twice: without the grounder, doing the same reads
//! and actions by hand, and with it; the difference of the two peaks is
//! what the grounder adds.

use serde_json::{json, Value};
use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::{channel, Receiver};
use std::time::{Duration, Instant};

const PEAK_BUDGET_KB: u64 = 250 * 1024;
const GROUNDER_BUDGET_KB: u64 = 30 * 1024;

struct Killed(Child);

impl Drop for Killed {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

struct Mcp {
    stdin: ChildStdin,
    rx: Receiver<Value>,
    next_id: u64,
    _proxy: Killed,
}

impl Mcp {
    fn call(&mut self, tool: &str, args: Value) -> Value {
        self.next_id += 1;
        let id = self.next_id;
        let request = json!({"jsonrpc": "2.0", "id": id, "method": "tools/call",
                             "params": {"name": tool, "arguments": args}});
        writeln!(self.stdin, "{request}").unwrap();
        self.stdin.flush().unwrap();
        let deadline = Instant::now() + Duration::from_secs(60);
        while Instant::now() < deadline {
            if let Ok(message) = self.rx.recv_timeout(Duration::from_secs(1)) {
                if message["id"] == json!(id) {
                    return message["result"].clone();
                }
            }
        }
        panic!("no answer to {tool}");
    }
}

fn status_kb(pid: u32, key: &str) -> u64 {
    std::fs::read_to_string(format!("/proc/{pid}/status"))
        .ok()
        .and_then(|s| {
            s.lines()
                .find_map(|l| l.strip_prefix(key))
                .and_then(|v| v.trim().trim_end_matches("kB").trim().parse().ok())
        })
        .unwrap_or(0)
}

fn text(result: &Value) -> String {
    result["content"]
        .as_array()
        .map(|parts| {
            parts
                .iter()
                .filter_map(|p| p["text"].as_str())
                .collect::<Vec<_>>()
                .join("\n")
        })
        .unwrap_or_default()
}

/// Start a daemon (with or without the grounder) and its MCP proxy.
fn start(bin: &PathBuf, home: &PathBuf, model: Option<&str>) -> (Killed, Mcp) {
    let socket = home.join("driver.sock");
    let _ = std::fs::remove_file(&socket);
    let env = |cmd: &mut Command| {
        cmd.env("HOME", home)
            .env("XDG_CONFIG_HOME", home.join("config"))
            .env("XDG_DATA_HOME", home.join("data"))
            .env("XDG_STATE_HOME", home.join("state"))
            .env("XDG_CACHE_HOME", home.join("cache"))
            .env("CUA_DRIVER_PERMISSION_MODE", "unrestricted")
            .env("CUA_DRIVER_DANGEROUSLY_BYPASS_APPROVALS", "1")
            .env("CUA_DRIVER_RS_TELEMETRY_ENABLED", "false")
            .env_remove("DOVE_DRIVER_GROUNDER_MODEL");
        if let Some(model) = model {
            cmd.env("DOVE_DRIVER_GROUNDER_MODEL", model);
        }
    };
    let mut serve = Command::new(bin);
    serve
        .args([
            "serve",
            "--socket",
            socket.to_str().unwrap(),
            "--no-permissions-gate",
            "--no-overlay",
        ])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    env(&mut serve);
    let daemon = Killed(serve.spawn().expect("start the daemon"));
    let deadline = Instant::now() + Duration::from_secs(20);
    while !socket.exists() && Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(100));
    }
    assert!(socket.exists(), "the daemon did not open its socket");
    let mut proxy = Command::new(bin);
    proxy
        .args(["mcp", "--socket", socket.to_str().unwrap()])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    env(&mut proxy);
    let mut proxy = proxy.spawn().expect("start the MCP proxy");
    let mut stdin = proxy.stdin.take().unwrap();
    let stdout = proxy.stdout.take().unwrap();
    let (tx, rx) = channel();
    std::thread::spawn(move || {
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            if let Ok(message) = serde_json::from_str::<Value>(&line) {
                if tx.send(message).is_err() {
                    break;
                }
            }
        }
    });
    writeln!(
        stdin,
        "{}",
        json!({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {},
        "clientInfo": {"name": "dove-grounder-daemon-test", "version": "0"}}})
    )
    .unwrap();
    let _ = rx
        .recv_timeout(Duration::from_secs(30))
        .expect("initialize");
    writeln!(
        stdin,
        "{}",
        json!({"jsonrpc": "2.0", "method": "notifications/initialized"})
    )
    .unwrap();
    stdin.flush().unwrap();
    (
        daemon,
        Mcp {
            stdin,
            rx,
            next_id: 1,
            _proxy: Killed(proxy),
        },
    )
}

/// The demo window's (pid, window_id).
fn demo_window(mcp: &mut Mcp) -> (i64, u64) {
    let deadline = Instant::now() + Duration::from_secs(20);
    while Instant::now() < deadline {
        let listed = mcp.call("list_windows", json!({}));
        if let Some(windows) = listed["structuredContent"]["windows"].as_array() {
            if let Some(w) = windows
                .iter()
                .find(|w| w["title"].as_str().unwrap_or("").contains("Grounder Demo"))
            {
                return (w["pid"].as_i64().unwrap(), w["window_id"].as_u64().unwrap());
            }
        }
        std::thread::sleep(Duration::from_millis(250));
    }
    panic!("the demo window did not appear");
}

fn status_label(mcp: &mut Mcp, pid: i64, window_id: u64) -> String {
    let state = mcp.call(
        "get_window_state",
        json!({"pid": pid, "window_id": window_id, "full_output": true, "include_screenshot": false}),
    );
    state["structuredContent"]["tree_markdown"]
        .as_str()
        .unwrap_or("")
        .to_owned()
}

#[test]
fn daemon_with_grounder_stays_under_250_mb_peak() {
    let (Some(model), Some(bin)) = (
        std::env::var_os("DOVE_DRIVER_GROUNDER_MODEL"),
        std::env::var_os("DOVE_DRIVER_BIN"),
    ) else {
        eprintln!("DOVE_DRIVER_GROUNDER_MODEL and DOVE_DRIVER_BIN are not both set: skipping");
        return;
    };
    if !cfg!(target_os = "linux") || std::env::var_os("DISPLAY").is_none() {
        eprintln!("needs Linux with DISPLAY and an AT-SPI session: skipping");
        return;
    }
    let bin = PathBuf::from(bin);
    let model = model.to_str().unwrap().to_owned();
    let python = std::env::var("DOVE_GROUNDER_DEMO_PYTHON").unwrap_or_else(|_| "python3".into());
    let demo = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/grounder_demo.py");
    let home = std::env::temp_dir().join(format!("dove-grounder-daemon-{}", std::process::id()));
    std::fs::create_dir_all(&home).unwrap();
    let _app = Killed(
        Command::new(&python)
            .arg(&demo)
            .env("GTK_MODULES", "gail:atk-bridge")
            .env("NO_AT_BRIDGE", "0")
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .expect("start the GTK demo"),
    );

    let mut peaks = Vec::new();
    for with_grounder in [false, true] {
        let (daemon, mut mcp) = start(&bin, &home, with_grounder.then_some(model.as_str()));
        let daemon_pid = daemon.0.id();
        let (pid, window_id) = demo_window(&mut mcp);
        // The same reads in both runs.
        for _ in 0..3 {
            let _ = status_label(&mut mcp, pid, window_id);
        }
        if !with_grounder {
            // The same actions, chosen by hand, so the two peaks differ by
            // the grounder alone: read the rows, act on one, read the diff.
            let calls = [
                ("set_value", "Email", json!({"value": "b@example.com"})),
                ("click", "Remember me", json!({})),
                ("click", "Save", json!({})),
            ];
            for (tool, label, mut args) in calls {
                let state = mcp.call(
                    "get_window_state",
                    json!({"pid": pid, "window_id": window_id, "tree_format": "elements",
                           "max_elements": 250, "include_screenshot": false}),
                );
                let token = state["structuredContent"]["elements"]
                    .as_array()
                    .and_then(|rows| rows.iter().find(|r| r["label"].as_str() == Some(label)))
                    .and_then(|r| r["element_token"].as_str())
                    .unwrap_or_else(|| panic!("no {label} row"))
                    .to_owned();
                args["element_token"] = json!(token);
                args["pid"] = json!(pid);
                args["window_id"] = json!(window_id);
                let result = mcp.call(tool, args);
                assert_ne!(result["isError"], json!(true), "{}", text(&result));
                let _ = mcp.call(
                    "get_window_state",
                    json!({"pid": pid, "window_id": window_id, "since": "latest",
                           "max_elements": 250, "include_screenshot": false}),
                );
            }
        } else {
            let typed = mcp.call(
                "act",
                json!({"pid": pid, "window_id": window_id,
                       "intent": "type \"a@example.com\" into the Email field"}),
            );
            assert_ne!(typed["isError"], json!(true), "{}", text(&typed));
            let batch = mcp.call(
                "run_steps",
                json!({"pid": pid, "window_id": window_id,
                       "steps": [{"intent": "check Remember me"}, {"intent": "click Save"}]}),
            );
            assert_ne!(batch["isError"], json!(true), "{}", text(&batch));
            let abstained = mcp.call(
                "act",
                json!({"pid": pid, "window_id": window_id,
                       "intent": "click the glowing purple button"}),
            );
            assert_eq!(
                abstained["structuredContent"]["code"],
                json!("abstained"),
                "{}",
                text(&abstained)
            );
            let tree = status_label(&mut mcp, pid, window_id);
            assert!(
                tree.contains("saved:a@example.com"),
                "the form was not saved:\n{tree}"
            );
            eprintln!(
                "act: {}\nrun_steps: {}\nabstain: {}",
                text(&typed),
                text(&batch),
                text(&abstained)
            );
        }
        let peak = status_kb(daemon_pid, "VmHWM:");
        eprintln!(
            "daemon {} the grounder: peak RSS {peak} kB, now {} kB",
            if with_grounder { "with" } else { "without" },
            status_kb(daemon_pid, "VmRSS:")
        );
        peaks.push(peak);
        drop(mcp);
        drop(daemon);
    }
    let _ = std::fs::remove_dir_all(&home);
    eprintln!(
        "the grounder added {} kB to the daemon's peak",
        peaks[1].saturating_sub(peaks[0])
    );
    assert!(peaks[1] > 0, "could not read the daemon's peak RSS");
    assert!(
        peaks[1] < PEAK_BUDGET_KB,
        "daemon peak {} kB, budget {PEAK_BUDGET_KB} kB",
        peaks[1]
    );
    let added = peaks[1].saturating_sub(peaks[0]);
    assert!(
        added < GROUNDER_BUDGET_KB,
        "the grounder added {added} kB, budget {GROUNDER_BUDGET_KB} kB"
    );
}
