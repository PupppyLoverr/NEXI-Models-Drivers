//! nexi-cua's synthetic GUI-decision generator (`nexi_cua/training/synth.py`),
//! ported to draw from [`PyRandom`] in exactly Python's order, so
//! `generate(n, seed)` rebuilds the very screens, goals and labels Python's
//! `generate(n, seed=seed)` produces (the held-out set of `semantic_eval`).
//!
//! Every `rng` call below happens where Python evaluates it: arguments left to
//! right before the callee's own draws, every element of a list literal
//! before the `choice` over it, the condition of `x if cond else y` first.

use super::pyrandom::PyRandom;
use dove_grounder::actions::{candidate_actions, ARG};
use dove_grounder::infer::resolve_args;
use dove_grounder::pystr;
use dove_grounder::types::{Action, Bounds, BrowserState, Element, Observation, Tab, Verb};
use std::cmp::Ordering;

// ---------------------------------------------------------- intents.py names
const SAVE_NAMES: &[&str] = &[
    "Save",
    "Save…",
    "Save Document",
    "Save File",
    "Done",
    "Apply",
    "Keep",
    "Save As…",
    "Save Changes",
    "✓ Save",
];
const CANCEL_NAMES: &[&str] = &[
    "Cancel",
    "Close",
    "Dismiss",
    "No",
    "Don't Save",
    "Discard",
    "Not Now",
    "Later",
    "Skip",
    "Back",
];
const OK_NAMES: &[&str] = &[
    "OK",
    "Confirm",
    "Yes",
    "Continue",
    "Accept",
    "Allow",
    "Agree",
    "Next",
    "Proceed",
    "Got It",
    "I Understand",
];
const OPEN_NAMES: &[&str] = &[
    "Open…",
    "Open File",
    "Browse…",
    "Choose File",
    "Import…",
    "Upload",
    "Attach",
    "Select File",
    "Add Files",
];
const SEND_NAMES: &[&str] = &[
    "Send",
    "Submit",
    "Post",
    "Share",
    "Publish",
    "Reply",
    "Send Message",
    "Submit Form",
];
const DELETE_NAMES: &[&str] = &[
    "Delete",
    "Remove",
    "Trash",
    "Move to Trash",
    "Erase",
    "Delete Permanently",
    "Remove Item",
];
const UNDO_NAMES: &[&str] = &["Undo", "Revert", "Restore", "Back", "Go Back"];

// ---------------------------------------------------------------- vocab
const NOUNS: &[&str] = &[
    "document",
    "file",
    "image",
    "photo",
    "project",
    "report",
    "email",
    "message",
    "tab",
    "window",
    "profile",
    "account",
    "settings",
    "playlist",
    "invoice",
    "recording",
    "draft",
    "form",
    "order",
];
const FIELD_NAMES: &[&str] = &[
    "Name",
    "Email",
    "Username",
    "Address",
    "Phone",
    "City",
    "First name",
    "Last name",
    "Title",
    "Subject",
    "Notes",
    "Description",
    "Password",
    "Search",
    "Message",
    "Comment",
    "URL",
    "Server",
    "Folder name",
    "Filename",
];
const TOGGLE_NAMES: &[&str] = &[
    "Dark Mode",
    "Notifications",
    "Wi-Fi",
    "Bluetooth",
    "Auto-save",
    "Spell Check",
    "Mute",
    "Enabled",
    "Vibrations",
    "Location Services",
    "Analytics",
    "Cookies",
    "JavaScript",
];
const COMBO_NAMES: &[&str] = &[
    "Theme",
    "Language",
    "Font Size",
    "Quality",
    "Region",
    "Format",
    "Resolution",
    "Sort By",
    "View",
    "Duration",
];
const TABS: &[&str] = &[
    "Dashboard",
    "Settings",
    "Inbox",
    "Search results",
    "Documentation",
    "Pull requests",
    "Issues",
    "Home",
    "Profile",
    "Checkout",
    "Report",
];
const WINDOWS: &[&str] = &[
    "Notes", "Finder", "Mail", "Safari", "Terminal", "Settings", "Music", "Photos", "Calendar",
    "TextEdit", "Preview",
];
const NAV_ITEMS: &[&str] = &[
    "Home",
    "Back",
    "Forward",
    "Reload",
    "Menu",
    "New Tab",
    "Minimize",
    "Maximize",
    "Zoom In",
    "Zoom Out",
    "Print",
    "Download",
    "Bookmark",
    "History",
    "Edit",
    "Copy",
    "Paste",
    "Cut",
    "Select All",
    "Find",
    "Share",
    "More",
    "Help",
    "Log In",
    "Sign Up",
    "Log Out",
    "Add",
    "New",
    "Start",
    "Stop",
    "Play",
    "Pause",
    "Next",
    "Previous",
    "Finish",
];
const DOMAINS: &[&str] = &[
    "example.com",
    "github.com",
    "docs.python.org",
    "apple.com",
    "wikipedia.org",
    "localhost:3000",
    "news.ycombinator.com",
    "stackoverflow.com",
    "developer.mozilla.org",
    "pypi.org",
];
const TYPE_WORDS: &[&str] = &[
    "hello",
    "test123",
    "john.doe@example.com",
    "quarterly report",
    "my search query",
    "Hello world",
    "Meeting at 3pm",
    "https://example.com",
    "Project Falcon",
    "note to self",
];
const KEY_GOALS: &[(&str, &str)] = &[
    ("press {k}", "enter"),
    ("press the {k} key", "enter"),
    ("hit {k}", "tab"),
    ("press {k}", "escape"),
    ("press {k}", "space"),
    ("press {k}", "backspace"),
    ("undo the last action", "cmd+z"),
    ("copy the selection", "cmd+c"),
    ("paste the clipboard", "cmd+v"),
    ("select all text", "cmd+a"),
    ("open spotlight search", "cmd+space"),
    ("quit the app", "cmd+q"),
    ("find on page", "cmd+f"),
    ("new tab", "cmd+t"),
    ("close the tab", "cmd+w"),
    ("save with keyboard", "cmd+s"),
    ("print", "cmd+p"),
    ("go back", "alt+left"),
    ("page down", "pagedown"),
    ("scroll to top", "home"),
    ("scroll to bottom", "end"),
];

// ---- real-web archetype vocab
const SHOP_ACTIONS: &[&str] = &[
    "Add to Cart",
    "Buy Now",
    "Add to Bag",
    "Checkout",
    "Apply Coupon",
    "Update Quantity",
    "Save for Later",
    "Add to Wishlist",
    "Remove",
    "Continue Shopping",
    "Place Order",
    "Track Package",
    "Write a Review",
];
const SHOP_FIELDS: &[&str] = &[
    "Size",
    "Color",
    "Quantity",
    "Shipping Address",
    "Card Number",
    "Expiry",
    "CVV",
    "Promo Code",
    "Zip Code",
    "Gift Message",
];
const SOCIAL_ACTIONS: &[&str] = &[
    "Like",
    "Comment",
    "Share",
    "Repost",
    "Follow",
    "Unfollow",
    "Bookmark",
    "Mute",
    "Block",
    "Report",
    "Subscribe",
    "Join",
    "Leave",
    "Pin",
    "React",
];
const MAIL_ACTIONS: &[&str] = &[
    "Compose",
    "Reply",
    "Reply All",
    "Forward",
    "Archive",
    "Mark as Read",
    "Mark as Unread",
    "Star",
    "Snooze",
    "Move to Spam",
    "Move to Inbox",
    "Empty Trash",
    "Attach",
];
const FILE_NAMES: &[&str] = &[
    "report.pdf",
    "photo.jpg",
    "notes.txt",
    "backup.zip",
    "presentation.key",
    "budget.xlsx",
    "readme.md",
    "archive.tar",
    "screenshot.png",
    "contract.docx",
    "song.mp3",
    "video.mov",
];
const TABLE_COLS: &[&str] = &[
    "Name", "Date", "Status", "Size", "Owner", "Amount", "Priority", "Modified", "Type", "Score",
    "Price", "Updated",
];
const CONSENT_NAMES: &[&str] = &[
    "Accept All",
    "Accept Cookies",
    "Reject All",
    "Manage",
    "Preferences",
    "Necessary Only",
    "Agree",
    "Dismiss",
];
const PLAYER_ACTIONS: &[&str] = &[
    "Play",
    "Pause",
    "Mute",
    "Unmute",
    "Skip",
    "Replay",
    "Fullscreen",
    "Next Episode",
    "Volume",
    "Speed",
    "Captions",
];
const CHAT_ACTIONS: &[&str] = &[
    "Send",
    "New Chat",
    "Attach",
    "Emoji",
    "Voice Message",
    "Edit",
    "Delete",
    "Pin",
    "Search",
    "Archive",
    "Mute",
];
const COLOR_ATTRS: &[&str] = &["green", "red", "blue", "orange", "purple", "gray"];

/// `ZONE_REGIONS`: the y range of each screen zone.
fn zone_region(zone: &str) -> (f64, f64) {
    match zone {
        "nav" => (0.0, 90.0),
        "main" => (90.0, 760.0),
        "side" => (700.0, 960.0),
        "foot" => (760.0, 980.0),
        _ => panic!("no zone {zone}"),
    }
}

// dense-page name pools: long, unicode, numeric, a11y-style, like real DOMs
const DENSE_LINKS: &[&str] = &[
    "Download the app on Google Play",
    "Install for iOS",
    "Read more",
    "Privacy policy",
    "Terms of service",
    "Contact us",
    "About us",
    "Čeština",
    "",
    "Deutsch",
    "Español",
    "Français",
    "한국어",
    "1,210",
    "23,576",
    "[45]",
    "[12]",
    "†",
    "edit",
    "view source",
    "Christopher J.C.H. Watkins",
    "Biorobotics",
    "Hardware security",
    "Knowsley Hall shootings",
    "World model (artificial intelligence)",
    "Paul Hunter",
    "2024 Summer Olympics",
    "Ancient Rome",
    "DNA",
    "Learn how to contribute",
    "See all events",
    "Show preview",
    "permalink",
    "Get shortened URL",
    "Cite this page",
    "Special pages",
    "Block hidden trackers in emails",
    "Browser Extensions",
    "choose DuckDuckGo over Chrome and other browsers",
    "iOS Browser",
    "Mac Browser",
    "Windows Browser",
    "Themes",
    "Order #1024",
    "Ticket Z-55",
    "User alice_92",
    "Build #918",
    "release-v2.4.1",
    "hotfix/security-patch",
    "PR #1042",
    "Reinforcement learning: An introduction",
    "artificial intelligence",
];
const DENSE_BUTTONS: &[&str] = &[
    "Search",
    "Go",
    "Apply",
    "Submit",
    "Load more",
    "Show all",
    "Accept all cookies",
    "Manage preferences",
    "Sign in",
    "Join now",
    "Try it Yourself",
    "Run »",
    "Buy",
    "Donate",
    "Share",
    "More",
    "Log in",
    "Create account",
    "Download",
    "Print",
    "Export",
];
const DENSE_TEXTS: &[&str] = &[
    "Search Wikipedia",
    "Search",
    "Email",
    "Username",
    "Password",
    "Enter your question",
    "Find a repository",
    "Search mail",
    "First name",
    "Last name",
    "Company",
    "Street address",
];

/// One synthetic decision (`Sample`).
#[derive(Clone, Debug)]
pub struct Sample {
    pub obs: Observation,
    pub candidates: Vec<Action>,
    /// `None` = abstain.
    pub correct_idx: Option<usize>,
    /// debug/analysis tag
    pub kind: String,
    pub gold_arg: String,
}

/// Python list concatenation `a + b + ...`.
fn cat(parts: &[&[&'static str]]) -> Vec<&'static str> {
    parts.iter().flat_map(|p| p.iter().copied()).collect()
}

/// `rng.choice` over a list of `&str`, as an owned string.
fn pick(rng: &mut PyRandom, seq: &[&str]) -> String {
    (*rng.choice(seq)).to_owned()
}

/// `rng.choice` over a list of strings built (with their own draws) before it.
fn pick_owned(rng: &mut PyRandom, seq: Vec<String>) -> String {
    rng.choice(&seq).clone()
}

/// `_el(role, name, i, rng, value="", w=1600, h=1000)`.
fn el(role: &str, name: &str, i: usize, rng: &mut PyRandom, value: &str) -> Element {
    let (w, h) = (1600.0, 1000.0);
    let x = rng.uniform(0.0, w - 200.0);
    let y = rng.uniform(0.0, h - 60.0);
    let bw = rng.uniform(60.0, 300.0);
    let bh = rng.uniform(24.0, 60.0);
    let enabled = rng.random() > 0.06;
    let focused = rng.random() < 0.05;
    let children_count = rng.randint(0, 4);
    let depth = rng.randint(1, 6);
    Element {
        id: format!("e{i}"),
        role: role.to_owned(),
        name: name.to_owned(),
        value: value.to_owned(),
        bounds: Some(Bounds { x, y, w: bw, h: bh }),
        enabled,
        focused,
        children_count,
        depth,
        ..Element::default()
    }
}

/// `_zone_el(role, name, i, rng, zone="main")`: element placed in a
/// realistic screen zone (nav/main/side/foot).
fn zone_el(role: &str, name: &str, i: usize, rng: &mut PyRandom, zone: &str) -> Element {
    let (y0, y1) = zone_region(zone);
    let x = rng.uniform(0.0, 1450.0);
    let y = rng.uniform(y0, y1);
    let bw = rng.uniform(50.0, 280.0);
    let bh = rng.uniform(22.0, 56.0);
    let enabled = rng.random() > 0.06;
    let focused = rng.random() < 0.05;
    let children_count = rng.randint(0, 4);
    let depth = rng.randint(1, 6);
    Element {
        id: format!("e{i}"),
        role: role.to_owned(),
        name: name.to_owned(),
        bounds: Some(Bounds { x, y, w: bw, h: bh }),
        enabled,
        focused,
        children_count,
        depth,
        ..Element::default()
    }
}

/// `for j, e in enumerate(els): e.id = f"e{j}"`.
fn renumber(els: &mut [Element]) {
    for (j, e) in els.iter_mut().enumerate() {
        e.id = format!("e{j}");
    }
}

/// `rng.shuffle(els)` followed by renumbering.
fn shuffle_renumber(els: &mut [Element], rng: &mut PyRandom) {
    rng.shuffle(els);
    renumber(els);
}

/// `_screen(rng, n_extra)`: a plausible background screen of elements.
fn screen(rng: &mut PyRandom, n_extra: i64) -> Vec<Element> {
    let mut els: Vec<Element> = Vec::new();
    let mut i = 0usize;
    let archetype = pick(
        rng,
        &[
            "dialog", "form", "toolbar", "browser", "settings", "editor", "list",
        ],
    );
    match archetype.as_str() {
        "dialog" => {
            let pool = cat(&[OK_NAMES, CANCEL_NAMES, SAVE_NAMES]);
            let k = 3.min(rng.randint(2, 3)) as usize;
            for nm in rng.sample(&pool, k) {
                els.push(el("button", nm, i, rng, ""));
                i += 1;
            }
            let text = pick(
                rng,
                &[
                    "Are you sure?",
                    "Unsaved changes",
                    "This action cannot be undone",
                    "Do you want to continue?",
                ],
            );
            els.push(el("statictext", &text, i, rng, ""));
        }
        "form" => {
            let k = rng.randint(2, 5) as usize;
            for nm in rng.sample(FIELD_NAMES, k) {
                let word = pick(rng, TYPE_WORDS);
                let value = pick_owned(rng, vec![String::new(), word]);
                els.push(el("textfield", nm, i, rng, &value));
                i += 1;
            }
            let nm = pick(rng, &cat(&[SEND_NAMES, OK_NAMES]));
            els.push(el("button", &nm, i, rng, ""));
        }
        "toolbar" => {
            let k = rng.randint(4, 8) as usize;
            for nm in rng.sample(NAV_ITEMS, k) {
                els.push(el("button", nm, i, rng, ""));
                i += 1;
            }
        }
        "browser" => {
            for (role, nm) in [
                ("button", "Back"),
                ("button", "Forward"),
                ("button", "Reload"),
                ("searchfield", "Address"),
            ] {
                els.push(el(role, nm, i, rng, ""));
                i += 1;
            }
            let pool = cat(&[NAV_ITEMS, &["Sign In", "Download", "Read More"]]);
            let k = rng.randint(2, 6) as usize;
            for nm in rng.sample(&pool, k) {
                let role = pick(rng, &["link", "button"]);
                els.push(el(&role, nm, i, rng, ""));
                i += 1;
            }
        }
        "settings" => {
            let k = rng.randint(3, 7) as usize;
            for nm in rng.sample(TOGGLE_NAMES, k) {
                let role = pick(rng, &["checkbox", "switch"]);
                els.push(el(&role, nm, i, rng, ""));
                i += 1;
            }
            let k = rng.randint(1, 3) as usize;
            for nm in rng.sample(COMBO_NAMES, k) {
                els.push(el("combobox", nm, i, rng, ""));
                i += 1;
            }
        }
        "editor" => {
            let value = pick(rng, TYPE_WORDS);
            els.push(el("textarea", "Document", i, rng, &value));
            i += 1;
            let pool = cat(&[NAV_ITEMS, SAVE_NAMES]);
            let k = rng.randint(3, 6) as usize;
            for nm in rng.sample(&pool, k) {
                let role = pick(rng, &["button", "menuitem"]);
                els.push(el(&role, nm, i, rng, ""));
                i += 1;
            }
        }
        _ => {
            // list
            let pool = cat(&[NAV_ITEMS, TABS]);
            for _ in 0..rng.randint(3, 8) {
                let nm = pick(rng, &pool);
                els.push(el("listitem", &nm, i, rng, ""));
                i += 1;
            }
            els.push(el("scrollarea", "", i, rng, ""));
        }
    }
    i = els.len();
    // unrelated distractors
    let names = cat(&[NAV_ITEMS, FIELD_NAMES, &[""]]);
    for _ in 0..n_extra {
        let role = pick(
            rng,
            &["statictext", "image", "group", "button", "menuitem", "link"],
        );
        let nm = pick(rng, &names);
        els.push(el(&role, &nm, i, rng, ""));
        i += 1;
    }
    shuffle_renumber(&mut els, rng);
    els
}

/// `_screen2(rng)`: real-web archetypes (ecommerce, social, mail, files,
/// table, login, consent banner, player, chat, kanban, wizard, tabstrip,
/// radio group, menu bar).
fn screen2(rng: &mut PyRandom) -> Vec<Element> {
    let mut els: Vec<Element> = Vec::new();
    let arch = pick(
        rng,
        &[
            "shop", "social", "mail", "files", "table", "login", "consent", "player", "chat",
            "kanban", "wizard", "tabstrip", "radio", "menubar",
        ],
    );
    // `i` always equals `len(els)` in Python's loops.
    macro_rules! push {
        ($role:expr, $name:expr, $zone:expr) => {{
            let i = els.len();
            let e = zone_el($role, $name, i, rng, $zone);
            els.push(e);
        }};
    }
    match arch.as_str() {
        "shop" => {
            let k = rng.randint(3, 7) as usize;
            for nm in rng.sample(SHOP_ACTIONS, k) {
                push!("button", nm, "main");
            }
            let k = rng.randint(1, 4) as usize;
            for nm in rng.sample(SHOP_FIELDS, k) {
                let r = pick(rng, &["combobox", "textfield", "stepper"]);
                push!(&r, nm, "main");
            }
            push!("link", "See all reviews", "main");
            let nm = pick(
                rng,
                &["Classic Hoodie", "Wireless Mouse", "Desk Lamp", "Sneakers"],
            );
            push!("heading", &nm, "main");
        }
        "social" => {
            let k = rng.randint(4, 8) as usize;
            for nm in rng.sample(SOCIAL_ACTIONS, k) {
                push!("button", nm, "main");
            }
            push!("textfield", "Write a comment", "main");
            let nm = pick(rng, &["@friend", "#topic", "View profile"]);
            push!("link", &nm, "main");
        }
        "mail" => {
            let k = rng.randint(4, 8) as usize;
            for nm in rng.sample(MAIL_ACTIONS, k) {
                let role = pick(rng, &["button", "menuitem"]);
                push!(&role, nm, "main");
            }
            for _ in 0..rng.randint(2, 5) {
                let nm = pick(
                    rng,
                    &[
                        "Invoice from Acme",
                        "Weekly digest",
                        "Team standup",
                        "Your receipt",
                        "Invitation",
                        "Security alert",
                    ],
                );
                push!("row", &nm, "main");
            }
            push!("searchfield", "Search mail", "nav");
        }
        "files" => {
            let k = rng.randint(4, 9) as usize;
            for nm in rng.sample(FILE_NAMES, k) {
                let role = pick(rng, &["listitem", "treeitem", "cell"]);
                push!(&role, nm, "main");
            }
            let nm = pick(
                rng,
                &["New Folder", "Upload", "Download", "Get Info", "Rename"],
            );
            push!("button", &nm, "main");
            push!("searchfield", "Search files", "nav");
        }
        "table" => {
            let k = rng.randint(3, 5) as usize;
            for nm in rng.sample(TABLE_COLS, k) {
                push!("column", nm, "nav");
            }
            for _ in 0..rng.randint(3, 7) {
                let nm = pick(
                    rng,
                    &[
                        "Order #1024",
                        "Ticket Z-55",
                        "User alice",
                        "Item 42",
                        "Build #918",
                        "Customer ACME",
                    ],
                );
                push!("row", &nm, "main");
            }
        }
        "login" => {
            let nm = pick(rng, &["Email", "Username", "Email or phone"]);
            push!("textfield", &nm, "main");
            push!("securetextfield", "Password", "main");
            let nm = pick(rng, &["Sign In", "Log In", "Continue", "Sign in with SSO"]);
            push!("button", &nm, "main");
            push!("link", "Forgot password?", "main");
            push!("checkbox", "Remember me", "main");
        }
        "consent" => {
            let k = rng.randint(2, 4) as usize;
            for nm in rng.sample(CONSENT_NAMES, k) {
                push!("button", nm, "foot");
            }
            push!(
                "statictext",
                "We use cookies to improve your experience",
                "foot"
            );
        }
        "player" => {
            let k = rng.randint(4, 7) as usize;
            for nm in rng.sample(PLAYER_ACTIONS, k) {
                let role = pick(rng, &["button", "slider"]);
                push!(&role, nm, "foot");
            }
            push!("progress", "", "foot");
        }
        "chat" => {
            let k = rng.randint(3, 6) as usize;
            for nm in rng.sample(CHAT_ACTIONS, k) {
                push!("button", nm, "main");
            }
            push!("textarea", "Message", "foot");
            for _ in 0..rng.randint(2, 5) {
                let nm = pick(
                    rng,
                    &["Alice", "Bob", "Team channel", "#general", "Support"],
                );
                push!("listitem", &nm, "side");
            }
        }
        "kanban" => {
            let k = rng.randint(2, 4) as usize;
            for nm in rng.sample(&["To Do", "In Progress", "Review", "Done"], k) {
                push!("column", nm, "nav");
            }
            for _ in 0..rng.randint(3, 8) {
                let nm = pick(
                    rng,
                    &[
                        "Fix login bug",
                        "Write docs",
                        "Design mockup",
                        "Ship v2",
                        "Review PR",
                        "Update deps",
                    ],
                );
                push!("listitem", &nm, "main");
            }
            push!("button", "Add card", "foot");
        }
        "wizard" => {
            let k = rng.randint(2, 4) as usize;
            for nm in rng.sample(&["Account", "Profile", "Payment", "Review", "Finish"], k) {
                push!("tab", nm, "nav");
            }
            let nm = pick(rng, &["Next", "Continue", "Previous"]);
            push!("button", &nm, "main");
            let k = rng.randint(1, 3) as usize;
            for nm in rng.sample(FIELD_NAMES, k) {
                push!("textfield", nm, "main");
            }
        }
        "tabstrip" => {
            let pool = cat(&[TABS, &["Unread", "Mentions", "Starred", "Archived"]]);
            let k = rng.randint(3, 6) as usize;
            for nm in rng.sample(&pool, k) {
                push!("tab", nm, "nav");
            }
            let names = cat(&[NAV_ITEMS, FILE_NAMES]);
            for _ in 0..rng.randint(2, 6) {
                let nm = pick(rng, &names);
                push!("listitem", &nm, "main");
            }
        }
        "radio" => {
            let group = pick(
                rng,
                &["Delivery", "Payment method", "Plan", "Size", "Theme"],
            );
            for nm in rng.sample(
                &[
                    "Standard", "Express", "Free", "Pro", "Team", "Basic", "Small", "Large",
                ],
                3,
            ) {
                push!("radio", nm, "main");
            }
            push!("radiogroup", &group, "main");
            let nm = pick(rng, OK_NAMES);
            push!("button", &nm, "main");
        }
        _ => {
            // menubar
            let k = rng.randint(3, 6) as usize;
            for nm in rng.sample(
                &["File", "Edit", "View", "Window", "Help", "Format", "Tools"],
                k,
            ) {
                push!("menubutton", nm, "nav");
            }
            let pool = cat(&[SAVE_NAMES, CANCEL_NAMES, OPEN_NAMES]);
            let k = rng.randint(2, 4) as usize;
            for nm in rng.sample(&pool, k) {
                push!("menuitem", nm, "main");
            }
        }
    }
    if rng.random() < 0.45 {
        push!("scrollarea", "", "main");
    }
    shuffle_renumber(&mut els, rng);
    els
}

/// Python's `f"{n:,}"` for a non-negative int.
fn thousands(n: i64) -> String {
    let digits = n.to_string();
    let mut out = String::new();
    for (k, c) in digits.chars().enumerate() {
        if k > 0 && (digits.len() - k).is_multiple_of(3) {
            out.push(',');
        }
        out.push(c);
    }
    out
}

/// `_screen3(rng)`: dense real-web page — nav links + big content body +
/// footer, 40-140 elements, heavy same-role distractors, unicode/numeric names.
fn screen3(rng: &mut PyRandom) -> Vec<Element> {
    let mut els: Vec<Element> = Vec::new();
    macro_rules! push {
        ($role:expr, $name:expr, $zone:expr) => {{
            let i = els.len();
            let e = zone_el($role, $name, i, rng, $zone);
            els.push(e);
        }};
    }
    // nav row: 5-10 links/buttons at the top
    let k = rng.randint(4, 8) as usize;
    for nm in rng.sample(DENSE_LINKS, k) {
        push!("link", nm, "nav");
    }
    let k = rng.randint(0, 3) as usize;
    for nm in rng.sample(DENSE_BUTTONS, k) {
        push!("button", nm, "nav");
    }
    if rng.random() < 0.8 {
        let nm = pick(rng, DENSE_TEXTS);
        push!("searchfield", &nm, "nav");
    }
    // main body: long lists of links / rows / items
    let n_main = rng.randint(20, 80);
    let k = rng.randint(1, 3) as usize;
    let kinds = rng.sample(&["link", "link", "listitem", "row", "menuitem"], k);
    let mut names: Vec<String> = DENSE_LINKS.iter().map(|s| (*s).to_owned()).collect();
    for _ in 0..8 {
        let n = rng.randint(1, 99999);
        names.push(thousands(n));
    }
    for _ in 0..4 {
        let a = pick(rng, &["et al.", "Inc.", "LLC"]);
        let b = pick(rng, &["Alpha", "Beta", "Gamma", "Delta"]);
        names.push(format!("{a} {b}"));
    }
    for _ in 0..n_main {
        let r = *rng.choice(&kinds);
        let nm = if rng.random() < 0.9 {
            rng.choice(&names).clone()
        } else {
            String::new()
        };
        push!(r, &nm, "main");
    }
    // scatter interactive furniture
    let furniture = cat(&[DENSE_BUTTONS, DENSE_LINKS]);
    for _ in 0..rng.randint(2, 8) {
        let r = pick(rng, &["button", "checkbox", "tab", "heading", "image"]);
        let nm = if r != "image" {
            pick(rng, &furniture)
        } else {
            String::new()
        };
        push!(&r, &nm, "main");
    }
    // footer
    let k = rng.randint(3, 8) as usize;
    for nm in rng.sample(&DENSE_LINKS[..12], k) {
        push!("link", nm, "foot");
    }
    if rng.random() < 0.5 {
        push!("scrollarea", "", "main");
    }
    shuffle_renumber(&mut els, rng);
    els
}

/// The browser part of `_obs(els, rng, browser)`.
fn obs_browser(rng: &mut PyRandom) -> BrowserState {
    let url = format!("https://{}/page", rng.choice(DOMAINS));
    let title = pick(rng, TABS);
    let tabs = rng
        .sample(TABS, 3)
        .into_iter()
        .enumerate()
        .map(|(i, t)| Tab {
            id: format!("t{i}"),
            title: t.to_owned(),
        })
        .collect();
    BrowserState { url, title, tabs }
}

/// `_obs(els, rng, browser)`: a macOS 1600x1000 observation.
fn obs(els: Vec<Element>, browser: Option<BrowserState>, goal: String) -> Observation {
    Observation {
        goal,
        elements: els,
        browser,
        screen_w: 1600,
        screen_h: 1000,
    }
}

/// Python's `(bounds.y if bounds else 0, bounds.x if bounds else 0) <`.
fn reading_lt(a: &Element, b: &Element) -> bool {
    let (ay, ax) = a.reading_key();
    let (by, bx) = b.reading_key();
    ay < by || (ay == by && ax < bx)
}

/// `min(idx, key=reading key)`: the first index with the smallest key.
fn topmost(els: &[Element], idx: &[usize]) -> usize {
    let mut best = idx[0];
    for &k in &idx[1..] {
        if reading_lt(&els[k], &els[best]) {
            best = k;
        }
    }
    best
}

/// `_pick_named(els, pool, rng)`: pick a target; when several candidates
/// share its name the goal can only mean the topmost one.
fn pick_named(els: &[Element], pool: &[usize], rng: &mut PyRandom) -> Element {
    let mut j = *rng.choice(pool);
    let same: Vec<usize> = pool
        .iter()
        .copied()
        .filter(|&k| els[k].name == els[j].name)
        .collect();
    if same.len() > 1 {
        j = topmost(els, &same);
    }
    els[j].clone()
}

/// `_find(els, pred)`.
fn find(els: &[Element], pred: impl Fn(&Element) -> bool) -> Vec<usize> {
    els.iter()
        .enumerate()
        .filter(|(_, e)| pred(e))
        .map(|(i, _)| i)
        .collect()
}

fn role_in(e: &Element, roles: &[&str]) -> bool {
    roles.contains(&e.role.as_str())
}

type Pred = Box<dyn Fn(&Element) -> bool>;

/// `gen_sample(rng)` with nexi's `_drag_boost`/`_ord_boost` (both 0 unless
/// `generate` is given others): one synthetic decision.
fn gen_sample(rng: &mut PyRandom, drag_boost: f64, ord_boost: f64) -> Sample {
    let browser = rng.random() < 0.45;
    let pick_r = rng.random();
    let mut els: Vec<Element>;
    if pick_r < 0.30 {
        // dense real-web pages
        els = screen3(rng);
        if rng.random() < 0.4 {
            let extra = screen2(rng);
            let k = rng.randint(2, 8) as usize;
            els.extend(extra.into_iter().take(k));
            shuffle_renumber(&mut els, rng);
        }
    } else if pick_r < 0.70 {
        els = screen2(rng);
        if rng.random() < 0.35 {
            // mixed screens: classic bg + real-web fg
            let extra = screen(rng, 0);
            let k = rng.randint(2, 6) as usize;
            els.extend(extra.into_iter().take(k));
            shuffle_renumber(&mut els, rng);
        }
        // The comprehension reads `len(els)` before any of its items is added.
        let n = els.len();
        let mut added = Vec::new();
        for _ in 0..rng.randint(0, 3) {
            let role = pick(rng, &["statictext", "image", "group"]);
            let nav = pick(rng, NAV_ITEMS);
            let name = pick_owned(rng, vec![String::new(), nav]);
            added.push(el(&role, &name, n, rng, ""));
        }
        els.extend(added);
    } else {
        let n_extra = rng.randint(0, 4);
        els = screen(rng, n_extra);
    }
    renumber(&mut els);
    let browser_state = if browser {
        Some(obs_browser(rng))
    } else {
        None
    };

    let mut r = rng.random();
    if ord_boost != 0.0 && rng.random() < ord_boost {
        r = 0.983; // positional band
    }
    if drag_boost != 0.0
        && rng.random() < drag_boost
        && find(&els, |e| {
            role_in(e, &["listitem", "treeitem", "row", "cell", "image", "tab"])
                && !e.name.is_empty()
        })
        .len()
            >= 2
    {
        r = 0.958;
    }
    // ---- abstain cases
    if r < 0.08 {
        let options = vec![
            format!("click the {}xplode button", rng.choice(NAV_ITEMS)),
            format!("press the {} teleport key", rng.choice(FIELD_NAMES)),
            format!("enable {} warp drive", rng.choice(TOGGLE_NAMES)),
            format!("open {} quantum editor", rng.choice(WINDOWS)),
            format!(
                "type something into the {} transporter",
                rng.choice(FIELD_NAMES)
            ),
            // ungroundable visual attributes: abstain (vision's job)
            format!("click the {} button", rng.choice(COLOR_ATTRS)),
            format!("click the {} icon in the corner", rng.choice(COLOR_ATTRS)),
            format!("press the glowing {} button", rng.choice(NAV_ITEMS)),
        ];
        let mut goal = pick_owned(rng, options);
        if ["xplode", "teleport", "warp", "quantum", "transporter"]
            .iter()
            .any(|w| goal.contains(w))
        {
            goal += &format!(" {}", rng.randint(99, 999));
        }
        let obs = obs(els, browser_state, goal);
        let cands = candidate_actions(&obs);
        return Sample {
            obs,
            candidates: cands,
            correct_idx: None,
            kind: "abstain-absent".into(),
            gold_arg: String::new(),
        };
    }

    // ---- goal archetypes
    let goal: String;
    let verb: Verb;
    let mut target_pred: Option<Pred> = None;
    let mut arg = String::new();

    if r < 0.22 {
        // click named target
        let names = cat(&[
            SAVE_NAMES,
            OK_NAMES,
            CANCEL_NAMES,
            OPEN_NAMES,
            SEND_NAMES,
            DELETE_NAMES,
            UNDO_NAMES,
            NAV_ITEMS,
        ]);
        let mut tgt = pick(rng, &names);
        let lower = pystr::lower(&tgt);
        let pool = find(&els, |e| pystr::lower(&e.name) == lower);
        if pool.is_empty() {
            match els
                .iter()
                .find(|e| role_in(e, &["button", "link", "menuitem"]) && !e.name.is_empty())
            {
                Some(e) => tgt = e.name.clone(),
                None => return gen_sample(rng, drag_boost, ord_boost),
            }
        }
        let t = tgt.clone();
        target_pred = Some(Box::new(move |e: &Element| e.name == t));
        goal = pick_owned(
            rng,
            vec![
                format!("click the {tgt} button"),
                format!("press {tgt}"),
                format!("click {tgt}"),
                format!("tap {tgt}"),
                format!("hit the {tgt} button"),
                format!("choose {tgt}"),
                format!("activate {tgt}"),
                format!("select the {tgt} option"),
            ],
        );
        verb = Verb::Click;
    } else if r < 0.32 {
        // semantic click (save/confirm/close/send/open/delete/undo)
        let kind = pick(
            rng,
            &[
                "save", "confirm", "cancel", "send", "open", "delete", "undo",
            ],
        );
        let names: &[&str] = match kind.as_str() {
            "save" => SAVE_NAMES,
            "confirm" => OK_NAMES,
            "cancel" => CANCEL_NAMES,
            "send" => SEND_NAMES,
            "open" => OPEN_NAMES,
            "delete" => DELETE_NAMES,
            _ => UNDO_NAMES,
        };
        let word = kind;
        let noun = pick(rng, NOUNS);
        goal = pick_owned(
            rng,
            vec![
                format!("{word} the {noun}"),
                format!("{word} it"),
                format!("{word} the current {noun}"),
                format!("{word} now"),
                format!("please {word} the {noun}"),
            ],
        );
        let lowered: Vec<String> = names.iter().map(|n| pystr::lower(n)).collect();
        target_pred = Some(Box::new(move |e: &Element| {
            lowered.contains(&pystr::lower(&e.name))
        }));
        verb = Verb::Click;
    } else if r < 0.44 {
        // type into a field
        let field = pick(rng, FIELD_NAMES);
        let text = pick(rng, TYPE_WORDS);
        verb = Verb::Type;
        arg = text.clone();
        let fl = pystr::lower(&field);
        let pred: Pred = Box::new(move |e: &Element| {
            let name = pystr::lower(&e.name);
            (role_in(e, &["textfield", "searchfield", "textarea", "combobox"])
                && name.contains(&fl))
                || (name.contains(&fl) && e.role == "textfield")
        });
        goal = pick_owned(
            rng,
            vec![
                format!("type \"{text}\" into the {field} field"),
                format!("enter \"{text}\" in {field}"),
                format!("fill in {field} with \"{text}\""),
                format!("write \"{text}\" into {field}"),
                format!("set the {field} to \"{text}\""),
            ],
        );
        // usually an answerable target: inject the named field if absent
        if find(&els, &pred).is_empty() && rng.random() < 0.8 {
            let role = pick(rng, &["textfield", "searchfield", "textarea"]);
            let n = els.len();
            els.push(el(&role, &field, n, rng, ""));
        }
        target_pred = Some(pred);
    } else if r < 0.52 {
        // keypress
        let key_goals: Vec<(&str, &str)> = KEY_GOALS
            .iter()
            .copied()
            .filter(|(tpl, _)| !browser || !["new tab", "close the tab", "go back"].contains(tpl))
            .collect();
        let (tpl, keys) = *rng.choice(&key_goals);
        let k = if keys.contains("cmd") {
            keys.replace("cmd", "command")
        } else {
            keys.to_owned()
        };
        goal = tpl.replace("{k}", &k);
        verb = Verb::Keypress;
        arg = keys.to_owned();
    } else if r < 0.60 {
        // toggle / checkbox
        let tgt = pick(rng, TOGGLE_NAMES);
        let tl = pystr::lower(&tgt);
        let pred: Pred = Box::new(move |e: &Element| {
            pystr::lower(&e.name).contains(&tl) && role_in(e, &["checkbox", "switch", "toggle"])
        });
        if find(&els, &pred).is_empty() && rng.random() < 0.6 {
            let n = els.len();
            els.push(el("checkbox", &tgt, n, rng, ""));
        }
        target_pred = Some(pred);
        let style = rng.random();
        if style < 0.45 {
            // explicit check/uncheck phrasing -> CHECK
            verb = Verb::Check;
            goal = pick_owned(
                rng,
                vec![
                    format!("check the {tgt} box"),
                    format!("tick {tgt}"),
                    format!("uncheck {tgt}"),
                    format!("check {tgt}"),
                    format!("mark the {tgt} checkbox"),
                ],
            );
        } else {
            // enable/toggle phrasing -> plain CLICK
            verb = Verb::Click;
            goal = pick_owned(
                rng,
                vec![
                    format!("enable {tgt}"),
                    format!("turn on {tgt}"),
                    format!("toggle {tgt}"),
                    format!("activate {tgt}"),
                    format!("switch on {tgt}"),
                ],
            );
        }
    } else if r < 0.66 {
        // select option
        let tgt = pick(rng, COMBO_NAMES);
        let opt = pick(
            rng,
            &[
                "High", "Low", "English", "Dark", "Compact", "Weekly", "1080p", "Latest",
            ],
        );
        let tl = pystr::lower(&tgt);
        let pred: Pred = Box::new(move |e: &Element| {
            pystr::lower(&e.name).contains(&tl)
                && role_in(e, &["combobox", "select", "popupbutton"])
        });
        if find(&els, &pred).is_empty() && rng.random() < 0.6 {
            let n = els.len();
            els.push(el("combobox", &tgt, n, rng, ""));
        }
        target_pred = Some(pred);
        verb = Verb::Select;
        arg = opt.clone();
        goal = pick_owned(
            rng,
            vec![
                format!("set {tgt} to {opt}"),
                format!("choose {opt} for {tgt}"),
                format!("change {tgt} to {opt}"),
                format!("pick {opt} in the {tgt} dropdown"),
            ],
        );
    } else if r < 0.72 {
        // scroll
        let scrollable = find(&els, |e| e.role == "scrollarea");
        let direction = pick(rng, &["down", "up"]);
        if !scrollable.is_empty() {
            target_pred = Some(Box::new(|e: &Element| e.role == "scrollarea"));
            verb = Verb::Scroll;
            arg = direction.clone();
            goal = pick_owned(
                rng,
                vec![
                    format!("scroll {direction} the list"),
                    format!("scroll {direction}"),
                    format!("scroll the page {direction}"),
                    format!("swipe {direction}"),
                ],
            );
        } else {
            verb = Verb::Keypress;
            arg = if direction == "down" {
                "pagedown"
            } else {
                "pageup"
            }
            .to_owned();
            goal = pick_owned(
                rng,
                vec![
                    format!("scroll {direction}"),
                    format!("page {direction}"),
                    format!("go {direction} the page"),
                ],
            );
        }
    } else if r < 0.78 {
        // wait / done
        if rng.random() < 0.5 {
            verb = Verb::Wait;
            goal = pick(
                rng,
                &[
                    "wait for the page to load",
                    "wait a moment",
                    "pause briefly",
                    "hold on",
                    "wait",
                ],
            );
        } else {
            verb = Verb::Done;
            goal = pick(
                rng,
                &[
                    "the task is complete",
                    "nothing else needed",
                    "you are finished",
                    "finish up",
                    "done",
                ],
            );
        }
    } else if r < 0.90 && browser {
        // browser verbs
        let bverb = *rng.choice(&[
            Verb::Navigate,
            Verb::Back,
            Verb::Forward,
            Verb::Refresh,
            Verb::NewTab,
            Verb::SwitchTab,
        ]);
        verb = bverb;
        if bverb == Verb::Navigate {
            arg = pick(rng, DOMAINS);
            goal = pick_owned(
                rng,
                vec![
                    format!("go to {arg}"),
                    format!("navigate to {arg}"),
                    format!("open {arg}"),
                    format!("visit {arg}"),
                ],
            );
        } else if bverb == Verb::SwitchTab {
            let tabs = &browser_state.as_ref().unwrap().tabs;
            let tab = rng.choice(tabs).clone();
            arg = tab.id.clone();
            let title = &tab.title;
            goal = pick_owned(
                rng,
                vec![
                    format!("switch to the {title} tab"),
                    format!("open the {title} tab"),
                    format!("go to tab {title}"),
                ],
            );
        } else {
            // The dict literal draws all four phrasings before indexing.
            let back = pick(rng, &["go back", "previous page", "navigate back"]);
            let forward = pick(rng, &["go forward", "next page"]);
            let refresh = pick(rng, &["refresh the page", "reload", "reload the page"]);
            let new_tab = pick(rng, &["open a new tab", "new tab"]);
            goal = match bverb {
                Verb::Back => back,
                Verb::Forward => forward,
                Verb::Refresh => refresh,
                _ => new_tab,
            };
        }
    } else if r < 0.94 {
        // focus field
        let pool = find(&els, |e| {
            role_in(e, &["textfield", "searchfield", "textarea"])
        });
        if pool.is_empty() {
            return gen_sample(rng, drag_boost, ord_boost);
        }
        let tgt = els[pool[0]].clone();
        let id = tgt.id.clone();
        target_pred = Some(Box::new(move |e: &Element| e.id == id));
        verb = Verb::Focus;
        let or = |fallback: &str| {
            if tgt.name.is_empty() {
                fallback.to_owned()
            } else {
                tgt.name.clone()
            }
        };
        goal = pick_owned(
            rng,
            vec![
                format!("focus the {} field", or("text")),
                format!("click into {}", or("the text field")),
                format!("put the cursor in {}", or("the field")),
            ],
        );
    } else if r < 0.955 {
        // double-click (open files/items)
        let pool = find(&els, |e| {
            role_in(e, &["listitem", "treeitem", "cell", "row", "image"]) && !e.name.is_empty()
        });
        if pool.is_empty() {
            return gen_sample(rng, drag_boost, ord_boost);
        }
        let tgt = pick_named(&els, &pool, rng);
        let id = tgt.id.clone();
        target_pred = Some(Box::new(move |e: &Element| e.id == id));
        verb = Verb::DoubleClick;
        let n = &tgt.name;
        goal = pick_owned(
            rng,
            vec![
                format!("double-click {n}"),
                format!("double click on {n}"),
                format!("open {n} by double-clicking"),
                format!("double-click the {n} file"),
            ],
        );
    } else if r < 0.965 {
        // drag src -> dst
        let pool = find(&els, |e| {
            role_in(e, &["listitem", "treeitem", "row", "cell", "image", "tab"])
                && !e.name.is_empty()
        });
        if pool.len() < 2 {
            return gen_sample(rng, drag_boost, ord_boost);
        }
        let picked = rng.sample(&pool, 2);
        let (src_i, dst_i) = (picked[0], picked[1]);
        let mut src = els[src_i].clone();
        let dst = els[dst_i].clone();
        // several elements sharing the source name: the topmost one
        let same: Vec<usize> = pool
            .iter()
            .copied()
            .filter(|&j| els[j].name == src.name)
            .collect();
        if same.len() > 1 {
            src = els[topmost(&els, &same)].clone();
        }
        let id = src.id.clone();
        target_pred = Some(Box::new(move |e: &Element| e.id == id));
        verb = Verb::Drag;
        let (s, d) = (&src.name, &dst.name);
        goal = pick_owned(
            rng,
            vec![
                format!("drag {s} onto {d}"),
                format!("move {s} to {d}"),
                format!("drag the {s} item over {d}"),
                format!("reorder {s} before {d}"),
            ],
        );
    } else if r < 0.98 {
        // right-click / context menu
        let pool = find(&els, |e| {
            !e.name.is_empty()
                && role_in(
                    e,
                    &[
                        "listitem", "treeitem", "cell", "row", "image", "button", "link",
                    ],
                )
        });
        if pool.is_empty() {
            return gen_sample(rng, drag_boost, ord_boost);
        }
        let tgt = pick_named(&els, &pool, rng);
        let id = tgt.id.clone();
        target_pred = Some(Box::new(move |e: &Element| e.id == id));
        verb = Verb::RightClick;
        let n = &tgt.name;
        goal = pick_owned(
            rng,
            vec![
                format!("right-click {n}"),
                format!("open the context menu on {n}"),
                format!("right click on {n}"),
            ],
        );
    } else if r < 0.987 {
        // positional reference (ordinal among matching role)
        let options: [(&str, &[&str]); 8] = [
            ("tab", &["tab"]),
            ("link", &["link"]),
            ("item", &["listitem", "treeitem"]),
            ("result", &["link", "listitem"]),
            ("row", &["row", "cell"]),
            ("card", &["listitem"]),
            ("menu item", &["menuitem"]),
            ("button", &["button"]),
        ];
        let (kind, roles) = *rng.choice(&options);
        let mut pool = find(&els, |e| role_in(e, roles) && !e.name.is_empty());
        // sorted(): stable
        pool.sort_by(|&a, &b| {
            if reading_lt(&els[a], &els[b]) {
                Ordering::Less
            } else if reading_lt(&els[b], &els[a]) {
                Ordering::Greater
            } else {
                Ordering::Equal
            }
        });
        if pool.is_empty() {
            return gen_sample(rng, drag_boost, ord_boost);
        }
        let style = rng.random();
        let tgt;
        if style < 0.25 && pool.len() >= 2 {
            // last / bottom
            tgt = els[*pool.last().unwrap()].clone();
            goal = pick_owned(
                rng,
                vec![
                    format!("click the last {kind}"),
                    format!("open the bottom {kind}"),
                    format!("select the last {kind} on the page"),
                ],
            );
        } else if style < 0.5 && pool.len() >= 2 {
            // named position
            tgt = els[pool[0]].clone();
            goal = pick_owned(
                rng,
                vec![
                    format!("click the {kind} at the top"),
                    format!("open the topmost {kind}"),
                    format!("click the first {kind} in the list"),
                ],
            );
        } else {
            let ord_idx = rng.randrange(pool.len().min(3) as i64) as usize;
            tgt = els[pool[ord_idx]].clone();
            let ord_name = ["first", "second", "third"][ord_idx];
            goal = pick_owned(
                rng,
                vec![
                    format!("click the {ord_name} {kind}"),
                    format!("open the {ord_name} {kind}"),
                    format!("select the {ord_name} {kind} on the page"),
                ],
            );
        }
        let id = tgt.id.clone();
        target_pred = Some(Box::new(move |e: &Element| e.id == id));
        verb = Verb::Click;
    } else if r < 0.995 {
        // radio option pick
        let pool = find(&els, |e| e.role == "radio" && !e.name.is_empty());
        if pool.is_empty() {
            return gen_sample(rng, drag_boost, ord_boost);
        }
        let tgt = pick_named(&els, &pool, rng);
        let id = tgt.id.clone();
        target_pred = Some(Box::new(move |e: &Element| e.id == id));
        verb = Verb::Click;
        let n = &tgt.name;
        goal = pick_owned(
            rng,
            vec![
                format!("choose the {n} option"),
                format!("select {n}"),
                format!("pick {n}"),
                format!("choose {n}"),
            ],
        );
    } else {
        // generic click on any actionable named element
        let pool = find(&els, |e| {
            !e.name.is_empty() && role_in(e, &["button", "link", "menuitem", "tab", "listitem"])
        });
        if pool.is_empty() {
            return gen_sample(rng, drag_boost, ord_boost);
        }
        let tgt = pick_named(&els, &pool, rng);
        let id = tgt.id.clone();
        target_pred = Some(Box::new(move |e: &Element| e.id == id));
        verb = Verb::Click;
        let n = &tgt.name;
        goal = pick_owned(
            rng,
            vec![
                format!("click {n}"),
                format!("press {n}"),
                format!("open {n}"),
                format!("select {n}"),
            ],
        );
    }

    // ---- ambiguity case: two matching targets
    let mut ambiguous = false;
    if rng.random() < 0.06 {
        if let Some(pred) = &target_pred {
            let matches = find(&els, pred);
            if matches.len() == 1 {
                let mut dup = els[matches[0]].clone();
                dup.id = format!("e{}", els.len());
                let (w, h) = match &dup.bounds {
                    Some(b) => (b.w, b.h),
                    None => (80.0, 30.0),
                };
                let x = rng.uniform(0.0, 1400.0);
                let y = rng.uniform(0.0, 900.0);
                dup.bounds = Some(Bounds { x, y, w, h });
                els.push(dup);
                ambiguous = true;
            }
        }
    }

    let obs = obs(els, browser_state, goal);
    let cands = candidate_actions(&obs);
    let correct_idx = label(&cands, &obs, verb, target_pred.as_deref(), &arg);
    let mut kind = if ambiguous { "ambiguous" } else { "semantic" };
    if correct_idx.is_none() && !ambiguous {
        kind = "abstain-implicit";
    }
    Sample {
        obs,
        candidates: cands,
        correct_idx,
        kind: kind.into(),
        gold_arg: arg,
    }
}

/// `_label(cands, obs, verb, pred, arg)`: the index of the gold candidate.
fn label(
    cands: &[Action],
    obs: &Observation,
    verb: Verb,
    pred: Option<&dyn Fn(&Element) -> bool>,
    arg: &str,
) -> Option<usize> {
    use Verb::*;
    if matches!(
        verb,
        Keypress | Wait | Done | Back | Forward | Refresh | NewTab | Navigate
    ) {
        return cands
            .iter()
            .position(|a| a.verb == verb && !(verb == Navigate && a.text != ARG));
    }
    if verb == SwitchTab {
        return cands.iter().position(|a| a.verb == verb && a.tab == arg);
    }
    for (i, a) in cands.iter().enumerate() {
        let Some(id) = a.element_id.as_deref().filter(|_| a.verb == verb) else {
            continue;
        };
        let Some(el) = obs.elements.iter().find(|e| e.id == id) else {
            continue;
        };
        // Python would raise calling `None`; no branch reaches it.
        let pred = pred.expect("element verb without a target predicate");
        if pred(el) && (verb != Scroll || a.direction == arg) {
            return Some(i);
        }
    }
    None
}

/// `generate(n, seed)`: `n` samples from `random.Random(seed)`.
///
/// Python retries a sample that raises; no Rust branch can fail that way
/// (and Python's `generate(2000, seed=31337)` raises none), so there is no
/// retry here.
pub fn generate(n: usize, seed: u64) -> Vec<Sample> {
    generate_boosted(n, seed, 0.0, 0.0)
}

/// `generate(n, seed, drag_boost, ord_boost)`.
pub fn generate_boosted(n: usize, seed: u64, drag_boost: f64, ord_boost: f64) -> Vec<Sample> {
    let mut rng = PyRandom::new(seed);
    (0..n)
        .map(|_| gen_sample(&mut rng, drag_boost, ord_boost))
        .collect()
}

/// The `semantic_eval` truth for a sample, as `make_goldens.py` records it:
/// `str(_resolve_args(gold, goal, elements))` with the gold argument put
/// back (keys for a keypress, text for type/select/navigate); `None` when
/// the sample is an abstention.
pub fn truth(s: &Sample) -> Option<String> {
    let gold = &s.candidates[s.correct_idx?];
    let mut resolved = resolve_args(gold, &s.obs.goal, &s.obs.elements);
    if !s.gold_arg.is_empty() {
        match resolved.verb {
            Verb::Keypress => {
                resolved.keys = s.gold_arg.split('+').map(str::to_owned).collect();
            }
            Verb::Type | Verb::Select | Verb::Navigate => resolved.text = s.gold_arg.clone(),
            _ => {}
        }
    }
    Some(resolved.to_string())
}
