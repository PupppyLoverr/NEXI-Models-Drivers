"""Synthetic GUI-decision data generator for NEXI-CUA-1.

Generates (goal, elements, candidates, correct_index | None) at speed. Every
sample is a plausible screen built from archetypes (dialogs, forms, toolbars,
browsers, settings, calculators...) with realistic labels, plus distractors.

Label logic is programmatic — the "teacher" is the generator's own world
model, so ground truth is exact. ~8% of samples are abstention cases (no
correct candidate exists) and ~6% are ambiguous (two good answers).
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Optional

from ..actions import Action, Verb, candidate_actions
from ..policy.intents import (CANCEL_NAMES, DELETE_NAMES, OK_NAMES,
                              OPEN_NAMES, SAVE_NAMES, SEND_NAMES, UNDO_NAMES)
from ..types import Bounds, Element, NormalizedObservation, Platform, BrowserState

# ---------------------------------------------------------------- vocab
NOUNS = ["document", "file", "image", "photo", "project", "report", "email",
         "message", "tab", "window", "profile", "account", "settings",
         "playlist", "invoice", "recording", "draft", "form", "order"]
SEARCH_HINTS = ["Search", "Search…", "Find", "Filter", "Query",
                "Search items", "Search the web"]
FIELD_NAMES = ["Name", "Email", "Username", "Address", "Phone", "City",
               "First name", "Last name", "Title", "Subject", "Notes",
               "Description", "Password", "Search", "Message", "Comment",
               "URL", "Server", "Folder name", "Filename"]
TOGGLE_NAMES = ["Dark Mode", "Notifications", "Wi-Fi", "Bluetooth",
                "Auto-save", "Spell Check", "Mute", "Enabled", "Vibrations",
                "Location Services", "Analytics", "Cookies", "JavaScript"]
COMBO_NAMES = ["Theme", "Language", "Font Size", "Quality", "Region",
               "Format", "Resolution", "Sort By", "View", "Duration"]
TABS = ["Dashboard", "Settings", "Inbox", "Search results", "Documentation",
        "Pull requests", "Issues", "Home", "Profile", "Checkout", "Report"]
WINDOWS = ["Notes", "Finder", "Mail", "Safari", "Terminal", "Settings",
           "Music", "Photos", "Calendar", "TextEdit", "Preview"]
NAV_ITEMS = ["Home", "Back", "Forward", "Reload", "Menu", "New Tab",
             "Minimize", "Maximize", "Zoom In", "Zoom Out", "Print",
             "Download", "Bookmark", "History", "Edit", "Copy", "Paste",
             "Cut", "Select All", "Find", "Share", "More", "Help",
             "Log In", "Sign Up", "Log Out", "Add", "New", "Start",
             "Stop", "Play", "Pause", "Next", "Previous", "Finish"]
DOMAINS = ["example.com", "github.com", "docs.python.org", "apple.com",
           "wikipedia.org", "localhost:3000", "news.ycombinator.com",
           "stackoverflow.com", "developer.mozilla.org", "pypi.org"]
TYPE_WORDS = ["hello", "test123", "john.doe@example.com", "quarterly report",
              "my search query", "Hello world", "Meeting at 3pm",
              "https://example.com", "Project Falcon", "note to self"]
KEY_GOALS = [
    ("press {k}", "enter"), ("press the {k} key", "enter"),
    ("hit {k}", "tab"), ("press {k}", "escape"), ("press {k}", "space"),
    ("press {k}", "backspace"), ("undo the last action", "cmd+z"),
    ("copy the selection", "cmd+c"), ("paste the clipboard", "cmd+v"),
    ("select all text", "cmd+a"), ("open spotlight search", "cmd+space"),
    ("quit the app", "cmd+q"), ("find on page", "cmd+f"),
    ("new tab", "cmd+t"), ("close the tab", "cmd+w"),
    ("save with keyboard", "cmd+s"), ("print", "cmd+p"),
    ("go back", "alt+left"), ("page down", "pagedown"),
    ("scroll to top", "home"), ("scroll to bottom", "end"),
]

VERBS_CLICK = [Verb.CLICK]

# ---- real-web archetype vocab ---------------------------------------------
SHOP_ACTIONS = ["Add to Cart", "Buy Now", "Add to Bag", "Checkout",
                "Apply Coupon", "Update Quantity", "Save for Later",
                "Add to Wishlist", "Remove", "Continue Shopping",
                "Place Order", "Track Package", "Write a Review"]
SHOP_FIELDS = ["Size", "Color", "Quantity", "Shipping Address", "Card Number",
               "Expiry", "CVV", "Promo Code", "Zip Code", "Gift Message"]
SOCIAL_ACTIONS = ["Like", "Comment", "Share", "Repost", "Follow", "Unfollow",
                  "Bookmark", "Mute", "Block", "Report", "Subscribe",
                  "Join", "Leave", "Pin", "React"]
MAIL_ACTIONS = ["Compose", "Reply", "Reply All", "Forward", "Archive",
                "Mark as Read", "Mark as Unread", "Star", "Snooze",
                "Move to Spam", "Move to Inbox", "Empty Trash", "Attach"]
FILE_NAMES = ["report.pdf", "photo.jpg", "notes.txt", "backup.zip",
              "presentation.key", "budget.xlsx", "readme.md", "archive.tar",
              "screenshot.png", "contract.docx", "song.mp3", "video.mov"]
TABLE_COLS = ["Name", "Date", "Status", "Size", "Owner", "Amount",
              "Priority", "Modified", "Type", "Score", "Price", "Updated"]
CONSENT_NAMES = ["Accept All", "Accept Cookies", "Reject All", "Manage",
                 "Preferences", "Necessary Only", "Agree", "Dismiss"]
PLAYER_ACTIONS = ["Play", "Pause", "Mute", "Unmute", "Skip", "Replay",
                  "Fullscreen", "Next Episode", "Volume", "Speed", "Captions"]
CHAT_ACTIONS = ["Send", "New Chat", "Attach", "Emoji", "Voice Message",
                "Edit", "Delete", "Pin", "Search", "Archive", "Mute"]
ORDINALS = ["first", "second", "third", "fourth", "top", "last", "next"]
COLOR_ATTRS = ["green", "red", "blue", "orange", "purple", "gray"]
CASUAL_PATTERNS = [
    "wanna {v} {t}", "get me to {t}", "open up {t}", "could you {v} {t}",
    "can you {v} the {t}", "please {v} {t}", "go ahead and {v} {t}",
    "{v} {t} please", "hey {v} {t}", "let's {v} {t}", "need to {v} {t}",
    "just {v} {t}", "{t}", "{v} it", "quick {v} {t}",
]
ZONE_REGIONS = {"nav": (0, 90), "main": (90, 760), "side": (700, 960),
                "foot": (760, 980)}


@dataclass
class Sample:
    obs: NormalizedObservation
    candidates: list[Action]
    correct_idx: Optional[int]      # None = abstain
    kind: str                       # debug/analysis tag
    gold_arg: str = ""


def _el(role: str, name: str, i: int, rng: random.Random,
        value: str = "", w: int = 1600, h: int = 1000) -> Element:
    return Element(
        id=f"e{i}", role=role, name=name, value=value,
        bounds=Bounds(rng.uniform(0, w - 200), rng.uniform(0, h - 60),
                      rng.uniform(60, 300), rng.uniform(24, 60)),
        enabled=rng.random() > 0.06, focused=rng.random() < 0.05,
        children_count=rng.randint(0, 4), depth=rng.randint(1, 6))


def _screen(rng: random.Random, n_extra: int = 0) -> tuple[list[Element], int]:
    """A plausible background screen of elements; returns (elements, next_i)."""
    els: list[Element] = []
    i = 0
    archetype = rng.choice(["dialog", "form", "toolbar", "browser",
                            "settings", "editor", "list"])
    if archetype == "dialog":
        for nm in rng.sample(OK_NAMES + CANCEL_NAMES + SAVE_NAMES,
                             min(3, rng.randint(2, 3))):
            els.append(_el("button", nm, i, rng)); i += 1
        els.append(_el("statictext",
                       rng.choice(["Are you sure?", "Unsaved changes",
                                   "This action cannot be undone",
                                   "Do you want to continue?"]),
                       i, rng)); i += 1
    elif archetype == "form":
        for nm in rng.sample(FIELD_NAMES, rng.randint(2, 5)):
            els.append(_el("textfield", nm, i, rng,
                           value=rng.choice(["", rng.choice(TYPE_WORDS)])))
            i += 1
        els.append(_el("button", rng.choice(SEND_NAMES + OK_NAMES), i, rng))
        i += 1
    elif archetype == "toolbar":
        for nm in rng.sample(NAV_ITEMS, rng.randint(4, 8)):
            els.append(_el("button", nm, i, rng)); i += 1
    elif archetype == "browser":
        els.append(_el("button", "Back", i, rng)); i += 1
        els.append(_el("button", "Forward", i, rng)); i += 1
        els.append(_el("button", "Reload", i, rng)); i += 1
        els.append(_el("searchfield", "Address", i, rng)); i += 1
        for nm in rng.sample(NAV_ITEMS + ["Sign In", "Download", "Read More"],
                             rng.randint(2, 6)):
            els.append(_el(rng.choice(["link", "button"]), nm, i, rng)); i += 1
    elif archetype == "settings":
        for nm in rng.sample(TOGGLE_NAMES, rng.randint(3, 7)):
            els.append(_el(rng.choice(["checkbox", "switch"]), nm, i, rng))
            i += 1
        for nm in rng.sample(COMBO_NAMES, rng.randint(1, 3)):
            els.append(_el("combobox", nm, i, rng)); i += 1
    elif archetype == "editor":
        els.append(_el("textarea", "Document", i, rng,
                       value=rng.choice(TYPE_WORDS))); i += 1
        for nm in rng.sample(NAV_ITEMS + SAVE_NAMES, rng.randint(3, 6)):
            els.append(_el(rng.choice(["button", "menuitem"]), nm, i, rng))
            i += 1
    else:  # list
        for j in range(rng.randint(3, 8)):
            els.append(_el("listitem", rng.choice(NAV_ITEMS + TABS), i, rng))
            i += 1
        els.append(_el("scrollarea", "", i, rng)); i += 1
    # unrelated distractors
    for _ in range(n_extra):
        els.append(_el(rng.choice(["statictext", "image", "group", "button",
                                   "menuitem", "link"]),
                       rng.choice(NAV_ITEMS + FIELD_NAMES + [""]), i, rng))
        i += 1
    rng.shuffle(els)
    for j, e in enumerate(els):
        e.id = f"e{j}"
    return els, len(els)


def _zone_el(role: str, name: str, i: int, rng: random.Random,
             zone: str = "main") -> Element:
    """Element placed in a realistic screen zone (nav/main/side/foot)."""
    y0, y1 = ZONE_REGIONS[zone]
    e = Element(
        id=f"e{i}", role=role, name=name,
        bounds=Bounds(rng.uniform(0, 1450), rng.uniform(y0, y1),
                      rng.uniform(50, 280), rng.uniform(22, 56)),
        enabled=rng.random() > 0.06, focused=rng.random() < 0.05,
        children_count=rng.randint(0, 4), depth=rng.randint(1, 6))
    return e


def _screen2(rng: random.Random) -> tuple[list[Element], int]:
    """Real-web archetypes: ecommerce, social, mail, files, table, login,
    consent banner, player, chat, kanban, wizard, tabstrip, radio group,
    menu bar. Frequently mixed with the classic archetypes via gen_sample."""
    els: list[Element] = []
    i = 0
    arch = rng.choice([
        "shop", "social", "mail", "files", "table", "login", "consent",
        "player", "chat", "kanban", "wizard", "tabstrip", "radio", "menubar"])
    if arch == "shop":
        for nm in rng.sample(SHOP_ACTIONS, rng.randint(3, 7)):
            els.append(_zone_el("button", nm, i, rng)); i += 1
        for nm in rng.sample(SHOP_FIELDS, rng.randint(1, 4)):
            r = rng.choice(["combobox", "textfield", "stepper"])
            els.append(_zone_el(r, nm, i, rng)); i += 1
        els.append(_zone_el("link", "See all reviews", i, rng)); i += 1
        els.append(_zone_el("heading", rng.choice(
            ["Classic Hoodie", "Wireless Mouse", "Desk Lamp", "Sneakers"]),
            i, rng)); i += 1
    elif arch == "social":
        for nm in rng.sample(SOCIAL_ACTIONS, rng.randint(4, 8)):
            els.append(_zone_el("button", nm, i, rng)); i += 1
        els.append(_zone_el("textfield", "Write a comment", i, rng)); i += 1
        els.append(_zone_el("link", rng.choice(
            ["@friend", "#topic", "View profile"]), i, rng)); i += 1
    elif arch == "mail":
        for nm in rng.sample(MAIL_ACTIONS, rng.randint(4, 8)):
            els.append(_zone_el(rng.choice(["button", "menuitem"]), nm, i, rng))
            i += 1
        for _ in range(rng.randint(2, 5)):
            els.append(_zone_el("row", rng.choice(
                ["Invoice from Acme", "Weekly digest", "Team standup",
                 "Your receipt", "Invitation", "Security alert"]), i, rng))
            i += 1
        els.append(_zone_el("searchfield", "Search mail", i, rng,
                            zone="nav")); i += 1
    elif arch == "files":
        for nm in rng.sample(FILE_NAMES, rng.randint(4, 9)):
            els.append(_zone_el(rng.choice(["listitem", "treeitem", "cell"]),
                                nm, i, rng)); i += 1
        els.append(_zone_el("button", rng.choice(
            ["New Folder", "Upload", "Download", "Get Info", "Rename"]),
            i, rng)); i += 1
        els.append(_zone_el("searchfield", "Search files", i, rng,
                            zone="nav")); i += 1
    elif arch == "table":
        for nm in rng.sample(TABLE_COLS, rng.randint(3, 5)):
            els.append(_zone_el("column", nm, i, rng, zone="nav")); i += 1
        for _ in range(rng.randint(3, 7)):
            els.append(_zone_el("row", rng.choice(
                ["Order #1024", "Ticket Z-55", "User alice", "Item 42",
                 "Build #918", "Customer ACME"]), i, rng)); i += 1
    elif arch == "login":
        els.append(_zone_el("textfield", rng.choice(
            ["Email", "Username", "Email or phone"]), i, rng)); i += 1
        els.append(_zone_el("securetextfield", "Password", i, rng)); i += 1
        els.append(_zone_el("button", rng.choice(
            ["Sign In", "Log In", "Continue", "Sign in with SSO"]),
            i, rng)); i += 1
        els.append(_zone_el("link", "Forgot password?", i, rng)); i += 1
        els.append(_zone_el("checkbox", "Remember me", i, rng)); i += 1
    elif arch == "consent":
        for nm in rng.sample(CONSENT_NAMES, rng.randint(2, 4)):
            els.append(_zone_el("button", nm, i, rng, zone="foot")); i += 1
        els.append(_zone_el("statictext",
                            "We use cookies to improve your experience",
                            i, rng, zone="foot")); i += 1
    elif arch == "player":
        for nm in rng.sample(PLAYER_ACTIONS, rng.randint(4, 7)):
            els.append(_zone_el(rng.choice(["button", "slider"]), nm,
                                i, rng, zone="foot")); i += 1
        els.append(_zone_el("progress", "", i, rng, zone="foot")); i += 1
    elif arch == "chat":
        for nm in rng.sample(CHAT_ACTIONS, rng.randint(3, 6)):
            els.append(_zone_el("button", nm, i, rng)); i += 1
        els.append(_zone_el("textarea", "Message", i, rng, zone="foot"))
        i += 1
        for _ in range(rng.randint(2, 5)):
            els.append(_zone_el("listitem", rng.choice(
                ["Alice", "Bob", "Team channel", "#general", "Support"]),
                i, rng, zone="side")); i += 1
    elif arch == "kanban":
        for nm in rng.sample(["To Do", "In Progress", "Review", "Done"],
                             rng.randint(2, 4)):
            els.append(_zone_el("column", nm, i, rng, zone="nav")); i += 1
        for _ in range(rng.randint(3, 8)):
            els.append(_zone_el("listitem", rng.choice(
                ["Fix login bug", "Write docs", "Design mockup",
                 "Ship v2", "Review PR", "Update deps"]), i, rng)); i += 1
        els.append(_zone_el("button", "Add card", i, rng, zone="foot"))
        i += 1
    elif arch == "wizard":
        for nm in rng.sample(["Account", "Profile", "Payment", "Review",
                              "Finish"], rng.randint(2, 4)):
            els.append(_zone_el("tab", nm, i, rng, zone="nav")); i += 1
        els.append(_zone_el("button", rng.choice(["Next", "Continue",
                                                  "Previous"]), i, rng))
        i += 1
        for nm in rng.sample(FIELD_NAMES, rng.randint(1, 3)):
            els.append(_zone_el("textfield", nm, i, rng)); i += 1
    elif arch == "tabstrip":
        for nm in rng.sample(TABS + ["Unread", "Mentions", "Starred",
                                     "Archived"], rng.randint(3, 6)):
            els.append(_zone_el("tab", nm, i, rng, zone="nav")); i += 1
        for _ in range(rng.randint(2, 6)):
            els.append(_zone_el("listitem", rng.choice(
                NAV_ITEMS + FILE_NAMES), i, rng)); i += 1
    elif arch == "radio":
        group = rng.choice(["Delivery", "Payment method", "Plan",
                            "Size", "Theme"])
        for nm in rng.sample(["Standard", "Express", "Free", "Pro",
                              "Team", "Basic", "Small", "Large"], 3):
            els.append(_zone_el("radio", nm, i, rng)); i += 1
        els.append(_zone_el("radiogroup", group, i, rng)); i += 1
        els.append(_zone_el("button", rng.choice(OK_NAMES), i, rng)); i += 1
    else:  # menubar
        for nm in rng.sample(["File", "Edit", "View", "Window", "Help",
                              "Format", "Tools"], rng.randint(3, 6)):
            els.append(_zone_el("menubutton", nm, i, rng, zone="nav"))
            i += 1
        for nm in rng.sample(SAVE_NAMES + CANCEL_NAMES + OPEN_NAMES,
                             rng.randint(2, 4)):
            els.append(_zone_el("menuitem", nm, i, rng)); i += 1
    if rng.random() < 0.45:
        els.append(_zone_el("scrollarea", "", len(els), rng))
    rng.shuffle(els)
    for j, e in enumerate(els):
        e.id = f"e{j}"
    return els, len(els)


# dense-page name pools: long, unicode, numeric, a11y-style, like real DOMs
DENSE_LINKS = [
    "Download the app on Google Play", "Install for iOS", "Read more",
    "Privacy policy", "Terms of service", "Contact us", "About us",
    "Čeština", "", "Deutsch", "Español", "Français", "한국어",
    "1,210", "23,576", "[45]", "[12]", "†", "edit", "view source",
    "Christopher J.C.H. Watkins", "Biorobotics", "Hardware security",
    "Knowsley Hall shootings", "World model (artificial intelligence)",
    "Paul Hunter", "2024 Summer Olympics", "Ancient Rome", "DNA",
    "Learn how to contribute", "See all events", "Show preview",
    "permalink", "Get shortened URL", "Cite this page", "Special pages",
    "Block hidden trackers in emails", "Browser Extensions",
    "choose DuckDuckGo over Chrome and other browsers",
    "iOS Browser", "Mac Browser", "Windows Browser", "Themes",
    "Order #1024", "Ticket Z-55", "User alice_92", "Build #918",
    "release-v2.4.1", "hotfix/security-patch", "PR #1042",
    "Reinforcement learning: An introduction", "artificial intelligence",
]
DENSE_BUTTONS = [
    "Search", "Go", "Apply", "Submit", "Load more", "Show all",
    "Accept all cookies", "Manage preferences", "Sign in", "Join now",
    "Try it Yourself", "Run »", "Buy", "Donate", "Share", "More",
    "Log in", "Create account", "Download", "Print", "Export",
]
DENSE_TEXTS = [
    "Search Wikipedia", "Search", "Email", "Username", "Password",
    "Enter your question", "Find a repository", "Search mail",
    "First name", "Last name", "Company", "Street address",
]


def _screen3(rng: random.Random) -> tuple[list[Element], int]:
    """Dense real-web page: nav links + big content body + footer —
    40-140 elements, heavy same-role distractors, unicode/numeric names."""
    els: list[Element] = []
    i = 0
    # nav row: 5-10 links/buttons at the top
    for nm in rng.sample(DENSE_LINKS, rng.randint(4, 8)):
        e = _zone_el("link", nm, i, rng, zone="nav"); i += 1
        els.append(e)
    for nm in rng.sample(DENSE_BUTTONS, rng.randint(0, 3)):
        els.append(_zone_el("button", nm, i, rng, zone="nav")); i += 1
    if rng.random() < 0.8:
        els.append(_zone_el("searchfield", rng.choice(DENSE_TEXTS),
                            i, rng, zone="nav")); i += 1
    # main body: long lists of links / rows / items
    n_main = rng.randint(20, 80)
    kinds = rng.sample(["link", "link", "listitem", "row", "menuitem"],
                       rng.randint(1, 3))
    names = DENSE_LINKS + [f"{rng.randint(1,99999):,}" for _ in range(8)] + \
        [f"{rng.choice(['et al.', 'Inc.', 'LLC'])} "
         f"{rng.choice(['Alpha','Beta','Gamma','Delta'])}" for _ in range(4)]
    for _ in range(n_main):
        r = rng.choice(kinds)
        nm = rng.choice(names) if rng.random() < 0.9 else ""
        els.append(_zone_el(r, nm, i, rng)); i += 1
    # scatter interactive furniture
    for _ in range(rng.randint(2, 8)):
        r = rng.choice(["button", "checkbox", "tab", "heading", "image"])
        nm = rng.choice(DENSE_BUTTONS + DENSE_LINKS) if r != "image" else ""
        els.append(_zone_el(r, nm, i, rng)); i += 1
    # footer
    for nm in rng.sample(DENSE_LINKS[:12], rng.randint(3, 8)):
        els.append(_zone_el("link", nm, i, rng, zone="foot")); i += 1
    if rng.random() < 0.5:
        els.append(_zone_el("scrollarea", "", i, rng)); i += 1
    rng.shuffle(els)
    for j, e in enumerate(els):
        e.id = f"e{j}"
    return els, len(els)


def _obs(els: list[Element], rng: random.Random,
         browser: bool = False) -> NormalizedObservation:
    obs = NormalizedObservation(platform=Platform.MACOS,
                                screen_w=1600, screen_h=1000)
    obs.elements = els
    if browser:
        obs.browser = BrowserState(
            url="https://" + rng.choice(DOMAINS) + "/page",
            title=rng.choice(TABS), dom_available=True,
            tabs=[{"id": f"t{i}", "title": t}
                  for i, t in enumerate(rng.sample(TABS, 3))])
    return obs


# ---------------------------------------------------------------- goals
def _pick_named(els, pool, rng):
    """Pick a target; when several candidates share its name the goal can
    only mean the topmost one — deterministic ground truth, learnable."""
    j = rng.choice(pool)
    same = [k for k in pool if els[k].name == els[j].name]
    if len(same) > 1:
        j = min(same, key=lambda k: (els[k].bounds.y if els[k].bounds else 0,
                                     els[k].bounds.x if els[k].bounds else 0))
    return els[j]


def _find(els: list[Element], pred) -> list[int]:
    return [i for i, e in enumerate(els) if pred(e)]


def gen_sample(rng: random.Random) -> Sample:
    """One synthetic decision. ~50% click targets, rest spread over verbs."""
    browser = rng.random() < 0.45
    pick = rng.random()
    if pick < 0.30:                      # dense real-web pages
        els, _ = _screen3(rng)
        if rng.random() < 0.4:
            extra, _ = _screen2(rng)
            els = els + extra[:rng.randint(2, 8)]
            rng.shuffle(els)
            for j, e in enumerate(els):
                e.id = f"e{j}"
    elif pick < 0.70:
        els, _ = _screen2(rng)
        if rng.random() < 0.35:  # mixed screens: classic bg + real-web fg
            extra, _ = _screen(rng, n_extra=0)
            els = els + extra[:rng.randint(2, 6)]
            rng.shuffle(els)
            for j, e in enumerate(els):
                e.id = f"e{j}"
        els += [_el(rng.choice(["statictext", "image", "group"]),
                    rng.choice(["", rng.choice(NAV_ITEMS)]), len(els), rng)
                for _ in range(rng.randint(0, 3))]
    else:
        els, _ = _screen(rng, n_extra=rng.randint(0, 4))
    for j, e in enumerate(els):
        e.id = f"e{j}"
    obs = _obs(els, rng, browser=browser)

    r = rng.random()
    ord_boost = gen_sample._ord_boost
    if ord_boost and rng.random() < ord_boost:
        r = 0.983                       # positional band
    drag_boost = gen_sample._drag_boost
    if drag_boost and rng.random() < drag_boost and \
            len(_find(els, lambda e: e.role in
                      ("listitem", "treeitem", "row", "cell", "image", "tab")
                      and e.name)) >= 2:
        r = 0.958
    # ---- abstain cases ------------------------------------------------
    if r < 0.08:
        goal = rng.choice([
            f"click the {rng.choice(NAV_ITEMS)}xplode button",
            f"press the {rng.choice(FIELD_NAMES)} teleport key",
            f"enable {rng.choice(TOGGLE_NAMES)} warp drive",
            f"open {rng.choice(WINDOWS)} quantum editor",
            f"type something into the {rng.choice(FIELD_NAMES)} transporter",
            # ungroundable visual attributes — the AX/DOM layer cannot see
            # colour or style, so the honest answer is abstain (vision's job)
            f"click the {rng.choice(COLOR_ATTRS)} button",
            f"click the {rng.choice(COLOR_ATTRS)} icon in the corner",
            f"press the glowing {rng.choice(NAV_ITEMS)} button",
        ])
        if "xplode" not in goal and "teleport" not in goal and \
                "warp" not in goal and "quantum" not in goal and \
                "transporter" not in goal:
            pass  # attribute abstains need no numeric salt
        else:
            goal += f" {rng.randint(99,999)}"
        obs.goal = goal
        cands = candidate_actions(obs)
        return Sample(obs, cands, None, "abstain-absent")

    # ---- goal archetypes -----------------------------------------------
    goal, verb, target_pred, arg = "", Verb.CLICK, None, ""

    if r < 0.22:  # click named target
        names = SAVE_NAMES + OK_NAMES + CANCEL_NAMES + OPEN_NAMES + \
            SEND_NAMES + DELETE_NAMES + UNDO_NAMES + NAV_ITEMS
        tgt = rng.choice(names)
        pool = _find(els, lambda e: e.name.lower() == tgt.lower())
        if not pool:
            tgt = next((e.name for e in els if e.role in
                        ("button", "link", "menuitem") and e.name), None)
            if tgt is None:
                return gen_sample(rng)
            pool = _find(els, lambda e: e.name == tgt)
        target_pred = lambda e: e.name == tgt
        goal = rng.choice([
            f"click the {tgt} button", f"press {tgt}", f"click {tgt}",
            f"tap {tgt}", f"hit the {tgt} button", f"choose {tgt}",
            f"activate {tgt}", f"select the {tgt} option",
        ])
        verb = Verb.CLICK
    elif r < 0.32:  # semantic click (save/confirm/close/send/open/delete/undo)
        kind = rng.choice(["save", "confirm", "cancel", "send", "open",
                           "delete", "undo"])
        pools = {"save": SAVE_NAMES, "confirm": OK_NAMES,
                 "cancel": CANCEL_NAMES, "send": SEND_NAMES,
                 "open": OPEN_NAMES, "delete": DELETE_NAMES,
                 "undo": UNDO_NAMES}
        names = pools[kind]
        word = {"save": "save", "confirm": "confirm", "cancel": "cancel",
                "send": "send", "open": "open", "delete": "delete",
                "undo": "undo"}[kind]
        noun = rng.choice(NOUNS)
        goal = rng.choice([
            f"{word} the {noun}", f"{word} it",
            f"{word} the current {noun}", f"{word} now",
            f"please {word} the {noun}",
        ])
        target_pred = lambda e: e.name.lower() in [n.lower() for n in names]
        verb = Verb.CLICK
    elif r < 0.44:  # type into a field
        field = rng.choice(FIELD_NAMES)
        text = rng.choice(TYPE_WORDS)
        verb = Verb.TYPE
        arg = text
        target_pred = lambda e: (e.role in ("textfield", "searchfield",
                                            "textarea", "combobox")
                                 and field.lower() in e.name.lower()) or \
            (field.lower() in e.name.lower() and e.role == "textfield")
        goal = rng.choice([
            f'type "{text}" into the {field} field',
            f'enter "{text}" in {field}',
            f'fill in {field} with "{text}"',
            f'write "{text}" into {field}',
            f'set the {field} to "{text}"',
        ])
        # usually an answerable target: inject the named field if absent
        if not _find(els, target_pred) and rng.random() < 0.8:
            els.append(_el(rng.choice(
                ["textfield", "searchfield", "textarea"]), field,
                len(els), rng))
            obs.elements = els
    elif r < 0.52:  # keypress
        key_goals = KEY_GOALS
        if browser:
            key_goals = [(tpl, keys) for tpl, keys in KEY_GOALS
                         if tpl not in ("new tab", "close the tab", "go back")]
        tpl, keys = rng.choice(key_goals)
        goal = tpl.format(k=keys.replace("cmd", "command") if "cmd" in keys else keys)
        verb = Verb.KEYPRESS
        arg = keys
    elif r < 0.60:  # toggle / checkbox
        tgt = rng.choice(TOGGLE_NAMES)
        target_pred = lambda e: tgt.lower() in e.name.lower() and \
            e.role in ("checkbox", "switch", "toggle")
        if not _find(els, target_pred) and rng.random() < 0.6:
            els.append(_el("checkbox", tgt, len(els), rng))
            obs.elements = els
        style = rng.random()
        if style < 0.45:          # explicit check/uncheck phrasing -> CHECK
            verb = Verb.CHECK
            goal = rng.choice([
                f"check the {tgt} box", f"tick {tgt}",
                f"uncheck {tgt}", f"check {tgt}",
                f"mark the {tgt} checkbox",
            ])
        else:                     # enable/toggle phrasing -> plain CLICK
            verb = Verb.CLICK
            goal = rng.choice([
                f"enable {tgt}", f"turn on {tgt}", f"toggle {tgt}",
                f"activate {tgt}", f"switch on {tgt}",
            ])
    elif r < 0.66:  # select option
        tgt = rng.choice(COMBO_NAMES)
        opt = rng.choice(["High", "Low", "English", "Dark", "Compact",
                          "Weekly", "1080p", "Latest"])
        target_pred = lambda e: tgt.lower() in e.name.lower() and \
            e.role in ("combobox", "select", "popupbutton")
        if not _find(els, target_pred) and rng.random() < 0.6:
            els.append(_el("combobox", tgt, len(els), rng))
            obs.elements = els
        verb = Verb.SELECT
        arg = opt
        goal = rng.choice([
            f"set {tgt} to {opt}", f"choose {opt} for {tgt}",
            f"change {tgt} to {opt}", f"pick {opt} in the {tgt} dropdown",
        ])
    elif r < 0.72:  # scroll
        scrollable = _find(els, lambda e: e.role == "scrollarea")
        direction = rng.choice(["down", "up"])
        if scrollable:
            target_pred = lambda e: e.role == "scrollarea"
            verb = Verb.SCROLL
            arg = direction
            goal = rng.choice([
                f"scroll {direction} the list", f"scroll {direction}",
                f"scroll the page {direction}", f"swipe {direction}",
            ])
        else:
            verb = Verb.KEYPRESS
            arg = "pagedown" if direction == "down" else "pageup"
            goal = rng.choice([f"scroll {direction}", f"page {direction}",
                               f"go {direction} the page"])
    elif r < 0.78:  # wait / done
        if rng.random() < 0.5:
            verb = Verb.WAIT
            goal = rng.choice(["wait for the page to load", "wait a moment",
                               "pause briefly", "hold on", "wait"])
        else:
            verb = Verb.DONE
            goal = rng.choice(["the task is complete", "nothing else needed",
                               "you are finished", "finish up", "done"])
    elif r < 0.90 and browser:  # browser verbs
        bverb = rng.choice([Verb.NAVIGATE, Verb.BACK, Verb.FORWARD,
                            Verb.REFRESH, Verb.NEW_TAB, Verb.SWITCH_TAB])
        verb = bverb
        if bverb == Verb.NAVIGATE:
            arg = rng.choice(DOMAINS)
            goal = rng.choice([f"go to {arg}", f"navigate to {arg}",
                               f"open {arg}", f"visit {arg}"])
        elif bverb == Verb.SWITCH_TAB:
            tab = rng.choice(obs.browser.tabs)
            arg = tab["id"]
            goal = rng.choice([f"switch to the {tab['title']} tab",
                               f"open the {tab['title']} tab",
                               f"go to tab {tab['title']}"])
        else:
            goal = {Verb.BACK: rng.choice(["go back", "previous page",
                                           "navigate back"]),
                    Verb.FORWARD: rng.choice(["go forward", "next page"]),
                    Verb.REFRESH: rng.choice(["refresh the page", "reload",
                                              "reload the page"]),
                    Verb.NEW_TAB: rng.choice(["open a new tab", "new tab"])}[bverb]
    elif r < 0.94:  # focus field
        pool = _find(els, lambda e: e.role in
                     ("textfield", "searchfield", "textarea"))
        if not pool:
            return gen_sample(rng)
        tgt = els[pool[0]]
        target_pred = lambda e: e.id == tgt.id
        verb = Verb.FOCUS
        goal = rng.choice([f"focus the {tgt.name or 'text'} field",
                           f"click into {tgt.name or 'the text field'}",
                           f"put the cursor in {tgt.name or 'the field'}"])
    elif r < 0.955:  # double-click (open files/items)
        pool = _find(els, lambda e: e.role in
                     ("listitem", "treeitem", "cell", "row", "image")
                     and e.name)
        if not pool:
            return gen_sample(rng)
        tgt = _pick_named(els, pool, rng)
        target_pred = lambda e: e.id == tgt.id
        verb = Verb.DOUBLE_CLICK
        goal = rng.choice([
            f"double-click {tgt.name}", f"double click on {tgt.name}",
            f"open {tgt.name} by double-clicking",
            f"double-click the {tgt.name} file",
        ])
    elif r < 0.965:  # drag src -> dst
        pool = _find(els, lambda e: e.role in
                     ("listitem", "treeitem", "row", "cell", "image", "tab")
                     and e.name)
        if len(pool) < 2:
            return gen_sample(rng)
        src_i, dst_i = rng.sample(pool, 2)
        src, dst = els[src_i], els[dst_i]
        # when several elements share the source name the goal can only
        # mean the first/topmost one — deterministic label, not a coin flip
        same = [j for j in pool if els[j].name == src.name]
        if len(same) > 1:
            top = min(same, key=lambda j: (els[j].bounds.y if els[j].bounds
                                           else 0,
                                           els[j].bounds.x if els[j].bounds
                                           else 0))
            src = els[top]
        target_pred = lambda e: e.id == src.id
        verb = Verb.DRAG
        goal = rng.choice([
            f"drag {src.name} onto {dst.name}",
            f"move {src.name} to {dst.name}",
            f"drag the {src.name} item over {dst.name}",
            f"reorder {src.name} before {dst.name}",
        ])
    elif r < 0.98:  # right-click / context menu
        pool = _find(els, lambda e: e.name and e.role in
                     ("listitem", "treeitem", "cell", "row", "image",
                      "button", "link"))
        if not pool:
            return gen_sample(rng)
        tgt = _pick_named(els, pool, rng)
        target_pred = lambda e: e.id == tgt.id
        verb = Verb.RIGHT_CLICK
        goal = rng.choice([
            f"right-click {tgt.name}", f"open the context menu on {tgt.name}",
            f"right click on {tgt.name}",
        ])
    elif r < 0.987:  # positional reference (ordinal among matching role)
        kind, roles = rng.choice([
            ("tab", ("tab",)), ("link", ("link",)),
            ("item", ("listitem", "treeitem")),
            ("result", ("link", "listitem")),
            ("row", ("row", "cell")), ("card", ("listitem",)),
            ("menu item", ("menuitem",)),
            ("button", ("button",))])
        pool = sorted(_find(els, lambda e: e.role in roles and e.name),
                      key=lambda j: (els[j].bounds.y if els[j].bounds else 0,
                                     els[j].bounds.x if els[j].bounds else 0))
        if not pool:
            return gen_sample(rng)
        style = rng.random()
        if style < 0.25 and len(pool) >= 2:      # last / bottom
            tgt = els[pool[-1]]
            goal = rng.choice([
                f"click the last {kind}", f"open the bottom {kind}",
                f"select the last {kind} on the page",
            ])
        elif style < 0.5 and len(pool) >= 2:     # named position
            tgt = els[pool[0]]
            goal = rng.choice([
                f"click the {kind} at the top",
                f"open the topmost {kind}",
                f"click the first {kind} in the list",
            ])
        else:
            ord_idx = rng.randrange(min(len(pool), 3))
            tgt = els[pool[ord_idx]]
            ord_name = ["first", "second", "third"][ord_idx]
            goal = rng.choice([
                f"click the {ord_name} {kind}",
                f"open the {ord_name} {kind}",
                f"select the {ord_name} {kind} on the page",
            ])
        target_pred = lambda e: e.id == tgt.id
        verb = Verb.CLICK
    elif r < 0.995:  # radio option pick
        pool = _find(els, lambda e: e.role == "radio" and e.name)
        if not pool:
            return gen_sample(rng)
        tgt = _pick_named(els, pool, rng)
        target_pred = lambda e: e.id == tgt.id
        verb = Verb.CLICK
        goal = rng.choice([
            f"choose the {tgt.name} option", f"select {tgt.name}",
            f"pick {tgt.name}", f"choose {tgt.name}",
        ])
    else:  # generic click on any actionable named element
        pool = _find(els, lambda e: e.name and e.role in
                     ("button", "link", "menuitem", "tab", "listitem"))
        if not pool:
            return gen_sample(rng)
        tgt = _pick_named(els, pool, rng)
        target_pred = lambda e: e.id == tgt.id
        verb = Verb.CLICK
        goal = rng.choice([f"click {tgt.name}", f"press {tgt.name}",
                           f"open {tgt.name}", f"select {tgt.name}"])

    # ---- ambiguity case: two matching targets ---------------------------
    ambiguous = False
    if rng.random() < 0.06 and target_pred is not None:
        matches = _find(els, target_pred)
        if len(matches) == 1:
            dup = Element(**{**els[matches[0]].__dict__})
            dup.id = f"e{len(els)}"
            dup.bounds = Bounds(rng.uniform(0, 1400), rng.uniform(0, 900),
                                dup.bounds.w if dup.bounds else 80,
                                dup.bounds.h if dup.bounds else 30)
            els.append(dup)
            obs.elements = els
            ambiguous = True

    obs.goal = goal
    cands = candidate_actions(obs)
    correct_idx = _label(cands, obs, verb, target_pred, arg)
    kind = "ambiguous" if ambiguous else "semantic"
    if correct_idx is None and not ambiguous:
        kind = "abstain-implicit"
    return Sample(obs, cands, correct_idx, kind, gold_arg=str(arg))


def _label(cands: list[Action], obs: NormalizedObservation,
           verb: Verb, pred, arg: str) -> Optional[int]:
    if verb in (Verb.KEYPRESS, Verb.WAIT, Verb.DONE, Verb.BACK, Verb.FORWARD,
                Verb.REFRESH, Verb.NEW_TAB, Verb.NAVIGATE):
        for i, a in enumerate(cands):
            if a.verb == verb:
                if verb == Verb.NAVIGATE and a.text != "\x00ARG":
                    continue
                return i
        return None
    if verb == Verb.SWITCH_TAB:
        for i, a in enumerate(cands):
            if a.verb == verb and a.tab == arg:
                return i
        return None
    for i, a in enumerate(cands):
        if a.verb != verb or a.element_id is None:
            continue
        el = next((e for e in obs.elements if e.id == a.element_id), None)
        if el is not None and pred(el) and \
                (verb != Verb.SCROLL or a.direction == arg):
            return i
    return None


gen_sample._drag_boost = 0.0
gen_sample._ord_boost = 0.0


def generate(n: int, seed: int = 0, drag_boost: float = 0.0,
             ord_boost: float = 0.0) -> list[Sample]:
    gen_sample._drag_boost = drag_boost
    gen_sample._ord_boost = ord_boost
    rng = random.Random(seed)
    out = []
    while len(out) < n:
        try:
            out.append(gen_sample(rng))
        except (RecursionError, Exception):  # noqa: BLE001
            out.append(gen_sample(rng))
    return out
