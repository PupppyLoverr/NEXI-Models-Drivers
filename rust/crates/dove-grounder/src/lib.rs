//! Local Grounder (ROADMAP W9): a Rust port of nexi-cua v0.4.0's decision
//! policy (Apache-2.0), which turns an explicit goal ("click Save") into one
//! action over a window's snapshot rows, with no LLM call.
//!
//! - [`resolver`]: the deterministic first stage (full accessible names,
//!   ordinals, key chords, session commands).
//! - [`actions`], [`features`], [`model`], [`infer`]: candidate enumeration,
//!   hashed text features, the NEXI-CUA-1 ranker run with tract, and the
//!   decision with calibrated abstention and margin rescue.
//! - [`rows`], [`act`], [`service`]: dove-driver snapshot rows in, one driver
//!   call (or an abstention with candidate rows) out; the network loads on
//!   first use and unloads when idle, and is off without its weights.
//!
//! `tests/gate.rs` holds the port to nexi-cua's own decisions.

pub mod act;
pub mod actions;
pub mod features;
pub mod infer;
pub mod model;
pub mod pystr;
pub mod resolver;
pub mod rows;
pub mod service;
pub mod types;
