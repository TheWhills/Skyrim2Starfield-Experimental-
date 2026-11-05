"""scripts/armor/os_probe.py: talking to Outfit Studio's MCP server, against a fake server on localhost only."""
import base64
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "armor"))
import os_probe as OP  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\nfake"
BODY = "meshes\\actors\\human\\characterassets\\female\\naked_f.nif"
TOOLS = [
    {"name": "get_status", "description": "Shapes, reference and sliders. More text.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "browse_archives", "description": "Lists archive files.",
     "inputSchema": {"type": "object", "properties": {"filter": {}, "pattern": {}, "folder": {}}}},
    {"name": "get_step_schema", "description": "Automation steps.", "inputSchema": {"type": "object"}},
    {"name": "load_from_archive", "description": "Loads files.",
     "inputSchema": {"type": "object", "properties": {"files": {}, "mode": {}}, "required": ["files"]}},
    {"name": "render_view", "description": "Renders.", "inputSchema": {"type": "object", "properties": {"views": {}}}},
    {"name": "list_shapes", "description": "Shapes.", "inputSchema": {"type": "object"}},
]


class Fake(BaseHTTPRequestHandler):
    calls = []
    sse = False

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if body.get("method") != "initialize":
            assert self.headers.get("Mcp-Session-Id") == "s1", "session header missing"
        if "id" not in body:                                   # a notification
            self.send_response(202)
            self.end_headers()
            return
        m, p = body["method"], body.get("params", {})
        if m == "initialize":
            res = {"protocolVersion": OP.PROTOCOL, "serverInfo": {"name": "Outfit Studio", "version": "6.1.0"},
                   "capabilities": {"tools": {}}}
        elif m == "tools/list":
            res = ({"tools": TOOLS[:3], "nextCursor": "c2"} if not p.get("cursor") else {"tools": TOOLS[3:]})
        elif m == "tools/call":
            Fake.calls.append((p["name"], p["arguments"]))
            name = p["name"]
            if name == "browse_archives" and p["arguments"].get("filter") == "naked":
                res = {"content": [{"type": "text", "text": json.dumps(
                    {"files": [BODY, "meshes\\clothes\\naked_f_old\\x.nif", "meshes\\a\\naked_m.nif"]})}]}
            elif name == "get_step_schema":
                res = {"content": [{"type": "text", "text": "busy: a dialog is open"}], "isError": True}
            elif name == "render_view":
                res = {"content": [{"type": "image", "mimeType": "image/png",
                                    "data": base64.b64encode(PNG).decode()}]}
            else:
                res = {"content": [{"type": "text", "text": f"{name} ok"}]}
        else:
            res = None
        msg = {"jsonrpc": "2.0", "id": body["id"], "result": res}
        if res is None:
            msg = {"jsonrpc": "2.0", "id": body["id"], "error": {"code": -32601, "message": "no such method"}}
        self.send_response(200)
        if m == "initialize":
            self.send_header("Mcp-Session-Id", "s1")
        if Fake.sse:
            data = ("event: message\ndata: " + json.dumps({"jsonrpc": "2.0", "method": "notifications/progress"})
                    + "\n\nevent: message\ndata: " + json.dumps(msg) + "\n\n").encode()
            self.send_header("Content-Type", "text/event-stream")
        else:
            data = json.dumps(msg).encode()
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class ProbeTests(unittest.TestCase):
    def setUp(self):
        Fake.calls = []
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/mcp"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        Fake.sse = False

    def _probe(self, **kw):
        out = tempfile.mkdtemp()
        return out, OP.probe(OP.Client(self.url, timeout=10), out, **kw)

    def test_read_only_probe(self):
        out, rep = self._probe()
        self.assertEqual(rep["server"]["version"], "6.1.0")
        self.assertEqual(rep["tools"], 6)                        # both pages of tools/list
        self.assertIn("list_reference_templates", rep["missing"])
        names = [c[0] for c in Fake.calls]
        self.assertNotIn("load_from_archive", names)            # nothing changes without --load-body
        self.assertEqual(names.count("browse_archives"), 3)
        failed = [c for c in rep["calls"] if c["error"]]
        self.assertEqual(len(failed), 1)
        self.assertIn("busy", failed[0]["text"])
        tools_txt = open(os.path.join(out, "tools.txt")).read()
        self.assertIn("load_from_archive(files, mode?) - Loads files.", tools_txt)
        self.assertIn("get_status() - Shapes, reference and sliders.", tools_txt)
        self.assertTrue(os.path.exists(os.path.join(out, "report.txt")))
        self.assertEqual(len(json.load(open(os.path.join(out, "tools.json")))), 6)

    def test_load_body_auto_over_event_stream(self):
        Fake.sse = True
        out, rep = self._probe(load_body="auto")
        self.assertEqual(rep["body"], BODY)
        self.assertIn(("load_from_archive", {"files": [BODY], "mode": "import"}), Fake.calls)
        img = [f for f in os.listdir(os.path.join(out, "calls")) if f.endswith(".png")]
        self.assertEqual(len(img), 1)
        with open(os.path.join(out, "calls", img[0]), "rb") as fh:
            self.assertEqual(fh.read(), PNG)
        saved = json.load(open(os.path.join(out, "calls", img[0].rsplit("_", 1)[0] + ".json")))
        self.assertEqual(saved["content"][0]["file"], img[0])

    def test_pick_body_and_helpers(self):
        listing = {"content": [{"type": "text", "text": "Found meshes\\x\\naked_f.nif and " + BODY}]}
        self.assertEqual(OP.pick_body(listing), BODY)
        self.assertIsNone(OP.pick_body({"content": []}))
        self.assertEqual(OP.parse_messages("application/json", b""), [])
        self.assertEqual(OP.parse_messages("application/json", b'[{"id":1},{"id":2}]'), [{"id": 1}, {"id": 2}])

    def test_unreachable_server(self):
        c = OP.Client("http://127.0.0.1:9/mcp", timeout=2)
        with self.assertRaises(OP.McpError) as e:
            c.initialize()
        self.assertIn("--mcp", str(e.exception))

    def test_out_inside_repo_refused(self):
        with self.assertRaises(SystemExit):
            OP.main(["--out", os.path.join(ROOT, "tmp_probe")])


if __name__ == "__main__":
    unittest.main()
