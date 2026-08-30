#!/bin/sh
# Drop the grainifier module into a darktable source tree, register it, and build.
#
#   darktable/build.sh /path/to/darktable-src [build-dir]
#
# Idempotent: re-run after editing grainifier.c. Registers the module in src/iop/CMakeLists.txt
# and inserts it right after "grain" in every pipeline-order table of src/common/iop_order.c.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
DT=${1:?darktable source dir}
BUILD=${2:-$DT/build}

cp "$HERE/grainifier.c" "$HERE/grainifier_profiles.h" "$DT/src/iop/"

grep -q 'add_iop(grainifier' "$DT/src/iop/CMakeLists.txt" || \
  sed -i.bak 's|^add_iop(grain "grain.c")|add_iop(grain "grain.c")\nadd_iop(grainifier "grainifier.c")|' "$DT/src/iop/CMakeLists.txt"

grep -q '"grainifier"' "$DT/src/common/iop_order.c" || python3 - "$DT/src/common/iop_order.c" <<'EOF'
import re, sys
p = sys.argv[1]; s = open(p).read()
# after every table entry  { {65.0f }, "grain", 0},  add a grainifier entry 0.5 later, same style
pat = re.compile(r'(\n(\s*)\{ *\{ *([0-9.]+)f *\}, *"grain", *0 *\},?[^\n]*)')
s2 = pat.sub(lambda m: m.group(1) + "\n" + m.group(2) + "{ {" + f"{float(m.group(3)) + 0.5:.1f}" + 'f }, "grainifier", 0},', s)
assert s2.count('"grainifier"') >= 4, "iop_order patch failed"
open(p, "w").write(s2)
print("iop_order.c: added", s2.count('"grainifier"'), "entries")
EOF

mkdir -p "$BUILD"
cd "$BUILD"
if [ ! -f CMakeCache.txt ]; then
  BREW=$(brew --prefix 2>/dev/null || echo /usr/local)
  cmake -G Ninja "$DT" \
    -DCMAKE_BUILD_TYPE=RelWithDebInfo \
    -DCMAKE_INSTALL_PREFIX="$BUILD/install" \
    -DCMAKE_PREFIX_PATH="$BREW" \
    -DOpenMP_C_INCLUDE_DIR="$BREW/opt/libomp/include" -DOpenMP_CXX_INCLUDE_DIR="$BREW/opt/libomp/include" \
    -DCMAKE_LIBRARY_PATH="$BREW/opt/libomp/lib" \
    -DUSE_LUA=OFF -DUSE_GMIC=OFF -DUSE_GRAPHICSMAGICK=OFF -DUSE_PORTMIDI=OFF -DUSE_MAP=OFF -DUSE_LIBSECRET=OFF -DUSE_KWALLET=OFF \
    -DBUILD_CMSTEST=OFF -DBUILD_PRINT=OFF -DUSE_CAMERA_SUPPORT=OFF -DBUILD_SSE2_CODEPATHS=OFF
fi
ninja
echo "built: $BUILD/lib/darktable/plugins/libgrainifier.so (or .dylib)"
