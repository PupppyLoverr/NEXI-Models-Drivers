"""Multi-agent browser demo: two agents in parallel tabs + one in its own
window, each with its own visible colored cursor, driven by NEXI-S1.

agent-shop:  search the demo shop + add headphones to cart
agent-flights: start the MEL->DEL flight booking flow
agent-orders:  independent window, opens orders

Run headless=False to watch; the cursors move before every action.
"""
import sys, threading, time
sys.path.insert(0, "nexi-cua")
sys.path.insert(0, "nexi-s1")

from nexi_cua.browser import BrowserController
from nexi_cua import gates
from s1.model import S1
import torch, json, os

def load_s1():
    m = S1()
    ck = torch.load("nexi-s1/s1_v1.pt", map_location="cpu", weights_only=True)
    m.load_state_dict(ck["weights"] if "weights" in ck else ck)
    m.eval()
    return m

SHOP = os.path.abspath("nexi-cua/demo_site/index.html")
FLIGHTS = os.path.abspath("nexi-cua/demo_site/flights.html")

def s1_pick(m, goal, cands):
    d = m.decide(goal, cands)
    if d["choice"] is None:
        return None, d
    return cands[d["choice"]], d

def agent_run(ctl, name, url, script, m, log):
    ag = ctl.new_agent(name, "file://" + url)
    time.sleep(0.5)
    done_descs = []
    for step_goal, text in script:
        cands = ctl.candidates(ag)
        g = step_goal if not done_descs else step_goal + " [done: " + "; ".join(done_descs) + "]"
        pick, d = s1_pick(m, g, cands)
        log.append({"agent": name, "goal": g, "pick": pick and pick["id"],
                    "abstain_prob": d["abstain_prob"]})
        if pick is None:
            log.append({"agent": name, "event": "abstained"})
            break
        gate = gates.check(g, pick)
        if not gate["allow"]:
            log.append({"agent": name, "event": "gated", "reason": gate["reason"]})
            break
        ok = ctl.act(ag, pick, text=text)
        verb = "typed in" if pick["action"] == "type" else "clicked"
        done_descs.append(f"{verb} {pick['label']}")
        if not ok:
            log.append({"agent": name, "event": "act failed"})
            break
        time.sleep(0.8)

def agent_step(ctl, ag, goal, text, m, log, done_descs):
    cands = ctl.candidates(ag)
    g = goal if not done_descs else goal + " [done: " + "; ".join(done_descs) + "]"
    pick, d = s1_pick(m, g, cands)
    log.append({"agent": ag.name, "goal": g, "pick": pick and pick["id"],
                "abstain_prob": d["abstain_prob"]})
    if pick is None:
        log.append({"agent": ag.name, "event": "abstained"})
        return False
    gate = gates.check(g, pick)
    if not gate["allow"]:
        log.append({"agent": ag.name, "event": "gated", "reason": gate["reason"]})
        return False
    ok = ctl.act(ag, pick, text=text)
    if not ok:
        log.append({"agent": ag.name, "event": "act failed"})
        return False
    verb = "typed in" if pick["action"] == "type" else "clicked"
    done_descs.append(f"{verb} {pick['label']}")
    return True


def main():
    # playwright sync API is single-threaded: agents interleave round-robin
    # instead of parallel threads — same visual effect, no thread-unsafety
    m = load_s1()
    ctl = BrowserController(headless=False)
    log = []
    shop = ctl.new_agent("agent-shop", "file://" + SHOP)
    flights = ctl.new_agent("agent-flights", "file://" + FLIGHTS)
    orders = ctl.new_agent("agent-orders", "file://" + SHOP, new_window=True)
    time.sleep(0.5)
    shop_steps = [
        ("search the shop for wireless headphones", "wireless headphones"),
        ("search the shop for wireless headphones", None),
        ("add the item to cart", "Red"),
        ("add the item to cart", None),
    ]
    flight_steps = [
        ("book a flight from Melbourne to Delhi", "Melbourne"),
        ("book a flight from Melbourne to Delhi", "Delhi"),
        ("book a flight from Melbourne to Delhi", None),
    ]
    orders_steps = [("view my orders", None)]
    ds, df, do = [], [], []
    alive = True
    for i in range(max(len(shop_steps), len(flight_steps), len(orders_steps))):
        if i < len(shop_steps) and ds is not None:
            g, t = shop_steps[i]
            if not agent_step(ctl, shop, g, t, m, log, ds): ds = None
        if i < len(flight_steps) and df is not None:
            g, t = flight_steps[i]
            if not agent_step(ctl, flights, g, t, m, log, df): df = None
        if i < len(orders_steps) and do is not None:
            g, t = orders_steps[i]
            if not agent_step(ctl, orders, g, t, m, log, do): do = None
        time.sleep(0.6)
    json.dump(log, open("demo/cua/multi_agent_log.json", "w"), indent=2)
    print(json.dumps(log, indent=2)[:2000])
    time.sleep(3)
    ctl.close()

if __name__ == "__main__":
    main()
