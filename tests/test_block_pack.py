"""scripts/armor/block_pack.py: the block transitions get the requested blend times, nothing else changes."""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
import block_pack as B  # noqa: E402


def link(event, blend):
    return ("<link><node>1</node><property_sheet>\r\n<row><prop> <type>2</type> <value>Event</value> </prop>"
            f"<prop> <type>2</type> <value>{event}</value> </prop></row>\r\n<row><prop> <type>2</type> "
            f"<value>Blend Time</value> </prop><prop> <type>1</type> <value>{blend}</value> </prop></row>\r\n"
            "</property_sheet></link>\r\n")


GRAPH = ("<root>\r\n" + link("BlockStart", "0.3") + link("BlockStart", "0.3") + link("BlockStop", "0.3")
         + link("BlockHitStart", "0.1") + link("CastSelfStart", "0.3") + "</root>\r\n").encode()


class BlockPackTests(unittest.TestCase):
    def test_build(self):
        out, rep = B.build(GRAPH, 0.08, 0.2)
        self.assertEqual((rep["BlockStart"], rep["BlockStop"]), (2, 1))
        self.assertEqual(out.count(b"<value>0.08</value>"), 2)
        self.assertEqual(out.count(b"<value>0.2</value>"), 1)
        self.assertIn(link("CastSelfStart", "0.3").encode(), out)
        self.assertIn(link("BlockHitStart", "0.1").encode(), out)

    def test_main_writes_the_graph(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "meleeactions.agx")
            with open(src, "wb") as fh:
                fh.write(GRAPH)
            B.main(["--graph", src, "--out", os.path.join(tmp, "pack")])
            with open(os.path.join(tmp, "pack", *B.GRAPH_PATH), "rb") as fh:
                self.assertEqual(fh.read().count(b"<value>0.1</value>"), 3)     # 2 raises + the untouched hit link


if __name__ == "__main__":
    unittest.main()
