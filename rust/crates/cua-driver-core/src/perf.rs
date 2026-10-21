//! Stage timing for latency work (Dove W4).
//!
//! `CUA_LOG=dove_perf=debug` prints one line per timed operation, listing
//! each stage's duration in microseconds. When that target is disabled the
//! timer records nothing and costs one `Instant::now()`.

use std::time::Instant;

/// Records consecutive stage durations and logs them when dropped.
pub struct StageTimer {
    what: &'static str,
    started: Instant,
    last: Instant,
    stages: Option<Vec<(&'static str, u128)>>,
}

impl StageTimer {
    pub fn new(what: &'static str) -> Self {
        let now = Instant::now();
        let enabled = tracing::enabled!(target: "dove_perf", tracing::Level::DEBUG);
        Self {
            what,
            started: now,
            last: now,
            stages: enabled.then(Vec::new),
        }
    }

    /// Close the stage that ran since the previous mark (or since `new`).
    pub fn mark(&mut self, stage: &'static str) {
        if let Some(stages) = self.stages.as_mut() {
            let now = Instant::now();
            stages.push((stage, now.duration_since(self.last).as_micros()));
            self.last = now;
        }
    }
}

impl Drop for StageTimer {
    fn drop(&mut self) {
        let Some(stages) = self.stages.take() else {
            return;
        };
        let mut line = String::new();
        for (stage, us) in &stages {
            line.push_str(&format!("{stage}={us} "));
        }
        tracing::debug!(
            target: "dove_perf",
            "{} total_us={} {}",
            self.what,
            self.started.elapsed().as_micros(),
            line.trim_end()
        );
    }
}
