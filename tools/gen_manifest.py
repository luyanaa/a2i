#!/usr/bin/env python3
"""Generate the P0 freeze manifest for the A2I golden-layer scaffold.

Tier-A files are the silicon-proven BlueGene/Q datapath leaf kernels plus the
support libraries they depend on. They are byte-frozen: any change requires a
new provenance version, never an in-place edit.

Tier-B files are A2O-only local units that will be back-ported to VHDL in a
later pass; they are listed separately and start as "converted-unverified".

Run:  python3 tools/gen_manifest.py > tools/manifest.sha256
Then: python3 tools/check_manifest.py   (verifies hashes)
"""
import hashlib
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "rel", "src", "vhdl")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# Support libraries every kernel needs (must be frozen, they carry the
# clk_logic record, power_logic type, and tri latch/array macros).
TIER_A_LIBS = [
    "ibm/std_ulogic_support.vhdl",
    "ibm/std_ulogic_unsigned.vhdl",
    "ibm/std_ulogic_function_support.vhdl",
    "ibm/std_ulogic_ao_support.vhdl",
    "ibm/std_ulogic_mux_support.vhdl",
    "support/power_logic_pkg.vhdl",
    "clib/c_prism_csa32.vhdl",
    "clib/c_prism_csa42.vhdl",
    "clib/c_prism_bthmx.vhdl",
    "clib/c_event_mux.vhdl",
    "clib/c_debug_mux4.vhdl",
    "clib/c_debug_mux8.vhdl",
    "clib/c_debug_mux16.vhdl",
    "clib/c_debug_mux32.vhdl",
    "clib/c_scom_addr_decode.vhdl",
]

# Frozen FPU leaf kernels (ISA-neutral arithmetic datapath).
TIER_A_FPU = [
    "work/fuq_alg.vhdl", "work/fuq_alg_add.vhdl", "work/fuq_alg_bypmux.vhdl",
    "work/fuq_alg_or16.vhdl", "work/fuq_alg_sh16.vhdl", "work/fuq_alg_sh4.vhdl",
    "work/fuq_add.vhdl", "work/fuq_add_all1.vhdl", "work/fuq_add_glbc.vhdl",
    "work/fuq_nrm.vhdl", "work/fuq_nrm_or16.vhdl", "work/fuq_nrm_sh.vhdl",
    "work/fuq_lza.vhdl", "work/fuq_lza_clz.vhdl", "work/fuq_lza_ej.vhdl",
    "work/fuq_lze.vhdl",
    "work/fuq_hc16pp.vhdl", "work/fuq_hc16pp_lsb.vhdl", "work/fuq_hc16pp_msb.vhdl",
    "work/fuq_csa22_h2.vhdl",
    "work/fuq_mul.vhdl", "work/fuq_mul_62.vhdl", "work/fuq_mul_92.vhdl",
    "work/fuq_mul_bthdcd.vhdl", "work/fuq_mul_bthmux.vhdl", "work/fuq_mul_bthrow.vhdl",
    "work/fuq_tblexp.vhdl", "work/fuq_tbllut.vhdl", "work/fuq_tblres.vhdl",
    "work/fuq_tblsqe.vhdl", "work/fuq_tblsqo.vhdl",
    "work/fuq_tblmul.vhdl", "work/fuq_tblmul_bthdcd.vhdl", "work/fuq_tblmul_bthrow.vhdl",
    "work/fuq_sa3.vhdl",
    "work/fuq_gst.vhdl", "work/fuq_gst_add11.vhdl", "work/fuq_gst_inc19.vhdl",
    "work/fuq_gst_loa.vhdl",
    "work/fuq_loc8inc.vhdl", "work/fuq_loc8inc_lsb.vhdl",
]

# Frozen FXU/ALU leaf kernels (+ packages they depend on).
TIER_A_FXU = [
    "work/xuq_pkg.vhdl", "work/a2x_pkg.vhdl", "work/iuq_pkg.vhdl",
    "work/xuq_alu.vhdl", "work/xuq_alu_add.vhdl", "work/xuq_alu_or3232.vhdl",
    "work/xuq_add.vhdl", "work/xuq_add_csmux.vhdl", "work/xuq_add_glbglbci.vhdl",
    "work/xuq_add_glbloc.vhdl", "work/xuq_add_loc.vhdl",
    "work/xuq_alu_mrg.vhdl", "work/xuq_alu_mask.vhdl", "work/xuq_alu_ins.vhdl",
    "work/xuq_alu_rol64.vhdl", "work/xuq_alu_caor.vhdl",
    "work/xuq_alu_mult.vhdl", "work/xuq_alu_mult_boothdcd.vhdl",
    "work/xuq_alu_mult_boothrow.vhdl", "work/xuq_alu_mult_core.vhdl",
    "work/xuq_alu_mult_csa22.vhdl", "work/xuq_alu_div.vhdl",
    "work/xuq_agen.vhdl", "work/xuq_agen_cmp.vhdl", "work/xuq_agen_csmux.vhdl",
    "work/xuq_agen_csmuxe.vhdl", "work/xuq_agen_glbglb.vhdl",
    "work/xuq_agen_glbloc.vhdl", "work/xuq_agen_glbloc_lsb.vhdl",
    "work/xuq_agen_loca.vhdl", "work/xuq_agen_locae.vhdl", "work/xuq_agen_lo.vhdl",
]

# Remaining FPU control-adjacent arithmetic units that share the frozen leaf
# datapath (kept in the frozen set because they are datapath, not issue logic).
TIER_A_FPU_EXTRA = [
    "work/fuq_fmt.vhdl", "work/fuq_rnd.vhdl", "work/fuq_pic.vhdl",
    "work/fuq_cr2.vhdl", "work/fuq_eie.vhdl", "work/fuq_eov.vhdl",
    "work/fuq_byp.vhdl", "work/fuq_sto.vhdl", "work/fuq_fpr.vhdl",
    "work/fuq_dcd.vhdl", "work/fuq_dcd_uc_hooks.vhdl", "work/fuq_mad.vhdl",
    "work/fuq_scr.vhdl", "work/fuq_perv.vhdl", "work/fuq_tbllut.vhdl",
]

# tri latch/array library (frozen; the component/entity name cycle in
# tri_latches_pkg forces a specific analyze order — see tools/analyze.sh).
TIER_A_TRI = [os.path.join("tri", f) for f in sorted(os.listdir(os.path.join(SRC, "tri"))) if f.endswith(".vhdl")]

TIER_A = TIER_A_LIBS + TIER_A_FPU + TIER_A_FXU + TIER_A_FPU_EXTRA + TIER_A_TRI

# Tier-B: A2O-only local units to back-port (converted-unverified).
TIER_B = [
    "work/fuq_divsqrt.vhdl", "work/fuq_divsqrt_add4.vhdl",
    "work/fuq_divsqrt_q_table.vhdl", "work/fuq_divsqrt_nq_table.vhdl",
    "work/xuq_bcd.vhdl", "work/xuq_bcd_bcdtd.vhdl", "work/xuq_bcd_dtbcd.vhdl",
    "work/xuq_dlmzb.vhdl", "work/xuq_div_r4.vhdl", "work/xuq_bprm.vhdl",
    "tri/tri_popcnt.vhdl", "tri/tri_popcnt_byte.vhdl", "tri/tri_popcnt_word.vhdl",
    "tri/tri_cntlz.vhdl", "tri/tri_cntlz_8b.vhdl",
]

def main():
    out = []
    out.append("# A2I golden-layer manifest (P0)")
    out.append("# generated by tools/gen_manifest.py — do not hand-edit")
    out.append("# tier  sha256  relpath  status")
    for rel in TIER_A:
        p = os.path.join(SRC, rel)
        if not os.path.exists(p):
            sys.stderr.write(f"MISSING tierA: {rel}\n")
            continue
        out.append(f"A\t{sha256(p)}\t{rel}\tsilicon-proven")
    # dedup while preserving order
    seen=set(); dedup=[]
    for l in out:
        if l.startswith("A\t"):
            rel=l.split("\t")[2]
            if rel in seen: continue
            seen.add(rel)
        dedup.append(l)
    out=dedup
    for rel in TIER_B:
        p = os.path.join(SRC, rel)
        status = "converted-unverified" if not os.path.exists(p) else "present"
        h = sha256(p) if os.path.exists(p) else "PENDING"
        out.append(f"B\t{h}\t{rel}\t{status}")
    print("\n".join(out))


if __name__ == "__main__":
    main()
