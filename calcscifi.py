#!/usr/bin/env python3
"""
CALC_SCI_FI - Sci-Fi themed safe calculator (CLI)
Features: safe expression eval, units, history, presets, story mode
"""

import ast
import operator as op
import math
import cmath
import readline
import json
import os
import random
from typing import Any, Dict

# ---------- Safe eval using AST ----------
# supported operators
_OPERATORS = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.Pow: op.pow,
    ast.Mod: op.mod,
    ast.USub: op.neg,
    ast.UAdd: op.pos,
    ast.FloorDiv: op.floordiv,
    ast.BitXor: op.xor,
}

# allowed names (math + cmath)
_ALLOWED_NAMES: Dict[str, Any] = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
_ALLOWED_NAMES.update({k: getattr(cmath, k) for k in dir(cmath) if not k.startswith("_")})
# add constants
_ALLOWED_NAMES.update({"pi": math.pi, "e": math.e, "tau": math.tau, "j": 1j})

def _eval_node(node):
    if isinstance(node, ast.Num):  # <number>
        return node.n
    if isinstance(node, ast.Constant):  # Python 3.8+
        return node.value
    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        op_type = type(node.op)
        if op_type in _OPERATORS:
            return _OPERATORS[op_type](left, right)
        raise ValueError(f"Unsupported binary operator {op_type}")
    if isinstance(node, ast.UnaryOp):
        operand = _eval_node(node.operand)
        op_type = type(node.op)
        if op_type in _OPERATORS:
            return _OPERATORS[op_type](operand)
        raise ValueError(f"Unsupported unary operator {op_type}")
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name):
            fname = func.id
            if fname in _ALLOWED_NAMES:
                args = [_eval_node(a) for a in node.args]
                return _ALLOWED_NAMES[fname](*args)
        raise ValueError("Function calls are restricted to math/cmath functions")
    if isinstance(node, ast.Name):
        if node.id in _ALLOWED_NAMES:
            return _ALLOWED_NAMES[node.id]
        raise ValueError(f"Name {node.id} is not allowed")
    if isinstance(node, ast.Expr):
        return _eval_node(node.value)
    raise ValueError(f"Unsupported expression: {ast.dump(node)}")

def safe_eval(expr: str):
    tree = ast.parse(expr, mode="eval")
    return _eval_node(tree.body)

# ---------- Units ----------
_UNITS = {
    # length
    ("m", "km"): lambda x: x / 1000.0,
    ("km", "m"): lambda x: x * 1000.0,
    ("m", "cm"): lambda x: x * 100.0,
    ("cm", "m"): lambda x: x / 100.0,
    # mass
    ("kg", "g"): lambda x: x * 1000.0,
    ("g", "kg"): lambda x: x / 1000.0,
    # time
    ("s", "min"): lambda x: x / 60.0,
    ("min", "s"): lambda x: x * 60.0,
}

def convert_units(value: float, src: str, dst: str):
    key = (src, dst)
    if key in _UNITS:
        return _UNITS[key](value)
    raise ValueError(f"No conversion registered for {src} -> {dst}")

# ---------- Persistence ----------
DATA_FILE = os.path.expanduser("~/.calc_scifi_presets.json")
def load_presets():
    try:
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_presets(presets):
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(presets, f, indent=2)
    except Exception:
        pass

# ---------- UI helpers ----------
def sci_print(text: str):
    # simple atmospheric printing
    prefix = random.choice(["⟡", "✦", "✶", "⚝", "✺"])
    print(f"{prefix} {text}")

def colorize_result(val: Any) -> str:
    if isinstance(val, complex):
        return f"\033[95m{val}\033[0m"
    if isinstance(val, float):
        return f"\033[94m{val}\033[0m"
    return f"\033[92m{val}\033[0m"

# ---------- Main REPL ----------
def repl():
    sci_print("CALC SCI-FI boot sequence initiated.")
    presets = load_presets()
    history = []
    story_lines = [
        "Starboard sensors humming. Calculations queued.",
        "Quantum coils stabilizing. Recomputing trajectories.",
        "Nebula dust detected. Re-evaluating constants.",
        "AI chorus: 'Proceed with caution, Captain.'",
    ]

    while True:
        try:
            inp = input("calc> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            sci_print("Shutting down. May your equations converge.")
            break

        if not inp:
            continue

        # Commands
        if inp.startswith(":"):
            parts = inp[1:].split()
            cmd = parts[0].lower() if parts else ""
            args = parts[1:]

            if cmd in ("q", "quit", "exit"):
                sci_print("Powering down engines.")
                break
            if cmd in ("h", "help"):
                print("Commands:")
                print(":help                 show this help")
                print(":history              show history")
                print(":save <name> <expr>   save preset")
                print(":load <name>          load preset (prints expression)")
                print(":presets              list saved presets")
                print(":convert <v> <a> <b>  convert units (e.g. :convert 10 km m)")
                print(":units                list available unit conversions")
                print(":story                print a sci-fi line")
                print(":quit                 exit")
                continue
            if cmd == "history":
                for i, (e, r) in enumerate(history[-50:], 1):
                    print(f"{i:3d}: {e} => {r}")
                continue
            if cmd == "save" and len(args) >= 2:
                name = args[0]
                expr = " ".join(args[1:])
                presets[name] = expr
                save_presets(presets)
                sci_print(f"Preset '{name}' saved.")
                continue
            if cmd == "load" and len(args) == 1:
                name = args[0]
                expr = presets.get(name)
                if expr is None:
                    sci_print(f"Preset '{name}' not found.")
                else:
                    print(expr)
                continue
            if cmd == "presets":
                if presets:
                    for k, v in presets.items():
                        print(f"{k}: {v}")
                else:
                    print("No presets saved.")
                continue
            if cmd == "convert" and len(args) == 3:
                try:
                    v = float(args[0])
                    a = args[1]
                    b = args[2]
                    out = convert_units(v, a, b)
                    print(f"{v} {a} = {out} {b}")
                except Exception as e:
                    print("Conversion error:", e)
                continue
            if cmd == "units":
                for a, b in _UNITS.keys():
                    print(f"{a} -> {b}")
                continue
            if cmd == "story":
                sci_print(random.choice(story_lines))
                continue
            sci_print("Unknown command. Type :help for commands.")
            continue

        # Expression evaluation
        try:
            result = safe_eval(inp)
            history.append((inp, result))
            sci_print(random.choice(story_lines))
            print("=>", colorize_result(result))
        except Exception as e:
            print("Error:", e)

if __name__ == "__main__":
    repl()
