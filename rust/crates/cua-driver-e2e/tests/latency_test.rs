//! Dove W4.5: the `get_window_state` latency gate, and the W4.2 tree-cache
//! invalidation contract.
//!
//! The gate reads one fixture window with a `query` many times over MCP and
//! fails when p50 is 40 ms or more, p95 is 150 ms or more, or either is more
//! than 20% above the recorded baseline for the same OS, fixture and case
//! (with a 2 ms floor, so sub-millisecond jitter on a fast runner is not a
//! regression). Other cases are measured and recorded but not gated.
//!
//! Baselines come from `DOVE_LATENCY_BASELINE` (a results file from an
//! earlier run, which is how CI should feed its own runner's numbers back
//! in) or else from `latency_baseline.json` beside this file. A case with no
//! baseline entry skips only the regression check. Results are written to
//! `DOVE_LATENCY_RESULTS`, or `target/dove-latency/<os>-<fixture>.json`.
//!
//! Fixtures:
//! - Windows: `support/latency_fixture.ps1`, a WinForms window with nine
//!   controls that applies commands written to a file (rename, add, remove,
//!   enable, disable, set value) and acknowledges each one. Verified locally.
//! - Linux: the GTK3 harness; macOS: the SwiftUI harness. Unverified until the
//!   W7 CI runs them. The invalidation tests need the command file, so they
//!   run on Windows only.
//!
//! Run (needs a desktop; never steals focus on Windows):
//!   cargo test -p cua-driver-e2e --test latency_test -- --ignored --nocapture --test-threads=1

use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use cua_driver_testkit::{Driver, McpDriver, ToolResponse};
use serde_json::{json, Value};

const P50_LIMIT_MS: f64 = 40.0;
const P95_LIMIT_MS: f64 = 150.0;
const REGRESSION_LIMIT: f64 = 0.20;
const REGRESSION_FLOOR_MS: f64 = 2.0;
const WARMUP: usize = 5;
const SAMPLES: usize = 100;
/// The gated case.
const GATED_CASE: &str = "gws_query";

struct Fixture {
    pid: u32,
    window_id: u64,
    /// `<os>/<fixture>`, the baseline key prefix.
    key: String,
    /// A query that matches at least one row.
    query: &'static str,
    /// Command directory of the Windows fixture.
    control: Option<tempfile::TempDir>,
}

fn require_fixtures() -> bool {
    std::env::var_os("CUA_TEST_REQUIRE_FIXTURES").is_some()
}

fn skip(why: &str) -> Option<Fixture> {
    assert!(!require_fixtures(), "required latency fixture missing: {why}");
    eprintln!("[latency] skipping: {why}");
    None
}

#[cfg(target_os = "windows")]
fn launch_fixture(driver: &mut McpDriver) -> Option<Fixture> {
    use std::process::{Command, Stdio};
    let script = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/support/latency_fixture.ps1");
    let control = tempfile::tempdir().expect("fixture command directory");
    driver
        .reaper()
        .spawn(
            Command::new("powershell.exe")
                .args(["-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden"])
                .arg("-File")
                .arg(&script)
                .arg("-Dir")
                .arg(control.path())
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null()),
        )
        .expect("launch the WinForms latency fixture");
    let ready = control.path().join("fixture.json");
    let deadline = Instant::now() + Duration::from_secs(30);
    let info: Value = loop {
        if let Some(info) = std::fs::read_to_string(&ready)
            .ok()
            .and_then(|text| serde_json::from_str(&text).ok())
        {
            break info;
        }
        if Instant::now() > deadline {
            return skip("the WinForms fixture did not start within 30 s");
        }
        std::thread::sleep(Duration::from_millis(100));
    };
    let pid = info["pid"].as_u64().expect("fixture pid") as u32;
    let window_id = info["hwnd"].as_u64().expect("fixture hwnd");
    driver.reaper().track_pid(pid);
    let fixture = Fixture {
        pid,
        window_id,
        key: "windows/winforms".into(),
        query: "Save",
        control: Some(control),
    };
    // Wait until UI Automation exposes the client area.
    let deadline = Instant::now() + Duration::from_secs(15);
    while !read(driver, &fixture, json!({ "query": "Save", "include_screenshot": false }))
        .tree_text()
        .contains("\"Save\"")
    {
        if Instant::now() > deadline {
            return skip("the WinForms fixture never exposed its controls");
        }
        std::thread::sleep(Duration::from_millis(200));
    }
    Some(fixture)
}

#[cfg(target_os = "linux")]
fn launch_fixture(driver: &mut McpDriver) -> Option<Fixture> {
    launch_harness(
        driver,
        cua_driver_testkit::harness_app("harness-gtk3", "CuaTestHarness.Gtk3"),
        "CuaTestHarness GTK3",
        "linux/gtk3",
        "button",
    )
}

#[cfg(target_os = "macos")]
fn launch_fixture(driver: &mut McpDriver) -> Option<Fixture> {
    launch_harness(
        driver,
        cua_driver_testkit::harness_app(
            "harness-swiftui",
            "CuaTestHarness.SwiftUI.app/Contents/MacOS/CuaTestHarness.SwiftUI",
        ),
        "CuaTestHarness SwiftUI",
        "macos/swiftui",
        "AXButton",
    )
}

#[cfg(any(target_os = "linux", target_os = "macos"))]
fn launch_harness(
    driver: &mut McpDriver,
    exe: PathBuf,
    title: &str,
    key: &str,
    query: &'static str,
) -> Option<Fixture> {
    use std::process::{Command, Stdio};
    if !exe.exists() {
        return skip(&format!("harness not built: {exe:?}"));
    }
    driver
        .reaper()
        .spawn(Command::new(&exe).stdout(Stdio::null()).stderr(Stdio::null()))
        .expect("launch the harness");
    let deadline = Instant::now() + Duration::from_secs(15);
    while Instant::now() < deadline {
        let response = driver.call("list_windows", json!({}));
        for window in response.structured()["windows"].as_array().into_iter().flatten() {
            if window["title"].as_str().unwrap_or("").contains(title) {
                let pid = window["pid"].as_u64().unwrap_or(0) as u32;
                let window_id = window["window_id"].as_u64().unwrap_or(0);
                if pid != 0 && window_id != 0 {
                    driver.reaper().track_pid(pid);
                    std::thread::sleep(Duration::from_millis(500));
                    return Some(Fixture {
                        pid,
                        window_id,
                        key: key.into(),
                        query,
                        control: None,
                    });
                }
            }
        }
        std::thread::sleep(Duration::from_millis(300));
    }
    skip(&format!("{title} window never appeared"))
}

/// A driver whose daemon has an isolated home and `extra` in its environment.
fn spawn_driver(extra: &[(&str, &str)]) -> Option<(McpDriver, tempfile::TempDir)> {
    let home = tempfile::tempdir().expect("isolated home");
    let root = home.path().display().to_string();
    let local = home.path().join("AppData/Local").display().to_string();
    let roaming = home.path().join("AppData/Roaming").display().to_string();
    let _ = std::fs::create_dir_all(&local);
    let _ = std::fs::create_dir_all(&roaming);
    let mut env: Vec<(&str, &str)> = vec![
        ("USERPROFILE", &root),
        ("HOME", &root),
        ("LOCALAPPDATA", &local),
        ("APPDATA", &roaming),
    ];
    env.extend_from_slice(extra);
    let driver = McpDriver::spawn_with_env(&env)?;
    Some((driver, home))
}

fn read(driver: &mut McpDriver, fixture: &Fixture, extra: Value) -> ToolResponse {
    let mut args = json!({
        "pid": fixture.pid,
        "window_id": fixture.window_id,
        "tree_format": "markdown",
    });
    for (key, value) in extra.as_object().into_iter().flatten() {
        args[key] = value.clone();
    }
    let response = driver.call("get_window_state", args);
    assert!(
        !response.is_error(),
        "get_window_state failed: {}",
        response.text()
    );
    response
}

#[derive(Debug, Clone, Copy)]
struct Stats {
    p50: f64,
    p95: f64,
    mean: f64,
    min: f64,
    max: f64,
    n: usize,
}

fn percentile(sorted: &[f64], p: f64) -> f64 {
    // Nearest rank.
    let rank = (p * sorted.len() as f64).ceil() as usize;
    sorted[rank.clamp(1, sorted.len()) - 1]
}

fn measure(mut call: impl FnMut() -> ToolResponse) -> Stats {
    for _ in 0..WARMUP {
        call();
    }
    let mut samples: Vec<f64> = (0..SAMPLES)
        .map(|_| {
            let started = Instant::now();
            let response = call();
            let elapsed = started.elapsed().as_secs_f64() * 1000.0;
            assert!(!response.is_error(), "call failed: {}", response.text());
            elapsed
        })
        .collect();
    samples.sort_by(|a, b| a.total_cmp(b));
    Stats {
        p50: percentile(&samples, 0.50),
        p95: percentile(&samples, 0.95),
        mean: samples.iter().sum::<f64>() / samples.len() as f64,
        min: samples[0],
        max: samples[samples.len() - 1],
        n: samples.len(),
    }
}

fn baseline() -> Value {
    let path = std::env::var_os("DOVE_LATENCY_BASELINE")
        .map(PathBuf::from)
        .unwrap_or_else(|| Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/latency_baseline.json"));
    std::fs::read_to_string(&path)
        .ok()
        .and_then(|text| serde_json::from_str(&text).ok())
        .unwrap_or_else(|| json!({}))
}

fn results_path(fixture: &Fixture) -> PathBuf {
    std::env::var_os("DOVE_LATENCY_RESULTS")
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            cua_driver_testkit::workspace_root()
                .join("target/dove-latency")
                .join(format!("{}.json", fixture.key.replace('/', "-")))
        })
}

/// Failures of `stats` against the absolute limits (gated case only) and the
/// baseline entry for `key`.
fn gate(key: &str, stats: Stats, gated: bool, baseline: &Value) -> Vec<String> {
    let mut failures = Vec::new();
    if gated {
        if stats.p50 >= P50_LIMIT_MS {
            failures.push(format!("{key}: p50 {:.1} ms >= {P50_LIMIT_MS} ms", stats.p50));
        }
        if stats.p95 >= P95_LIMIT_MS {
            failures.push(format!("{key}: p95 {:.1} ms >= {P95_LIMIT_MS} ms", stats.p95));
        }
    }
    if let Some(entry) = baseline.get(key) {
        for (name, measured) in [("p50", stats.p50), ("p95", stats.p95)] {
            let Some(base) = entry[format!("{name}_ms")].as_f64() else {
                continue;
            };
            let limit = (base * (1.0 + REGRESSION_LIMIT)).max(base + REGRESSION_FLOOR_MS);
            if gated && measured > limit {
                failures.push(format!(
                    "{key}: {name} {measured:.1} ms regressed more than 20% over the \
                     baseline {base:.1} ms (limit {limit:.1} ms)"
                ));
            }
        }
    } else {
        eprintln!("[latency] {key}: no baseline entry; regression check skipped");
    }
    failures
}

/// The gate, on the default configuration (tree cache off). Also records
/// ungated cases: the read with a screenshot, an unqueried read,
/// `list_windows`, and the query with the opt-in tree cache.
#[test]
#[ignore = "needs a desktop and a fixture app"]
fn get_window_state_query_latency_gate() {
    let Some((mut driver, _home)) = spawn_driver(&[]) else {
        return;
    };
    let Some(fixture) = launch_fixture(&mut driver) else {
        return;
    };
    let query = fixture.query;
    let mut cases: Vec<(&str, Stats)> = Vec::new();
    // A just-launched (or just-restored) window can take a moment to expose
    // its controls.
    let deadline = Instant::now() + Duration::from_secs(15);
    loop {
        let first = read(&mut driver, &fixture, json!({ "query": query, "include_screenshot": false }));
        if first.tree_text().to_lowercase().contains(&query.to_lowercase()) {
            break;
        }
        assert!(
            Instant::now() < deadline,
            "the query {query:?} matched nothing:\n{}",
            first.tree_text()
        );
        std::thread::sleep(Duration::from_millis(200));
    }
    cases.push((
        GATED_CASE,
        measure(|| read(&mut driver, &fixture, json!({ "query": query, "include_screenshot": false }))),
    ));
    cases.push((
        "gws_query_screenshot",
        measure(|| read(&mut driver, &fixture, json!({ "query": query }))),
    ));
    cases.push((
        "gws_full_tree",
        measure(|| read(&mut driver, &fixture, json!({ "include_screenshot": false }))),
    ));
    cases.push((
        "list_windows_pid",
        measure(|| driver.call("list_windows", json!({ "pid": fixture.pid }))),
    ));

    // The same query with the opt-in tree cache. `driver` stays alive: its
    // reaper owns the fixture.
    if let Some((mut cached, _home)) = spawn_driver(&[("DOVE_TREE_CACHE", "1")]) {
        cases.push((
            "gws_query_cache_opt_in",
            measure(|| read(&mut cached, &fixture, json!({ "query": query, "include_screenshot": false }))),
        ));
    }

    let baseline = baseline();
    let mut failures = Vec::new();
    let mut results = serde_json::Map::new();
    for (case, stats) in &cases {
        let key = format!("{}/{case}", fixture.key);
        eprintln!(
            "[latency] {key}: p50 {:.1} ms  p95 {:.1} ms  mean {:.1}  min {:.1}  max {:.1}  (n={})",
            stats.p50, stats.p95, stats.mean, stats.min, stats.max, stats.n
        );
        failures.extend(gate(&key, *stats, *case == GATED_CASE, &baseline));
        results.insert(
            key,
            json!({
                "p50_ms": stats.p50,
                "p95_ms": stats.p95,
                "mean_ms": stats.mean,
                "min_ms": stats.min,
                "max_ms": stats.max,
                "n": stats.n,
                "gated": *case == GATED_CASE,
            }),
        );
    }
    let path = results_path(&fixture);
    if let Some(parent) = path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    let _ = std::fs::write(&path, serde_json::to_string_pretty(&Value::Object(results)).unwrap());
    eprintln!("[latency] results written to {}", path.display());
    assert!(failures.is_empty(), "latency gate failed:\n{}", failures.join("\n"));
}

// ── tree-cache invalidation (Windows fixture) ──────────────────────────────

/// Apply one fixture command and wait until the fixture's UI thread has
/// applied it.
#[cfg(target_os = "windows")]
fn mutate(fixture: &Fixture, command: &str) {
    let dir = fixture.control.as_ref().expect("command directory").path();
    let acks = || {
        std::fs::read_to_string(dir.join("ack.txt"))
            .map(|text| text.lines().count())
            .unwrap_or(0)
    };
    let before = acks();
    let staged = dir.join("cmd.txt.tmp");
    std::fs::write(&staged, format!("{command}\n")).expect("stage fixture command");
    std::fs::rename(&staged, dir.join("cmd.txt")).expect("publish fixture command");
    let deadline = Instant::now() + Duration::from_secs(10);
    while acks() <= before {
        assert!(Instant::now() < deadline, "fixture never applied {command:?}");
        std::thread::sleep(Duration::from_millis(5));
    }
}

/// A query read. A read whose walk timed out says nothing about staleness
/// (the response says the provider did not answer), so it is retried.
#[cfg(target_os = "windows")]
fn tree(driver: &mut McpDriver, fixture: &Fixture, query: &str) -> String {
    for _ in 0..10 {
        let text = read(driver, fixture, json!({ "query": query, "include_screenshot": false }))
            .tree_text()
            .to_owned();
        if !text.contains("did not answer") {
            return text;
        }
        std::thread::sleep(Duration::from_millis(200));
    }
    panic!("the fixture's UIA provider did not answer ten reads in a row");
}

/// With the opt-in tree cache, a row a read returns is never stale: each
/// mutation of a row the query already matches is followed by a read with
/// no delay, many times, so a cached row that was not re-read would show up
/// here. (Rows the application adds are covered by
/// `added_rows_appear_within_the_event_window`.)
#[cfg(target_os = "windows")]
#[test]
#[ignore = "needs a desktop and the WinForms fixture"]
fn cached_reads_never_return_stale_rows() {
    let Some((mut driver, _home)) = spawn_driver(&[("DOVE_TREE_CACHE", "1")]) else {
        return;
    };
    let Some(fixture) = launch_fixture(&mut driver) else {
        return;
    };
    // Warm the cache: these reads are answered from the stored walk.
    for _ in 0..3 {
        assert!(tree(&mut driver, &fixture, "Status").contains("Status: idle"));
    }

    // Renames (PropertyChanged on a text row).
    for round in 1..=25 {
        let name = format!("Status: renamed {round}");
        mutate(&fixture, &format!("label {name}"));
        let text = tree(&mut driver, &fixture, "Status");
        assert!(
            text.contains(&format!("\"{name}\"")),
            "round {round}: rename not visible:\n{text}"
        );
        // A second read is a cache hit; it must agree.
        let again = tree(&mut driver, &fixture, "Status");
        assert!(again.contains(&format!("\"{name}\"")), "round {round}: hit lost the rename");
    }

    // Value changes (PropertyChanged on an actionable row).
    for round in 1..=10 {
        let value = format!("typed {round}");
        mutate(&fixture, &format!("value {value}"));
        let text = tree(&mut driver, &fixture, "entry");
        assert!(
            text.contains(&format!("value=\"{value}\"")),
            "round {round}: value change not visible:\n{text}"
        );
    }

    // Removed rows: the query lists the row, so the read re-reads it.
    for round in 1..=10 {
        let name = format!("Extra{round}");
        mutate(&fixture, &format!("add {name}"));
        let deadline = Instant::now() + Duration::from_secs(5);
        while !tree(&mut driver, &fixture, &name).contains(&format!("\"{name}\"")) {
            assert!(Instant::now() < deadline, "round {round}: added row never listed");
            std::thread::sleep(Duration::from_millis(20));
        }
        mutate(&fixture, &format!("remove {name}"));
        let removed = tree(&mut driver, &fixture, &name);
        assert!(
            !removed.contains(&format!("\"{name}\"")),
            "round {round}: removed row still listed:\n{removed}"
        );
    }

    // Disable and enable (an actionable row loses and regains its index).
    for round in 1..=5 {
        mutate(&fixture, "disable save");
        let disabled = tree(&mut driver, &fixture, "Save");
        assert!(
            disabled.lines().any(|line| line.contains("Button \"Save\"") && !line.contains("] Button")),
            "round {round}: disabled Save still indexed:\n{disabled}"
        );
        mutate(&fixture, "enable save");
        let enabled = tree(&mut driver, &fixture, "Save");
        assert!(
            enabled.lines().any(|line| line.contains("] Button \"Save\"")),
            "round {round}: enabled Save not indexed:\n{enabled}"
        );
    }
}

/// A row the application adds is missing from opt-in cached reads until its
/// UIA event arrives (the reason the cache is off by default). Measures that
/// window and fails only if it exceeds the cache's age bound plus slack,
/// which would mean the event never invalidated the walk.
#[cfg(target_os = "windows")]
#[test]
#[ignore = "needs a desktop and the WinForms fixture"]
fn added_rows_appear_within_the_event_window() {
    let Some((mut driver, _home)) = spawn_driver(&[("DOVE_TREE_CACHE", "1")]) else {
        return;
    };
    let Some(fixture) = launch_fixture(&mut driver) else {
        return;
    };
    let mut lags = Vec::new();
    for round in 1..=10 {
        let name = format!("Late{round}");
        let _ = tree(&mut driver, &fixture, &name);
        let _ = tree(&mut driver, &fixture, &name);
        mutate(&fixture, &format!("add {name}"));
        let started = Instant::now();
        while !tree(&mut driver, &fixture, &name).contains(&format!("\"{name}\"")) {
            assert!(
                started.elapsed() < Duration::from_millis(3000),
                "round {round}: added row still missing after 3 s"
            );
            std::thread::sleep(Duration::from_millis(5));
        }
        lags.push(started.elapsed().as_secs_f64() * 1000.0);
    }
    lags.sort_by(|a, b| a.total_cmp(b));
    eprintln!(
        "[latency] opt-in cache: added rows appeared after p50 {:.0} ms, max {:.0} ms",
        percentile(&lags, 0.5),
        lags[lags.len() - 1]
    );
}

/// A driver action invalidates every cached walk before it runs.
#[cfg(target_os = "windows")]
#[test]
#[ignore = "needs a desktop and the WinForms fixture"]
fn reads_after_a_driver_action_see_its_effect() {
    let Some((mut driver, _home)) = spawn_driver(&[("DOVE_TREE_CACHE", "1")]) else {
        return;
    };
    let Some(fixture) = launch_fixture(&mut driver) else {
        return;
    };
    // Warm the cache on the label the click changes.
    assert!(tree(&mut driver, &fixture, "Status").contains("Status: idle"));
    assert!(tree(&mut driver, &fixture, "Status").contains("Status: idle"));
    // The token's snapshot must be the window's latest read.
    let state = read(&mut driver, &fixture, json!({ "query": "Save", "tree_format": "elements" }));
    let token = state.structured()["elements"]
        .as_array()
        .into_iter()
        .flatten()
        .find(|element| element["label"].as_str() == Some("Save"))
        .and_then(|element| element["element_token"].as_str())
        .expect("Save element_token")
        .to_owned();
    let click = driver.call(
        "click",
        json!({ "pid": fixture.pid, "window_id": fixture.window_id, "element_token": token }),
    );
    assert!(!click.is_error(), "click failed: {}", click.text());
    // The click already returned, so the change happened before this read.
    let text = tree(&mut driver, &fixture, "Status");
    assert!(text.contains("Status: saved"), "click effect not visible:\n{text}");
}

/// Reads with the cache on and off return the same tree.
#[cfg(target_os = "windows")]
#[test]
#[ignore = "needs a desktop and the WinForms fixture"]
fn cached_and_uncached_reads_agree() {
    let Some((mut cached, _home)) = spawn_driver(&[("DOVE_TREE_CACHE", "1")]) else {
        return;
    };
    let Some(fixture) = launch_fixture(&mut cached) else {
        return;
    };
    let Some((mut uncached, _home2)) = spawn_driver(&[]) else {
        return;
    };
    for query in [None, Some("Save"), Some("Status"), Some("mode")] {
        let extra = match query {
            Some(query) => json!({ "query": query, "include_screenshot": false }),
            None => json!({ "include_screenshot": false }),
        };
        let _ = read(&mut cached, &fixture, extra.clone());
        let hit = read(&mut cached, &fixture, extra.clone()).tree_text().to_owned();
        let walked = read(&mut uncached, &fixture, extra).tree_text().to_owned();
        assert_eq!(hit, walked, "query {query:?}");
    }
}
