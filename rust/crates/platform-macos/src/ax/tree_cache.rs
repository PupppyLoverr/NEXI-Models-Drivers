//! macOS side of the event-invalidated tree cache (Dove W4.2).
//!
//! UNVERIFIED until the W7 CI runs it on macOS, so it is off unless
//! `DOVE_TREE_CACHE=1`. When on, `get_window_state` asks [`watch`] for an
//! `AXObserver` on the target application. One background thread owns every
//! observer's run-loop source. Any of the notifications in [`NOTIFICATIONS`]
//! from that application invalidates every stored walk of its windows, and so
//! do driver actions and the age bound of [`cua_driver_core::tree_cache`]. A
//! walk is stored only when the application's observer was live before the
//! walk began, so no change can fall between them.
//!
//! Walks are stored per (window, query, menu collapse), because the macOS
//! walker filters by query while it walks. A stored walk keeps its own
//! retain on every indexed element and hands each read a fresh retain, which
//! that read's snapshot releases as usual.
//!
//! Unlike Windows, a reused walk's rows are not re-read from the application
//! before they are returned, and there is no dirty-subtree re-walk. Both are
//! needed before this can be on by default.

use super::bindings::{AXUIElementCreateApplication, AXUIElementRef};
use super::tree::{AXNode, TreeWalkResult};
use super::window_scope::WindowScope;
use core_foundation::base::{CFRelease, CFRetain, CFTypeRef, TCFType};
use core_foundation::string::{CFString, CFStringRef};
use cua_driver_core::tree_cache::{Lookup, TreeCache, WalkParams, WalkTicket, TREE_CACHE_ENV};
use cua_driver_core::walk_budget::WalkOutcome;
use std::collections::HashSet;
use std::os::raw::c_void;
use std::sync::mpsc::{channel, Sender};
use std::sync::{Mutex, OnceLock};

/// Application notifications that can change a row. Registered on the
/// application element, they arrive for every element of the application.
const NOTIFICATIONS: &[&str] = &[
    "AXCreated",
    "AXUIElementDestroyed",
    "AXValueChanged",
    "AXTitleChanged",
    "AXFocusedUIElementChanged",
    "AXSelectedChildrenChanged",
    "AXSelectedRowsChanged",
    "AXSelectedTextChanged",
    "AXRowCountChanged",
    "AXRowExpanded",
    "AXRowCollapsed",
    "AXLayoutChanged",
    "AXResized",
    "AXMoved",
    "AXWindowCreated",
    "AXWindowMoved",
    "AXWindowResized",
    "AXWindowMiniaturized",
    "AXWindowDeminiaturized",
    "AXMenuOpened",
    "AXMenuClosed",
    "AXElementBusyChanged",
];

/// Applications observed at once.
const MAX_WATCHED: usize = 64;

type AXObserverRef = *mut c_void;
type AXObserverCallback =
    unsafe extern "C" fn(AXObserverRef, AXUIElementRef, CFStringRef, *mut c_void);

#[link(name = "ApplicationServices", kind = "framework")]
extern "C" {
    fn AXObserverCreate(
        application: i32,
        callback: AXObserverCallback,
        out_observer: *mut AXObserverRef,
    ) -> i32;
    fn AXObserverAddNotification(
        observer: AXObserverRef,
        element: AXUIElementRef,
        notification: CFStringRef,
        refcon: *mut c_void,
    ) -> i32;
    fn AXObserverGetRunLoopSource(observer: AXObserverRef) -> *mut c_void;
}

#[link(name = "CoreFoundation", kind = "framework")]
extern "C" {
    fn CFRunLoopGetCurrent() -> *mut c_void;
    fn CFRunLoopAddSource(run_loop: *mut c_void, source: *mut c_void, mode: *const c_void);
    fn CFRunLoopRunInMode(mode: *const c_void, seconds: f64, return_after_source: u8) -> i32;
    static kCFRunLoopDefaultMode: *const c_void;
}

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

// ── stored walks ────────────────────────────────────────────────────────────

/// A walk kept for reuse. Owns one retain on each indexed element.
pub(crate) struct CachedWalk {
    tree_markdown: String,
    nodes: Vec<AXNode>,
    truncated: bool,
    walk: WalkOutcome,
    window_scope: Option<WindowScope>,
}

// SAFETY: AXUIElementRef is a CFType; CFRetain/CFRelease are thread-safe and
// the AX API may be called from any thread.
unsafe impl Send for CachedWalk {}
unsafe impl Sync for CachedWalk {}

fn retain_indexed(nodes: &[AXNode]) {
    for node in nodes.iter().filter(|n| n.element_index.is_some() && n.element_ptr != 0) {
        unsafe { CFRetain(node.element_ptr as CFTypeRef) };
    }
}

impl CachedWalk {
    fn keep(result: &TreeWalkResult) -> Self {
        retain_indexed(&result.nodes);
        Self {
            tree_markdown: result.tree_markdown.clone(),
            nodes: result.nodes.clone(),
            truncated: result.truncated,
            walk: result.walk,
            window_scope: result.window_scope.clone(),
        }
    }

    /// A result for one more read. Its indexed elements carry a retain the
    /// read's snapshot will own, exactly like a fresh walk's.
    fn hand_out(&self) -> TreeWalkResult {
        retain_indexed(&self.nodes);
        TreeWalkResult {
            tree_markdown: self.tree_markdown.clone(),
            nodes: self.nodes.clone(),
            truncated: self.truncated,
            walk: WalkOutcome {
                elapsed_ms: 0,
                ..self.walk
            },
            window_scope: self.window_scope.clone(),
        }
    }
}

impl Drop for CachedWalk {
    fn drop(&mut self) {
        for node in self
            .nodes
            .iter()
            .filter(|n| n.element_index.is_some() && n.element_ptr != 0)
        {
            unsafe { CFRelease(node.element_ptr as CFTypeRef) };
        }
    }
}

fn cache() -> &'static TreeCache<CachedWalk> {
    static CACHE: OnceLock<TreeCache<CachedWalk>> = OnceLock::new();
    CACHE.get_or_init(TreeCache::from_env)
}

/// Cache key: the walker filters by query and collapses menus while it walks.
fn key(window_id: u32, query: Option<&str>, collapse_menus: bool) -> u64 {
    let mut parts = vec![window_id as i32, i32::from(collapse_menus)];
    parts.extend(query.unwrap_or("").chars().map(|c| c as i32));
    cua_driver_core::tree_cache::subtree_id(&parts)
}

/// Pending store for one walk.
pub(crate) struct Pending {
    ticket: WalkTicket,
    params: WalkParams,
}

/// Look up a reusable walk, or start one: `Ok` is a stored walk, `Err` a
/// ticket to pass to [`store`] (`None` when nothing may be stored).
pub(crate) fn lookup_or_begin(
    pid: i32,
    window_id: u32,
    query: Option<&str>,
    collapse_menus: bool,
    max_elements: usize,
    max_depth: usize,
) -> Result<TreeWalkResult, Option<Pending>> {
    if !enabled() {
        return Err(None);
    }
    let key = key(window_id, query, collapse_menus);
    let params = WalkParams {
        max_elements,
        max_depth,
    };
    if is_watched(pid) {
        if let Lookup::Fresh { value, .. } = cache().lookup(key, params) {
            return Ok(value.hand_out());
        }
    }
    let live = watch(pid);
    // The ticket must predate the walk, and the observer must predate the
    // ticket, or a change between them would go unseen.
    let ticket = cache().begin_walk(pid, key);
    Err(live.then_some(Pending { ticket, params }))
}

/// Keep a complete, window-matched walk.
pub(crate) fn store(pending: Option<Pending>, result: &TreeWalkResult) {
    let Some(pending) = pending else {
        return;
    };
    let complete = !result.truncated
        && result
            .window_scope
            .as_ref()
            .is_none_or(WindowScope::is_matched);
    if complete {
        cache().finish_walk(pending.ticket, pending.params, CachedWalk::keep(result));
    }
}

// ── observers ───────────────────────────────────────────────────────────────

fn watched() -> &'static Mutex<HashSet<i32>> {
    static WATCHED: OnceLock<Mutex<HashSet<i32>>> = OnceLock::new();
    WATCHED.get_or_init(|| Mutex::new(HashSet::new()))
}

fn is_watched(pid: i32) -> bool {
    watched()
        .lock()
        .unwrap_or_else(|p| p.into_inner())
        .contains(&pid)
}

/// Ask for `pid`'s observer. Returns whether it is already live; a new one
/// becomes live on the observer thread shortly after.
fn watch(pid: i32) -> bool {
    if is_watched(pid) {
        return true;
    }
    static REQUESTS: OnceLock<Mutex<Sender<i32>>> = OnceLock::new();
    let sender = REQUESTS.get_or_init(|| {
        let (sender, receiver) = channel::<i32>();
        std::thread::Builder::new()
            .name("dove-ax-observer".into())
            .spawn(move || observer_thread(receiver))
            .expect("spawn the AX observer thread");
        Mutex::new(sender)
    });
    let _ = sender.lock().unwrap_or_else(|p| p.into_inner()).send(pid);
    false
}

fn observer_thread(requests: std::sync::mpsc::Receiver<i32>) {
    let run_loop = unsafe { CFRunLoopGetCurrent() };
    loop {
        while let Ok(pid) = requests.try_recv() {
            if is_watched(pid) || watched().lock().map(|w| w.len()).unwrap_or(0) >= MAX_WATCHED {
                continue;
            }
            if unsafe { add_observer(run_loop, pid) } {
                watched()
                    .lock()
                    .unwrap_or_else(|p| p.into_inner())
                    .insert(pid);
            }
        }
        // Deliver notifications; wake regularly to pick up new requests.
        unsafe { CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0.05, 0) };
    }
}

/// Create `pid`'s observer and add its source to `run_loop`. The observer
/// and application element live for the rest of the process.
unsafe fn add_observer(run_loop: *mut c_void, pid: i32) -> bool {
    let mut observer: AXObserverRef = std::ptr::null_mut();
    if AXObserverCreate(pid, on_notification, &mut observer) != 0 || observer.is_null() {
        return false;
    }
    let application = AXUIElementCreateApplication(pid);
    if application.is_null() {
        CFRelease(observer as CFTypeRef);
        return false;
    }
    let mut added = 0;
    for name in NOTIFICATIONS {
        let notification = CFString::new(name);
        let refcon = pid as isize as *mut c_void;
        if AXObserverAddNotification(
            observer,
            application,
            notification.as_concrete_TypeRef(),
            refcon,
        ) == 0
        {
            added += 1;
        }
    }
    if added == 0 {
        CFRelease(application as CFTypeRef);
        CFRelease(observer as CFTypeRef);
        return false;
    }
    CFRunLoopAddSource(
        run_loop,
        AXObserverGetRunLoopSource(observer),
        kCFRunLoopDefaultMode,
    );
    true
}

unsafe extern "C" fn on_notification(
    _observer: AXObserverRef,
    _element: AXUIElementRef,
    _notification: CFStringRef,
    refcon: *mut c_void,
) {
    cache().invalidate_pid(refcon as isize as i32);
}
