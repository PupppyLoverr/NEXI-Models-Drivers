//! Invalidation rules of the tree cache. Each test owns its action clock so
//! actions dispatched by other tests in this process cannot interfere.

use super::*;

const PARAMS: WalkParams = WalkParams {
    max_elements: 250,
    max_depth: 25,
};
const WINDOW: u64 = 0x1234;
const PID: i32 = 42;

fn clock() -> &'static ActionClock {
    Box::leak(Box::new(ActionClock::new()))
}

fn cache(actions: &'static ActionClock) -> TreeCache<&'static str> {
    TreeCache::with_clock(true, Duration::from_secs(60), actions)
}

fn walk(cache: &TreeCache<&'static str>, value: &'static str) {
    let ticket = cache.begin_walk(PID, WINDOW);
    cache.finish_walk(ticket, PARAMS, value);
}

fn fresh(cache: &TreeCache<&'static str>) -> Option<&'static str> {
    match cache.lookup(WINDOW, PARAMS) {
        Lookup::Fresh { value, .. } => Some(*value),
        _ => None,
    }
}

fn miss(cache: &TreeCache<&'static str>) -> Option<MissReason> {
    match cache.lookup(WINDOW, PARAMS) {
        Lookup::Miss(reason) => Some(reason),
        _ => None,
    }
}

#[test]
fn a_quiet_window_is_reused() {
    let cache = cache(clock());
    assert_eq!(miss(&cache), Some(MissReason::Empty));
    walk(&cache, "v1");
    assert_eq!(fresh(&cache), Some("v1"));
    assert_eq!(fresh(&cache), Some("v1"));
}

#[test]
fn a_full_invalidation_forces_a_walk_and_the_next_walk_is_reused() {
    let cache = cache(clock());
    walk(&cache, "v1");
    cache.invalidate(WINDOW, Invalidation::Full);
    assert_eq!(miss(&cache), Some(MissReason::Changed));
    walk(&cache, "v2");
    assert_eq!(fresh(&cache), Some("v2"));
}

#[test]
fn an_event_during_the_walk_leaves_the_result_dirty() {
    let cache = cache(clock());
    let ticket = cache.begin_walk(PID, WINDOW);
    // The application changes after the walk read part of the tree.
    cache.invalidate(WINDOW, Invalidation::Full);
    cache.finish_walk(ticket, PARAMS, "torn");
    assert_eq!(miss(&cache), Some(MissReason::Changed));
}

#[test]
fn an_event_before_the_walk_does_not_dirty_it() {
    let cache = cache(clock());
    walk(&cache, "v1");
    cache.invalidate(WINDOW, Invalidation::Full);
    walk(&cache, "v2");
    assert_eq!(fresh(&cache), Some("v2"));
}

#[test]
fn subtree_events_report_the_dirty_subtrees() {
    let cache = cache(clock());
    walk(&cache, "v1");
    cache.invalidate(WINDOW, Invalidation::Subtree(7));
    cache.invalidate(WINDOW, Invalidation::Subtree(9));
    cache.invalidate(WINDOW, Invalidation::Subtree(7));
    match cache.lookup(WINDOW, PARAMS) {
        Lookup::Dirty {
            value, subtrees, ..
        } => {
            assert_eq!(*value, "v1");
            assert_eq!(
                subtrees,
                vec![
                    DirtySubtree {
                        id: 7,
                        required: true
                    },
                    DirtySubtree {
                        id: 9,
                        required: true
                    }
                ]
            );
        }
        _ => panic!("expected a dirty lookup"),
    }
    // A subtree re-walk that started after those events cleans the entry.
    walk(&cache, "v1+subtrees");
    assert_eq!(fresh(&cache), Some("v1+subtrees"));
}

#[test]
fn hints_are_optional_unless_a_required_event_names_the_same_subtree() {
    let cache = cache(clock());
    walk(&cache, "v1");
    cache.invalidate_pid_with(PID, Invalidation::Hint(3));
    cache.invalidate_pid_with(PID + 1, Invalidation::Full);
    match cache.lookup(WINDOW, PARAMS) {
        Lookup::Dirty { subtrees, .. } => assert_eq!(
            subtrees,
            vec![DirtySubtree {
                id: 3,
                required: false
            }]
        ),
        _ => panic!("expected a dirty lookup"),
    }
    cache.invalidate(WINDOW, Invalidation::Subtree(3));
    match cache.lookup(WINDOW, PARAMS) {
        Lookup::Dirty { subtrees, .. } => assert!(subtrees[0].required),
        _ => panic!("expected a dirty lookup"),
    }
}

#[test]
fn a_full_invalidation_wins_over_subtrees() {
    let cache = cache(clock());
    walk(&cache, "v1");
    cache.invalidate(WINDOW, Invalidation::Subtree(7));
    cache.invalidate(WINDOW, Invalidation::Full);
    assert_eq!(miss(&cache), Some(MissReason::Changed));
}

#[test]
fn too_many_subtrees_force_a_full_walk() {
    let cache = cache(clock());
    walk(&cache, "v1");
    for id in 0..(MAX_DIRTY_SUBTREES as u64 + 1) {
        cache.invalidate(WINDOW, Invalidation::Subtree(id));
    }
    assert_eq!(miss(&cache), Some(MissReason::Changed));
}

#[test]
fn an_event_flood_collapses_into_a_full_invalidation() {
    let cache = cache(clock());
    walk(&cache, "v1");
    for _ in 0..(MAX_DIRTY_SUBTREES * 4) {
        cache.invalidate(WINDOW, Invalidation::Subtree(1));
    }
    assert_eq!(miss(&cache), Some(MissReason::Changed));
}

#[test]
fn an_action_after_the_walk_forces_a_walk() {
    let actions = clock();
    let cache = cache(actions);
    walk(&cache, "v1");
    drop(ActionGuard::enter_on(actions));
    assert_eq!(miss(&cache), Some(MissReason::Action));
    walk(&cache, "v2");
    assert_eq!(fresh(&cache), Some("v2"));
}

#[test]
fn nothing_is_reused_while_an_action_runs() {
    let actions = clock();
    let cache = cache(actions);
    walk(&cache, "v1");
    let action = ActionGuard::enter_on(actions);
    assert_eq!(miss(&cache), Some(MissReason::Action));
    // A walk taken during the action is not stored for later reads either:
    // the action may change the application after the walk read it.
    walk(&cache, "during");
    drop(action);
    assert_eq!(miss(&cache), Some(MissReason::Action));
}

#[test]
fn different_walk_bounds_walk_again() {
    let cache = cache(clock());
    walk(&cache, "v1");
    let other = WalkParams {
        max_elements: 5000,
        max_depth: 25,
    };
    assert!(matches!(
        cache.lookup(WINDOW, other),
        Lookup::Miss(MissReason::Params)
    ));
}

#[test]
fn an_old_walk_expires() {
    let cache: TreeCache<&'static str> =
        TreeCache::with_clock(true, Duration::from_millis(20), clock());
    walk(&cache, "v1");
    assert_eq!(fresh(&cache), Some("v1"));
    std::thread::sleep(Duration::from_millis(40));
    assert_eq!(miss(&cache), Some(MissReason::Expired));
}

#[test]
fn a_disabled_cache_never_reuses() {
    let cache: TreeCache<&'static str> =
        TreeCache::with_clock(false, Duration::from_secs(60), clock());
    walk(&cache, "v1");
    assert_eq!(miss(&cache), Some(MissReason::Disabled));
}

#[test]
fn pid_and_global_invalidation_reach_every_window() {
    let cache = cache(clock());
    let other_window = WINDOW + 1;
    walk(&cache, "v1");
    let ticket = cache.begin_walk(PID + 1, other_window);
    cache.finish_walk(ticket, PARAMS, "other");
    cache.invalidate_pid(PID);
    assert_eq!(miss(&cache), Some(MissReason::Changed));
    assert!(matches!(
        cache.lookup(other_window, PARAMS),
        Lookup::Fresh { .. }
    ));
    cache.invalidate_all();
    assert!(matches!(
        cache.lookup(other_window, PARAMS),
        Lookup::Miss(MissReason::Changed)
    ));
}

#[test]
fn an_older_walk_cannot_replace_a_newer_one() {
    let cache = cache(clock());
    let slow = cache.begin_walk(PID, WINDOW);
    cache.invalidate(WINDOW, Invalidation::Full);
    let fast = cache.begin_walk(PID, WINDOW);
    cache.finish_walk(fast, PARAMS, "new");
    cache.finish_walk(slow, PARAMS, "old");
    assert_eq!(fresh(&cache), Some("new"));
}

#[test]
fn a_forgotten_window_starts_empty() {
    let cache = cache(clock());
    walk(&cache, "v1");
    cache.forget(WINDOW);
    assert_eq!(miss(&cache), Some(MissReason::Empty));
    // Events for a window with no slot are ignored, not stored.
    cache.invalidate(WINDOW, Invalidation::Full);
    walk(&cache, "v2");
    assert_eq!(fresh(&cache), Some("v2"));
}

#[test]
fn subtree_ids_are_stable_and_distinct() {
    assert_eq!(subtree_id(&[42, 1, 2]), subtree_id(&[42, 1, 2]));
    assert_ne!(subtree_id(&[42, 1, 2]), subtree_id(&[42, 2, 1]));
}

#[test]
fn pure_reads_exclude_actions() {
    assert!(is_pure_read_tool("get_window_state"));
    for action in ["click", "type_text", "run_steps", "set_value", "launch_app"] {
        assert!(!is_pure_read_tool(action), "{action}");
    }
}

#[test]
fn a_subtree_rewalk_keeps_the_full_walk_age() {
    let cache: TreeCache<&'static str> =
        TreeCache::with_clock(true, Duration::from_millis(60), clock());
    walk(&cache, "v1");
    std::thread::sleep(Duration::from_millis(40));
    cache.invalidate(WINDOW, Invalidation::Subtree(5));
    let Lookup::Dirty { age, .. } = cache.lookup(WINDOW, PARAMS) else {
        panic!("expected a dirty lookup");
    };
    let ticket = cache.begin_walk(PID, WINDOW);
    cache.finish_rewalk(ticket, PARAMS, "v1+subtree", age);
    assert_eq!(fresh(&cache), Some("v1+subtree"));
    // The full walk is now older than the bound; the re-walk did not renew it.
    std::thread::sleep(Duration::from_millis(40));
    assert_eq!(miss(&cache), Some(MissReason::Expired));
}
