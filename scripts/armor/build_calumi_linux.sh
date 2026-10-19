#!/usr/bin/env bash
# Build CALUMI.Animation (github.com/Calaverah/CALUMI.Animation, LGPL-3.0) as a Linux shared library, OUTSIDE this
# repository, so the .hkx -> .af chain (scripts/armor/hkx_to_af.py) can run and be checked on Linux. No CALUMI source
# enters this repo: this script clones it and applies portability edits to the clone.
#
#   bash scripts/armor/build_calumi_linux.sh <work dir outside the repo>   -> <work dir>/libcalumi.so
#
# Edits (2026-10-19, commit b0f3b5c; each only makes MSVC-specific code build with g++ 13 / C++23):
#   * framework.h: no <windows.h>; __declspec / __stdcall empty; _stricmp = strcasecmp; std::min / max / abs in scope.
#     `using std::abs` matters: unqualified abs(float) resolves to C's int abs under GCC, which broke the quaternion
#     encoder's "is |x| > 1/sqrt 2" test (rotations over 90 degrees came back clamped near 90).
#   * shims for <print> (std::print via std::format), corecrt_math_defines.h, objbase.h.
#   * PathContainer::w_str keeps a std::wstring (Linux paths are narrow); fstreams open std::filesystem::path.
#   * explicit namespace qualifications on two definitions removed; path.c_str() -> path.wstring().c_str() where a
#     wchar_t* overload is meant.
set -euo pipefail
WORK="${1:?usage: build_calumi_linux.sh <work dir outside the repo>}"
COMMIT="b0f3b5c49d7e380c2fde0f8b7174f2771dee4659"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
case "$(cd "$(dirname "$WORK")" 2>/dev/null && pwd)/$(basename "$WORK")" in "$REPO_ROOT"*) echo "work dir must be outside the repo"; exit 2;; esac
mkdir -p "$WORK"
cd "$WORK"
[ -d CALUMI.Animation ] || git clone -q https://github.com/Calaverah/CALUMI.Animation.git
git -C CALUMI.Animation checkout -q "$COMMIT"
rm -rf build && mkdir -p build/shim && cp CALUMI.Animation/CALUMI.Animation/*.{cpp,h} build/ && cd build
rm -f dllmain.cpp
cat > framework.h <<'EOF'
#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <cmath>
#include <cstdlib>
#include <strings.h>
#include <algorithm>
#include <format>
#include <string>
#include <filesystem>
#define __declspec(x)
#define __stdcall
#define __cdecl
#define _stricmp strcasecmp
using std::min; using std::max; using std::abs;
EOF
cat > shim/print <<'EOF'
#pragma once
#include <format>
#include <cstdio>
#include <string>
namespace std {
template <class... A> void print(std::format_string<A...> f, A&&... a) { std::fputs(std::format(f, std::forward<A>(a)...).c_str(), stdout); }
template <class... A> void println(std::format_string<A...> f, A&&... a) { std::puts(std::format(f, std::forward<A>(a)...).c_str()); }
template <class... A> void print(FILE* o, std::format_string<A...> f, A&&... a) { std::fputs(std::format(f, std::forward<A>(a)...).c_str(), o); }
template <class... A> void println(FILE* o, std::format_string<A...> f, A&&... a) { std::fputs((std::format(f, std::forward<A>(a)...) + "\n").c_str(), o); }
}
EOF
printf '#pragma once\n#define _USE_MATH_DEFINES\n#include <cmath>\n' > shim/corecrt_math_defines.h
printf '#pragma once\n#include <cstdlib>\n' > shim/objbase.h
python3 - <<'EOF'
import re
def edit(p, f):
    s = open(p, encoding="latin-1").read(); t = f(s)
    if t == s: raise SystemExit(f"edit did not apply: {p}")
    open(p, "w", encoding="latin-1").write(t)
edit("CALUMI_Utilities.cpp", lambda s: s.replace(
    "std::string cStringHolder;", "std::string cStringHolder;\n\t\t\tstd::wstring wStringHolder;", 1).replace(
    "return pImpl->path.c_str();\n\t\t}", "pImpl->wStringHolder = pImpl->path.wstring();\n\t\t\treturn pImpl->wStringHolder.c_str();\n\t\t}", 1))
edit("FileValidation.cpp", lambda s: s.replace("std::ifstream file(inputPath.w_str(), ", "std::ifstream file(std::filesystem::path(inputPath.w_str()), ")
     .replace("std::ofstream(outputPath.w_str(), ", "std::ofstream(std::filesystem::path(outputPath.w_str()), "))
edit("CALUMI_Math.cpp", lambda s: s.replace("CALUMI::Math::operator/", "operator/"))
edit("CALUMI_AnimationScene.cpp", lambda s: re.sub(r"(\n\s*[\w:<>\*& ]+?\s)UNIV::(\w+C\()", r"\1\2", s))
edit("SFBGS_AnimationScene.cpp", lambda s: re.sub(r"((?:WriteToFile|ReadFromFile)\()([\w\.\(\)]+?)\.c_str\(\)\)", r"\1\2.wstring().c_str())", s))
EOF
for f in *.cpp; do g++ -std=c++23 -O2 -fPIC -fpermissive -w -Ishim -include framework.h -c "$f" -o "${f%.cpp}.o"; done
g++ -shared -o "$WORK/libcalumi.so" ./*.o
echo "built $WORK/libcalumi.so (CALUMI $COMMIT)"
