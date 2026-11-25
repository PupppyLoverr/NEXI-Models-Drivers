"""NEXI-S1 synthetic decision data.

Task: given a goal + K typed candidate actions, score each and pick the best —
or abstain when no candidate serves the goal (the cua-s1 OOD failure mode we
explicitly train against).

Row: {"goal": str, "candidates": [{"id","action","label"}], "answer": int|-1}
-1 means ABSTAIN (no candidate is right). ~25% of rows abstain.

Difficulty knobs vs v1: goals and labels are paraphrased (so memorized word
pairs don't solve it), and each row mixes in HARD decoys — candidates that
share goal vocabulary but do the wrong thing (e.g. "Log out" vs "log in",
"Search hotels" vs "search flights"). Abstain rows are built entirely from
hard decoys, so "looks related" is not a signal.
"""
import json
import random

# goal: list of paraphrases, right candidates (id, action, label paraphrases),
# hard decoys that look goal-adjacent but are wrong.
GOALS = [
    {
        "goal": ["log in", "sign in", "log into my account", "sign into the app"],
        "right": [("input-email", "type", ["Email field", "Email input", "Email address box"]),
                  ("input-pass", "type", ["Password field", "Password input", "Password box"]),
                  ("btn-login", "click", ["Log in button", "Sign in button", "Login btn"])],
        "hard": [("btn-logout", "click", ["Log out button", "Sign out"]),
                 ("btn-reset-pass", "click", ["Forgot password", "Reset password link"]),
                 ("input-email", "type", ["Confirm email field"])],
    },
    {
        "goal": ["search for flights", "find flights", "look up plane tickets",
                 "search airline tickets"],
        "right": [("input-search", "type", ["Search box", "Flight search field", "Destination input"]),
                  ("btn-search", "click", ["Search button", "Find flights button"])],
        "hard": [("btn-hotel-search", "click", ["Search hotels button"]),
                 ("input-search", "type", ["Hotel search box"]),
                 ("link-deals", "click", ["Flight deals link"])],
    },
    {
        "goal": ["check out the cart", "checkout", "pay for my cart",
                 "complete the purchase"],
        "right": [("btn-cart", "click", ["Cart icon", "Shopping cart", "Basket icon"]),
                  ("btn-checkout", "click", ["Checkout button", "Proceed to checkout"])],
        "hard": [("btn-empty-cart", "click", ["Empty cart", "Clear basket"]),
                 ("btn-continue", "click", ["Continue shopping"]),
                 ("link-wishlist", "click", ["Save to wishlist"])],
    },
    {
        "goal": ["play music", "start the music", "play a song", "play some tunes"],
        "right": [("btn-play", "click", ["Play", "Play button", "Play track"]),
                  ("card-song", "click", ["Song card", "Track tile", "Song item"])],
        "hard": [("btn-pause", "click", ["Pause", "Pause button"]),
                 ("btn-stop", "click", ["Stop playback"]),
                 ("vol-slider", "click", ["Volume slider"])],
    },
    {
        "goal": ["open settings", "go to settings", "open the settings page",
                 "configure the app"],
        "right": [("btn-settings", "click", ["Settings gear", "Settings icon", "Gear icon"]),
                  ("menu-settings", "click", ["Settings menu item", "Settings entry"])],
        "hard": [("menu-profile", "click", ["Profile menu item", "Account settings link"]),
                 ("btn-reset", "click", ["Reset settings", "Restore defaults"]),
                 ("menu-help", "click", ["Help & settings"])],
    },
    {
        "goal": ["send an email", "compose an email", "write an email",
                 "email someone"],
        "right": [("btn-compose", "click", ["Compose", "Compose button", "New email"]),
                  ("input-to", "type", ["To field", "Recipient input", "To address box"])],
        "hard": [("btn-delete", "click", ["Delete email", "Trash message"]),
                 ("input-cc", "type", ["Cc field"]),
                 ("btn-archive", "click", ["Archive email"])],
    },
]

# v2: more served intents + abstain rows drawn from UNSERVED goals so
# "goal vocabulary seen in training" is not the abstain signal.
GOALS += [
    {"goal": ["remove the item from my basket", "delete the cart item",
              "get rid of this item"],
     "right": [("btn-remove", "click", ["Remove", "Delete item", "Remove from cart"]),
               ("btn-move-wish", "click", ["Move to wishlist"])],
     "hard": [("link-keep", "click", ["Keep shopping"]),
              ("btn-update", "click", ["Update quantity"])]},
    {"goal": ["mute the audio", "stop the sound", "silence the video"],
     "right": [("btn-mute", "click", ["Mute", "Mute audio", "Sound off"])],
     "hard": [("btn-volup", "click", ["Volume +", "Louder"]),
              ("link-cc", "click", ["Captions", "Subtitles"])]},
    {"goal": ["download the document", "save a copy", "export the file",
              "grab a copy of the document"],
     "right": [("btn-dl", "click", ["Download", "Export", "Download file"]),
               ("link-save", "click", ["Save as"])],
     "hard": [("link-preview", "click", ["Preview"]),
              ("btn-print2", "click", ["Print document"])]},
    {"goal": ["talk to support", "contact support", "chat with an agent",
              "start a conversation with support"],
     "right": [("btn-chat", "click", ["Chat with us", "Support chat"]),
               ("link-phone", "click", ["Call us", "Phone support"])],
     "hard": [("link-faq", "click", ["FAQ", "Help articles"]),
              ("btn-ticket", "click", ["Submit ticket"])]},
    {"goal": ["reply to the message", "write back", "respond to this"],
     "right": [("btn-reply", "click", ["Reply", "Reply to sender"])],
     "hard": [("btn-forward", "click", ["Forward"]),
              ("btn-del-msg", "click", ["Delete message"])]},
    {"goal": ["play the video", "start the video", "watch this"],
     "right": [("btn-play-v", "click", ["Play", "Play video"])],
     "hard": [("btn-mute-v", "click", ["Mute"]),
              ("link-subs", "click", ["Subtitles"])]},
    {"goal": ["sort by price", "sort items by price", "order by price"],
     "right": [("sel-sort", "select", ["Sort by", "Sort options"])],
     "hard": [("btn-filter", "click", ["Filter"]),
              ("link-grid", "click", ["Grid view"])]},
    {"goal": ["zoom in on the map", "zoom in", "enlarge the map"],
     "right": [("btn-zin", "click", ["+", "Zoom in"])],
     "hard": [("btn-zout", "click", ["-", "Zoom out"]),
              ("link-layers", "click", ["Layers"])]},
    {"goal": ["upload a file", "upload a document", "attach a file"],
     "right": [("btn-upload", "click", ["Upload", "Attach file"])],
     "hard": [("btn-download", "click", ["Download"]),
              ("input-fname", "type", ["File name"])]},
    {"goal": ["increase the font size", "make the text bigger", "larger text"],
     "right": [("btn-fontup", "click", ["A+", "Increase font size"])],
     "hard": [("btn-fontdown", "click", ["A-", "Decrease font size"]),
              ("link-a11y", "click", ["Accessibility"])]},
]

# Goals that have NO serving candidates anywhere: abstain rows are built
# from these so the model learns "no candidate serves this goal" rather than
# "this is one of my training goals with wrong elements".
# NOTE: goals removed when an existing GENERIC/served candidate plausibly
# serves them (e.g. "print my boarding pass" vs the Print button) — those
# rows would be mislabeled abstains.
ABSENT_GOALS = [
    "book a table for dinner", "change my password", "translate this page",
    "pay with crypto", "rent a car",
    "order a pizza", "book a haircut",
    "renew my passport", "schedule a dentist appointment",
    "buy concert tickets", "adopt a pet", "file a warranty claim",
    "check the weather tomorrow", "post a job listing",
    "register to vote",
    "book a taxi",
    "verify my identity", "upgrade my plan",
    "merge the accounts", "join the webinar",
]

# Multi-step episodes: sequences of (id, action, [labels], done-description).
# Rows built from these carry step history in the goal string, e.g.
#   "search for flights [done: typed in search box]"
# and the COMPLETED elements are the hard decoys — teaching the model that
# an element matching the goal but already used is WRONG. This is the exact
# failure mode the live browser test exposed (re-clicking the search input
# after typing, picking swatches instead of add-to-cart).
EPISODES = [
    {"goal": ["search for flights", "find flights", "look up plane tickets"],
     "steps": [("input-search", "type", ["Search box", "Flight search field"], "typed the query in the search box"),
               ("btn-search", "click", ["Search button", "Find flights button"], "clicked search")]},
    {"goal": ["search the shop", "search for a product", "find wireless headphones"],
     "steps": [("input-q", "type", ["Search input", "Search the store"], "typed the query in the search input"),
               ("btn-go", "click", ["Search button", "Go"], "submitted the search")]},
    {"goal": ["add the item to cart", "add this to my cart", "put it in the basket"],
     "steps": [("swatch-color", "click", ["Red color swatch", "Colour option"], "picked the color"),
               ("btn-add-cart", "click", ["Add to cart", "Add to basket"], "added it to the cart")],
     "extra_hard": [("btn-buy-now", "click", ["Buy now"]), ("link-wish", "click", ["Add to wishlist"])]},
    {"goal": ["check out", "proceed to checkout", "pay for my order"],
     "steps": [("btn-cart", "click", ["Cart icon", "Shopping cart"], "opened the cart"),
               ("btn-checkout", "click", ["Checkout button", "Proceed to checkout"], "went to checkout"),
               ("btn-continue-pay", "click", ["Continue to payment", "Next: payment"], "continued to payment")],
     "extra_hard": [("btn-empty", "click", ["Empty cart"]), ("link-cont-shop", "click", ["Continue shopping"])]},
    {"goal": ["book the flight", "book this flight", "complete the flight booking",
              "book a flight", "book a flight from Melbourne to Delhi",
              "book a flight to Delhi", "book my flight", "book the plane ticket",
              "book a flight from Sydney to Tokyo"],
     "steps": [("input-origin", "type", ["Origin field", "From airport"], "typed the origin"),
               ("input-dest", "type", ["Destination field", "To airport"], "typed the destination"),
               ("input-date", "type", ["Departure date", "Travel date field"], "picked the dates"),
               ("btn-fsearch", "click", ["Search flights", "Find flights"], "searched flights"),
               ("card-flight", "click", ["Select", "First flight result", "Flight option card"], "picked the flight"),
               ("btn-passengers", "click", ["Continue to passengers", "Next: traveller details"], "continued to passenger details")],
     "extra_hard": [("link-deals", "click", ["Flight deals"]), ("btn-hotel", "click", ["Search hotels"])]},
    {"goal": ["fill in the passenger details", "enter the traveller details",
              "fill in my details", "complete the passenger form"],
     "steps": [("input-fname", "type", ["First name field", "First name"], "typed in First name field"),
               ("input-lname", "type", ["Last name field", "Last name"], "typed in Last name field"),
               ("input-email-p", "type", ["Email field", "Email address"], "typed in Email field"),
               ("btn-continue-pay", "click", ["Continue to payment", "Next: payment"], "continued to payment")],
     "extra_hard": [("btn-back", "click", ["Back"]), ("link-help", "click", ["Help"])]},
    {"goal": ["complete the flight booking", "book the flight", "book my flight"],
     "steps": [("input-fname", "type", ["First name", "First name field"], "typed in First name"),
               ("input-lname", "type", ["Last name", "Last name field"], "typed in Last name"),
               ("input-email-p", "type", ["Email", "Email address"], "typed in Email"),
               ("btn-continue-pay", "click", ["Continue to payment", "Continue to passengers"], "continued to payment")],
     "extra_hard": [("btn-back", "click", ["Back"]), ("input-date", "type", ["Departure date"])]},
    {"goal": ["view my orders", "open my orders", "see my order history"],
     "steps": [("link-orders", "click", ["My orders", "Order history"], "opened orders")],
     "extra_hard": [("link-account", "click", ["My account"]), ("link-returns", "click", ["Returns"])]},
]


def _episode_rows(rng, n):
    rows = []
    for _ in range(n):
        ep = rng.choice(EPISODES)
        goal = rng.choice(ep["goal"])
        k = 0 if rng.random() < 0.4 else rng.randrange(len(ep["steps"]))
        cid, act, labels, done_desc = ep["steps"][k]
        right = {"id": cid, "action": act,
                   "label": labels[0] if rng.random() < 0.8 else rng.choice(labels)}
        variant_of = {}  # element id -> chosen label, consistent within row
        cands = [right]
        done = []
        # completed steps become decoys + history text, phrased exactly the
        # way loop.py narrates them at inference time ("typed in <label>" /
        # "clicked <label>")
        for j in range(k):
            did, dact, dlabels, ddesc = ep["steps"][j]
            # real loops narrate with the ACTUAL dom label every time — bias
            # hard toward the first (canonical/real) variant so training
            # matches inference instead of random synonyms
            dlab = dlabels[0] if rng.random() < 0.8 else rng.choice(dlabels)
            verb = {"type": "typed in", "click": "clicked",
                    "select": "selected"}.get(dact, "used")
            done.append(f"{verb} {dlab}")
            cands.append({"id": did, "action": dact, "label": dlab})
        # future steps as decoys too (right element is only the NEXT one)
        for j in range(k + 1, len(ep["steps"])):
            fid, fact, flabels, _ = ep["steps"][j]
            if rng.random() < 0.5:
                cands.append({"id": fid, "action": fact, "label": rng.choice(flabels)})
        for hid, hact, hlab in ep.get("extra_hard", []):
            if rng.random() < 0.5:
                lab = hlab if isinstance(hlab, str) else rng.choice(hlab)
                cands.append({"id": hid, "action": hact, "label": lab})
        for did, act2, lab in rng.sample(GENERIC, rng.randint(1, 2)):
            cands.append({"id": did, "action": act2, "label": lab})
        gtext = goal if not done else goal + " [done: " + "; ".join(done) + "]"
        rng.shuffle(cands)
        rows.append({"goal": gtext, "candidates": cands,
                     "answer": cands.index(right)})
    return rows


GENERIC = [
    ("btn-cancel", "click", "Cancel"), ("btn-help", "click", "Help"),
    ("link-terms", "click", "Terms of Service"), ("ad-banner", "click", "Ad"),
    ("btn-close", "click", "Close popup"), ("nav-home", "click", "Home"),
    ("img-logo", "click", "Logo"), ("btn-share", "click", "Share"),
    ("tab-back", "click", "Back"), ("btn-print", "click", "Print"),
    ("link-privacy", "click", "Privacy"), ("btn-newsletter", "click", "Subscribe"),
    ("footer-careers", "click", "Careers"),
]

# Pool of distractor candidates that never serve an ABSENT_GOAL row.
def _all_served_cands():
    pool = []
    for g in GOALS:
        for cid, act, labels in g["right"]:
            pool.append((cid, act, labels))
        for hid, act, labels in g["hard"]:
            pool.append((hid, act, labels))
    return pool


def build(n: int, seed: int = 3) -> list[dict]:
    rng = random.Random(seed)
    rows = []
    served_pool = _all_served_cands()
    n_seq = int(n * 0.35)
    rows.extend(_episode_rows(rng, n_seq))
    for _ in range(n):
        abstain = rng.random() < 0.28
        cands = []
        answer = -1
        right_cand = None
        if abstain:
            # unserved goal: candidates come ONLY from served pools +
            # generics — plausible page elements, none serving this goal.
            goal = rng.choice(ABSENT_GOALS)
            for cid, act, labels in rng.sample(served_pool,
                                               rng.randint(1, 3)):
                lab = labels if isinstance(labels, str) else rng.choice(labels)
                cands.append({"id": cid, "action": act, "label": lab})
            for did, act, lab in rng.sample(GENERIC, rng.randint(1, 3)):
                cands.append({"id": did, "action": act, "label": lab})
        else:
            g = rng.choice(GOALS)
            goal = rng.choice(g["goal"])
            cid, act, labels = rng.choice(g["right"])
            right_cand = {"id": cid, "action": act,
                          "label": rng.choice(labels)}
            cands.append(right_cand)
            hard = rng.sample(g["hard"], rng.randint(0, 2))
            for hid, act, labels in hard:
                lab = labels if isinstance(labels, str) else rng.choice(labels)
                cands.append({"id": hid, "action": act, "label": lab})
            for did, act, lab in rng.sample(GENERIC, rng.randint(1, 3)):
                cands.append({"id": did, "action": act, "label": lab})
        rng.shuffle(cands)
        if right_cand is not None:
            answer = cands.index(right_cand)
        rows.append({"goal": goal, "candidates": cands, "answer": answer})
    return rows


def write_jsonl(rows, path):
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


if __name__ == "__main__":
    import sys
    rows = build(int(sys.argv[1]) if len(sys.argv) > 1 else 8000)
    write_jsonl(rows, sys.argv[2] if len(sys.argv) > 2 else "s1_train.jsonl")
    n_ab = sum(1 for r in rows if r["answer"] < 0)
    print(f"{len(rows)} rows, {n_ab} abstain")
