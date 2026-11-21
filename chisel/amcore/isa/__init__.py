"""ISA decode tables -> control signals, shared by both pipeline profiles.

The golden A2I decode (`fuq_dcd`, `xuq_dec`) is a big flat ROM producing a
`f_dcd_rf1_*` control bundle per instruction. The generator emits that same
contract from a compact per-ISA table so a new instruction = one table row,
not new RTL.
"""

from .ppc64 import (  # noqa: F401
    Decoded,
    XO_FCFID,
    XO_FMSUB,
    XO_FMUL,
    XO_FNMSUB,
    decode,
)
