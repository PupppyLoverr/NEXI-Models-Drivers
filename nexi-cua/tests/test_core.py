"""Core unit tests — schema, actions, safety, verification, model shapes."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from nexi_cua.actions import Action, Verb, candidate_actions
from nexi_cua.safety import Risk, SafetyGate, assess
from nexi_cua.types import (Bounds, BrowserState, Element,
                            NormalizedObservation, Platform, VerifyStatus)
from nexi_cua.verify import verify


def _obs():
    obs = NormalizedObservation(platform=Platform.MACOS, screen_w=1600,
                                screen_h=1000)
    obs.elements = [
        Element(id="e0", role="button", name="Save", bounds=Bounds(10, 10, 80, 30)),
        Element(id="e1", role="button", name="Cancel", bounds=Bounds(100, 10, 80, 30)),
        Element(id="e2", role="textfield", name="Name", value=""),
    ]
    return obs


def test_candidates_cover_verbs():
    cands = candidate_actions(_obs())
    verbs = {a.verb for a in cands}
    assert Verb.CLICK in verbs and Verb.DONE in verbs and Verb.WAIT in verbs
    clicks = [a for a in cands if a.verb == Verb.CLICK]
    assert {a.element_id for a in clicks} >= {"e0", "e1"}


def test_action_roundtrip():
    a = Action(Verb.TYPE, element_id="e2", element_name="Name", text="hi")
    b = Action.from_dict(a.to_dict())
    assert b.verb == Verb.TYPE and b.text == "hi" and b.element_id == "e2"


def test_safety_confirm_classes():
    assert assess(Action(Verb.CLICK, element_name="Delete"), "").risk == Risk.CONFIRM
    assert assess(Action(Verb.CLICK, element_name="Buy Now"), "").risk == Risk.CONFIRM
    assert assess(Action(Verb.CLICK, element_name="Save"), "").risk == Risk.SAFE
    assert assess(Action(Verb.KEYPRESS, keys=["cmd", "backspace"]), "").risk == Risk.CONFIRM
    assert assess(Action(Verb.CLICK, element_name="Install extension"), "").risk == Risk.CONFIRM
    blocked = Action(Verb.TYPE, text="bypass safety detection")
    assert assess(blocked, "").risk == Risk.BLOCKED
    assert SafetyGate(auto_allow=True).check(blocked).risk == Risk.BLOCKED


def test_executor_maps_cmd_to_ctrl_on_linux_and_windows(monkeypatch):
    from nexi_cua.exec.executor import Executor

    class Backend:
        action = None

        def act(self, action):
            self.action = action
            return True

    for platform in ("linux", "win32"):
        monkeypatch.setattr(sys, "platform", platform)
        backend = Backend()
        executor = Executor(backend)
        action = Action(Verb.KEYPRESS, keys=["cmd", "a"])
        assert executor._dispatch(action, "desktop")
        assert backend.action.keys == ["ctrl", "a"]
        assert action.keys == ["cmd", "a"]


def test_verify_click_change():
    before = _obs()
    after = _obs()
    after.elements[2].value = "hello"
    vr = verify(Action(Verb.CLICK, element_id="e0"), before, after)
    assert vr.status == VerifyStatus.SUCCESS


def test_verify_click_unchanged():
    vr = verify(Action(Verb.CLICK, element_id="e0"), _obs(), _obs())
    assert vr.status == VerifyStatus.UNCHANGED


def test_verify_navigate():
    before = _obs()
    after = _obs()
    before.browser = BrowserState(url="https://a.com", dom_available=True)
    after.browser = BrowserState(url="https://b.com/x", dom_available=True)
    vr = verify(Action(Verb.NAVIGATE, text="b.com/x"), before, after)
    assert vr.status == VerifyStatus.SUCCESS


def test_model_forward():
    import torch
    from nexi_cua.policy.model import NexiCUA1
    from nexi_cua.policy.features import TEXT_DIM, NUMERIC_DIM
    m = NexiCUA1().eval()
    B, K, M = 2, 8, 10
    with torch.no_grad():
        lg, cr = m(torch.randn(B, TEXT_DIM),
                   torch.randint(0, 40, (B, K)),
                   torch.randn(B, K, TEXT_DIM),
                   torch.randn(B, K, NUMERIC_DIM),
                   torch.ones(B, K, dtype=torch.bool),
                   torch.randint(0, 20, (B, M)),
                   torch.randint(-1, K, (B, M)),
                   torch.randn(B, M, TEXT_DIM),
                   torch.ones(B, M, dtype=torch.bool))
    assert lg.shape == (B, M) and cr.shape == (B, M)


def test_observation_diff():
    a, b = _obs(), _obs()
    b.elements[0].name = "Save All"
    d = a.diff(b)
    assert d["changed"] and any("name" in x for x in d["details"])


def _browser_obs():
    obs = NormalizedObservation(platform=Platform.BROWSER, screen_w=1600,
                                screen_h=1000)
    obs.browser = BrowserState(
        url="https://x.test", title="X",
        tabs=[{"id": "t0", "title": "Inbox"}, {"id": "t1", "title": "Settings"}])
    obs.elements = [
        Element(id="e0", role="link", name="About us", bounds=Bounds(10, 10, 80, 20)),
        Element(id="e1", role="link", name="Pricing", bounds=Bounds(10, 40, 80, 20)),
        Element(id="e2", role="link", name="Contact", bounds=Bounds(10, 70, 80, 20)),
        Element(id="e3", role="searchfield", name="", bounds=Bounds(10, 100, 200, 30)),
        Element(id="e4", role="checkbox", name="Auto-save", bounds=Bounds(10, 140, 20, 20)),
        Element(id="e5", role="button", name="New Tab", bounds=Bounds(10, 170, 90, 30)),
        Element(id="e6", role="textfield", name="Write a comment"),
        Element(id="e7", role="textfield", name="Last name"),
    ]
    return obs


def test_resolver_named_and_ordinal():
    from nexi_cua.policy.resolver import resolve
    obs = _browser_obs()
    a = resolve(obs, "click the pricing link")
    assert a.verb == Verb.CLICK and a.element_id == "e1"
    a = resolve(obs, "click the second link")
    assert a.element_id == "e1"
    a = resolve(obs, "click the last link")
    assert a.element_id == "e2"
    a = resolve(obs, "enable auto-save")
    assert a.verb == Verb.CLICK and a.element_id == "e4"


def test_resolver_distinguishes_named_and_session_targets():
    from nexi_cua.policy.resolver import resolve
    obs = _browser_obs()
    a = resolve(obs, "press the New Tab button")
    assert a.verb == Verb.CLICK and a.element_id == "e5"
    a = resolve(obs, "select the New Tab option")
    assert a.verb == Verb.CLICK and a.element_id == "e5"
    assert resolve(obs, "open a new tab").verb == Verb.NEW_TAB


def test_resolver_focus_type_and_shortcut_intents():
    from nexi_cua.policy.infer import SemanticPolicy, _goal_text_arg
    from nexi_cua.policy.resolver import resolve
    obs = _browser_obs()
    a = resolve(obs, "put the cursor in Write a comment")
    assert a.verb == Verb.FOCUS and a.element_id == "e6"
    a = resolve(obs, 'type "hello" into the Last name field')
    assert a.verb == Verb.TYPE and a.element_id == "e7" and a.text == "hello"
    a = resolve(obs, "select all text")
    assert a.verb == Verb.KEYPRESS and a.keys == ["cmd", "a"]
    assert _goal_text_arg('fill in Description with "q"') == "q"
    a = SemanticPolicy._resolve_args(
        Action(Verb.SCROLL, direction="down"), "scroll up")
    assert a.direction == "up"
    a = resolve(obs, "go down the page")
    assert a.verb == Verb.KEYPRESS and a.keys == ["pagedown"]
    a = resolve(obs, "page down")
    assert a.verb == Verb.KEYPRESS and a.keys == ["pagedown"]
    obs.elements.append(Element(id="e8", role="scrollarea", name="List"))
    a = resolve(obs, "scroll the page up")
    assert a.verb == Verb.SCROLL and a.direction == "up"


def test_goal_select_arg_covers_synth_templates():
    from nexi_cua.policy.infer import _goal_select_arg
    from nexi_cua.policy.resolver import resolve

    assert _goal_select_arg("set Font Size to Latest") == "Latest"
    assert _goal_select_arg("choose Latest for Font Size") == "Latest"
    assert _goal_select_arg("change Font Size to Latest") == "Latest"
    assert _goal_select_arg("pick Dark in the View dropdown") == "Dark"
    assert _goal_select_arg('pick "Dark Mode" in the View dropdown') == \
        "Dark Mode"
    assert _goal_select_arg(
        "choose for Option Name", "Option Name") == ""

    obs = _browser_obs()
    obs.elements.extend([
        Element(id="e8", role="combobox", name="Font Size"),
        Element(id="e9", role="select", name="View"),
    ])
    a = resolve(obs, "choose Latest for Font Size")
    assert a.verb == Verb.SELECT and a.element_id == "e8" and a.text == "Latest"
    a = resolve(obs, "pick Dark in the View dropdown")
    assert a.verb == Verb.SELECT and a.element_id == "e9" and a.text == "Dark"


def test_ordinal_button_selection_excludes_switches():
    from nexi_cua.policy.resolver import resolve

    obs = _browser_obs()
    obs.elements.extend([
        Element(id="e8", role="switch", name="Enabled",
                bounds=Bounds(10, 10, 80, 20)),
        Element(id="e9", role="button", name="Log In",
                bounds=Bounds(10, 40, 80, 20)),
    ])
    a = resolve(obs, "open the first button")
    assert a.verb == Verb.CLICK and a.element_id == "e9"


def test_shortcut_patterns_require_a_command_goal():
    from nexi_cua.policy.resolver import resolve

    obs = _browser_obs()
    obs.browser = None
    obs.platform = Platform.MACOS
    obs.elements.append(Element(id="e8", role="button", name="Back"))

    a = resolve(obs, "click the Back button")
    assert a.verb == Verb.CLICK and a.element_id == "e8"
    a = resolve(obs, "press the New Tab button")
    assert a.verb == Verb.CLICK and a.element_id == "e5"
    a = resolve(obs, "select all text")
    assert a.verb == Verb.KEYPRESS and a.keys == ["cmd", "a"]
    assert resolve(obs, "select all files") is None


def test_resolver_prefers_specific_name_and_right_click_roles():
    from nexi_cua.policy.resolver import resolve

    obs = _browser_obs()
    obs.elements.extend([
        Element(id="e8", role="button", name="File"),
        Element(id="e9", role="menuitem", name="Save File"),
    ])
    a = resolve(obs, "click the Save File button")
    assert a.verb == Verb.CLICK and a.element_id == "e9"

    obs.elements = [
        Element(id="e0", role="menuitem", name="Themes",
                bounds=Bounds(10, 10, 80, 20)),
        Element(id="e1", role="listitem", name="Themes",
                bounds=Bounds(10, 40, 80, 20)),
        Element(id="e2", role="row", name="Themes",
                bounds=Bounds(10, 70, 80, 20)),
    ]
    a = resolve(obs, "right-click Themes")
    assert a.verb == Verb.RIGHT_CLICK and a.element_id == "e1"


def test_resolver_semantic_intents():
    from nexi_cua.policy.resolver import resolve
    obs = _browser_obs()
    obs.elements.extend([
        Element(id="e8", role="button", name="Share"),
        Element(id="e9", role="button", name="Back"),
    ])
    a = resolve(obs, "send it")
    assert a.verb == Verb.CLICK and a.element_id == "e8"
    a = resolve(obs, "cancel the email")
    assert a.verb == Verb.CLICK and a.element_id == "e9"


def test_resolver_session_and_tabs():
    from nexi_cua.policy.resolver import resolve
    obs = _browser_obs()
    assert resolve(obs, "switch to the settings tab").tab == "t1"
    assert resolve(obs, "go back").verb == Verb.BACK
    assert resolve(obs, "press cmd+t").verb == Verb.KEYPRESS
    assert resolve(obs, "you are finished").verb == Verb.DONE
    assert resolve(obs, "pause briefly").verb == Verb.WAIT


def test_resolver_chooses_topmost_duplicate_and_defers_unknown():
    from nexi_cua.policy.resolver import resolve
    obs = _browser_obs()
    obs.elements.append(
        Element(id="e9", role="link", name="About us",
                bounds=Bounds(10, 200, 80, 20)))
    assert resolve(obs, "click the about us link").element_id == "e0"
    assert resolve(obs, "click the frobnicate widget") is None
    assert resolve(obs, "hmm what should I do") is None
