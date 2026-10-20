//! The grounder as the driver uses it: off unless the weights exist, loaded
//! on first use, dropped again after a quiet spell.
//!
//! `DOVE_DRIVER_GROUNDER_MODEL` names the ONNX asset. Unset, or pointing at
//! a missing file, the feature is off and [`Grounder::from_env`] returns
//! None. `DOVE_DRIVER_GROUNDER_IDLE_SECS` (default 300) is how long the
//! loaded network may sit unused before it is unloaded.

use crate::infer::{self, Calibration};
use crate::model::Model;
use crate::types::{Decision, Observation};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, OnceLock, Weak};
use std::time::{Duration, Instant};

pub const MODEL_ENV: &str = "DOVE_DRIVER_GROUNDER_MODEL";
pub const IDLE_ENV: &str = "DOVE_DRIVER_GROUNDER_IDLE_SECS";
const DEFAULT_IDLE: Duration = Duration::from_secs(300);

struct Loaded {
    model: Arc<Model>,
    last_used: Instant,
}

pub struct Grounder {
    path: PathBuf,
    idle: Duration,
    loaded: Mutex<Option<Loaded>>,
    reaper_running: Mutex<bool>,
}

impl Grounder {
    /// The process-wide grounder, or None when the weights are absent.
    pub fn from_env() -> Option<Arc<Grounder>> {
        static SHARED: OnceLock<Option<Arc<Grounder>>> = OnceLock::new();
        SHARED
            .get_or_init(|| {
                let path = PathBuf::from(std::env::var_os(MODEL_ENV)?);
                if !path.is_file() {
                    return None;
                }
                let idle = std::env::var(IDLE_ENV)
                    .ok()
                    .and_then(|s| s.trim().parse::<u64>().ok())
                    .map(Duration::from_secs)
                    .unwrap_or(DEFAULT_IDLE);
                Some(Arc::new(Grounder::new(path, idle)))
            })
            .clone()
    }

    pub fn new(path: PathBuf, idle: Duration) -> Self {
        Self {
            path,
            idle,
            loaded: Mutex::new(None),
            reaper_running: Mutex::new(false),
        }
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    /// Whether the network is in memory now.
    pub fn is_loaded(&self) -> bool {
        self.loaded
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .is_some()
    }

    /// Drop the network now (it reloads on the next decision).
    pub fn unload(&self) {
        *self.loaded.lock().unwrap_or_else(|e| e.into_inner()) = None;
        crate::model::release_free_memory();
    }

    fn model(self: &Arc<Self>) -> Result<Arc<Model>, String> {
        let mut slot = self.loaded.lock().unwrap_or_else(|e| e.into_inner());
        if let Some(loaded) = slot.as_mut() {
            loaded.last_used = Instant::now();
            return Ok(loaded.model.clone());
        }
        let model = Arc::new(
            Model::load(&self.path)
                .map_err(|e| format!("loading {}: {e:#}", self.path.display()))?,
        );
        *slot = Some(Loaded {
            model: model.clone(),
            last_used: Instant::now(),
        });
        drop(slot);
        self.start_reaper();
        Ok(model)
    }

    /// One thread per load: it ends once the network is unloaded.
    fn start_reaper(self: &Arc<Self>) {
        let mut running = self
            .reaper_running
            .lock()
            .unwrap_or_else(|e| e.into_inner());
        if *running {
            return;
        }
        *running = true;
        let weak: Weak<Self> = Arc::downgrade(self);
        let tick = (self.idle / 4).clamp(Duration::from_millis(50), Duration::from_secs(30));
        let spawned = std::thread::Builder::new()
            .name("dove-grounder-idle".into())
            .spawn(move || loop {
                std::thread::sleep(tick);
                let Some(this) = weak.upgrade() else { return };
                let mut slot = this.loaded.lock().unwrap_or_else(|e| e.into_inner());
                let expired = slot
                    .as_ref()
                    .is_none_or(|loaded| loaded.last_used.elapsed() >= this.idle);
                if expired {
                    *slot = None;
                    drop(slot);
                    crate::model::release_free_memory();
                    *this
                        .reaper_running
                        .lock()
                        .unwrap_or_else(|e| e.into_inner()) = false;
                    return;
                }
            });
        if spawned.is_err() {
            *running = false;
        }
    }

    /// Decide one goal: resolver first, then NEXI-CUA-1. A load failure
    /// is an abstention whose reason says why.
    pub fn decide(self: &Arc<Self>, obs: &Observation, goal: &str) -> Decision {
        match self.model() {
            Ok(model) => infer::decide(Some(&model), model.calibration, obs, goal, true),
            Err(error) => {
                let mut decision = infer::decide(None, Calibration::NONE, obs, goal, true);
                if decision.abstain {
                    decision.reason = error;
                }
                decision
            }
        }
    }
}
