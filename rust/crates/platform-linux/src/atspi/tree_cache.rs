//! Linux side of the event-invalidated tree cache (Dove W4.2).
//!
//! UNVERIFIED until the W7 CI runs it on Linux, so it is off unless
//! `DOVE_TREE_CACHE=1`. When on, the shared AT-SPI connection also subscribes
//! to every `object:` event (`children-changed`, `state-changed`,
//! `property-change`, `text-changed`, ...). AT-SPI events name an application
//! bus, not a window, so any of them invalidates every stored walk; so does
//! every driver action and the age bound of [`cua_driver_core::tree_cache`].
//! Nothing is reused until the subscription is live.
//!
//! Unlike Windows, a reused walk's rows are not re-read from the application
//! before they are returned, and there is no dirty-subtree re-walk. Both are
//! needed before this can be on by default.

use super::native::WalkedTree;
use cua_driver_core::tree_cache::{Lookup, TreeCache, WalkParams, WalkTicket, TREE_CACHE_ENV};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::OnceLock;

static EVENTS_LIVE: AtomicBool = AtomicBool::new(false);

/// Whether `DOVE_TREE_CACHE` explicitly turns the cache on.
pub(crate) fn enabled() -> bool {
    static ENABLED: OnceLock<bool> = OnceLock::new();
    *ENABLED.get_or_init(|| {
        matches!(
            std::env::var(TREE_CACHE_ENV)
                .unwrap_or_default()
                .trim()
                .to_ascii_lowercase()
                .as_str(),
            "1" | "true" | "on" | "yes"
        )
    })
}

fn cache() -> &'static TreeCache<WalkedTree> {
    static CACHE: OnceLock<TreeCache<WalkedTree>> = OnceLock::new();
    CACHE.get_or_init(TreeCache::from_env)
}

fn active() -> bool {
    enabled() && EVENTS_LIVE.load(Ordering::SeqCst)
}

/// The shared connection now receives every `object:` event.
pub(crate) fn note_events_live() {
    EVENTS_LIVE.store(true, Ordering::SeqCst);
}

/// One AT-SPI object event from any application.
pub(crate) fn note_object_event(event: &atspi::ObjectEvents) {
    if matches!(
        event,
        atspi::ObjectEvents::TextCaretMoved(_) | atspi::ObjectEvents::Announcement(_)
    ) {
        return;
    }
    cache().invalidate_all();
}

fn params(max_elements: Option<usize>, max_depth: Option<usize>) -> WalkParams {
    WalkParams {
        max_elements: max_elements.unwrap_or(usize::MAX),
        max_depth: max_depth.unwrap_or(usize::MAX),
    }
}

/// A stored walk of window `xid` that nothing could have changed.
pub(crate) fn lookup(
    xid: u64,
    max_elements: Option<usize>,
    max_depth: Option<usize>,
) -> Option<WalkedTree> {
    if !active() || xid == 0 {
        return None;
    }
    match cache().lookup(xid, params(max_elements, max_depth)) {
        Lookup::Fresh { value, .. } => {
            let mut walked = (*value).clone();
            walked.elapsed = std::time::Duration::ZERO;
            Some(walked)
        }
        _ => None,
    }
}

/// Call before walking `xid`; pass the ticket to [`store`].
pub(crate) fn begin(pid: u32, xid: u64) -> Option<WalkTicket> {
    (active() && xid != 0).then(|| cache().begin_walk(pid as i32, xid))
}

/// Keep a complete walk for later reads.
pub(crate) fn store(
    ticket: Option<WalkTicket>,
    max_elements: Option<usize>,
    max_depth: Option<usize>,
    walked: &WalkedTree,
) {
    if let Some(ticket) = ticket {
        if walked.truncation.is_none() && walked.nodes.len() > 1 {
            cache().finish_walk(ticket, params(max_elements, max_depth), walked.clone());
        }
    }
}
