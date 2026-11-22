# golden/ — frozen A2I datapath layer

This directory mirrors the byte-frozen Tier-A kernel source. Do **not** copy
files here; the manifest (`tools/manifest.sha256`) references the canonical
sources under `../rel/src/vhdl/` and this layer is read-only by design.

Structure:

- `vhdl/`  — (placeholder for extracted golden fileset symlinks; sources stay
  under `rel/src/vhdl/` to keep the manifest paths stable)

Verification gate: `python3 ../tools/check_manifest.py` — all Tier-A entries
must print `silicon-proven` and the run must end with `golden layer intact`.

Any modification to a Tier-A file invalidates the manifest and is a defect;
produce a new provenance version instead.
