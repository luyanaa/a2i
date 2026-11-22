#!/usr/bin/env python3
"""gen_manifest_kernels.py -- port-manifest generator for the CPU IP generator.

Parses a fixed list of *golden* VHDL entities out of the read-only frozen
source tree and emits ``chisel/kernels/manifest.json``, which the Amaranth
generator consumes to build ``Instance`` blackbox port maps.

Pure Python 3 stdlib, no third-party dependencies.

Usage
-----
    python3 chisel/tools/gen_manifest_kernels.py [--src DIR] [--out FILE]

Defaults
--------
--src  /shared/a2i/rel/src/vhdl/work   (read-only golden RTL)
--out  <repo>/chisel/kernels/manifest.json

Notes on the port grammar (canonical shape: fuq_mul.vhdl:48-74)
--------------------------------------------------------------
* ``name : dir type ;`` with dir in {in, out, inout}.
* ``type`` is captured raw; for ``std_ulogic_vector(lo to hi)`` the explicit
  bounds are captured too.
* A2I is **MSB-first**: ``std_ulogic_vector(0 to 52)`` means index 0 is the
  MSB, width = hi-lo+1.  The manifest records ``lo``/``hi``/``width`` and
  ``msb_first``; it never assumes ``downto`` (``downto`` would be recorded
  with ``msb_first:false``).
* Some bounds are expressions in entity generics, e.g.
  ``std_ulogic_vector(64-(2**regmode) to 63)`` in xuq_alu.  Generic defaults
  are parsed from the entity and the bounds are evaluated with a tiny
  safe integer evaluator.  If an expression cannot be resolved, ``lo``/``hi``/
  ``width`` are null and the raw text is kept in ``bounds_expr``.

Classification (``role``)
-------------------------
Driven by the small, editable rule table ``PERVASIVE_*`` / ``CONTROL_*`` below
(name-pattern + type based -- not a hard-coded per-port mapping):

* ``pervasive`` -- tie-off / clock-domain ports: vdd, gnd, clkoff_b, act_dis,
  delay_lclkr, mpw1_b, mpw2_b, sg_1, thold_1, nclk, *_si, *_so, scan_in/out,
  the *_dc pervasive family, and every ``power_logic`` / ``clk_logic`` port.
  These get tied off for expand_type=1 / thold=0.
* ``control``   -- activation/enable/strobe/valid: ex1_act, flush, *_act,
  fpu_enable, *_en, *_val, *valid*, *strobe*, *flush*.
* ``data``      -- everything else (operand/result buses and scalar data).

Rule order: pervasive-by-type -> pervasive-by-name -> control -> data.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

#: Golden entities to parse (fixed list from the task spec).
KERNELS: List[str] = [
    "fuq_mul",
    "fuq_add",
    "fuq_alg",
    "fuq_nrm",
    "xuq_alu",
    "xuq_alu_add",
    "xuq_agen",
]

#: Frozen (read-only) golden RTL root.
DEFAULT_SRC = Path("/shared/a2i/rel/src/vhdl/work")

# --------------------------------------------------------------------------
# Classifier rule table  (EDIT ME -- name/type based, no per-port hard-coding)
# --------------------------------------------------------------------------

#: Types whose ports are pervasive tie-offs (matched before name rules).
PERVASIVE_TYPES = {
    "power_logic",  # inout supply rail (std_logic subtype, width 1)
    "clk_logic",    # nclk record (clk, sreset, clk2x, clk4x)
}

#: Full-name regexes for pervasive ports (re.fullmatch).
PERVASIVE_NAME_RES = [
    r"vdd",
    r"gnd",
    r"clkoff_b",
    r"act_dis",
    r"delay_lclkr(_dc)?",              # LCB delayed clock strobe (+ _dc form)
    r"mpw[12]((_dc)?_b)?",             # mpw1_b / mpw2_b / mpw1_dc_b / mpw2_dc_b
    r"sg_[01]",                        # scan gate (sg_1 / sg_0)
    r"thold_[01](_b)?",                # threshold hold
    r"nclk",                           # clk_logic record
    r"d_mode_dc",
    r"func_sl.*",                      # func_sl_force / func_sl_thold_0_b ...
    r"scan_(in|out)",
    r".*_si",                          # scan-in (f_mul_si ...)
    r".*_so",                          # scan-out (f_mul_so ...)
]

#: Full-name regexes for control ports (re.fullmatch).  Evaluated AFTER the
#: pervasive rules, so e.g. ``act_dis`` stays pervasive.
CONTROL_NAME_RES = [
    r".*flush.*",                      # flush / fxa_fxb_ex1_hold_ctr_flush
    r".*_act.*",                       # ex1_act, ex1_act_b, *_write_act_01 ...
    r".*enable.*",                     # fpu_enable
    r".*_en",                          # f_lza_ex4_sh_rgt_en
    r".*_val.*",                       # binv_val, inv1_val_b, *_mul_val ...
    r".*valid.*",
    r".*strobe.*",
]

# Scalar / special type widths (None = not a plain bit vector).
TYPE_WIDTH: Dict[str, Optional[int]] = {
    "std_ulogic": 1,
    "power_logic": 1,
    "clk_logic": None,  # record type -- tied off, no bit width in the manifest
}

# --------------------------------------------------------------------------
# VHDL parsing helpers
# --------------------------------------------------------------------------

_COMMENT_RE = re.compile(r"--[^\n]*")
_PORT_OPEN_RE = re.compile(r"\bport\s*\(", re.IGNORECASE)
_GENERIC_OPEN_RE = re.compile(r"\bgeneric\s*\(", re.IGNORECASE)
_DECL_RE = re.compile(r"^\s*(\w+)\s*:\s*(in|out|inout)\b(.*)$", re.IGNORECASE | re.DOTALL)
_GENERIC_RE = re.compile(r"^\s*(\w+)\s*:\s*\w+\s*:=\s*(.+?)\s*$", re.DOTALL)
_VECTOR_BOUNDS_RE = re.compile(
    r"^\s*(.+?)\s+(to|downto)\s+(.+?)\s*$", re.IGNORECASE | re.DOTALL
)


def strip_comments(text: str) -> str:
    """Remove ``--`` line comments (safe: no string literals in port clauses)."""
    return _COMMENT_RE.sub("", text)


def match_paren(text: str, open_idx: int) -> int:
    """Given index of ``(``, return index just past the matching ``)``."""
    if text[open_idx] != "(":
        raise ValueError("expected '(' at %d" % open_idx)
    depth = 0
    for i in range(open_idx, len(text)):
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i + 1
    raise ValueError("unbalanced parentheses")


def split_top_level(text: str, sep: str = ";") -> List[str]:
    """Split on ``sep`` occurring outside parentheses."""
    out: List[str] = []
    depth = 0
    start = 0
    for i, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == sep and depth == 0:
            out.append(text[start:i])
            start = i + 1
    out.append(text[start:])
    return out


def eval_int_expr(expr: str, generics: Dict[str, int]) -> Optional[int]:
    """Evaluate a VHDL integer expression (``+ - * / **``, parens, generics).

    Deliberately tiny and safe: only integer AST nodes and names bound to
    previously parsed generic defaults.  Returns None when unresolvable.
    """
    expr = expr.strip()
    if not expr:
        return None

    def _eval(node: ast.AST) -> int:
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            return int(node.value)
        if isinstance(node, ast.Name):
            if node.id in generics:
                return int(generics[node.id])
            raise ValueError("unknown identifier %r" % node.id)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            val = _eval(node.operand)
            return -val if isinstance(node.op, ast.USub) else val
        if isinstance(node, ast.BinOp):
            lhs, rhs = _eval(node.left), _eval(node.right)
            if isinstance(node.op, ast.Add):
                return lhs + rhs
            if isinstance(node.op, ast.Sub):
                return lhs - rhs
            if isinstance(node.op, ast.Mult):
                return lhs * rhs
            if isinstance(node.op, ast.Pow):
                if rhs < 0 or rhs > 64:
                    raise ValueError("absurd exponent")
                return int(lhs ** rhs)
            if isinstance(node.op, (ast.Div, ast.FloorDiv)):
                if rhs == 0:
                    raise ValueError("divide by zero")
                return int(lhs // rhs)  # VHDL integer "/" truncates
            raise ValueError("unsupported operator")
        raise ValueError("unsupported node %s" % type(node).__name__)

    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return None
    try:
        return _eval(tree)
    except (ValueError, TypeError, OverflowError):
        return None


def parse_generics(body: str) -> Dict[str, int]:
    """Parse ``name : type := default`` from the text inside ``generic( ... )``."""
    generics: Dict[str, int] = {}
    for decl in split_top_level(strip_comments(body)):
        gm = _GENERIC_RE.match(decl.strip())
        if not gm:
            continue
        try:
            generics[gm.group(1)] = int(gm.group(2).strip())
        except ValueError:
            pass  # non-integer generic -- bounds referencing it stay unresolved
    return generics


def parse_port_clause(text: str, entity_name: str) -> Tuple[Optional[str], Dict[str, int]]:
    """Locate and extract the entity's port-clause body + generic defaults."""
    m = re.search(r"\bentity\s+%s\s+is\b" % re.escape(entity_name), text, re.IGNORECASE)
    if not m:
        return None, {}
    after_entity = text[m.end() :]
    pm = _PORT_OPEN_RE.search(after_entity)
    if not pm:
        return None, {}
    # Generic clause lives between `entity X is` and `port(` (if present).
    generics: Dict[str, int] = {}
    gm = _GENERIC_OPEN_RE.search(after_entity[: pm.start()])
    if gm:
        g_open = m.end() + gm.end() - 1  # absolute index of '('
        generics = parse_generics(
            text[g_open + 1 : match_paren(text, g_open) - 1]
        )
    p_open = m.end() + pm.end() - 1  # absolute index of '('
    return text[p_open + 1 : match_paren(text, p_open) - 1], generics


def classify(name: str, base_type: str) -> str:
    """Return one of ``pervasive`` / ``control`` / ``data`` (rule-table order)."""
    if base_type in PERVASIVE_TYPES:
        return "pervasive"
    if any(re.fullmatch(pat, name, re.IGNORECASE) for pat in PERVASIVE_NAME_RES):
        return "pervasive"
    if any(re.fullmatch(pat, name, re.IGNORECASE) for pat in CONTROL_NAME_RES):
        return "control"
    return "data"


def parse_decl(decl: str, generics: Dict[str, int], entity: str) -> Optional[dict]:
    """Parse a single ``name : dir type`` port declaration into a manifest entry."""
    m = _DECL_RE.match(decl.strip())
    if not m:
        if decl.strip():
            print(
                "warning: %s: unparsed port declaration: %r"
                % (entity, " ".join(decl.split())[:100]),
                file=sys.stderr,
            )
        return None
    name, direction, type_text = m.group(1), m.group(2).lower(), m.group(3)
    type_text = " ".join(type_text.split())

    base_type = re.match(r"\w+", type_text).group(0)
    lo: Optional[int] = None
    hi: Optional[int] = None
    width: Optional[int] = TYPE_WIDTH.get(base_type)
    msb_first: Optional[bool] = None
    bounds_expr: Optional[str] = None

    if base_type == "std_ulogic_vector":
        open_idx = type_text.find("(")
        if open_idx < 0:
            print(
                "warning: %s: unconstrained vector port %r" % (entity, name),
                file=sys.stderr,
            )
        else:
            inner = type_text[open_idx + 1 : type_text.rfind(")")]
            bm = _VECTOR_BOUNDS_RE.match(inner)
            if not bm:
                print(
                    "warning: %s: unparseable vector bounds on %r: %r"
                    % (entity, name, inner),
                    file=sys.stderr,
                )
            else:
                direction_kw = bm.group(2).lower()
                # A2I convention is MSB-first: `lo to hi` => index lo is MSB.
                msb_first = direction_kw == "to"
                lo = eval_int_expr(bm.group(1), generics)
                hi = eval_int_expr(bm.group(3), generics)
                if lo is None or hi is None:
                    bounds_expr = "%s %s %s" % (bm.group(1), bm.group(2), bm.group(3))
                else:
                    width = hi - lo + 1

    port = {
        "name": name,
        "dir": direction,
        "type": base_type,
        "type_raw": type_text,
        "lo": lo,
        "hi": hi,
        "width": width,
        "msb_first": msb_first,
        "role": classify(name, base_type),
    }
    if bounds_expr is not None:
        port["bounds_expr"] = bounds_expr
    return port


def parse_entity_file(path: Path, entity_name: str) -> Optional[dict]:
    """Parse one golden entity file into ``{"file": ..., "ports": [...]}``."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print("error: cannot read %s: %s" % (path, exc), file=sys.stderr)
        return None
    clause, generics = parse_port_clause(text, entity_name)
    if clause is None:
        print(
            "error: %s: no entity/port clause found for %s"
            % (path, entity_name),
            file=sys.stderr,
        )
        return None

    ports: List[dict] = []
    for decl in split_top_level(strip_comments(clause)):
        port = parse_decl(decl, generics, entity_name)
        if port is not None:
            ports.append(port)
    return {"file": rel_file_name(path), "ports": ports}


def rel_file_name(path: Path) -> str:
    """Repo-style relative path (``rel/src/vhdl/work/fuq_mul.vhdl``) if the
    source tree sits under a ``rel/`` directory, else just the file name."""
    parts = path.resolve().parts
    if "rel" in parts:
        idx = len(parts) - 1 - parts[::-1].index("rel")
        return "/".join(parts[idx:])
    return path.name


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

def summarize(kernels: Dict[str, dict]) -> List[dict]:
    rows = []
    for name, info in kernels.items():
        counts = {"pervasive": 0, "control": 0, "data": 0}
        for port in info["ports"]:
            counts[port["role"]] += 1
        rows.append(
            {
                "kernel": name,
                "file": info["file"],
                "ports": len(info["ports"]),
                **counts,
            }
        )
    return rows


def print_summary(rows: List[dict], skipped: List[str]) -> None:
    hdr = ("kernel", "file", "ports", "pervasive", "control", "data")
    table = [hdr] + [
        (
            r["kernel"],
            r["file"],
            str(r["ports"]),
            str(r["pervasive"]),
            str(r["control"]),
            str(r["data"]),
        )
        for r in rows
    ]
    widths = [max(len(row[i]) for row in table) for i in range(len(hdr))]
    print("port_counts / role_counts per kernel")
    print("-" * (sum(widths) + 3 * (len(widths) - 1)))
    for n, row in enumerate(table):
        print("  " + "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))
        if n == 0:
            print("  " + "  ".join("-" * w for w in widths))
    if rows:
        total = {
            "ports": sum(r["ports"] for r in rows),
            "pervasive": sum(r["pervasive"] for r in rows),
            "control": sum(r["control"] for r in rows),
            "data": sum(r["data"] for r in rows),
        }
        print(
            "  "
            + "  ".join(
                ["TOTAL".ljust(widths[0]), "".ljust(widths[1])]
                + [str(total[k]).ljust(widths[i]) for i, k in
                   enumerate(("ports", "pervasive", "control", "data"), start=2)]
            )
        )
    if skipped:
        print("skipped (missing/unparsable source): " + ", ".join(skipped))


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    script = Path(__file__).resolve()
    default_out = script.parent.parent / "kernels" / "manifest.json"

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC,
                    help="golden VHDL work library (read-only)")
    ap.add_argument("--out", type=Path, default=default_out,
                    help="output manifest path")
    args = ap.parse_args(argv)

    src: Path = args.src
    out: Path = args.out
    if not src.is_dir():
        print("error: source directory not found: %s" % src, file=sys.stderr)
        return 2

    manifest: Dict[str, dict] = {}
    skipped: List[str] = []
    for name in KERNELS:
        path = src / ("%s.vhdl" % name)
        if not path.is_file():
            print("warning: missing golden entity file: %s" % path, file=sys.stderr)
            skipped.append(name)
            continue
        info = parse_entity_file(path, name)
        if info is None:
            skipped.append(name)
            continue
        if not info["ports"]:
            print("warning: %s parsed zero ports" % name, file=sys.stderr)
            skipped.append(name)
            continue
        manifest[name] = info

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")

    rows = summarize(manifest)
    print_summary(rows, skipped)
    print("wrote %s (%d kernels, %d ports)"
          % (out, len(manifest), sum(r["ports"] for r in rows)))
    return 0 if manifest and not skipped else (1 if not manifest else 0)


if __name__ == "__main__":
    sys.exit(main())
