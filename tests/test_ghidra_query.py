"""scripts/re/ghidra_query.py (2026-11-24): command checks and the headless command line (no Ghidra needed)."""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "re"))

import ghidra_query as Q  # noqa: E402


class CheckCommands(unittest.TestCase):
    def test_keeps_known_drops_blank_and_comments(self):
        lines = ["", "# note", " decomp 0x140bf45f0 ", "insn 0x1 0x2 \\+ 0x260\\]"]
        self.assertEqual(Q.check_commands(lines), ["decomp 0x140bf45f0", "insn 0x1 0x2 \\+ 0x260\\]"])

    def test_rejects_unknown(self):
        with self.assertRaises(ValueError):
            Q.check_commands(["disassemble 0x1"])


class HeadlessCommand(unittest.TestCase):
    def test_project_split_and_gpr_suffix(self):
        cmd = Q.headless_command(os.path.join("G", "ghidra"), os.path.join("P", "Starfiled 44.gpr"),
                                 "Starfield.exe.1", "cmds.txt", "out.txt", script_dir="S")
        self.assertEqual(cmd[1:3], ["P", "Starfiled 44"])
        self.assertIn("-readOnly", cmd)
        self.assertIn("-noanalysis", cmd)
        i = cmd.index("-process")
        self.assertEqual(cmd[i + 1], "Starfield.exe.1")
        self.assertEqual(cmd[-4:], ["-postScript", "QueryDump.java", "cmds.txt", "out.txt"])
        self.assertTrue(cmd[0].startswith(os.path.join("G", "ghidra", "support", "analyzeHeadless")))


if __name__ == "__main__":
    unittest.main()
