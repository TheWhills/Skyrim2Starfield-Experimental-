"""An isolated Starfield for headless, automated in-game tests.

    python -I scripts\\harness\\test_instance.py build --starfield $sf [--mod "$mods\\S2S Armor Test" ...]
    python -I scripts\\harness\\test_instance.py smoke [--crash] [--settle 30]
    python -I scripts\\harness\\test_instance.py launch | status | shot [--out x.png] | stop

`build` makes the instance folder from HARD LINKS to the vanilla files of the Steam install (exe, game-root DLLs,
the official masters and their archives, SFSE and the Address Library) plus the named mod folders, and writes its
INIs and Plugins.txt into a sandbox profile inside it. `launch` starts it muted, at 640x360, on a hidden desktop,
with the profile redirected (S2SSandbox.dll), so it never touches the player's screen, speakers, input, INIs,
saves or logs, and never the MO2 setup. `smoke` launches, waits for the window, screenshots it, and checks that
the player's own profile files kept their timestamps.

Ported from tes4skyrim's tools/live/test_instance.py (MIT, bryantmh), where the same design runs Skyrim SE.
In-game status on Starfield: unverified (see scripts/harness/README.md, "What is verified").
"""
import argparse
import json
import os
import re
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import hidden_launch  # noqa: E402

STEAM_APP_ID = "1716740"
EXE = "Starfield.exe"
SANDBOX_DLL = os.path.join(HERE, "sandbox", "bin", "S2SSandbox.dll")
DESKTOP = "S2SStarfieldTest"
OUT = os.path.join(REPO, "out", "harness")
#: Masters the game loads by itself; Starfield.ccc in the game root names the official (SFBGS*) rest.
BASE_MASTERS = ("Starfield.esm", "Constellation.esm", "OldMars.esm", "BlueprintShips-Starfield.esm",
                "ShatteredSpace.esm", "SFBGS003.esm", "SFBGS004.esm", "SFBGS006.esm", "SFBGS007.esm",
                "SFBGS008.esm")
#: Game-root DLLs that are mod loaders or overlays (proxy DLLs, ReShade, ENB): never linked.
PROXY_DLLS = {"dxgi.dll", "d3d11.dll", "d3d12.dll", "dinput8.dll", "version.dll", "winhttp.dll", "winmm.dll",
              "xinput1_3.dll", "xinput1_4.dll", "dsound.dll", "opengl32.dll", "reshade.dll", "enbseries.dll"}
#: Sandbox INIs (Documents\My Games\Starfield). Keys are Starfield's, from the community INI references; that the
#: engine honours each one is UNVERIFIED until the owner's first smoke run (the screenshot shows size / intro).
CUSTOM_INI = (("General", "sIntroSequence", ""), ("General", "bAlwaysActive", "1"),
              ("Archive", "bInvalidateOlderFiles", "1"), ("Archive", "sResourceDataDirsFinal", ""))
PREFS_INI = (("Display", "bFull Screen", "0"), ("Display", "bBorderless", "1"),
             ("Display", "iSize W", "640"), ("Display", "iSize H", "360"))


class Instance:
    """The folders of one test instance rooted at `root`."""

    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        self.data = os.path.join(self.root, "Data")
        self.profile = os.path.join(self.root, "_profile")
        self.documents = os.path.join(self.profile, "Documents")
        self.local_appdata = os.path.join(self.profile, "LocalAppData")
        self.my_games = os.path.join(self.documents, "My Games", "Starfield")
        self.plugins_txt = os.path.join(self.local_appdata, "Starfield", "Plugins.txt")
        self.state = os.path.join(self.profile, "instance.json")
        self.pid_file = os.path.join(self.profile, "pid.txt")
        self.sfse_log = os.path.join(self.my_games, "SFSE", "Logs", "sfse.txt")
        self.sandbox_log = os.path.join(self.documents, "S2SSandbox.log")

    def load(self) -> dict:
        if not os.path.exists(self.state):
            raise SystemExit("no instance at %s: run build first" % self.root)
        with open(self.state, encoding="utf-8") as f:
            return json.load(f)


# ---- pure helpers (tested in tests/test_harness.py) ----

def set_ini(text: str, section: str, key: str, value: str) -> str:
    """`text` (an INI) with `key` in `[section]` set to `value`, adding the section or key when missing.
    Section and key match case-insensitively, as the engine reads them."""
    lines = text.splitlines()
    header = "[%s]" % section.lower()
    start = next((i for i, line in enumerate(lines) if line.strip().lower() == header), None)
    if start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines += ["[%s]" % section, "%s=%s" % (key, value)]
        return "\n".join(lines) + "\n"
    end = next((i for i in range(start + 1, len(lines)) if lines[i].strip().startswith("[")), len(lines))
    at = next((i for i in range(start + 1, end)
               if "=" in lines[i] and lines[i].split("=", 1)[0].strip().lower() == key.lower()), None)
    if at is None:
        last = end
        while last > start + 1 and not lines[last - 1].strip():
            last -= 1
        lines.insert(last, "%s=%s" % (key, value))
    else:
        lines[at] = "%s=%s" % (key, value)
    return "\n".join(lines) + "\n"


def parse_ini_override(spec: str) -> tuple:
    """`File.ini:Section:Key=Value` -> (file, section, key, value)."""
    match = re.fullmatch(r"([^:]+\.ini):([^:]+):([^=]+)=(.*)", spec, re.I)
    if not match:
        raise ValueError("expected File.ini:Section:Key=Value, got %r" % spec)
    return tuple(part.strip() if i < 3 else part for i, part in enumerate(match.groups()))


def plugins_txt(plugins: list) -> str:
    """Starfield's Plugins.txt: one `*Name` line per enabled plugin, in load order."""
    return "# This file is used by the game to keep track of your downloaded content.\n" + \
        "".join("*%s\n" % name for name in plugins)


def sfse_dll(names: list):
    """The runtime SFSE DLL (sfse_1_X_Y.dll, highest version) among file `names`, or None."""
    found = []
    for name in names:
        match = re.fullmatch(r"sfse_(\d+)_(\d+)_(\d+)\.dll", name, re.I)
        if match:
            found.append((tuple(int(g) for g in match.groups()), name))
    return max(found)[1] if found else None


def official_masters(data_names: list, ccc_text: str = "") -> list:
    """The official plugins present in Data: BASE_MASTERS plus the Starfield.ccc entries, game order kept."""
    present = {n.lower(): n for n in data_names}
    wanted = list(BASE_MASTERS) + [line.strip() for line in ccc_text.splitlines() if line.strip()]
    out, seen = [], set()
    for name in wanted:
        real = present.get(name.lower())
        if real and real.lower() not in seen:
            seen.add(real.lower())
            out.append(real)
    return out


def vanilla_files(root_names: list, data_names: list, sfse_plugin_names: list, ccc_text: str = "") -> list:
    """Relative paths of the install to link: exe, non-proxy root DLLs, steam_api, Starfield.ccc, official masters
    and their archives (`Starfield - *.ba2` and `<master stem> - *.ba2`), the Address Library bins."""
    files = []
    for name in root_names:
        low = name.lower()
        if low == EXE.lower() or low == "starfield.ccc" or (low.endswith(".dll") and low not in PROXY_DLLS):
            files.append(name)
    masters = official_masters(data_names, ccc_text)
    stems = tuple(os.path.splitext(m)[0].lower() + " - " for m in masters) + ("starfield - ",)
    for name in data_names:
        if name in masters or (name.lower().endswith(".ba2") and name.lower().startswith(stems)):
            files.append(os.path.join("Data", name))
    for name in sfse_plugin_names:
        if re.fullmatch(r"versionlib-.*\.bin", name, re.I):
            files.append(os.path.join("Data", "SFSE", "Plugins", name))
    return files


def mod_plugins(names: list) -> list:
    """The plugins at a mod folder's root, .esm first (the engine sorts masters first anyway)."""
    rank = {".esm": 0, ".esp": 1, ".esl": 2}
    found = [n for n in names if os.path.splitext(n)[1].lower() in rank]
    return sorted(found, key=lambda n: (rank[os.path.splitext(n)[1].lower()], n.lower()))


def same_volume(a: str, b: str) -> bool:
    """Whether two Windows paths share a drive (hard links cannot cross volumes)."""
    return os.path.splitdrive(os.path.abspath(a))[0].lower() == os.path.splitdrive(os.path.abspath(b))[0].lower()


def default_root(starfield: str) -> str:
    """`<Starfield's drive>\\S2S Test`: the same volume as the game, so its files can be hard-linked."""
    drive = os.path.splitdrive(os.path.abspath(starfield))[0]
    return (drive + os.sep if drive else os.path.dirname(os.path.abspath(starfield))) + "S2S Test"


# ---- filesystem ----

def _place(src: str, dst: str, allow_copy: bool) -> str:
    """Hard-links (or, across volumes with `allow_copy`, copies) `src` to `dst`; "link" or "copy".
    A file already there is removed first, so a write can never go through an old link into the source."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.lexists(dst):
        os.remove(dst)
    try:
        os.link(src, dst)
        return "link"
    except OSError:
        if not allow_copy:
            raise
        shutil.copy2(src, dst)
        return "copy"


def _listdir(path: str) -> list:
    return sorted(os.listdir(path)) if os.path.isdir(path) else []


def build(args) -> int:
    starfield = os.path.abspath(args.starfield)
    if not os.path.exists(os.path.join(starfield, EXE)):
        raise SystemExit("%s not found in %s" % (EXE, starfield))
    inst = Instance(args.instance_dir or default_root(starfield))
    if not same_volume(starfield, inst.root):
        raise SystemExit("the instance (%s) must be on the same drive as Starfield (%s) for hard links"
                         % (inst.root, starfield))
    if hidden_launch.under(inst.root, starfield) or hidden_launch.under(starfield, inst.root):
        raise SystemExit("the instance folder must be outside the Starfield install")
    root_names = [n for n in _listdir(starfield) if os.path.isfile(os.path.join(starfield, n))]
    dll = sfse_dll(root_names)
    if not dll:
        raise SystemExit("no sfse_1_*.dll in %s: install SFSE into the game folder" % starfield)
    ccc = os.path.join(starfield, "Starfield.ccc")
    ccc_text = ""
    if os.path.exists(ccc):
        with open(ccc, encoding="utf-8", errors="replace") as f:
            ccc_text = f.read()
    data = os.path.join(starfield, "Data")
    files = vanilla_files(root_names, _listdir(data), _listdir(os.path.join(data, "SFSE", "Plugins")), ccc_text)
    if os.path.isdir(inst.data):  # a rebuild starts from a clean Data: links only, so nothing real is lost
        shutil.rmtree(inst.data)
    for rel in files:
        _place(os.path.join(starfield, rel), os.path.join(inst.root, rel), allow_copy=False)
    print("linked %d vanilla files (SFSE %s)" % (len(files), dll))
    plugins, copied = [], 0
    for mod in args.mod:
        mod = os.path.abspath(mod)
        for dirpath, _dirs, names in os.walk(mod):
            for name in names:
                rel = os.path.relpath(os.path.join(dirpath, name), mod)
                if rel.lower() in ("meta.ini",):  # MO2's own bookkeeping
                    continue
                copied += _place(os.path.join(dirpath, name), os.path.join(inst.data, rel), True) == "copy"
        plugins += [p for p in mod_plugins(_listdir(mod)) if p not in plugins]
        print("mod %s: %s" % (os.path.basename(mod), ", ".join(mod_plugins(_listdir(mod))) or "no plugins"))
    if copied:
        print("%d mod files copied (mod folder on another drive than the instance)" % copied)
    with open(os.path.join(inst.root, "steam_appid.txt"), "w") as f:
        f.write(STEAM_APP_ID)
    write_profile(inst, plugins, args.ini, args.prefs_from)
    with open(inst.state, "w", encoding="utf-8") as f:
        json.dump({"starfield": starfield, "sfse_dll": dll, "mods": [os.path.abspath(m) for m in args.mod],
                   "plugins": plugins, "ini": args.ini}, f, indent=1)
    print("instance ready: %s" % inst.root)
    if not os.path.exists(SANDBOX_DLL):
        print("NOTE: %s missing: run scripts\\harness\\sandbox\\build.bat before launch" % SANDBOX_DLL)
    return 0


def write_profile(inst: Instance, plugins: list, overrides: list, prefs_from: str) -> None:
    """The sandbox INIs and Plugins.txt. StarfieldPrefs.ini starts from `prefs_from` (the player's own, read
    only) when given, so graphics settings are sane, then gets the hidden-window overrides."""
    os.makedirs(inst.my_games, exist_ok=True)
    os.makedirs(os.path.dirname(inst.plugins_txt), exist_ok=True)
    texts = {"StarfieldCustom.ini": "", "StarfieldPrefs.ini": ""}
    if prefs_from and os.path.exists(prefs_from):
        with open(prefs_from, encoding="utf-8", errors="replace") as f:
            texts["StarfieldPrefs.ini"] = f.read()
    for section, key, value in CUSTOM_INI:
        texts["StarfieldCustom.ini"] = set_ini(texts["StarfieldCustom.ini"], section, key, value)
    for section, key, value in PREFS_INI:
        texts["StarfieldPrefs.ini"] = set_ini(texts["StarfieldPrefs.ini"], section, key, value)
    for spec in overrides:
        name, section, key, value = parse_ini_override(spec)
        match = next((n for n in texts if n.lower() == name.lower()), name)
        texts[match] = set_ini(texts.get(match, ""), section, key, value)
    for name, text in texts.items():
        with open(os.path.join(inst.my_games, name), "w", encoding="utf-8") as f:
            f.write(text)
    with open(inst.plugins_txt, "w", encoding="utf-8") as f:
        f.write(plugins_txt(plugins))


def running_pid(inst: Instance):
    """The instance's game pid when it is still running from the instance folder, else None."""
    if not os.path.exists(inst.pid_file):
        return None
    with open(inst.pid_file) as f:
        pid = int(f.read().strip() or 0)
    return pid if pid and hidden_launch.under(hidden_launch.process_image(pid), inst.root) else None


def launch(inst: Instance) -> int:
    state = inst.load()
    if running_pid(inst):
        raise SystemExit("already running (pid %d): stop it first" % running_pid(inst))
    if not os.path.exists(SANDBOX_DLL):
        raise SystemExit("%s missing: run scripts\\harness\\sandbox\\build.bat" % SANDBOX_DLL)
    env = {"S2S_SANDBOX_DOCUMENTS": inst.documents, "S2S_SANDBOX_LOCALAPPDATA": inst.local_appdata,
           "S2S_SANDBOX_MUTE": "1", "SteamAppId": STEAM_APP_ID, "SteamGameId": STEAM_APP_ID}
    for stale in (inst.sfse_log, inst.sandbox_log):
        if os.path.exists(stale):
            os.remove(stale)
    pid = hidden_launch.launch(os.path.join(inst.root, EXE), inst.root, DESKTOP,
                               [SANDBOX_DLL, (os.path.join(inst.root, state["sfse_dll"]),
                                              hidden_launch.SFSE_ENTRY_ORDINAL)], env)
    with open(inst.pid_file, "w") as f:
        f.write(str(pid))
    print("launched pid %d on hidden desktop %s" % (pid, DESKTOP))
    return pid


def stop(inst: Instance) -> int:
    pid = running_pid(inst)
    if not pid:
        print("not running")
        return 0
    print("stopped pid %d" % pid if hidden_launch.terminate(pid, inst.root) else "could not stop pid %d" % pid)
    return 0


def shot(inst: Instance, out: str) -> str:
    pid = running_pid(inst)
    if not pid:
        raise SystemExit("not running")
    image = hidden_launch.capture(DESKTOP, pid)
    if image is None:
        print("no window yet")
        return ""
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    image.save(out)
    dark = sum(image.convert("L").resize((64, 36)).getdata()) / (64 * 36) < 3
    print("screenshot %s (%dx%d)%s" % (out, image.width, image.height,
                                       "  WARNING: all black (D3D12 capture may not work)" if dark else ""))
    return out


def _tail(path: str, lines: int = 15) -> list:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read().splitlines()[-lines:]


def sfse_problems(log_lines: list) -> list:
    """Lines of an sfse.txt that report a plugin or the runtime failing to load."""
    bad = re.compile(r"couldn't load|disabled|incompatible|bad version|not found|failed", re.I)
    return [line for line in log_lines if bad.search(line)]


def status(inst: Instance) -> int:
    pid = running_pid(inst)
    print("instance %s: %s" % (inst.root, "running, pid %d" % pid if pid else "not running"))
    for label, path in (("sandbox log", inst.sandbox_log), ("sfse.txt", inst.sfse_log)):
        print("--- %s (%s)" % (label, path))
        print("\n".join(_tail(path)) or "(none)")
    return 0


def player_profile_files() -> list:
    """The player's own profile files the sandbox must never touch."""
    home = os.path.expanduser("~")
    local = os.environ.get("LOCALAPPDATA", os.path.join(home, "AppData", "Local"))
    my_games = os.path.join(home, "Documents", "My Games", "Starfield")
    return [os.path.join(my_games, n) for n in ("StarfieldCustom.ini", "StarfieldPrefs.ini")] + \
        [os.path.join(my_games, "SFSE", "Logs", "sfse.txt"), os.path.join(local, "Starfield", "Plugins.txt")]


def file_state(path: str) -> tuple:
    return (os.path.getmtime(path), os.path.getsize(path)) if os.path.exists(path) else (0, 0)


def smoke(inst: Instance, args) -> int:
    """Launch, wait for the window, settle, screenshot, check; exit 0 only when every check passes."""
    before = {p: file_state(p) for p in player_profile_files()}
    started = time.time()
    pid = launch(inst)
    if args.crash:
        import crash_capture
        crash_capture.attach(pid, os.path.join(OUT, "crash"), "smoke")
    checks = {}
    deadline = time.time() + args.timeout
    while time.time() < deadline and running_pid(inst) and not hidden_launch.has_window(DESKTOP, pid):
        time.sleep(1)
    checks["window"] = hidden_launch.has_window(DESKTOP, pid)
    window_s = round(time.time() - started, 1)
    time.sleep(args.settle)
    checks["alive_after_settle"] = bool(running_pid(inst))
    shot_path = shot(inst, os.path.join(OUT, "smoke.png")) if checks["alive_after_settle"] else ""
    checks["screenshot"] = bool(shot_path)
    sandbox = "\n".join(_tail(inst.sandbox_log, 200))
    checks["sandbox_redirected"] = "export table: 3 of 3" in sandbox
    sfse = _tail(inst.sfse_log, 400)
    checks["sfse_log_in_sandbox"] = bool(sfse)
    problems = sfse_problems(sfse)
    changed = [p for p, s in before.items() if file_state(p) != s]
    checks["player_profile_untouched"] = not changed
    if not args.keep:
        stop(inst)
    result = {"checks": checks, "window_seconds": window_s, "sfse_problems": problems,
              "player_files_changed": changed, "screenshot": shot_path}
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "smoke.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)
    for name, ok in checks.items():
        print("%-26s %s" % (name, "PASS" if ok else "FAIL"))
    print("window after %.1f s; sfse problem lines: %d; details: %s" % (window_s, len(problems),
                                                                       os.path.join(OUT, "smoke.json")))
    return 0 if all(checks.values()) else 1


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--instance-dir", help="instance folder (default: <Starfield's drive>\\S2S Test)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="link the instance and write its sandbox profile")
    b.add_argument("--starfield", required=True, help="the Starfield install folder ($sf)")
    b.add_argument("--mod", action="append", default=[], help="an MO2 mod folder to link into Data (repeatable)")
    b.add_argument("--ini", action="append", default=[], metavar="FILE.ini:Section:Key=Value",
                   help="extra sandbox INI setting (repeatable), e.g. StarfieldCustom.ini:General:iFPSClamp=6")
    b.add_argument("--prefs-from", default=os.path.join(os.path.expanduser("~"), "Documents", "My Games",
                                                        "Starfield", "StarfieldPrefs.ini"),
                   help="StarfieldPrefs.ini to start from (read only; default: the player's)")
    sm = sub.add_parser("smoke", help="launch, wait for the window, screenshot, check, stop")
    sm.add_argument("--timeout", type=float, default=180, help="seconds to wait for the window")
    sm.add_argument("--settle", type=float, default=30, help="seconds to let it run before the screenshot")
    sm.add_argument("--crash", action="store_true", help="attach crash_capture (cdb) right after launch")
    sm.add_argument("--keep", action="store_true", help="leave it running afterwards")
    s = sub.add_parser("shot", help="screenshot the hidden window")
    s.add_argument("--out", default=os.path.join(OUT, "shot.png"))
    for name in ("launch", "status", "stop"):
        sub.add_parser(name)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.cmd == "build":
        return build(args)
    if os.name != "nt":
        raise SystemExit("Windows only")
    root = args.instance_dir
    if not root:
        guess = [p for p in ("%s:\\S2S Test" % c for c in "CDEFGHIJKLMNOPQRSTUVWXYZ") if os.path.isdir(p)]
        root = guess[0] if len(guess) == 1 else None
        if not root:
            raise SystemExit("pass --instance-dir (found %d S2S Test folders)" % len(guess))
    inst = Instance(root)
    if args.cmd == "launch":
        launch(inst)
        return 0
    if args.cmd == "smoke":
        return smoke(inst, args)
    if args.cmd == "shot":
        return 0 if shot(inst, args.out) else 1
    return {"status": status, "stop": stop}[args.cmd](inst)


if __name__ == "__main__":
    sys.exit(main())
