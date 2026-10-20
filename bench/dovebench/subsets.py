"""Pinned, stratified task subsets drawn from bench/upstream-index/.

The draw is deterministic: within each domain, tasks are ordered by
sha256(SALT + task_id) and the first k are taken. Domain quotas are
proportional to domain size (largest remainder) with a per-domain floor.
Changing SALT, the pools, the targets or exclude.json changes the subset, so
any of those is a harness version bump (see bench/README.md).

    python3 -m dovebench subsets           # rewrite bench/subsets/*.json
    python3 -m dovebench subsets --check   # fail if the files would change
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

SALT = "dove-bench-subset-v1:"
BENCH = Path(__file__).resolve().parent.parent
INDEX = BENCH / "upstream-index"
SUBSETS = BENCH / "subsets"


def _load(name: str) -> dict[str, list[str]]:
    return json.loads((INDEX / name).read_text())


def _rank(task_id: str) -> str:
    return hashlib.sha256((SALT + task_id).encode()).hexdigest()


def quotas(sizes: dict[str, int], target: int, floor: int) -> dict[str, int]:
    """Largest-remainder allocation of `target` over domains, each at least min(floor, size)."""
    base = {d: min(floor, n) for d, n in sizes.items()}
    left = target - sum(base.values())
    if left < 0:
        raise ValueError("target is smaller than the per-domain floors")
    room = {d: sizes[d] - base[d] for d in sizes}
    total_room = sum(room.values())
    if left > total_room:
        raise ValueError("target exceeds the pool")
    exact = {d: left * room[d] / total_room for d in sizes} if total_room else {d: 0 for d in sizes}
    alloc = {d: base[d] + int(exact[d]) for d in sizes}
    rest = target - sum(alloc.values())
    for d in sorted(sizes, key=lambda d: (-(exact[d] - int(exact[d])), d))[:rest]:
        alloc[d] += 1
    return alloc


def draw(pool: dict[str, list[str]], target: int, floor: int) -> dict[str, list[str]]:
    pool = {d: sorted(set(ids)) for d, ids in pool.items() if ids}
    q = quotas({d: len(ids) for d, ids in pool.items()}, target, floor)
    return {d: sorted(sorted(ids, key=_rank)[: q[d]]) for d, ids in sorted(pool.items())}


def _without(pool: dict[str, list[str]], drop: set[str]) -> dict[str, list[str]]:
    return {d: [t for t in ids if t not in drop] for d, ids in pool.items()}


def build() -> dict[str, dict]:
    exclude = json.loads((SUBSETS / "exclude.json").read_text())
    excluded = {s: {e["id"] for e in exclude.get(s, [])} for s in ("osworld", "waa", "macarena")}

    infeasible = {t for ids in _load("osworld_test_infeasible.json").values() for t in ids}
    osworld_pool = _without(_load("osworld_test_nogdrive.json"), infeasible | excluded["osworld"])

    waa_pool = _without(_load("waa_test_all.json"), excluded["waa"])

    mac = _without(_load("macarena_machine_0_test.json"), excluded["macarena"])
    native = {d: ids for d, ids in mac.items() if d.startswith("macarena/")}
    macosworld = {d: ids for d, ids in mac.items() if d.startswith("macosworld/")}
    mac_tasks = {**draw(native, 20, 2), **draw(macosworld, 20, 2)}

    out = {
        "osworld": {
            "suite": "OSWorld-Verified",
            "source": "upstream-index/osworld_test_nogdrive.json minus osworld_test_infeasible.json and exclude.json",
            "tasks": draw(osworld_pool, 100, 4),
        },
        "waa": {
            "suite": "Windows Agent Arena",
            "source": "upstream-index/waa_test_all.json minus exclude.json",
            "tasks": draw(waa_pool, 60, 2),
        },
        "macarena": {
            "suite": "MacArena",
            "source": (
                "upstream-index/macarena_machine_0_test.json: 20 from macarena/* (native, MIT) and 20 from "
                "macosworld/* (CC BY-NC 4.0); osworld/* ports are left out because they overlap the Linux suite"
            ),
            "tasks": mac_tasks,
        },
    }
    for name, sub in out.items():
        sub["salt"] = SALT
        sub["count"] = sum(len(v) for v in sub["tasks"].values())
    return out


def write(check: bool = False) -> int:
    changed = []
    for name, sub in build().items():
        path = SUBSETS / f"{name}.json"
        text = json.dumps(sub, indent=2) + "\n"
        if not path.exists() or path.read_text() != text:
            changed.append(path.name)
            if not check:
                path.write_text(text)
    if check and changed:
        print("subsets out of date:", ", ".join(changed))
        return 1
    for name, sub in build().items():
        print(f"{name}: {sub['count']} tasks over {len(sub['tasks'])} domains")
    return 0


def load(suite: str) -> list[tuple[str, str]]:
    """(domain, task_id) pairs of a pinned subset, in file order."""
    sub = json.loads((SUBSETS / f"{suite}.json").read_text())
    return [(d, t) for d, ids in sub["tasks"].items() for t in ids]
