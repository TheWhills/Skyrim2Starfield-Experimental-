"""Look at Outfit Studio's automation server before building the armor conversion on it (owner 2026-11-05: BodySlide and
Outfit Studio v6.1.0, Nexus Starfield 18449, has Starfield as a target game and a built-in MCP server).

Plan (docs/ai/decisions.md 2026-11-05): Outfit Studio fits Skyrim armor to Starfield's body, copies its bone weights
and body morphs and exports .mesh / morph.dat; our Python picks the armor, drives Outfit Studio, converts materials
and writes the plugin. This probe finds out what its server really offers, so the driver is built on the real tool
names and arguments, not on what its guides suggest.

Start Outfit Studio first with Starfield as the target game and an empty project:
    OutfitStudio.exe --mcp          (or File > MCP Server; default port 47823, only this PC can connect)

    python -I scripts\\armor\\os_probe.py --out C:\\Modding\\work\\os_probe [--load-body auto | --load-body <archive path>]

Writes into --out:
  * server.json: the server's name, version and capabilities;
  * tools.json: every tool with its full argument schema; tools.txt: one line per tool (name, arguments, summary);
  * calls/<n>_<tool>.json: the result of each read-only call (status, reference templates, automation step schema,
    skeleton bones, archive listing of the Starfield bodies), images of renders as calls/<n>_<tool>_<i>.png;
  * report.txt: what was called, what failed.

Read-only, except --load-body: it imports one body mesh from the game's archives into the OPEN project (nothing is
saved; close Outfit Studio's project without saving afterwards). Without it nothing in Outfit Studio changes.
"""
import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))

DEFAULT_URL = "http://127.0.0.1:47823/mcp"
PROTOCOL = "2025-06-18"
CLIENT = {"name": "skyrim2starfield-os-probe", "version": "1"}

# (tool, arguments) called when the server has the tool; all read-only.
READ_CALLS = (
    ("get_status", {}),
    ("list_reference_templates", {}),
    ("list_slider_sets", {}),
    ("list_automation_scripts", {}),
    ("get_step_schema", {}),
    ("list_skeleton_bones", {"mainOnly": True, "withPoseInfo": True}),
    ("browse_archives", {}),
    ("browse_archives", {"filter": "naked"}),
    ("browse_archives", {"pattern": "*characterassets*body*"}),
    ("get_guide", {}),
)
MAX_GUIDES = 25
# After --load-body: what the loaded body looks like to Outfit Studio.
BODY_CALLS = (
    ("get_status", {}),
    ("list_shapes", {}),
    ("list_sliders", {}),
    ("validate_project", {}),
    ("render_view", {"views": ["front", "left"], "grid": True}),
)


class McpError(RuntimeError):
    pass


class Client:
    """A minimal MCP client over Streamable HTTP (JSON-RPC 2.0 POSTs; answers as JSON or as server-sent events)."""

    def __init__(self, url: str = DEFAULT_URL, token: str = "", timeout: float = 600.0, opener=None):
        self.url, self.token, self.timeout = url, token, timeout
        self.session = None
        self.protocol = None
        self._id = 0
        self._open = opener or urllib.request.urlopen

    def _post(self, body: dict):
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(self.url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json, text/event-stream")
        if self.token:
            req.add_header("Authorization", "Bearer " + self.token)
        if self.session:
            req.add_header("Mcp-Session-Id", self.session)
        if self.protocol:
            req.add_header("MCP-Protocol-Version", self.protocol)
        try:
            resp = self._open(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            raise McpError(f"HTTP {e.code} from {self.url}: {e.read()[:300]!r}") from e
        except urllib.error.URLError as e:
            raise McpError(f"cannot reach {self.url} ({e.reason}): is Outfit Studio running with --mcp?") from e
        with resp:
            sid = resp.headers.get("Mcp-Session-Id")
            if sid:
                self.session = sid
            return resp.status, resp.headers.get("Content-Type", ""), resp.read()

    def request(self, method: str, params: dict = None) -> dict:
        self._id += 1
        rid = self._id
        status, ctype, raw = self._post({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        msg = None
        for m in parse_messages(ctype, raw):
            if m.get("id") == rid:
                msg = m
        if msg is None:
            raise McpError(f"{method}: no answer in the server's reply (HTTP {status}, {ctype})")
        if "error" in msg:
            err = msg["error"]
            raise McpError(f"{method}: {err.get('code')} {err.get('message')}")
        return msg.get("result", {})

    def notify(self, method: str, params: dict = None) -> None:
        self._post({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def initialize(self) -> dict:
        res = self.request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": CLIENT})
        self.protocol = res.get("protocolVersion", PROTOCOL)
        self.notify("notifications/initialized")
        return res

    def tools(self) -> list:
        out, cursor = [], None
        while True:
            res = self.request("tools/list", {"cursor": cursor} if cursor else {})
            out += res.get("tools", [])
            cursor = res.get("nextCursor")
            if not cursor:
                return out

    def call(self, name: str, arguments: dict) -> dict:
        return self.request("tools/call", {"name": name, "arguments": arguments})


def parse_messages(ctype: str, raw: bytes) -> list:
    """The JSON-RPC messages of a reply: one JSON body (object or batch list), or the `data:` lines of an event
    stream (an event's data lines joined by newlines)."""
    text = raw.decode("utf-8", "replace")
    if "text/event-stream" in ctype.lower():
        out, data = [], []
        for line in text.splitlines() + [""]:
            if line.startswith("data:"):
                data.append(line[5:].lstrip(" "))
            elif not line.strip() and data:
                try:
                    out.append(json.loads("\n".join(data)))
                except ValueError:
                    pass
                data = []
        return out
    if not text.strip():
        return []
    body = json.loads(text)
    return body if isinstance(body, list) else [body]


def tool_line(t: dict) -> str:
    """One line per tool: name(arg, arg?, ...) - first sentence of its description (? = optional)."""
    schema = t.get("inputSchema") or {}
    req = set(schema.get("required") or [])
    args = ", ".join(a if a in req else a + "?" for a in (schema.get("properties") or {}))
    desc = (t.get("description") or "").strip().split("\n")[0]
    desc = re.split(r"(?<=[.!?])\s", desc)[0]
    return f"{t.get('name')}({args}) - {desc}"


def _strings(obj):
    """Every string in a result, also inside JSON text (tools often answer with JSON in a text block)."""
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)
    elif isinstance(obj, str):
        yield obj
        if obj.lstrip()[:1] in ("{", "["):
            try:
                yield from _strings(json.loads(obj))
            except ValueError:
                pass


def pick_body(listing: dict, female: bool = True):
    """The vanilla naked body NIF out of browse_archives results: paths ending naked_f.nif / naked_m.nif, preferring
    ones under characterassets or named naked_body, then the shortest."""
    letter = "f" if female else "m"
    paths = sorted({p for text in _strings(listing) for p in re.findall(r"[\w\\/.-]+\.nif", text)
                    if re.search(rf"naked[^\\/]*_{letter}\.nif$", p, re.I)})
    paths.sort(key=lambda p: (("naked_body" not in p.lower()) and ("characterassets" not in p.lower()), len(p)))
    return paths[0].strip() if paths else None


def save_result(out: str, n: int, name: str, res: dict) -> dict:
    """calls/<n>_<name>.json with the result (images replaced by their PNG file names); returns a summary row."""
    calls = os.path.join(out, "calls")
    os.makedirs(calls, exist_ok=True)
    stem = f"{n:02d}_{name}"
    keep = dict(res)
    content = []
    for i, c in enumerate(res.get("content") or []):
        if c.get("type") == "image" and c.get("data"):
            ext = {"image/png": "png", "image/jpeg": "jpg"}.get(c.get("mimeType", ""), "bin")
            png = f"{stem}_{i}.{ext}"
            with open(os.path.join(calls, png), "wb") as fh:
                fh.write(base64.b64decode(c["data"]))
            content.append({"type": "image", "file": png, "mimeType": c.get("mimeType")})
        else:
            content.append(c)
    keep["content"] = content
    with open(os.path.join(calls, stem + ".json"), "w", encoding="utf-8") as fh:
        json.dump(keep, fh, indent=1)
    text = " ".join(c.get("text", "") for c in content if c.get("type") == "text")
    return {"call": stem, "error": bool(res.get("isError")), "text": text[:300]}


def guide_topics(res) -> list:
    """Topic names out of get_guide's answer without a topic (JSON {"topics": [...]} of names or {name / topic}, or
    a text list of '- name' lines)."""
    out = []

    def add(t):
        if isinstance(t, dict):
            t = t.get("topic") or t.get("name") or t.get("id")
        if isinstance(t, str) and t.strip() and t.strip() not in out:
            out.append(t.strip())
    for s in _strings(res):
        if s.lstrip()[:1] in ("{", "["):
            try:
                obj = json.loads(s)
            except ValueError:
                obj = None
            if isinstance(obj, dict) and isinstance(obj.get("topics"), list):
                for t in obj["topics"]:
                    add(t)
            continue
        for line in s.splitlines():
            m = re.match(r"^\s*[-*]\s+`?([A-Za-z0-9_./-]+)`?", line)
            if m:
                add(m.group(1))
    return out


def target_game(results) -> str:
    """'skyrim-like' when the archives Outfit Studio browses are .bsa files (2026-11-06: the owner's first run listed
    Skyrim's _ResourcePack.bsa: its target game was not Starfield), 'starfield-like' for .ba2, else 'unknown'."""
    names = [s.lower() for res in results.get("browse_archives", []) for s in _strings(res)]
    bsa = sum(n.endswith(".bsa") for n in names)
    ba2 = sum(n.endswith(".ba2") for n in names)
    return "skyrim-like" if bsa > ba2 else ("starfield-like" if ba2 else "unknown")


def probe(client: Client, out: str, load_body: str = None) -> dict:
    os.makedirs(out, exist_ok=True)
    report = {"server": None, "tools": 0, "calls": [], "missing": [], "body": None}
    init = client.initialize()
    report["server"] = init.get("serverInfo")
    with open(os.path.join(out, "server.json"), "w", encoding="utf-8") as fh:
        json.dump(init, fh, indent=1)
    tools = client.tools()
    report["tools"] = len(tools)
    with open(os.path.join(out, "tools.json"), "w", encoding="utf-8") as fh:
        json.dump(tools, fh, indent=1)
    with open(os.path.join(out, "tools.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(sorted(tool_line(t) for t in tools)) + "\n")
    names = {t.get("name") for t in tools}

    n = 0
    results = {}

    def run(name, args):
        nonlocal n
        if name not in names:
            if name not in report["missing"]:
                report["missing"].append(name)
            return None
        n += 1
        try:
            res = client.call(name, args)
        except McpError as e:
            report["calls"].append({"call": f"{n:02d}_{name}", "error": True, "text": str(e)})
            return None
        report["calls"].append(save_result(out, n, name, res))
        results.setdefault(name, []).append(res)
        return res

    for name, args in READ_CALLS:
        run(name, args)
    for topic in guide_topics(results.get("get_guide", [None])[0])[:MAX_GUIDES]:
        run("get_guide", {"topic": topic})
    report["target_game"] = target_game(results)

    if load_body:
        path = load_body
        if load_body == "auto":
            path = None
            for res in results.get("browse_archives", []):
                path = path or pick_body(res)
        report["body"] = path
        if path and run("load_from_archive", {"files": [path], "mode": "import"}) is not None:
            for name, args in BODY_CALLS:
                run(name, args)
        elif not path:
            report["calls"].append({"call": "load_from_archive", "error": True,
                                    "text": "no naked_f.nif in the archive listings; pass --load-body <path>"})

    lines = [f"server: {report['server']}", f"tools: {report['tools']} (tools.txt)",
             f"body: {report['body']}" if load_body else "body: not loaded (no --load-body)",
             f"target game (from its archives): {report['target_game']}" +
             (" - set Outfit Studio's game to Starfield (Settings) and its Data folder to Starfield\\Data"
              if report["target_game"] == "skyrim-like" else "")]
    if report["missing"]:
        lines.append("not offered by this server: " + ", ".join(report["missing"]))
    for c in report["calls"]:
        lines.append(f"{c['call']}: {'ERROR ' if c['error'] else ''}{c['text']}")
    with open(os.path.join(out, "report.txt"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="a folder outside the repository for the report")
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--token", default="", help="MCP/Token from OutfitStudio.xml, if one is set")
    ap.add_argument("--load-body", default=None,
                    help="'auto' (the naked_f.nif the archive listing finds) or an archive path: imports it into the "
                         "open project and looks at it; nothing is saved")
    a = ap.parse_args(argv)
    if os.path.abspath(a.out).lower().startswith(os.path.abspath(REPO).lower()):
        sys.exit("--out must be outside the repository")
    try:
        rep = probe(Client(a.url, a.token), a.out, a.load_body)
    except McpError as e:
        sys.exit(str(e))
    print("server:", rep["server"], "-", rep["tools"], "tools")
    bad = [c for c in rep["calls"] if c["error"]]
    print(len(rep["calls"]), "calls,", len(bad), "failed;", "report:", os.path.join(a.out, "report.txt"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
