//! Windows side of the event-invalidated tree cache (Dove W4.2).
//!
//! `get_window_state` walks a window through [`walk_tree_cached`]. A full
//! walk keeps every visited control-view node (its cached element, runtime id
//! and row properties) in [`cua_driver_core::tree_cache`], and registers UIA
//! event handlers on the window's root element:
//!
//! - `StructureChanged` (subtree): a container's children changed. The
//!   container's subtree is dirty; `ChildAdded`, whose sender is the new child,
//!   dirties the whole window.
//! - `PropertyChanged` (subtree) for every property a row shows: the sender's
//!   subtree is dirty.
//! - `WindowClosed`: the window is forgotten.
//! - Focus changes (desktop-wide): the focused element's subtree is dirty when
//!   it is part of a cached window.
//!
//! A later read with the same bounds then either reuses the walk, re-walks
//! only the dirty subtrees and splices them in, or walks the window again.
//! Before answering from a reused walk, every row the response returns is
//! re-read from the provider (one element-scoped `BuildUpdatedCache` per row)
//! and compared with the cached row; any difference, a moved or resized
//! window, an unknown dirty subtree or a missing provider means a full walk.
//! A read walks instead when it would return more than [`MAX_VALIDATED_ROWS`]
//! rows, or when re-reading its rows is estimated to cost more than the
//! window's last full walk (so the cache never makes a read slower).
//!
//! Opt-in (`DOVE_TREE_CACHE=1`). Every returned row is current, but a row the
//! application added, or renamed into a query's match, is missing until its
//! UIA event arrives (350-850 ms on a WinForms window), or until the stored
//! walk ages out. With the cache off (the default) `walk_tree_cached` is a
//! plain walk and registers no event handlers.

use super::{
    automation, build_row, format_node_line, node_cache_request, read_node_props, render_lines,
    NodeProps, UiaNode, UiaTreeResult,
};
use cua_driver_core::tree_cache::{
    subtree_id, Invalidation, Lookup, SubtreeId, TreeCache, WalkParams,
};
use cua_driver_core::walk_budget::{WalkBudget, WalkOutcome, WalkStop};
use std::collections::{HashMap, HashSet};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Mutex, OnceLock};
use std::time::Instant;
use windows::core::{implement, Interface};
use windows::Win32::System::Com::SAFEARRAY;
use windows::Win32::UI::Accessibility::{
    IUIAutomation, IUIAutomationCacheRequest, IUIAutomationElement, IUIAutomationEventHandler,
    IUIAutomationEventHandler_Impl, IUIAutomationFocusChangedEventHandler,
    IUIAutomationFocusChangedEventHandler_Impl, IUIAutomationPropertyChangedEventHandler,
    IUIAutomationPropertyChangedEventHandler_Impl, IUIAutomationStructureChangedEventHandler,
    IUIAutomationStructureChangedEventHandler_Impl, StructureChangeType,
    StructureChangeType_ChildAdded, TreeScope_Element,
    TreeScope_Subtree, UIA_AutomationIdPropertyId, UIA_BoundingRectanglePropertyId,
    UIA_ControlTypePropertyId, UIA_EVENT_ID, UIA_HelpTextPropertyId,
    UIA_IsEnabledPropertyId, UIA_IsExpandCollapsePatternAvailablePropertyId,
    UIA_IsInvokePatternAvailablePropertyId, UIA_IsOffscreenPropertyId,
    UIA_IsRangeValuePatternAvailablePropertyId, UIA_IsScrollPatternAvailablePropertyId,
    UIA_IsSelectionItemPatternAvailablePropertyId, UIA_IsTextPatternAvailablePropertyId,
    UIA_IsTogglePatternAvailablePropertyId, UIA_IsValuePatternAvailablePropertyId,
    UIA_NamePropertyId, UIA_PROPERTY_ID, UIA_ProcessIdPropertyId, UIA_RuntimeIdPropertyId,
    UIA_ScrollHorizontalScrollPercentPropertyId, UIA_ScrollVerticalScrollPercentPropertyId,
    UIA_SelectionItemIsSelectedPropertyId, UIA_ToggleToggleStatePropertyId,
    UIA_ValueValuePropertyId, UIA_Window_WindowClosedEventId,
};

/// Reads that would return more rows than this walk instead of validating
/// each row against the provider.
pub const MAX_VALIDATED_ROWS: usize = 48;
/// Windows with registered event handlers at once; the least recently read
/// beyond this is dropped.
const MAX_WATCHED_WINDOWS: usize = 24;

/// Properties whose change events dirty a row: everything a row shows, plus
/// scroll position (it moves descendants' frames).
const WATCHED_PROPERTIES: &[UIA_PROPERTY_ID] = &[
    UIA_NamePropertyId,
    UIA_ValueValuePropertyId,
    UIA_AutomationIdPropertyId,
    UIA_HelpTextPropertyId,
    UIA_IsEnabledPropertyId,
    UIA_IsOffscreenPropertyId,
    UIA_BoundingRectanglePropertyId,
    UIA_ControlTypePropertyId,
    UIA_ToggleToggleStatePropertyId,
    UIA_SelectionItemIsSelectedPropertyId,
    UIA_IsInvokePatternAvailablePropertyId,
    UIA_IsTogglePatternAvailablePropertyId,
    UIA_IsSelectionItemPatternAvailablePropertyId,
    UIA_IsExpandCollapsePatternAvailablePropertyId,
    UIA_IsValuePatternAvailablePropertyId,
    UIA_IsRangeValuePatternAvailablePropertyId,
    UIA_IsTextPatternAvailablePropertyId,
    UIA_IsScrollPatternAvailablePropertyId,
    UIA_ScrollHorizontalScrollPercentPropertyId,
    UIA_ScrollVerticalScrollPercentPropertyId,
];

// ── cached walk ─────────────────────────────────────────────────────────────

/// One visited control-view node, in pre-order.
#[derive(Clone)]
struct WalkedNode {
    element: IUIAutomationElement,
    id: SubtreeId,
    depth: usize,
    in_web_content: bool,
    props: NodeProps,
    /// One past the index of this node's last descendant.
    end: usize,
}

pub(crate) struct CachedTree {
    walked: Vec<WalkedNode>,
    outcome: WalkOutcome,
    window_rect: (i32, i32, i32, i32),
    /// How long the last full walk of this window took.
    walk_cost_us: u64,
}

/// Running estimate of one row's validation round trip, in microseconds.
static ROW_COST_US: AtomicU64 = AtomicU64::new(300);

/// Why a stored walk did not answer a read.
enum Decline {
    /// A returned row differs from the provider, or could not be read.
    Changed,
    /// Re-reading the rows would cost more than walking again.
    Cost,
}

// SAFETY: UIA client elements are free-threaded; every thread that touches
// them has joined the MTA (see `super::automation`).
unsafe impl Send for CachedTree {}
unsafe impl Sync for CachedTree {}

fn cache() -> &'static TreeCache<CachedTree> {
    static CACHE: OnceLock<TreeCache<CachedTree>> = OnceLock::new();
    CACHE.get_or_init(TreeCache::from_env)
}

/// How a read was answered, for perf logs and tests.
#[derive(Debug, Clone, Default)]
pub struct CacheReport {
    /// `hit`, `partial`, `miss:<reason>`, `uncached:<why>` or `off`.
    pub status: String,
    pub validated_rows: usize,
    pub rewalked_subtrees: usize,
}

fn report(status: impl Into<String>) -> CacheReport {
    CacheReport {
        status: status.into(),
        ..CacheReport::default()
    }
}

/// [`super::walk_tree_budgeted`] through the tree cache. Returns the walk
/// outcome explicitly, because a reused walk never touches `budget`.
pub fn walk_tree_cached(
    hwnd: u64,
    pid: u32,
    query: Option<&str>,
    max_depth: usize,
    max_elements: usize,
    budget: &mut WalkBudget,
) -> (UiaTreeResult, WalkOutcome, CacheReport) {
    let started = Instant::now();
    let cache = cache();
    let uncached = |budget: &mut WalkBudget, why: &str| {
        let tree = super::walk_tree_budgeted(hwnd, query, max_depth, budget);
        (tree, budget.outcome(), report(why))
    };
    if !cache.enabled() {
        return uncached(budget, "off");
    }
    if super::is_sal_window(hwnd) {
        return uncached(budget, "uncached:msaa");
    }
    let Some(rect) = window_rect(hwnd) else {
        return uncached(budget, "uncached:no_window_rect");
    };
    let params = WalkParams {
        max_elements,
        max_depth,
    };
    let Ok(automation) = automation() else {
        return uncached(budget, "uncached:no_automation");
    };
    touch_watch(hwnd);

    let miss_reason = match cache.lookup(hwnd, params) {
        Lookup::Fresh { value, .. } if value.window_rect == rect => {
            match serve(&automation, &value, query) {
                Ok((tree, validated)) => {
                    let outcome = reused_outcome(&value.outcome, started);
                    let report = CacheReport {
                        status: "hit".into(),
                        validated_rows: validated,
                        rewalked_subtrees: 0,
                    };
                    return (tree, outcome, report);
                }
                Err(Decline::Cost) => "miss:cost".to_owned(),
                Err(Decline::Changed) => {
                    cache.invalidate(hwnd, Invalidation::Full);
                    "miss:validation".to_owned()
                }
            }
        }
        Lookup::Dirty {
            value,
            subtrees,
            age,
        } if value.window_rect == rect && value.outcome.stop.is_none() => {
            let ticket = cache.begin_walk(pid as i32, hwnd);
            match rewalk_subtrees(&automation, &value, &subtrees, params) {
                Some((walked, rewalked)) => {
                    let tree = CachedTree {
                        outcome: WalkOutcome {
                            nodes_visited: walked.len(),
                            ..value.outcome
                        },
                        walked,
                        window_rect: rect,
                        walk_cost_us: value.walk_cost_us,
                    };
                    let stored = cache.finish_rewalk(ticket, params, tree, age);
                    match serve(&automation, &stored, query) {
                        Ok((result, validated)) => {
                            let outcome = reused_outcome(&stored.outcome, started);
                            let report = CacheReport {
                                status: "partial".into(),
                                validated_rows: validated,
                                rewalked_subtrees: rewalked,
                            };
                            return (result, outcome, report);
                        }
                        Err(Decline::Cost) => "miss:cost".to_owned(),
                        Err(Decline::Changed) => {
                            cache.invalidate(hwnd, Invalidation::Full);
                            "miss:validation".to_owned()
                        }
                    }
                }
                None => "miss:subtree".to_owned(),
            }
        }
        Lookup::Fresh { .. } | Lookup::Dirty { .. } => "miss:moved_or_truncated".to_owned(),
        Lookup::Miss(reason) => format!("miss:{}", reason.as_str()),
    };

    // Full walk. Handlers go in before the walk's ticket is taken, so any
    // change after the walk starts reaches the cache.
    let watched = ensure_watch(&automation, hwnd);
    let ticket = cache.begin_walk(pid as i32, hwnd);
    let walk_started = Instant::now();
    match full_walk(&automation, hwnd, max_depth, budget) {
        FullWalk::Cacheable(walked) => {
            let outcome = budget.outcome();
            let tree = CachedTree {
                walked,
                outcome,
                window_rect: rect,
                walk_cost_us: walk_started.elapsed().as_micros() as u64,
            };
            let store = watched && outcome.stop != Some(WalkStop::Timeout);
            let (result, _) = project(&tree.walked, query);
            if store {
                cache.finish_walk(ticket, params, tree);
            }
            let status = if store {
                miss_reason
            } else {
                format!("{miss_reason}+unstored")
            };
            (result, outcome, report(status))
        }
        FullWalk::Other(result) => (result, budget.outcome(), report("uncached:fallback")),
    }
}

/// The outcome reported for a reused walk: the stored one, timed now.
fn reused_outcome(stored: &WalkOutcome, started: Instant) -> WalkOutcome {
    WalkOutcome {
        elapsed_ms: started.elapsed().as_millis() as u64,
        ..*stored
    }
}

fn window_rect(hwnd: u64) -> Option<(i32, i32, i32, i32)> {
    use windows::Win32::Foundation::{HWND, RECT};
    use windows::Win32::UI::WindowsAndMessaging::GetWindowRect;
    let mut rect = RECT::default();
    unsafe { GetWindowRect(HWND(hwnd as *mut _), &mut rect) }.ok()?;
    Some((rect.left, rect.top, rect.right, rect.bottom))
}

enum FullWalk {
    Cacheable(Vec<WalkedNode>),
    /// A result from the uncached fallbacks (CoreWindow root walk, errors).
    Other(UiaTreeResult),
}

/// The cache request for cached walks: row properties plus runtime ids.
fn walk_request(
    automation: &IUIAutomation,
    scope: windows::Win32::UI::Accessibility::TreeScope,
) -> windows::core::Result<IUIAutomationCacheRequest> {
    unsafe {
        let request = node_cache_request(automation)?;
        request.AddProperty(UIA_RuntimeIdPropertyId)?;
        request.SetTreeScope(scope)?;
        if let Ok(condition) = automation.ControlViewCondition() {
            request.SetTreeFilter(&condition)?;
        }
        Ok(request)
    }
}

fn full_walk(
    automation: &IUIAutomation,
    hwnd: u64,
    max_depth: usize,
    budget: &mut WalkBudget,
) -> FullWalk {
    let error = |message: String| {
        FullWalk::Other(UiaTreeResult {
            tree_markdown: message,
            nodes: Vec::new(),
        })
    };
    let request = match walk_request(automation, TreeScope_Subtree) {
        Ok(request) => request,
        Err(e) => return error(format!("CreateCacheRequest failed: {e}")),
    };
    let hwnd_win = windows::Win32::Foundation::HWND(hwnd as *mut _);
    let uncached = match unsafe { automation.ElementFromHandle(hwnd_win) } {
        Ok(element) => element,
        Err(e) => return error(format!("ElementFromHandle failed: {e}")),
    };
    // Same transient-error retry as the uncached walk (#1881).
    let root = {
        const MAX_ATTEMPTS: u32 = 3;
        let mut attempt = 0u32;
        loop {
            match unsafe { uncached.BuildUpdatedCache(&request) } {
                Ok(element) => break element,
                Err(e) => {
                    attempt += 1;
                    if attempt >= MAX_ATTEMPTS {
                        return error(format!(
                            "BuildUpdatedCache failed after {attempt} attempts: {e}"
                        ));
                    }
                    std::thread::sleep(std::time::Duration::from_millis(40));
                }
            }
        }
    };
    let mut walked = Vec::new();
    collect(&root, 0, false, max_depth, budget, &mut walked);
    if walked.iter().any(|node| node.props.is_actionable()) || budget.expired() {
        return FullWalk::Cacheable(walked);
    }
    // CoreWindow-class apps keep their tree at the desktop root. Use the
    // uncached walker's fallback and do not cache it.
    match super::core_window_fallback(automation, hwnd, max_depth, budget) {
        Some(result) => FullWalk::Other(result),
        None => FullWalk::Cacheable(walked),
    }
}

/// Collect `element`'s cached subtree in pre-order, under the same depth and
/// node budget rules as the uncached walk.
fn collect(
    element: &IUIAutomationElement,
    depth: usize,
    in_web_content: bool,
    max_depth: usize,
    budget: &mut WalkBudget,
    out: &mut Vec<WalkedNode>,
) {
    if depth > max_depth || !budget.admit() {
        return;
    }
    let props = read_node_props(element);
    let child_web = in_web_content || props.control_type.eq_ignore_ascii_case("Document");
    let index = out.len();
    out.push(WalkedNode {
        element: element.clone(),
        id: cached_runtime_id(element).map_or(0, |id| subtree_id(&id)),
        depth,
        in_web_content,
        props,
        end: index + 1,
    });
    if let Ok(children) = unsafe { element.GetCachedChildren() } {
        let len = unsafe { children.Length() }.unwrap_or(0);
        for i in 0..len {
            if let Ok(child) = unsafe { children.GetElement(i) } {
                collect(&child, depth + 1, child_web, max_depth, budget, out);
            }
        }
    }
    out[index].end = out.len();
}

// ── projection and validation ──────────────────────────────────────────────

/// Project walked nodes into rows exactly like the uncached walk. Returns the
/// result and, per row, the index of its walked node.
fn project(walked: &[WalkedNode], query: Option<&str>) -> (UiaTreeResult, Vec<usize>) {
    let mut nodes = Vec::new();
    let mut lines = Vec::new();
    let mut origins = Vec::new();
    let mut counter = 0usize;
    // (depth, parent index the node's children inherit)
    let mut stack: Vec<(usize, Option<usize>)> = Vec::new();
    for (i, node) in walked.iter().enumerate() {
        while stack.last().is_some_and(|(depth, _)| *depth >= node.depth) {
            stack.pop();
        }
        let parent_index = stack.last().and_then(|(_, parent)| *parent);
        let indexed = node.props.is_actionable();
        let ptr = if indexed {
            let retained = node.element.clone();
            let ptr = retained.as_raw() as usize;
            std::mem::forget(retained);
            ptr
        } else {
            0
        };
        let (row, emitted_parent) = build_row(
            &node.props,
            node.depth,
            parent_index,
            node.in_web_content,
            &mut counter,
            ptr,
        );
        stack.push((node.depth, emitted_parent));
        if let Some(row) = row {
            lines.push((node.depth, format_node_line(&row)));
            nodes.push(row);
            origins.push(i);
        }
    }
    let raw = render_lines(&lines);
    let tree_markdown = match query {
        Some(query) => super::filter_tree(&raw, query),
        None => raw,
    };
    (
        UiaTreeResult {
            tree_markdown,
            nodes,
        },
        origins,
    )
}

/// Answer from a stored walk after re-reading every returned row.
fn serve(
    automation: &IUIAutomation,
    tree: &CachedTree,
    query: Option<&str>,
) -> Result<(UiaTreeResult, usize), Decline> {
    let (result, origins) = project(&tree.walked, query);
    let returned: HashSet<&str> = result.tree_markdown.lines().collect();
    let rendered: Vec<String> = result
        .nodes
        .iter()
        .map(|node| format!("{}{}", "  ".repeat(node.depth), format_node_line(node)))
        .collect();
    let to_check: Vec<usize> = rendered
        .iter()
        .enumerate()
        .filter(|(_, line)| returned.contains(line.as_str()))
        .map(|(row, _)| origins[row])
        .collect();
    let estimate = to_check.len() as u64 * ROW_COST_US.load(Ordering::Relaxed);
    if to_check.len() > MAX_VALIDATED_ROWS || estimate >= tree.walk_cost_us {
        unsafe { release_rows(result.nodes) };
        return Err(Decline::Cost);
    }
    let validating = Instant::now();
    let valid = validate(automation, &tree.walked, &to_check).unwrap_or(false);
    if valid && !to_check.is_empty() {
        let per_row = validating.elapsed().as_micros() as u64 / to_check.len() as u64;
        let old = ROW_COST_US.load(Ordering::Relaxed);
        ROW_COST_US.store((old * 3 + per_row) / 4, Ordering::Relaxed);
    }
    if valid {
        Ok((result, to_check.len()))
    } else {
        unsafe { release_rows(result.nodes) };
        Err(Decline::Changed)
    }
}

/// Re-read each listed node from the provider and compare its row.
fn validate(
    automation: &IUIAutomation,
    walked: &[WalkedNode],
    indices: &[usize],
) -> windows::core::Result<bool> {
    if indices.is_empty() {
        return Ok(true);
    }
    let request = walk_request(automation, TreeScope_Element)?;
    for &i in indices {
        let node = &walked[i];
        let live = unsafe { node.element.BuildUpdatedCache(&request) }?;
        let props = read_node_props(&live);
        if !same_row(&node.props, &props) {
            tracing::debug!(target: "dove_perf", "tree cache: row {i} changed");
            return Ok(false);
        }
    }
    Ok(true)
}

/// Whether two reads of one element produce the same row.
fn same_row(cached: &NodeProps, live: &NodeProps) -> bool {
    let shown_rect = cached.is_actionable() || live.is_actionable();
    cached.control_type == live.control_type
        && cached.name == live.name
        && cached.value == live.value
        && cached.automation_id == live.automation_id
        && cached.help_text == live.help_text
        && cached.enabled == live.enabled
        && cached.selected == live.selected
        && cached.actions == live.actions
        && (!shown_rect || cached.rect == live.rect)
}

/// Release the element references `project` handed to rows that will not be
/// returned.
unsafe fn release_rows(nodes: Vec<UiaNode>) {
    for node in nodes {
        if node.element_ptr != 0 {
            drop(IUIAutomationElement::from_raw(node.element_ptr as *mut _));
        }
    }
}

// ── dirty-subtree re-walk ──────────────────────────────────────────────────

/// Re-walk the dirty subtrees of `tree` and splice them in. `None` when a
/// required subtree is not in the stored walk, a subtree cannot be read, or
/// the result would exceed the walk bounds.
fn rewalk_subtrees(
    automation: &IUIAutomation,
    tree: &CachedTree,
    dirty: &[cua_driver_core::tree_cache::DirtySubtree],
    params: WalkParams,
) -> Option<(Vec<WalkedNode>, usize)> {
    let mut positions: HashMap<SubtreeId, usize> = HashMap::new();
    for (i, node) in tree.walked.iter().enumerate() {
        if node.id != 0 {
            positions.entry(node.id).or_insert(i);
        }
    }
    let mut roots = Vec::new();
    for subtree in dirty {
        match positions.get(&subtree.id) {
            Some(&i) => roots.push(i),
            None if subtree.required => return None,
            None => {}
        }
    }
    roots.sort_unstable();
    roots.dedup();
    // Drop roots inside another dirty root's range.
    let mut outer: Vec<usize> = Vec::new();
    for i in roots {
        if outer
            .last()
            .is_some_and(|&o| i < tree.walked[o].end)
        {
            continue;
        }
        outer.push(i);
    }
    let request = walk_request(automation, TreeScope_Subtree).ok()?;
    let mut walked = tree.walked.clone();
    for &i in outer.iter().rev() {
        let root = &walked[i];
        let fresh = unsafe { root.element.BuildUpdatedCache(&request) }.ok()?;
        let mut budget = WalkBudget::nodes_only(params.max_elements);
        let mut replacement = Vec::new();
        collect(
            &fresh,
            root.depth,
            root.in_web_content,
            params.max_depth,
            &mut budget,
            &mut replacement,
        );
        if replacement.is_empty() || budget.outcome().stop.is_some() {
            return None;
        }
        let end = root.end;
        walked.splice(i..end, replacement).for_each(drop);
    }
    if walked.len() > params.max_elements {
        return None;
    }
    fix_ends(&mut walked);
    Some((walked, outer.len()))
}

/// Recompute every node's subtree end after a splice.
fn fix_ends(walked: &mut [WalkedNode]) {
    let mut stack: Vec<usize> = Vec::new();
    for i in 0..walked.len() {
        while let Some(&open) = stack.last() {
            if walked[open].depth >= walked[i].depth {
                walked[open].end = i;
                stack.pop();
            } else {
                break;
            }
        }
        stack.push(i);
    }
    let len = walked.len();
    for open in stack {
        walked[open].end = len;
    }
}

// ── runtime ids ─────────────────────────────────────────────────────────────

fn cached_runtime_id(element: &IUIAutomationElement) -> Option<Vec<i32>> {
    let variant = unsafe { element.GetCachedPropertyValue(UIA_RuntimeIdPropertyId) }.ok()?;
    let raw = variant.as_raw();
    // VT_ARRAY | VT_I4
    if unsafe { raw.Anonymous.Anonymous.vt } != 0x2003 {
        return None;
    }
    let array = unsafe { raw.Anonymous.Anonymous.Anonymous.parray } as *const SAFEARRAY;
    unsafe { read_i32_array(array) }
}

/// Read a one-dimensional `SAFEARRAY` of `VT_I4`.
unsafe fn read_i32_array(array: *const SAFEARRAY) -> Option<Vec<i32>> {
    let array = array.as_ref()?;
    if array.cDims != 1 || array.cbElements != 4 || array.pvData.is_null() {
        return None;
    }
    let len = array.rgsabound[0].cElements as usize;
    Some(std::slice::from_raw_parts(array.pvData as *const i32, len).to_vec())
}

fn cached_pid(element: &IUIAutomationElement) -> Option<u32> {
    let variant = unsafe { element.GetCachedPropertyValue(UIA_ProcessIdPropertyId) }.ok()?;
    let raw = variant.as_raw();
    (unsafe { raw.Anonymous.Anonymous.vt } == 3)
        .then(|| unsafe { raw.Anonymous.Anonymous.Anonymous.lVal } as u32)
}

// ── event handlers ──────────────────────────────────────────────────────────

#[implement(
    IUIAutomationStructureChangedEventHandler,
    IUIAutomationPropertyChangedEventHandler,
    IUIAutomationEventHandler
)]
struct WindowEvents {
    hwnd: u64,
}

impl IUIAutomationStructureChangedEventHandler_Impl for WindowEvents_Impl {
    fn HandleStructureChangedEvent(
        &self,
        sender: Option<&IUIAutomationElement>,
        change: StructureChangeType,
        _runtime_id: *const SAFEARRAY,
    ) -> windows::core::Result<()> {
        // ChildAdded names the new child, not the container that changed.
        let invalidation = if change == StructureChangeType_ChildAdded {
            Invalidation::Full
        } else {
            // ChildRemoved, ChildrenInvalidated, bulk changes and reorders
            // name the container.
            sender_invalidation(sender)
        };
        cache().invalidate(self.hwnd, invalidation);
        Ok(())
    }
}

impl IUIAutomationPropertyChangedEventHandler_Impl for WindowEvents_Impl {
    fn HandlePropertyChangedEvent(
        &self,
        sender: Option<&IUIAutomationElement>,
        _property: UIA_PROPERTY_ID,
        _value: &windows::core::VARIANT,
    ) -> windows::core::Result<()> {
        cache().invalidate(self.hwnd, sender_invalidation(sender));
        Ok(())
    }
}

impl IUIAutomationEventHandler_Impl for WindowEvents_Impl {
    fn HandleAutomationEvent(
        &self,
        _sender: Option<&IUIAutomationElement>,
        _event: UIA_EVENT_ID,
    ) -> windows::core::Result<()> {
        // WindowClosed. Handlers are removed on the next read path, never
        // from inside a UIA callback.
        cache().invalidate(self.hwnd, Invalidation::Full);
        Ok(())
    }
}

fn sender_invalidation(sender: Option<&IUIAutomationElement>) -> Invalidation {
    sender
        .and_then(cached_runtime_id)
        .map_or(Invalidation::Full, |id| Invalidation::Subtree(subtree_id(&id)))
}

#[implement(IUIAutomationFocusChangedEventHandler)]
struct FocusEvents;

impl IUIAutomationFocusChangedEventHandler_Impl for FocusEvents_Impl {
    fn HandleFocusChangedEvent(
        &self,
        sender: Option<&IUIAutomationElement>,
    ) -> windows::core::Result<()> {
        let Some(sender) = sender else {
            return Ok(());
        };
        if let (Some(pid), Some(id)) = (cached_pid(sender), cached_runtime_id(sender)) {
            // Only a cached window that contains the focused element changes.
            cache().invalidate_pid_with(pid as i32, Invalidation::Hint(subtree_id(&id)));
        }
        Ok(())
    }
}

struct Watch {
    root: IUIAutomationElement,
    events: IUIAutomationStructureChangedEventHandler,
    properties: IUIAutomationPropertyChangedEventHandler,
    closed: IUIAutomationEventHandler,
    last_used: Instant,
}

struct Watches {
    windows: HashMap<u64, Watch>,
    focus: Option<IUIAutomationFocusChangedEventHandler>,
}

// SAFETY: free-threaded UIA objects, used only from MTA threads.
unsafe impl Send for Watches {}

fn watches() -> &'static Mutex<Watches> {
    static WATCHES: OnceLock<Mutex<Watches>> = OnceLock::new();
    WATCHES.get_or_init(|| {
        Mutex::new(Watches {
            windows: HashMap::new(),
            focus: None,
        })
    })
}

fn touch_watch(hwnd: u64) {
    if let Some(watch) = watches()
        .lock()
        .unwrap_or_else(|p| p.into_inner())
        .windows
        .get_mut(&hwnd)
    {
        watch.last_used = Instant::now();
    }
}

/// Make sure `hwnd`'s events reach the cache. `false` when they cannot be
/// registered; such a window is never served from the cache.
fn ensure_watch(automation: &IUIAutomation, hwnd: u64) -> bool {
    let mut watches = watches().lock().unwrap_or_else(|p| p.into_inner());
    let request = match registration_request(automation) {
        Ok(request) => request,
        Err(_) => return false,
    };
    if watches.focus.is_none() {
        let handler: IUIAutomationFocusChangedEventHandler = FocusEvents.into();
        if unsafe { automation.AddFocusChangedEventHandler(&request, &handler) }.is_ok() {
            watches.focus = Some(handler);
        }
    }
    if watches.focus.is_none() {
        return false;
    }
    // Drop windows that closed.
    let closed: Vec<u64> = watches
        .windows
        .keys()
        .copied()
        .filter(|&w| !is_window(w))
        .collect();
    for window in closed {
        if let Some(watch) = watches.windows.remove(&window) {
            unwatch(automation, &watch);
        }
        cache().forget(window);
    }
    if let Some(watch) = watches.windows.get_mut(&hwnd) {
        watch.last_used = Instant::now();
        return true;
    }
    while watches.windows.len() >= MAX_WATCHED_WINDOWS {
        let Some(oldest) = watches
            .windows
            .iter()
            .min_by_key(|(_, watch)| watch.last_used)
            .map(|(&w, _)| w)
        else {
            break;
        };
        if let Some(watch) = watches.windows.remove(&oldest) {
            unwatch(automation, &watch);
        }
        cache().forget(oldest);
    }
    let Ok(root) =
        (unsafe { automation.ElementFromHandle(windows::Win32::Foundation::HWND(hwnd as *mut _)) })
    else {
        return false;
    };
    let events: IUIAutomationStructureChangedEventHandler = WindowEvents { hwnd }.into();
    let (Ok(properties), Ok(closed)) = (
        events.cast::<IUIAutomationPropertyChangedEventHandler>(),
        events.cast::<IUIAutomationEventHandler>(),
    ) else {
        return false;
    };
    let registered = unsafe {
        automation
            .AddStructureChangedEventHandler(&root, TreeScope_Subtree, &request, &events)
            .and_then(|()| {
                automation.AddPropertyChangedEventHandlerNativeArray(
                    &root,
                    TreeScope_Subtree,
                    &request,
                    &properties,
                    WATCHED_PROPERTIES,
                )
            })
            .and_then(|()| {
                automation.AddAutomationEventHandler(
                    UIA_Window_WindowClosedEventId,
                    &root,
                    TreeScope_Element,
                    &request,
                    &closed,
                )
            })
    };
    let watch = Watch {
        root,
        events,
        properties,
        closed,
        last_used: Instant::now(),
    };
    if registered.is_err() {
        unwatch(automation, &watch);
        return false;
    }
    watches.windows.insert(hwnd, watch);
    true
}

fn unwatch(automation: &IUIAutomation, watch: &Watch) {
    unsafe {
        let _ = automation.RemoveStructureChangedEventHandler(&watch.root, &watch.events);
        let _ = automation.RemovePropertyChangedEventHandler(&watch.root, &watch.properties);
        let _ = automation.RemoveAutomationEventHandler(
            UIA_Window_WindowClosedEventId,
            &watch.root,
            &watch.closed,
        );
    }
}

/// Event senders arrive with their runtime id and process id cached.
fn registration_request(automation: &IUIAutomation) -> windows::core::Result<IUIAutomationCacheRequest> {
    unsafe {
        let request = automation.CreateCacheRequest()?;
        request.AddProperty(UIA_RuntimeIdPropertyId)?;
        request.AddProperty(UIA_ProcessIdPropertyId)?;
        request.SetTreeScope(TreeScope_Element)?;
        Ok(request)
    }
}

fn is_window(hwnd: u64) -> bool {
    unsafe {
        windows::Win32::UI::WindowsAndMessaging::IsWindow(windows::Win32::Foundation::HWND(
            hwnd as *mut _,
        ))
    }
    .as_bool()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn props(name: &str) -> NodeProps {
        NodeProps {
            control_type: "Button".into(),
            name: Some(name.into()),
            value: None,
            automation_id: None,
            help_text: None,
            enabled: Some(true),
            selected: None,
            actions: vec!["invoke".into()],
            rect: Some((0, 0, 10, 10)),
        }
    }

    #[test]
    fn a_renamed_row_is_not_the_same_row() {
        assert!(same_row(&props("Save"), &props("Save")));
        assert!(!same_row(&props("Save"), &props("Saved")));
    }

    #[test]
    fn a_moved_actionable_row_is_not_the_same_row() {
        let mut moved = props("Save");
        moved.rect = Some((5, 0, 15, 10));
        assert!(!same_row(&props("Save"), &moved));
    }

    #[test]
    fn a_text_row_ignores_its_unshown_frame() {
        let mut text = props("Status");
        text.actions.clear();
        text.control_type = "Text".into();
        let mut moved = text.clone();
        moved.rect = Some((5, 0, 15, 10));
        assert!(same_row(&text, &moved));
    }

    #[test]
    fn a_disabled_row_is_not_the_same_row() {
        let mut disabled = props("Save");
        disabled.enabled = Some(false);
        assert!(!same_row(&props("Save"), &disabled));
    }
}
