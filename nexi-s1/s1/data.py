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

GENERIC = [
    ("btn-cancel", "click", "Cancel"), ("btn-help", "click", "Help"),
    ("link-terms", "click", "Terms of Service"), ("ad-banner", "click", "Ad"),
    ("btn-close", "click", "Close popup"), ("nav-home", "click", "Home"),
    ("img-logo", "click", "Logo"), ("btn-share", "click", "Share"),
    ("tab-back", "click", "Back"), ("btn-print", "click", "Print"),
    ("link-privacy", "click", "Privacy"), ("btn-newsletter", "click", "Subscribe"),
    ("footer-careers", "click", "Careers"),
]


def build(n: int, seed: int = 3) -> list[dict]:
    rng = random.Random(seed)
    rows = []
    for _ in range(n):
        abstain = rng.random() < 0.25
        g = rng.choice(GOALS)
        goal = rng.choice(g["goal"])
        cands = []
        answer = -1
        if not abstain:
            cid, act, labels = rng.choice(g["right"])
            cands.append({"id": cid, "action": act,
                          "label": rng.choice(labels)})
        # hard decoys: 0-2 goal-confusable wrong candidates
        hard = rng.sample(g["hard"], rng.randint(0, 2))
        for hid, act, labels in hard:
            lab = labels if isinstance(labels, str) else rng.choice(labels)
            cands.append({"id": hid, "action": act, "label": lab})
        # generic decoys
        for did, act, lab in rng.sample(GENERIC, rng.randint(1, 3)):
            cands.append({"id": did, "action": act, "label": lab})
        rng.shuffle(cands)
        if not abstain:
            right_ids = {c[0] for c in g["right"]}
            answer = next(j for j, c in enumerate(cands)
                          if c["id"] in right_ids and c["label"] in sum(
                              (c2[2] for c2 in g["right"] if c2[0] == c["id"]), []))
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
