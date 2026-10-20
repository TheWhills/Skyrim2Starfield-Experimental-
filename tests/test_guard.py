"""scripts/guard.py: game data and big files fail, except inside registered git submodules (third-party libraries)."""
import contextlib
import importlib.util
import io
import os
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("guard", os.path.join(ROOT, "scripts", "guard.py"))
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


def _write(root, rel, data=b"x"):
    path = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def _run(root):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = guard.main(root)
    return code, out.getvalue()


class GuardTests(unittest.TestCase):
    def test_submodule_contents_are_skipped(self):
        with tempfile.TemporaryDirectory() as root:
            _write(root, ".gitmodules", b'[submodule "lib"]\n\tpath = native/x/lib/dep\n\turl = https://example.invalid\n')
            _write(root, "native/x/lib/dep/huge.h", b"a" * (guard.MAX_BYTES + 1))
            _write(root, "native/x/lib/dep/tool.dll")
            _write(root, "native/x/src/ok.cpp", b"int main() {}\n")
            self.assertEqual(guard.submodule_paths(root), {"native/x/lib/dep"})
            code, out = _run(root)
            self.assertEqual(code, 0, out)

    def test_same_files_outside_a_submodule_fail(self):
        with tempfile.TemporaryDirectory() as root:
            _write(root, "native/x/lib/dep/huge.h", b"a" * (guard.MAX_BYTES + 1))
            _write(root, "native/x/lib/dep/tool.dll")
            code, out = _run(root)
            self.assertEqual(code, 1)
            self.assertIn("huge.h", out)
            self.assertIn("banned file type .dll", out)

    def test_only_the_listed_path_is_skipped(self):
        with tempfile.TemporaryDirectory() as root:
            _write(root, ".gitmodules", b'[submodule "a"]\n  path = lib/dep\n')
            _write(root, "lib/dep2/data.esm")                  # a sibling with a similar name is still checked
            _write(root, "other/lib/dep/data.esm")             # the same name elsewhere is still checked
            code, out = _run(root)
            self.assertEqual(code, 1)
            self.assertIn("lib/dep2/data.esm", out)
            self.assertIn("other/lib/dep/data.esm", out)


if __name__ == "__main__":
    unittest.main()
