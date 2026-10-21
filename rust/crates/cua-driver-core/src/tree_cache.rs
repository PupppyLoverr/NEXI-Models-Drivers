//! Event-invalidated cache of accessibility-tree walks (Dove W4.2).
//!
//! A platform walks a window's tree, stores the result here, and feeds the
//! cache the platform's change events (UIA StructureChanged/PropertyChanged
//! and focus, macOS AXObserver notifications, AT-SPI signals). A later read
//! reuses the stored walk only when nothing could have changed it:
//!
//! - **Events.** Each window has a sequence number that every invalidation
//!   bumps. A walk records the sequence number *before* it starts, so an event
//!   that arrives while the walk runs leaves the stored result dirty.
//! - **Actions.** Every tool call that is not a known pure read runs inside an
//!   [`ActionGuard`], which bumps a global epoch when it starts and again when
//!   it ends. A walk taken before or during an action is never reused after it.
//! - **Age.** A stored walk older than [`TreeCache::max_age`] is not reused,
//!   which bounds the effect of a provider that changes without raising events.
//! - **Subtrees.** Invalidations that name a subtree are kept as a list. The
//!   platform can re-walk just those subtrees and splice them in; a full
//!   invalidation, too many subtrees, or an unknown subtree means a full walk.
//!
//! Windows additionally re-reads every row it returns from a reused walk
//! against the live provider before answering (see `uia::tree_cache`), so a
//! returned row reflects the application at read time even when a provider
//! dropped or delayed an event.
//!
//! **Off by default.** A row the application ADDED (or renamed so that it now
//! matches a query) is not in the stored walk, so it can only appear once its
//! change event arrives. On a WinForms window those events arrived 350-850 ms
//! after the change (measured 2026-10-21), and a read in that window omitted
//! the new row. That is a stale answer, so reuse needs an explicit opt-in:
//! `DOVE_TREE_CACHE=1`. `DOVE_TREE_CACHE_MAX_AGE_MS` sets the age bound
//! (default 2000 ms, at most 60 000 ms).

use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

/// Environment switch: `1`, `true`, `on` or `yes` enables tree reuse.
pub const TREE_CACHE_ENV: &str = "DOVE_TREE_CACHE";
/// Environment override for the reuse age bound, in milliseconds.
pub const TREE_CACHE_MAX_AGE_ENV: &str = "DOVE_TREE_CACHE_MAX_AGE_MS";

/// Default age bound for reusing a walk.
pub const DEFAULT_MAX_AGE: Duration = Duration::from_millis(2000);
const MAX_MAX_AGE: Duration = Duration::from_millis(60_000);
/// More pending subtree invalidations than this collapse into a full one.
pub const MAX_DIRTY_SUBTREES: usize = 16;

/// Identifies a subtree inside one window's tree: a hash of the platform's
/// stable element identity (UIA runtime id, AX element hash, AT-SPI path).
pub type SubtreeId = u64;

/// What a change event invalidates.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Invalidation {
    /// The whole window's tree.
    Full,
    /// The subtree rooted at this element (the element itself included).
    Subtree(SubtreeId),
    /// Like `Subtree`, but only when the element is part of the stored walk;
    /// otherwise the event did not concern this window (focus moved
    /// elsewhere in the same process).
    Hint(SubtreeId),
}

/// A dirty subtree reported by [`TreeCache::lookup`].
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DirtySubtree {
    pub id: SubtreeId,
    /// False for [`Invalidation::Hint`]: ignore it when the element is not in
    /// the stored walk. True means an unknown element forces a full walk.
    pub required: bool,
}

// ── action barrier ──────────────────────────────────────────────────────────

/// Counts actions: the epoch is bumped when any action starts and again when
/// it ends.
pub struct ActionClock {
    epoch: AtomicU64,
    in_flight: AtomicU64,
}

impl ActionClock {
    pub const fn new() -> Self {
        Self {
            epoch: AtomicU64::new(0),
            in_flight: AtomicU64::new(0),
        }
    }

    /// The current epoch, or `None` while an action runs.
    fn epoch(&self) -> Option<u64> {
        // Read the epoch first: an action that starts after this load bumps
        // it, and one already running shows in the in-flight count.
        let epoch = self.epoch.load(Ordering::SeqCst);
        (self.in_flight.load(Ordering::SeqCst) == 0).then_some(epoch)
    }
}

impl Default for ActionClock {
    fn default() -> Self {
        Self::new()
    }
}

/// The process-wide clock that tool dispatch drives.
pub static ACTIONS: ActionClock = ActionClock::new();

/// Marks one action (any tool call that may change an application) for the
/// whole of its run. Walks never outlive an action: see the module docs.
pub struct ActionGuard(&'static ActionClock);

impl ActionGuard {
    /// Enter an action on the process-wide clock.
    pub fn enter() -> Self {
        Self::enter_on(&ACTIONS)
    }

    pub fn enter_on(clock: &'static ActionClock) -> Self {
        clock.in_flight.fetch_add(1, Ordering::SeqCst);
        clock.epoch.fetch_add(1, Ordering::SeqCst);
        Self(clock)
    }
}

impl Drop for ActionGuard {
    fn drop(&mut self) {
        self.0.epoch.fetch_add(1, Ordering::SeqCst);
        self.0.in_flight.fetch_sub(1, Ordering::SeqCst);
    }
}

/// Tools that only read. Every other tool runs inside an [`ActionGuard`].
/// An allowlist rather than the `read_only` annotation, so a new tool is
/// treated as an action until someone decides otherwise.
pub fn is_pure_read_tool(name: &str) -> bool {
    matches!(
        name,
        "get_window_state"
            | "get_accessibility_tree"
            | "list_windows"
            | "list_apps"
            | "get_screen_size"
            | "get_cursor_position"
            | "get_desktop_state"
            | "get_config"
            | "get_session"
            | "get_session_state"
            | "list_sessions"
            | "get_agent_cursor_state"
            | "get_recording_state"
            | "describe_tools"
            | "health_report"
            | "check_permissions"
            | "debug_window_info"
            | "zoom"
            | "verify_state"
    )
}

// ── cache ───────────────────────────────────────────────────────────────────

/// The walk parameters a stored result is valid for. Reads with different
/// bounds walk again.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct WalkParams {
    pub max_elements: usize,
    pub max_depth: usize,
}

/// Returned by [`TreeCache::begin_walk`]; hand it back to `finish_walk`.
#[derive(Debug, Clone, Copy)]
pub struct WalkTicket {
    window: u64,
    seq: u64,
    action_epoch: Option<u64>,
}

/// Result of [`TreeCache::lookup`].
pub enum Lookup<T> {
    /// Reusable as is.
    Fresh { value: Arc<T>, age: Duration },
    /// Reusable after re-walking these subtrees.
    Dirty {
        value: Arc<T>,
        subtrees: Vec<DirtySubtree>,
        age: Duration,
    },
    /// Walk the whole window.
    Miss(MissReason),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MissReason {
    Disabled,
    Empty,
    Params,
    Expired,
    Action,
    Changed,
}

impl MissReason {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Disabled => "disabled",
            Self::Empty => "empty",
            Self::Params => "params",
            Self::Expired => "expired",
            Self::Action => "action",
            Self::Changed => "changed",
        }
    }
}

struct Entry<T> {
    value: Arc<T>,
    params: WalkParams,
    seq: u64,
    action_epoch: u64,
    walked_at: Instant,
}

#[derive(Default)]
struct Slot<T> {
    pid: i32,
    seq: u64,
    /// Invalidations newer than the stored entry, oldest first.
    pending: Vec<(u64, Invalidation)>,
    entry: Option<Entry<T>>,
}

/// Per-window store of walk results. Cheap to share: wrap it in an `Arc` or
/// a `static`.
pub struct TreeCache<T> {
    slots: Mutex<HashMap<u64, Slot<T>>>,
    enabled: bool,
    max_age: Duration,
    actions: &'static ActionClock,
}

impl<T> TreeCache<T> {
    /// A cache configured from [`TREE_CACHE_ENV`] (off unless it is `1`,
    /// `true`, `on` or `yes`) and [`TREE_CACHE_MAX_AGE_ENV`].
    pub fn from_env() -> Self {
        let enabled = matches!(
            std::env::var(TREE_CACHE_ENV)
                .unwrap_or_default()
                .trim()
                .to_ascii_lowercase()
                .as_str(),
            "1" | "true" | "on" | "yes"
        );
        let max_age = std::env::var(TREE_CACHE_MAX_AGE_ENV)
            .ok()
            .and_then(|raw| raw.trim().parse::<u64>().ok())
            .map(Duration::from_millis)
            .unwrap_or(DEFAULT_MAX_AGE)
            .min(MAX_MAX_AGE);
        Self::new(enabled, max_age)
    }

    pub fn new(enabled: bool, max_age: Duration) -> Self {
        Self::with_clock(enabled, max_age, &ACTIONS)
    }

    /// A cache that follows `actions` instead of the process-wide clock.
    pub fn with_clock(enabled: bool, max_age: Duration, actions: &'static ActionClock) -> Self {
        Self {
            slots: Mutex::new(HashMap::new()),
            enabled,
            max_age,
            actions,
        }
    }

    pub fn enabled(&self) -> bool {
        self.enabled
    }

    pub fn max_age(&self) -> Duration {
        self.max_age
    }

    fn slots(&self) -> std::sync::MutexGuard<'_, HashMap<u64, Slot<T>>> {
        self.slots.lock().unwrap_or_else(|poison| poison.into_inner())
    }

    /// Call before reading anything from the application. Events that
    /// arrive after this point make the stored result dirty.
    pub fn begin_walk(&self, pid: i32, window: u64) -> WalkTicket {
        let action_epoch = self.actions.epoch();
        let mut slots = self.slots();
        let slot = slots.entry(window).or_insert_with(|| Slot {
            pid,
            seq: 0,
            pending: Vec::new(),
            entry: None,
        });
        slot.pid = pid;
        WalkTicket {
            window,
            seq: slot.seq,
            action_epoch,
        }
    }

    /// Store a completed walk. A walk that overlapped an action is dropped.
    pub fn finish_walk(&self, ticket: WalkTicket, params: WalkParams, value: T) -> Arc<T> {
        self.store(ticket, params, value, Instant::now())
    }

    /// Store the result of re-walking only the dirty subtrees of a stored walk
    /// that is `base_age` old. It keeps that walk's age: subtree events say
    /// nothing about the rest of the tree, so only a full walk restarts the
    /// age bound.
    pub fn finish_rewalk(
        &self,
        ticket: WalkTicket,
        params: WalkParams,
        value: T,
        base_age: Duration,
    ) -> Arc<T> {
        let walked_at = Instant::now()
            .checked_sub(base_age)
            .unwrap_or_else(Instant::now);
        self.store(ticket, params, value, walked_at)
    }

    fn store(&self, ticket: WalkTicket, params: WalkParams, value: T, walked_at: Instant) -> Arc<T> {
        let value = Arc::new(value);
        if !self.enabled {
            return value;
        }
        let Some(action_epoch) = ticket.action_epoch else {
            return value;
        };
        let mut slots = self.slots();
        let Some(slot) = slots.get_mut(&ticket.window) else {
            return value;
        };
        // A newer walk already stored a result; keep the newer one.
        if slot
            .entry
            .as_ref()
            .is_some_and(|entry| entry.seq > ticket.seq)
        {
            return value;
        }
        slot.pending.retain(|(seq, _)| *seq > ticket.seq);
        slot.entry = Some(Entry {
            value: value.clone(),
            params,
            seq: ticket.seq,
            action_epoch,
            walked_at,
        });
        value
    }

    /// Decide whether a stored walk of `window` can serve a read.
    pub fn lookup(&self, window: u64, params: WalkParams) -> Lookup<T> {
        if !self.enabled {
            return Lookup::Miss(MissReason::Disabled);
        }
        let current_action = self.actions.epoch();
        let slots = self.slots();
        let Some(slot) = slots.get(&window) else {
            return Lookup::Miss(MissReason::Empty);
        };
        let Some(entry) = slot.entry.as_ref() else {
            return Lookup::Miss(MissReason::Empty);
        };
        if entry.params != params {
            return Lookup::Miss(MissReason::Params);
        }
        if current_action != Some(entry.action_epoch) {
            return Lookup::Miss(MissReason::Action);
        }
        let age = entry.walked_at.elapsed();
        if age > self.max_age {
            return Lookup::Miss(MissReason::Expired);
        }
        let mut subtrees: Vec<DirtySubtree> = Vec::new();
        for (seq, invalidation) in &slot.pending {
            if *seq <= entry.seq {
                continue;
            }
            let (id, required) = match invalidation {
                Invalidation::Full => return Lookup::Miss(MissReason::Changed),
                Invalidation::Subtree(id) => (*id, true),
                Invalidation::Hint(id) => (*id, false),
            };
            match subtrees.iter_mut().find(|subtree| subtree.id == id) {
                Some(subtree) => subtree.required |= required,
                None => subtrees.push(DirtySubtree { id, required }),
            }
        }
        if subtrees.len() > MAX_DIRTY_SUBTREES {
            return Lookup::Miss(MissReason::Changed);
        }
        let value = entry.value.clone();
        if subtrees.is_empty() {
            Lookup::Fresh { value, age }
        } else {
            Lookup::Dirty {
                value,
                subtrees,
                age,
            }
        }
    }

    /// Record a change event for `window`. Unknown windows are ignored: a
    /// window with no slot has no stored walk and no walk in progress.
    pub fn invalidate(&self, window: u64, invalidation: Invalidation) {
        let mut slots = self.slots();
        if let Some(slot) = slots.get_mut(&window) {
            Self::push(slot, invalidation);
        }
    }

    /// Invalidate every window of `pid` completely.
    pub fn invalidate_pid(&self, pid: i32) {
        self.invalidate_pid_with(pid, Invalidation::Full);
    }

    /// Record `invalidation` for every window of `pid`.
    pub fn invalidate_pid_with(&self, pid: i32, invalidation: Invalidation) {
        let mut slots = self.slots();
        for slot in slots.values_mut().filter(|slot| slot.pid == pid) {
            Self::push(slot, invalidation);
        }
    }

    /// Invalidate every window completely.
    pub fn invalidate_all(&self) {
        let mut slots = self.slots();
        for slot in slots.values_mut() {
            Self::push(slot, Invalidation::Full);
        }
    }

    fn push(slot: &mut Slot<T>, invalidation: Invalidation) {
        slot.seq += 1;
        let seq = slot.seq;
        if slot.pending.len() >= MAX_DIRTY_SUBTREES * 2 {
            slot.pending.clear();
            slot.pending.push((seq, Invalidation::Full));
        } else {
            slot.pending.push((seq, invalidation));
        }
    }

    /// Drop everything stored for `window` (it closed).
    pub fn forget(&self, window: u64) {
        self.slots().remove(&window);
    }

    /// Windows that currently have a slot.
    pub fn windows(&self) -> Vec<u64> {
        self.slots().keys().copied().collect()
    }
}

/// Stable 64-bit hash of an element identity (FNV-1a), for [`SubtreeId`].
pub fn subtree_id(parts: &[i32]) -> SubtreeId {
    let mut hash: u64 = 0xcbf2_9ce4_8422_2325;
    for part in parts {
        for byte in part.to_le_bytes() {
            hash ^= u64::from(byte);
            hash = hash.wrapping_mul(0x0100_0000_01b3);
        }
    }
    hash
}

#[cfg(test)]
#[path = "tree_cache_tests.rs"]
mod tests;
