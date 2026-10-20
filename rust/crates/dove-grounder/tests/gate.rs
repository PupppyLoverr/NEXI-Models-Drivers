//! W9 gate: the Rust port against nexi-cua's own decisions.
//!
//! `tests/goldens/nexi-cua-0.4.0.json.gz` is written by
//! `scripts/make_goldens.py` from the unmodified Python policy (CPU torch,
//! fp32 weights) on the inputs nexi-cua's evals use: its five captured
//! real-web pages with their 72 labelled goals, and the 2,000 held-out
//! synthetic screens of `semantic_eval` (seed 31337). The synthetic screens
//! are not stored: `support::synth` regenerates them bit for bit, and each
//! golden record's BLAKE2b digest of its screen is checked first.
//!
//! Without weights only the resolver is checked. With
//! `DOVE_DRIVER_GROUNDER_MODEL` pointing at the ONNX asset the whole gate
//! runs: identical decisions (the action taken, or an abstention) and an
//! identical top-ranked candidate on every case, both with and without the
//! resolver, and therefore the same scores as Python.
//!
//! The scores are the ones nexi-cua v0.4.0 itself gets on these inputs with
//! CPU torch: 71/72 and 10/10 on real-web, 95.01% (full pipeline) and
//! 61.56% (ranker alone) on the synthetic screens. Its documents quote
//! 98.8% and 92.1% for the synthetic eval; the committed code and weights
//! do not reproduce those (Python 3.12 and 3.13, torch 2.14.1, any hash
//! seed), so they are not asserted here.

mod support;

use blake2::digest::{Update, VariableOutput};
use dove_grounder::infer::{decide, Calibration};
use dove_grounder::model::Model;
use dove_grounder::resolver;
use dove_grounder::types::{Bounds, BrowserState, Decision, Element, Observation, Tab};
use serde_json::Value;
use std::io::Read;
use std::path::PathBuf;
use std::sync::OnceLock;

fn goldens() -> &'static Value {
    static GOLDENS: OnceLock<Value> = OnceLock::new();
    GOLDENS.get_or_init(|| {
        let path =
            PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/goldens/nexi-cua-0.4.0.json.gz");
        let mut text = String::new();
        flate2::read::GzDecoder::new(std::fs::File::open(&path).expect("goldens"))
            .read_to_string(&mut text)
            .expect("gzip");
        serde_json::from_str(&text).expect("json")
    })
}

fn model() -> Option<&'static Model> {
    static MODEL: OnceLock<Option<Model>> = OnceLock::new();
    MODEL
        .get_or_init(|| {
            let path = std::env::var_os("DOVE_DRIVER_GROUNDER_MODEL")?;
            Some(Model::load(path.as_ref()).expect("load the grounder model"))
        })
        .as_ref()
}

fn observation(raw: &Value, goal: &str) -> Observation {
    let elements = raw["els"]
        .as_array()
        .unwrap()
        .iter()
        .map(|row| {
            let r = row.as_array().unwrap();
            let s = |i: usize| r[i].as_str().unwrap().to_owned();
            let flag = |i: usize| r[i].as_i64().unwrap() != 0;
            Element {
                id: s(0),
                role: s(1),
                name: s(2),
                value: s(3),
                bounds: r[4].as_array().map(|b| Bounds {
                    x: b[0].as_f64().unwrap(),
                    y: b[1].as_f64().unwrap(),
                    w: b[2].as_f64().unwrap(),
                    h: b[3].as_f64().unwrap(),
                }),
                enabled: flag(5),
                focused: flag(6),
                checked: r[7].as_i64().map(|c| c != 0),
                selected: flag(8),
                children_count: r[9].as_i64().unwrap(),
                source: String::new(),
                depth: r[10].as_i64().unwrap(),
                extra: r[11].as_object().cloned().unwrap_or_default(),
            }
        })
        .collect();
    let browser = raw.get("tabs").map(|tabs| BrowserState {
        tabs: tabs
            .as_array()
            .unwrap()
            .iter()
            .map(|t| Tab {
                id: t[0].as_str().unwrap().to_owned(),
                title: t[1].as_str().unwrap().to_owned(),
            })
            .collect(),
        ..Default::default()
    });
    Observation {
        goal: goal.to_owned(),
        elements,
        browser,
        screen_w: raw["sw"].as_i64().unwrap(),
        screen_h: raw["sh"].as_i64().unwrap(),
    }
}

/// `screen_digest` of make_goldens.py: BLAKE2b-64 of every field the
/// policy reads, floats by their bits.
fn screen_digest(obs: &Observation) -> String {
    let mut parts = vec![format!("{} {}", obs.screen_w, obs.screen_h)];
    for e in &obs.elements {
        let bounds = match &e.bounds {
            None => "-".to_owned(),
            Some(b) => [b.x, b.y, b.w, b.h]
                .iter()
                .map(|v| format!("{:016x}", v.to_bits()))
                .collect(),
        };
        let extra: Vec<String> = e
            .extra
            .iter()
            .map(|(k, v)| format!("{k}={}", serde_json::to_string(v).unwrap()))
            .collect();
        let flag = |b: bool| (b as u8).to_string();
        parts.push(
            [
                e.id.clone(),
                e.role.clone(),
                e.name.clone(),
                e.value.clone(),
                bounds,
                flag(e.enabled),
                flag(e.focused),
                e.checked.map_or("-".to_owned(), flag),
                flag(e.selected),
                e.children_count.to_string(),
                e.depth.to_string(),
                extra.join(","),
            ]
            .join("\x1f"),
        );
    }
    if let Some(browser) = &obs.browser {
        for tab in &browser.tabs {
            parts.push(format!("tab\x1f{}\x1f{}", tab.id, tab.title));
        }
    }
    let mut hasher = blake2::Blake2bVar::new(8).unwrap();
    hasher.update(parts.join("\x1e").as_bytes());
    let mut out = [0u8; 8];
    hasher.finalize_variable(&mut out).unwrap();
    out.iter().map(|b| format!("{b:02x}")).collect()
}

/// Every (observation, goal, case) in the goldens. Synthetic screens are
/// regenerated and must match the digest and scoring truth Python recorded.
fn cases() -> &'static [(String, Observation, &'static Value)] {
    static CASES: OnceLock<Vec<(String, Observation, &'static Value)>> = OnceLock::new();
    CASES.get_or_init(|| {
        let g = goldens();
        let mut out = Vec::new();
        for page in g["real"].as_array().unwrap() {
            let name = page["name"].as_str().unwrap();
            for (i, case) in page["cases"].as_array().unwrap().iter().enumerate() {
                let goal = case["goal"].as_str().unwrap();
                out.push((
                    format!("real/{name}/{i}"),
                    observation(&page["obs"], goal),
                    case,
                ));
            }
        }
        let records = g["synthetic"].as_array().unwrap();
        let seed = g["seed"].as_u64().unwrap();
        let samples = support::synth::generate(records.len(), seed);
        for (i, (case, sample)) in records.iter().zip(samples).enumerate() {
            let name = format!("synthetic/{i}");
            assert_eq!(
                case["goal"].as_str(),
                Some(sample.obs.goal.as_str()),
                "{name} goal"
            );
            assert_eq!(
                case["h"].as_str(),
                Some(screen_digest(&sample.obs).as_str()),
                "{name} screen"
            );
            assert_eq!(
                case["truth"].as_str(),
                support::synth::truth(&sample).as_deref(),
                "{name} truth"
            );
            out.push((name, sample.obs, case));
        }
        out
    })
}

/// Whether the Rust decision is one Python makes for this case.
fn agrees(decision: &Decision, python: &Value) -> bool {
    let ours = decision.summary();
    let theirs = python["d"].as_str().unwrap();
    let decision_ok = match python.get("alts").and_then(Value::as_array) {
        Some(alts) => alts.iter().any(|a| a.as_str() == Some(ours.as_str())),
        None => ours == theirs,
    };
    // The ranker's own top-1, abstained or not.
    let top_ok = match python.get("top").and_then(Value::as_str) {
        Some(top) => decision.top_k.first().map(|t| t.1.as_str()) == Some(top),
        None => true,
    };
    decision_ok && top_ok
}

fn describe(name: &str, decision: &Decision, python: &Value) -> String {
    format!(
        "{name}: rust {:?} (top {:?}, p {:.6}, conf {:.6}) vs python {}",
        decision.summary(),
        decision.top_k.first().map(|t| t.1.clone()),
        decision.probability,
        decision.confidence,
        python
    )
}

fn calibration() -> Calibration {
    let c = &goldens()["calibration"];
    Calibration {
        temperature: c["temperature"].as_f64().unwrap(),
        abstain_threshold: c["abstain_threshold"].as_f64().unwrap(),
    }
}

/// Runs without weights: every case Python settled with the resolver must be
/// settled the same way by the Rust resolver.
#[test]
fn resolver_matches_python_without_weights() {
    let mut checked = 0;
    let mut misses = Vec::new();
    for (name, obs, case) in cases() {
        let python = &case["full"];
        let rust = resolver::resolve(obs, &obs.goal);
        if python["by"] == "r" {
            checked += 1;
            let decision = decide(None, calibration(), obs, &obs.goal, true);
            if !agrees(&decision, python) {
                misses.push(describe(name, &decision, python));
            }
        } else if python.get("alts").is_none() {
            // Python deferred to the ranker, so the resolver must too.
            if let Some(action) = rust {
                misses.push(format!(
                    "{name}: rust resolved {action} where python deferred"
                ));
            }
        }
    }
    assert!(checked > 1000, "only {checked} resolver cases");
    assert!(
        misses.is_empty(),
        "{} of {checked} resolver cases differ:\n{}",
        misses.len(),
        misses.join("\n")
    );
}

struct Tally {
    total: usize,
    agree: usize,
    misses: Vec<String>,
}

fn run_mode(model: &Model, mode: &str) -> (Tally, Vec<(String, Decision, &'static Value)>) {
    let use_resolver = mode == "full";
    let mut tally = Tally {
        total: 0,
        agree: 0,
        misses: Vec::new(),
    };
    let mut decisions = Vec::new();
    for (name, obs, case) in cases() {
        let python = &case[mode];
        let decision = decide(Some(model), model.calibration, obs, &obs.goal, use_resolver);
        tally.total += 1;
        if agrees(&decision, python) {
            tally.agree += 1;
        } else {
            tally.misses.push(describe(name, &decision, python));
        }
        decisions.push((name.clone(), decision, *case));
    }
    (tally, decisions)
}

/// nexi-cua's real_eval score: the expected element and verb, or an abstain
/// on the two unanswerable goals per page.
fn real_score(decisions: &[(String, Decision, &Value)]) -> (usize, usize, usize, usize) {
    let (mut hit, mut total, mut abstain_hit, mut abstain_total) = (0, 0, 0, 0);
    for (name, d, case) in decisions.iter().filter(|(n, _, _)| n.starts_with("real/")) {
        let _ = name;
        total += 1;
        let ok = if case["expect_verb"].is_null() {
            abstain_total += 1;
            let ok = d.abstain;
            abstain_hit += ok as usize;
            ok
        } else {
            let want: Vec<&str> = match case["accept_verbs"].as_array() {
                Some(list) => list.iter().filter_map(Value::as_str).collect(),
                None => vec![case["expect_verb"].as_str().unwrap()],
            };
            match (&d.action, d.abstain) {
                (Some(a), false) => {
                    a.element_id.as_deref() == case["expect_element"].as_str()
                        && want.contains(&a.verb.as_str())
                }
                _ => false,
            }
        };
        hit += ok as usize;
    }
    (hit, total, abstain_hit, abstain_total)
}

/// semantic_eval's accuracy on answerable screens and abstain recall.
fn synthetic_score(decisions: &[(String, Decision, &Value)]) -> (f64, f64) {
    let (mut tp, mut wrong, mut abst_fp, mut abst_tp, mut abst_fn) = (0, 0, 0, 0, 0);
    for (_, d, case) in decisions
        .iter()
        .filter(|(n, _, _)| n.starts_with("synthetic/"))
    {
        match case["truth"].as_str() {
            None if d.abstain => abst_tp += 1,
            None => abst_fn += 1,
            Some(_) if d.abstain => abst_fp += 1,
            Some(truth) => {
                if d.summary() == truth {
                    tp += 1
                } else {
                    wrong += 1
                }
            }
        }
    }
    let accuracy = tp as f64 / (tp + wrong + abst_fp).max(1) as f64;
    let recall = abst_tp as f64 / (abst_tp + abst_fn).max(1) as f64;
    (accuracy, recall)
}

fn round4(x: f64) -> f64 {
    (x * 10_000.0).round() / 10_000.0
}

#[test]
fn full_pipeline_matches_python_and_scores() {
    let Some(model) = model() else {
        eprintln!("DOVE_DRIVER_GROUNDER_MODEL is not set: skipping the model gate");
        return;
    };
    let (tally, decisions) = run_mode(model, "full");
    let (hit, total, abstain_hit, abstain_total) = real_score(&decisions);
    let (accuracy, recall) = synthetic_score(&decisions);
    eprintln!(
        "full pipeline: {}/{} cases agree with python; real-web {hit}/{total}, abstain \
         {abstain_hit}/{abstain_total}; synthetic accuracy {:.4}, abstain recall {:.4}",
        tally.agree, tally.total, accuracy, recall
    );
    assert!(
        tally.misses.is_empty(),
        "{} cases differ from python:\n{}",
        tally.misses.len(),
        tally.misses.join("\n")
    );
    assert_eq!((hit, total), (71, 72), "real-web score");
    assert_eq!((abstain_hit, abstain_total), (10, 10), "real-web abstain");
    assert_eq!(round4(accuracy), 0.9501, "synthetic full-pipeline accuracy");
    assert_eq!(
        round4(recall),
        0.8847,
        "synthetic full-pipeline abstain recall"
    );
}

#[test]
fn ranker_alone_matches_python_and_scores() {
    let Some(model) = model() else {
        eprintln!("DOVE_DRIVER_GROUNDER_MODEL is not set: skipping the model gate");
        return;
    };
    let (tally, decisions) = run_mode(model, "ranker");
    let (accuracy, recall) = synthetic_score(&decisions);
    eprintln!(
        "ranker alone: {}/{} cases agree with python; synthetic accuracy {:.4}, abstain recall {:.4}",
        tally.agree, tally.total, accuracy, recall
    );
    assert!(
        tally.misses.is_empty(),
        "{} cases differ from python:\n{}",
        tally.misses.len(),
        tally.misses.join("\n")
    );
    assert_eq!(round4(accuracy), 0.6156, "synthetic ranker-only accuracy");
    assert_eq!(
        round4(recall),
        0.9172,
        "synthetic ranker-only abstain recall"
    );
}
