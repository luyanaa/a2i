"""Amaranth CPU IP generator — wraps frozen A2I datapath kernels with
generated pipeline control. Two pipeline profiles share the kernel set:

  - a2i: in-order (IF -> ID -> RF -> EX -> WB, scoreboard interlock)
  - a2o: out-of-order (dispatch -> rename -> RS -> issue -> CDB -> complete)

Golden kernels are instantiated as Amaranth Instance blackboxes; their port
maps come from chisel/kernels/manifest.json (auto-generated from the VHDL
entities). No frozen source is modified.
"""

from .kernel import Kernel, load_manifest  # noqa: F401
