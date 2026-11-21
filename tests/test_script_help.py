"""Every script's argparse help must format (Python 3.14 rejects a bare % in a help text at add_argument; 2026-11-21
the owner's build stopped on make_skyrim_interior's --meter-darks)."""
import ast
import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


def help_strings(path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "add_argument":
            for kw in node.keywords:
                if kw.arg == "help":
                    try:
                        yield node.lineno, ast.literal_eval(kw.value)
                    except ValueError:
                        pass


class HelpStringTest(unittest.TestCase):
    def test_no_bare_percent_in_any_help(self):
        bad = []
        for p in sorted((ROOT / "scripts").rglob("*.py")) + sorted((ROOT / "src").rglob("*.py")):
            for line, text in help_strings(p):
                try:
                    text % {"prog": "x", "default": 0, "type": "x", "dest": "x", "metavar": "x", "choices": "x",
                            "required": False, "nargs": None, "const": None, "option_strings": [], "help": ""}
                except (TypeError, ValueError, KeyError) as e:
                    bad.append(f"{p.relative_to(ROOT)}:{line}: {e}")
        self.assertEqual(bad, [])

    def test_make_skyrim_interior_help_formats(self):
        sys.path.insert(0, str(ROOT / "scripts" / "interior"))
        sys.path.insert(0, str(ROOT / "src"))
        spec = importlib.util.spec_from_file_location("msi_help", ROOT / "scripts" / "interior" / "make_skyrim_interior.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        self.assertIn("darkest pixels", m.parser().format_help())


if __name__ == "__main__":
    unittest.main()
