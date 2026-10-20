//! The Rust port of nexi-cua's synthetic generator against Python's own
//! output.
//!
//! `DOVE_GROUNDER_FULL_GOLDEN` names a gzip JSON file (written by
//! `scripts/make_goldens.py --with-screens`) whose `"synthetic"` list holds the 2,000
//! records of `generate(2000, seed=31337)`: the goal, the observation
//! (screen size, every element field, the browser tabs) and the scoring
//! truth. `support::synth::generate` must rebuild every one of them exactly,
//! floats to the bit. Without the variable the comparison is skipped.

mod support;

use dove_grounder::types::{Element, Observation};
use serde_json::Value;
use std::io::Read;
use support::synth::{generate, truth, Sample};

const SEED: u64 = 31337;

fn load(path: &str) -> Value {
    let mut text = String::new();
    flate2::read::GzDecoder::new(std::fs::File::open(path).expect("open the full golden"))
        .read_to_string(&mut text)
        .expect("gzip");
    serde_json::from_str(&text).expect("json")
}

/// `x == y` for a JSON float/int and an f64, bit for bit.
fn same_f64(json: &Value, ours: f64) -> bool {
    json.as_f64().is_some_and(|v| v.to_bits() == ours.to_bits())
}

fn same_i64(json: &Value, ours: i64) -> bool {
    json.as_i64() == Some(ours)
}

/// Differences between one golden element row and ours.
fn element_diffs(row: &Value, e: &Element, at: &str, out: &mut Vec<String>) {
    let r = row.as_array().expect("element row");
    let mut check = |field: &str, ok: bool| {
        if !ok {
            out.push(format!("{at}.{field}: python {row} rust {e:?}"));
        }
    };
    check("id", r[0].as_str() == Some(e.id.as_str()));
    check("role", r[1].as_str() == Some(e.role.as_str()));
    check("name", r[2].as_str() == Some(e.name.as_str()));
    check("value", r[3].as_str() == Some(e.value.as_str()));
    let bounds_ok = match (r[4].as_array(), &e.bounds) {
        (None, None) => r[4].is_null(),
        (Some(b), Some(ours)) => {
            b.len() == 4
                && same_f64(&b[0], ours.x)
                && same_f64(&b[1], ours.y)
                && same_f64(&b[2], ours.w)
                && same_f64(&b[3], ours.h)
        }
        _ => false,
    };
    check("bounds", bounds_ok);
    check("enabled", same_i64(&r[5], e.enabled as i64));
    check("focused", same_i64(&r[6], e.focused as i64));
    let checked_ok = match e.checked {
        None => r[7].is_null(),
        Some(c) => same_i64(&r[7], c as i64),
    };
    check("checked", checked_ok);
    check("selected", same_i64(&r[8], e.selected as i64));
    check("children_count", same_i64(&r[9], e.children_count));
    check("depth", same_i64(&r[10], e.depth));
    let extra_ok = if e.extra.is_empty() {
        r[11].is_null()
    } else {
        r[11].as_object() == Some(&e.extra)
    };
    check("extra", extra_ok);
}

fn observation_diffs(raw: &Value, obs: &Observation, at: &str, out: &mut Vec<String>) {
    if !same_i64(&raw["sw"], obs.screen_w) || !same_i64(&raw["sh"], obs.screen_h) {
        out.push(format!(
            "{at}.screen: python {}x{} rust {}x{}",
            raw["sw"], raw["sh"], obs.screen_w, obs.screen_h
        ));
    }
    let rows = raw["els"].as_array().expect("els");
    if rows.len() != obs.elements.len() {
        out.push(format!(
            "{at}.els: python {} elements, rust {}",
            rows.len(),
            obs.elements.len()
        ));
    }
    for (k, (row, e)) in rows.iter().zip(&obs.elements).enumerate() {
        element_diffs(row, e, &format!("{at}.els[{k}]"), out);
    }
    let python_tabs: Option<Vec<(String, String)>> = raw.get("tabs").map(|tabs| {
        tabs.as_array()
            .expect("tabs")
            .iter()
            .map(|t| {
                (
                    t[0].as_str().unwrap().to_owned(),
                    t[1].as_str().unwrap().to_owned(),
                )
            })
            .collect()
    });
    let rust_tabs: Option<Vec<(String, String)>> = obs.browser.as_ref().map(|b| {
        b.tabs
            .iter()
            .map(|t| (t.id.clone(), t.title.clone()))
            .collect()
    });
    if python_tabs != rust_tabs {
        out.push(format!(
            "{at}.tabs: python {python_tabs:?} rust {rust_tabs:?}"
        ));
    }
}

fn sample_diffs(rec: &Value, s: &Sample, at: &str) -> Vec<String> {
    let mut out = Vec::new();
    if rec["goal"].as_str() != Some(s.obs.goal.as_str()) {
        out.push(format!(
            "{at}.goal: python {} rust {:?}",
            rec["goal"], s.obs.goal
        ));
    }
    observation_diffs(&rec["obs"], &s.obs, &format!("{at}.obs"), &mut out);
    let ours = truth(s);
    if rec["truth"].as_str() != ours.as_deref() {
        out.push(format!("{at}.truth: python {} rust {ours:?}", rec["truth"]));
    }
    let verb = s.correct_idx.map(|i| s.candidates[i].verb.as_str());
    if rec["verb"].as_str() != verb {
        out.push(format!("{at}.verb: python {} rust {verb:?}", rec["verb"]));
    }
    out
}

#[test]
fn synthetic_screens_match_python() {
    let Ok(path) = std::env::var("DOVE_GROUNDER_FULL_GOLDEN") else {
        eprintln!("DOVE_GROUNDER_FULL_GOLDEN is not set; skipping the synth port comparison");
        return;
    };
    let golden = load(&path);
    let records = golden["synthetic"].as_array().expect("synthetic records");
    assert!(!records.is_empty(), "no synthetic records in {path}");
    let samples = generate(records.len(), SEED);
    let mut bad = 0usize;
    let mut shown = Vec::new();
    for (i, (rec, s)) in records.iter().zip(&samples).enumerate() {
        let diffs = sample_diffs(rec, s, &format!("synthetic/{i}"));
        if !diffs.is_empty() {
            bad += 1;
            if shown.len() < 20 {
                shown.extend(diffs.into_iter().take(5));
            }
        }
    }
    for line in &shown {
        eprintln!("{line}");
    }
    assert_eq!(
        bad,
        0,
        "{bad} of {} synthetic samples differ from Python",
        records.len()
    );
}
