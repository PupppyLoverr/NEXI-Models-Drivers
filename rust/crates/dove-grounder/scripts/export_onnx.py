"""Write the Local Grounder asset: NEXI-CUA-1 as one ONNX file for tract.

    python export_onnx.py NEXI_CUA_DIR OUT.onnx [--fp16]

Reads nexi-cua's `weights/nexi-cua-1.pt` and `nexi-cua-1.calib.json` and
writes the network of `nexi_cua/policy/model.py` (NexiCUA1.forward) for one
observation, unpadded:

    inputs   goal_p [1,80]  elem_p [K,80]  role_idx [K]  numeric [K,14]
             verb_idx [M]  tgt_idx [M]  arg_p [M,80]
    outputs  logits [M]  corr [M]

`*_p` are the text features already passed through `text_proj`. The
graph does not apply it: dove-grounder applies `text_proj.weight` to the
non-zero hashed buckets only (see src/model.rs), so the weight and bias
are stored here as initializers the graph does not read. Weights are fp32
(6.4 MB). `--fp16` stores them as fp16 (3.2 MB) with a Cast to fp32 for
compute; that asset makes the same decisions on every gate case but
picks a different top-ranked candidate on 3 abstained near-ties (top two
within 0.6%), so it does not pass the W9 gate. Calibration (temperature,
abstain threshold) goes in metadata_props.

Padding and masks are left out: nexi masks padded rows with -1e4 before
the softmaxes, so they contribute exactly 0, and the real rows are the
same either way.
"""
from __future__ import annotations

import argparse
import json
import os

import numpy as np
import onnx
import torch
from onnx import TensorProto, helper, numpy_helper

D = 192


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("nexi_cua_dir")
    ap.add_argument("out")
    ap.add_argument("--fp16", action="store_true",
                    help="store weights as fp16 (fails the gate, see above)")
    ap.add_argument("--fp32-layers", default="",
                    help="with --fp16: weight-name prefixes kept fp32")
    a = ap.parse_args()
    wdir = os.path.join(a.nexi_cua_dir, "weights")
    ckpt = torch.load(os.path.join(wdir, "nexi-cua-1.pt"), map_location="cpu",
                      weights_only=False)
    sd = {k: v.detach().float().numpy() for k, v in ckpt["state_dict"].items()}
    calib = dict(ckpt.get("stats", {}))
    with open(os.path.join(wdir, "nexi-cua-1.calib.json")) as f:
        calib.update(json.load(f))

    fp32 = not a.fp16
    store = np.float32 if fp32 else np.float16
    inits: list[TensorProto] = []
    nodes: list = []

    keep32 = tuple(p for p in a.fp32_layers.split(",") if p)

    def weight(name: str) -> str:
        """The weight as an initializer (fp16 ones get a Cast to fp32);
        returns the fp32 name."""
        if fp32 or name.startswith(keep32):
            inits.append(numpy_helper.from_array(sd[name].astype(np.float32), name))
            return name
        inits.append(numpy_helper.from_array(sd[name].astype(store), name))
        out = name + ".f32"
        nodes.append(helper.make_node("Cast", [name], [out], to=TensorProto.FLOAT))
        return out

    def const(name: str, value) -> str:
        inits.append(numpy_helper.from_array(np.asarray(value), name))
        return name

    counter = [0]

    def fresh(prefix: str) -> str:
        counter[0] += 1
        return f"{prefix}_{counter[0]}"

    def linear(x: str, prefix: str) -> str:
        """nn.Linear: x @ W^T + b (W^T stored, so MatMul reads it directly)."""
        sd[prefix + ".weight_t"] = np.ascontiguousarray(sd[prefix + ".weight"].T)
        w = weight(prefix + ".weight_t")
        b = weight(prefix + ".bias")
        mm, out = fresh(prefix + ".mm"), fresh(prefix + ".out")
        nodes.append(helper.make_node("MatMul", [x, w], [mm]))
        nodes.append(helper.make_node("Add", [mm, b], [out]))
        return out

    def gelu(x: str) -> str:
        """nn.GELU(): x * 0.5 * (1 + erf(x / sqrt(2)))."""
        s, e, p, h, y = (fresh("gelu") for _ in range(5))
        nodes.append(helper.make_node("Mul", [x, inv_sqrt2], [s]))
        nodes.append(helper.make_node("Erf", [s], [e]))
        nodes.append(helper.make_node("Add", [e, one], [p]))
        nodes.append(helper.make_node("Mul", [x, half], [h]))
        nodes.append(helper.make_node("Mul", [h, p], [y]))
        return y

    def mlp(x: str, prefix: str) -> str:
        return linear(gelu(linear(x, prefix + ".0")), prefix + ".2")

    inv_sqrt2 = const("c.inv_sqrt2", np.float32(0.7071067811865476))
    one = const("c.one", np.float32(1.0))
    half = const("c.half", np.float32(0.5))
    sqrt_d = const("c.sqrt_d", np.float32(D ** 0.5))
    zero_i = const("c.zero_i", np.int64(0))
    flat = const("c.flat", np.array([-1], dtype=np.int64))

    g = mlp("goal_p", "goal_enc")                                  # [1,d]
    role_e = fresh("role_e")
    nodes.append(helper.make_node("Gather", [weight("role_emb.weight"),
                                             "role_idx"], [role_e]))
    num_e = linear("numeric", "num_proj")
    elem_x = fresh("elem_x")
    nodes.append(helper.make_node("Concat", [role_e, "elem_p", num_e],
                                  [elem_x], axis=1))
    E = mlp(elem_x, "elem_enc")                                    # [K,d]

    # gather_targets: E[tgt] where tgt >= 0, none_vec elsewhere
    safe, picked, has, has2, tgt = (fresh("tgt") for _ in range(5))
    nodes.append(helper.make_node("Max", ["tgt_idx", zero_i], [safe]))
    nodes.append(helper.make_node("Gather", [E, safe], [picked], axis=0))
    nodes.append(helper.make_node("GreaterOrEqual", ["tgt_idx", zero_i], [has]))
    nodes.append(helper.make_node("Unsqueeze", [has, const("c.ax1", np.array([1], dtype=np.int64))], [has2]))
    nodes.append(helper.make_node("Where", [has2, picked, weight("none_vec")], [tgt]))

    verb_e = fresh("verb_e")
    nodes.append(helper.make_node("Gather", [weight("verb_emb.weight"),
                                             "verb_idx"], [verb_e]))
    act_x = fresh("act_x")
    nodes.append(helper.make_node("Concat", [verb_e, tgt, "arg_p"], [act_x],
                                  axis=1))
    A = mlp(act_x, "act_enc")                                      # [M,d]

    # context: softmax(q k^T / sqrt(d)) v
    q, k, v = linear(g, "att_q"), linear(E, "att_k"), linear(E, "att_v")
    kt, sc, scd, w, c = (fresh("att") for _ in range(5))
    nodes.append(helper.make_node("Transpose", [k], [kt], perm=[1, 0]))
    nodes.append(helper.make_node("MatMul", [q, kt], [sc]))
    nodes.append(helper.make_node("Div", [sc, sqrt_d], [scd]))
    nodes.append(helper.make_node("Softmax", [scd], [w], axis=-1))
    nodes.append(helper.make_node("MatMul", [w, v], [c]))          # [1,d]

    # joint = [g, A, g*A, c] per candidate
    shape_a, ge, ce, gA, joint = (fresh("joint") for _ in range(5))
    nodes.append(helper.make_node("Shape", [A], [shape_a]))
    nodes.append(helper.make_node("Expand", [g, shape_a], [ge]))
    nodes.append(helper.make_node("Expand", [c, shape_a], [ce]))
    nodes.append(helper.make_node("Mul", [ge, A], [gA]))
    nodes.append(helper.make_node("Concat", [ge, A, gA, ce], [joint], axis=1))
    for head, out in (("scorer", "logits"), ("correct_head", "corr")):
        y = mlp(joint, head)                                       # [M,1]
        nodes.append(helper.make_node("Reshape", [y, flat], [out]))

    # text_proj travels in the file, applied outside the graph.
    for name in ("text_proj.weight", "text_proj.bias"):
        inits.append(numpy_helper.from_array(sd[name].astype(store), name))

    f32, i64 = TensorProto.FLOAT, TensorProto.INT64
    graph = helper.make_graph(
        nodes, "nexi-cua-1",
        inputs=[
            helper.make_tensor_value_info("goal_p", f32, [1, 80]),
            helper.make_tensor_value_info("elem_p", f32, ["K", 80]),
            helper.make_tensor_value_info("role_idx", i64, ["K"]),
            helper.make_tensor_value_info("numeric", f32, ["K", 14]),
            helper.make_tensor_value_info("verb_idx", i64, ["M"]),
            helper.make_tensor_value_info("tgt_idx", i64, ["M"]),
            helper.make_tensor_value_info("arg_p", f32, ["M", 80]),
        ],
        outputs=[
            helper.make_tensor_value_info("logits", f32, ["M"]),
            helper.make_tensor_value_info("corr", f32, ["M"]),
        ],
        initializer=inits,
    )
    model = helper.make_model(
        graph, opset_imports=[helper.make_opsetid("", 17)],
        producer_name="dove-grounder export_onnx.py",
        doc_string="NEXI-CUA-1 from nexi-cua v0.4.0 (Apache-2.0)")
    model.ir_version = 8
    for key in ("temperature", "abstain_threshold"):
        entry = model.metadata_props.add()
        entry.key, entry.value = key, repr(float(calib[key]))
    onnx.checker.check_model(model)
    onnx.save(model, a.out)
    print(f"wrote {a.out}: {os.path.getsize(a.out)} bytes, "
          f"T={calib['temperature']} thr={calib['abstain_threshold']}")


if __name__ == "__main__":
    main()
