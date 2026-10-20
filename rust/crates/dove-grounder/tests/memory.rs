//! W9 gate: the grounder adds under 30 MB of resident memory, and unloads
//! when idle. Linux only (it reads /proc/self); runs when
//! `DOVE_DRIVER_GROUNDER_MODEL` is set; the budget is asserted on release
//! builds (`cargo test --release`), as the daemon ships.
//!
//! The inputs are built first, then the peak-RSS mark is reset, so the
//! measured growth is the load plus decisions on nexi-cua's five captured
//! pages (the largest has 1,000+ elements) and nothing else.

use dove_grounder::service::Grounder;
use dove_grounder::types::{Bounds, Element, Observation};
use serde_json::Value;
use std::io::Read;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::{Duration, Instant};

const BUDGET_KB: u64 = 30 * 1024;

fn status_kb(key: &str) -> u64 {
    let status = std::fs::read_to_string("/proc/self/status").expect("/proc/self/status");
    status
        .lines()
        .find_map(|line| line.strip_prefix(key))
        .and_then(|rest| rest.trim().trim_end_matches("kB").trim().parse().ok())
        .unwrap_or_else(|| panic!("no {key} in /proc/self/status"))
}

/// The real pages and their goals, as observations.
fn pages() -> Vec<(Observation, Vec<String>)> {
    let path =
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/goldens/nexi-cua-0.4.0.json.gz");
    let mut text = String::new();
    flate2::read::GzDecoder::new(std::fs::File::open(path).unwrap())
        .read_to_string(&mut text)
        .unwrap();
    let g: Value = serde_json::from_str(&text).unwrap();
    g["real"]
        .as_array()
        .unwrap()
        .iter()
        .map(|page| {
            let elements = page["obs"]["els"]
                .as_array()
                .unwrap()
                .iter()
                .map(|r| Element {
                    id: r[0].as_str().unwrap().into(),
                    role: r[1].as_str().unwrap().into(),
                    name: r[2].as_str().unwrap().into(),
                    value: r[3].as_str().unwrap().into(),
                    bounds: r[4].as_array().map(|b| Bounds {
                        x: b[0].as_f64().unwrap(),
                        y: b[1].as_f64().unwrap(),
                        w: b[2].as_f64().unwrap(),
                        h: b[3].as_f64().unwrap(),
                    }),
                    enabled: r[5].as_i64() != Some(0),
                    focused: r[6].as_i64() == Some(1),
                    checked: r[7].as_i64().map(|c| c != 0),
                    selected: r[8].as_i64() == Some(1),
                    children_count: r[9].as_i64().unwrap(),
                    depth: r[10].as_i64().unwrap(),
                    ..Default::default()
                })
                .collect();
            let goals = page["cases"]
                .as_array()
                .unwrap()
                .iter()
                .map(|c| c["goal"].as_str().unwrap().to_owned())
                .collect();
            let obs = Observation {
                elements,
                screen_w: page["obs"]["sw"].as_i64().unwrap(),
                screen_h: page["obs"]["sh"].as_i64().unwrap(),
                ..Default::default()
            };
            (obs, goals)
        })
        .collect()
}

#[test]
fn grounder_adds_under_30_mb_and_unloads_when_idle() {
    if !cfg!(target_os = "linux") {
        return;
    }
    let Some(path) = std::env::var_os("DOVE_DRIVER_GROUNDER_MODEL") else {
        eprintln!("DOVE_DRIVER_GROUNDER_MODEL is not set: skipping the memory gate");
        return;
    };
    let pages = pages();
    let goals: usize = pages.iter().map(|(_, g)| g.len()).sum();
    // Reset VmHWM to the current RSS (Linux >= 4.0).
    std::fs::write("/proc/self/clear_refs", "5").expect("reset the peak RSS mark");
    let base = status_kb("VmRSS:");
    let grounder = Arc::new(Grounder::new(
        PathBuf::from(path),
        Duration::from_millis(400),
    ));
    let started = Instant::now();
    for _ in 0..3 {
        for (obs, goals) in &pages {
            for goal in goals {
                std::hint::black_box(grounder.decide(obs, goal));
            }
        }
    }
    let per_decision = started.elapsed() / (3 * goals as u32);
    let peak = status_kb("VmHWM:");
    let added = peak.saturating_sub(base);
    eprintln!(
        "grounder: base RSS {base} kB, peak {peak} kB, added {added} kB over {} decisions \
         ({per_decision:?} each, first load included)",
        3 * goals
    );
    // The daemon ships as a release build; tract unoptimised allocates more.
    if cfg!(debug_assertions) {
        eprintln!("debug build: the {BUDGET_KB} kB budget is checked with --release");
    } else {
        assert!(
            added < BUDGET_KB,
            "the grounder added {added} kB, budget {BUDGET_KB} kB"
        );
    }

    assert!(grounder.is_loaded());
    let deadline = Instant::now() + Duration::from_secs(5);
    while grounder.is_loaded() && Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(50));
    }
    assert!(
        !grounder.is_loaded(),
        "the grounder did not unload after 400 ms idle"
    );
    // It loads again on demand.
    let (obs, goals) = &pages[0];
    assert!(!grounder.decide(obs, &goals[0]).reason.contains("loading"));
    assert!(grounder.is_loaded());
}
