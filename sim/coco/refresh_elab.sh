#!/usr/bin/env bash
# Refresh obsoleted work units (left side of "X is obsoleted by Y") until a2x_axi elaborates.
set -u
cd /tmp/opencode/a2x-sim
WORKDIR=/shared/a2i/rel/src/vhdl/work
TRIDIR=/tmp/opencode/a2x-sim/sim_shadow/tri
GH=/shared/oss-cad-suite/bin/ghdl
W=/tmp/opencode/a2x-sim/wd
F="--std=08 -frelaxed -fsynopsys"
P="-P$W/ibm2 -P$W/support -P$W/clib -P$W/tri -P$W/unimacro -P$W/work"
for i in $(seq 1 12); do
  echo "=== iter $i elab ==="
  rm -f a2x_axi
  $GH -e $F --work=work --workdir=$W/work $P a2x_axi > elab.log 2>&1
  if [ $? -eq 0 ]; then echo "ELAB OK"; exit 0; fi
  # obsoleted units: 'architecture "X" of "Y" is obsoleted' or 'entity "Y" is obsoleted'
  obs=$(grep -oP '(architecture "[a-z0-9_]+" of "|\bentity ")\K[a-z0-9_]+' elab.log | sort -u)
  if [ -z "$obs" ]; then echo "NON-OBSOLETE FAILURE:"; grep -v warning elab.log | tail -8; exit 1; fi
  for u in $obs; do
    if [ -f "$TRIDIR/$u.vhdl" ]; then f="$TRIDIR/$u.vhdl"; lib=tri; else f="$WORKDIR/$u.vhdl"; lib=work; fi
    [ -f "$f" ] || { echo "no source: $u"; continue; }
    echo "refreshing $u ($lib)"
    $GH -a $F --work=$lib --workdir=$W/$lib $P "$f" >> elab.log 2>&1 || echo "refresh failed: $u"
  done
done
echo GAVE-UP
