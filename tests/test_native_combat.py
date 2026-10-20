"""Builds native/combat (the combat plugin's game-independent core) and runs its C++ tests, when CMake and a C++
compiler are available; skipped otherwise (the Windows PC builds it with Visual Studio's tools)."""
import os
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "native", "combat")


def _compiler():
    return shutil.which("cmake") and (shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
                                      or shutil.which("cl"))


@unittest.skipUnless(_compiler(), "needs cmake and a C++ compiler")
class NativeCombatTests(unittest.TestCase):
    def test_core_builds_and_passes(self):
        with tempfile.TemporaryDirectory() as b:
            cfg = subprocess.run(["cmake", "-S", SRC, "-B", b, "-DCMAKE_BUILD_TYPE=Release"], capture_output=True,
                                 text=True)
            self.assertEqual(cfg.returncode, 0, cfg.stdout + cfg.stderr)
            build = subprocess.run(["cmake", "--build", b, "--config", "Release"], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
            test = subprocess.run(["ctest", "--output-on-failure", "-C", "Release"], cwd=b, capture_output=True,
                                  text=True)
            self.assertEqual(test.returncode, 0, test.stdout + test.stderr)


if __name__ == "__main__":
    unittest.main()
