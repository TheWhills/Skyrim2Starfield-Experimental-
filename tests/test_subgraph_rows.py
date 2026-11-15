"""scripts/armor/subgraph_rows.py: subgraph table rows naming given keywords, any role, on a synthetic table."""
import contextlib
import io
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
import subgraph_rows as S  # noqa: E402

TABLE = ("Role\tPerspective\tActor Keyword(s)\tTarget Keyword(s)\tBehavior Path\tAnimation Path(s)\n"
         "Furniture\t3rd\tFemale\tAnimFurnChair\tA\\Furn.agx\tfurniture\\chair\\female, furniture\\chair\n"
         "Dialogue\t3rd\t\tAnimFurnChair\tA\\Dlg.agx\tdialogue\\sitting\n"
         "Weapon\t3rd\tAnimArchetypePlayer\tAnimOneHanded\tA\\W.agx\tmelee\n"
         "Additive\t3rd\t\t\tA\\Conversation.agx\tcommon\\talk\n")


class SubgraphRowsTest(unittest.TestCase):
    def test_any_role_naming_the_keyword_and_talk_graphs(self):
        rows = S.stance_plugin.parse_table(TABLE)
        got = S.matching(rows, ["animfurnchair"])
        self.assertEqual([r["role"] for r in got], ["Furniture", "Dialogue", "Additive"])
        self.assertEqual([r["role"] for r in S.matching(rows, ["AnimFurnChair"], talky=False)],
                         ["Furniture", "Dialogue"])

    def test_main_reads_a_table_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "humanrace.txt")
            with open(p, "w") as fh:
                fh.write(TABLE)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(S.main(["--table", p, "--keyword", "AnimFurnChair", "--no-talky"]), 0)
        out = buf.getvalue()
        self.assertIn("4 rows; 2 match: Dialogue 1, Furniture 1", out)
        self.assertIn("Dialogue | 3rd | actor - | target AnimFurnChair | Dlg.agx | dialogue\\sitting", out)


if __name__ == "__main__":
    unittest.main()
