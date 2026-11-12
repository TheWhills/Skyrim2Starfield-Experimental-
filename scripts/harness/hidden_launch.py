"""Start a process on a hidden desktop, suspended, with DLLs injected before its first instruction.

The same shape as sfse_loader (CreateProcess suspended, LoadLibraryA on a remote thread, GetProcAddress by
ordinal, call it, resume), with two additions: the process runs on its own desktop, so it can never take focus,
input or the screen, and any number of DLLs load in order (the profile sandbox first, then SFSE).

Ported from tes4skyrim's tools/live/hidden_launch.py (MIT, bryantmh), which drives Skyrim SE the same way.
The remote stub is sfse_loader's own (ianpatt/sfse, sfse_loader/Inject.cpp, InjectDLLThreadData), byte for
byte: identical to skse64_loader's. SFSE's entry is export ordinal 1, StartSFSE (sfse/sfse.def).

Windows only. The payload builders are plain functions so they are tested on any OS.
See: scripts/harness/README.md
"""
import ctypes
import os
from ctypes import wintypes

CREATE_SUSPENDED = 0x4
CREATE_UNICODE_ENVIRONMENT = 0x400
MEM_COMMIT_RESERVE = 0x3000
PAGE_READWRITE = 0x4
PAGE_EXECUTE_READWRITE = 0x40
GENERIC_ALL = 0x10000000
WAIT_OBJECT_0 = 0
DUPLICATE_SAME_ACCESS = 0x2
DESKTOP_READOBJECTS_ENUMERATE = 0x0041
PW_RENDERFULLCONTENT = 2
PROCESS_TERMINATE_QUERY = 0x1001
SYNCHRONIZE = 0x100000

#: sfse_loader's remote stub: sub rsp,28; mov rbx,rcx; lea rcx,[rbx+10]; call [rbx] (LoadLibraryA);
#: mov rcx,rax; mov edx,<ordinal>; call [rbx+8] (GetProcAddress); call rax; add rsp,28; ret.
LOADER_STUB = bytes((0x48, 0x83, 0xEC, 0x28, 0x48, 0x8B, 0xD9, 0x48, 0x8D, 0x4B, 0x10, 0xFF, 0x13,
                     0x48, 0x8B, 0xC8, 0xBA, 0x01, 0x00, 0x00, 0x00, 0xFF, 0x53, 0x08, 0xFF, 0xD0,
                     0x48, 0x83, 0xC4, 0x28, 0xC3))
#: Offset of the ordinal immediate (the 4 bytes after BA) in LOADER_STUB.
ORDINAL_AT = 17
#: InjectDLLThreadData: loadLibraryA @0, getProcAddress @8, char dllPath[2048] @0x10, code @0x810.
PATH_SIZE = 2048
CODE_AT = 0x10 + PATH_SIZE
#: SFSE's StartSFSE export.
SFSE_ENTRY_ORDINAL = 1
#: A remote LoadLibrary that has not returned in this long has hung the loader (sfse_loader: one minute).
INJECT_TIMEOUT_MS = 60000


def loader_payload(load_library_a: int, get_proc_address: int, dll_path: bytes, ordinal: int) -> bytes:
    """The InjectDLLThreadData block for `dll_path` (ANSI bytes): run from offset CODE_AT with the block as rcx."""
    if len(dll_path) >= PATH_SIZE:
        raise ValueError("DLL path longer than %d bytes" % (PATH_SIZE - 1))
    stub = bytearray(LOADER_STUB)
    stub[ORDINAL_AT:ORDINAL_AT + 4] = ordinal.to_bytes(4, "little")
    return (load_library_a.to_bytes(8, "little") + get_proc_address.to_bytes(8, "little") +
            dll_path.ljust(PATH_SIZE, b"\0") + bytes(stub))


def environment_block(base: dict, extra: dict) -> str:
    """A CREATE_UNICODE_ENVIRONMENT block's text: `base` updated by `extra`, sorted, double-NUL ended."""
    env = dict(base)
    env.update(extra)
    return "".join("%s=%s\0" % kv for kv in sorted(env.items(), key=lambda kv: kv[0].upper())) + "\0"


if os.name == "nt":
    _K32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _U32 = ctypes.WinDLL("user32", use_last_error=True)
    _G32 = ctypes.WinDLL("gdi32")

    class StartupInfo(ctypes.Structure):
        """STARTUPINFOW."""
        _fields_ = (("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR),
                    ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
                    ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
                    ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
                    ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
                    ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                    ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
                    ("lpReserved2", ctypes.c_void_p), ("hStdInput", wintypes.HANDLE),
                    ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE))

    class ProcessInformation(ctypes.Structure):
        """PROCESS_INFORMATION."""
        _fields_ = (("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                    ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD))

    _ENUM_PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    _U32.CreateDesktopW.restype = wintypes.HANDLE
    _U32.CreateDesktopW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p,
                                    wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p)
    _U32.OpenDesktopW.restype = wintypes.HANDLE
    _U32.OpenDesktopW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _U32.CloseDesktop.argtypes = (wintypes.HANDLE,)
    _U32.EnumDesktopWindows.argtypes = (wintypes.HANDLE, _ENUM_PROC, wintypes.LPARAM)
    _U32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    _U32.GetDC.restype = wintypes.HANDLE
    _U32.GetDC.argtypes = (wintypes.HWND,)
    _U32.ReleaseDC.argtypes = (wintypes.HWND, wintypes.HANDLE)
    _U32.PrintWindow.argtypes = (wintypes.HWND, wintypes.HANDLE, wintypes.UINT)
    _G32.CreateCompatibleDC.restype = wintypes.HANDLE
    _G32.CreateCompatibleDC.argtypes = (wintypes.HANDLE,)
    _G32.CreateCompatibleBitmap.restype = wintypes.HANDLE
    _G32.CreateCompatibleBitmap.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_int)
    _G32.SelectObject.restype = wintypes.HANDLE
    _G32.SelectObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    _G32.GetBitmapBits.argtypes = (wintypes.HANDLE, ctypes.c_long, ctypes.c_void_p)
    _G32.DeleteObject.argtypes = (wintypes.HANDLE,)
    _G32.DeleteDC.argtypes = (wintypes.HANDLE,)
    _K32.VirtualAllocEx.restype = ctypes.c_void_p
    _K32.VirtualAllocEx.argtypes = (wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                                    wintypes.DWORD, wintypes.DWORD)
    _K32.WriteProcessMemory.argtypes = (wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                        ctypes.c_size_t, ctypes.c_void_p)
    _K32.GetProcAddress.restype = ctypes.c_void_p
    _K32.GetProcAddress.argtypes = (wintypes.HMODULE, ctypes.c_char_p)
    _K32.GetModuleHandleW.restype = wintypes.HMODULE
    _K32.CreateRemoteThread.restype = wintypes.HANDLE
    _K32.CreateRemoteThread.argtypes = (wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                                        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p)
    _K32.GetCurrentProcess.restype = wintypes.HANDLE
    _K32.DuplicateHandle.argtypes = (wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE,
                                     ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD,
                                     wintypes.BOOL, wintypes.DWORD)
    _K32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    _K32.GetExitCodeThread.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    _K32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    _K32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _K32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    _K32.ResumeThread.argtypes = (wintypes.HANDLE,)
    _K32.OpenProcess.restype = wintypes.HANDLE
    _K32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _K32.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                ctypes.POINTER(wintypes.DWORD))


def _check(ok, what: str):
    """Raises OSError naming `what` when a Win32 call failed."""
    if not ok:
        raise OSError(ctypes.get_last_error(), "%s failed" % what)
    return ok


def _kernel32(name: bytes) -> int:
    """`name`'s address in kernel32, which every process maps at the same base (until reboot)."""
    return _K32.GetProcAddress(_K32.GetModuleHandleW("kernel32.dll"), name)


def inject(process, dll_path: str, entry_ordinal: int = None) -> None:
    """Loads `dll_path` into the suspended `process`; with `entry_ordinal`, also calls that export (SFSE: 1)."""
    if entry_ordinal is None:
        data = (dll_path + "\0").encode("utf-16-le")
        protect = PAGE_READWRITE
    else:
        data = loader_payload(_kernel32(b"LoadLibraryA"), _kernel32(b"GetProcAddress"),
                              dll_path.encode("mbcs"), entry_ordinal)
        protect = PAGE_EXECUTE_READWRITE
    remote = _check(_K32.VirtualAllocEx(process, None, len(data), MEM_COMMIT_RESERVE, protect), "VirtualAllocEx")
    _check(_K32.WriteProcessMemory(process, remote, data, len(data), None), "WriteProcessMemory")
    start, argument = ((_kernel32(b"LoadLibraryW"), remote) if entry_ordinal is None
                       else (remote + CODE_AT, remote))
    thread = _check(_K32.CreateRemoteThread(process, None, 0, start, argument, 0, None), "CreateRemoteThread")
    try:
        if _K32.WaitForSingleObject(thread, INJECT_TIMEOUT_MS) != WAIT_OBJECT_0:
            raise OSError("loading %s did not return" % dll_path)
        code = wintypes.DWORD()
        _check(_K32.GetExitCodeThread(thread, ctypes.byref(code)), "GetExitCodeThread")
        if entry_ordinal is None and not code.value:
            raise OSError("LoadLibrary of %s returned null" % dll_path)
    finally:
        _K32.CloseHandle(thread)


def launch(exe: str, cwd: str, desktop: str, dlls: list, env: dict, args: str = "") -> int:
    """Starts `exe` on desktop `desktop`, injects `dlls` in order, resumes it; its pid.

    Each of `dlls` is a path, or (path, entry ordinal) for a DLL started by an export (SFSE).
    The process is terminated if any injection fails, so a half-loaded game never runs. It holds its own
    handle to the desktop, which keeps the desktop alive after this process exits.
    """
    desk = _check(_U32.CreateDesktopW(desktop, None, None, 0, GENERIC_ALL, None), "CreateDesktopW")
    info = StartupInfo(cb=ctypes.sizeof(StartupInfo), lpDesktop="WinSta0\\" + desktop)
    proc = ProcessInformation()
    text = environment_block(os.environ, env)
    block = ctypes.create_unicode_buffer(text, len(text))
    command = ctypes.create_unicode_buffer('"%s" %s' % (exe, args)) if args else None
    try:
        _check(_K32.CreateProcessW(exe, command, None, None, False, CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT,
                                   block, cwd, ctypes.byref(info), ctypes.byref(proc)), "CreateProcessW")
        kept = wintypes.HANDLE()
        _check(_K32.DuplicateHandle(_K32.GetCurrentProcess(), wintypes.HANDLE(desk), proc.hProcess,
                                    ctypes.byref(kept), 0, False, DUPLICATE_SAME_ACCESS), "DuplicateHandle")
        try:
            for dll in dlls:
                path, ordinal = dll if isinstance(dll, tuple) else (dll, None)
                inject(proc.hProcess, path, ordinal)
        except OSError:
            _K32.TerminateProcess(proc.hProcess, 1)
            raise
        _K32.ResumeThread(proc.hThread)
        return proc.dwProcessId
    finally:
        for handle in (proc.hThread, proc.hProcess):
            if handle:
                _K32.CloseHandle(handle)
        _U32.CloseDesktop(desk)


def _windows_of(desk, pid: int) -> list:
    """Visible top-level windows of process `pid` on the open desktop `desk`, largest first."""
    found = []

    def visit(hwnd, _):
        owner = wintypes.DWORD()
        _U32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and _U32.IsWindowVisible(hwnd):
            rect = wintypes.RECT()
            _U32.GetWindowRect(hwnd, ctypes.byref(rect))
            found.append(((rect.right - rect.left) * (rect.bottom - rect.top), hwnd))
        return True

    _U32.EnumDesktopWindows(desk, _ENUM_PROC(visit), 0)
    return [hwnd for _, hwnd in sorted(found, reverse=True)]


def has_window(desktop: str, pid: int) -> bool:
    """Whether `pid` has a visible window on `desktop` yet."""
    desk = _U32.OpenDesktopW(desktop, 0, False, DESKTOP_READOBJECTS_ENUMERATE)
    if not desk:
        return False
    try:
        return bool(_windows_of(desk, pid))
    finally:
        _U32.CloseDesktop(desk)


def capture(desktop: str, pid: int):
    """An image of `pid`'s largest window on `desktop`, or None when it has none.

    PrintWindow(PW_RENDERFULLCONTENT) captured Skyrim's D3D11 window on a hidden desktop; whether it captures
    Starfield's D3D12 swap chain (or returns black) is unverified. The desktop stays open throughout: once this
    process closes its handle, the window handle stops being valid here.
    """
    from PIL import Image
    desk = _U32.OpenDesktopW(desktop, 0, False, DESKTOP_READOBJECTS_ENUMERATE)
    if not desk:
        return None
    try:
        windows = _windows_of(desk, pid)
        if not windows:
            return None
        hwnd = windows[0]
        rect = wintypes.RECT()
        _U32.GetWindowRect(hwnd, ctypes.byref(rect))
        width, height = rect.right - rect.left, rect.bottom - rect.top
        screen = _U32.GetDC(None)
        mem = _G32.CreateCompatibleDC(screen)
        bitmap = _G32.CreateCompatibleBitmap(screen, width, height)
        try:
            _G32.SelectObject(mem, bitmap)
            _check(_U32.PrintWindow(hwnd, mem, PW_RENDERFULLCONTENT), "PrintWindow")
            pixels = ctypes.create_string_buffer(width * height * 4)
            _G32.GetBitmapBits(bitmap, len(pixels), pixels)
            return Image.frombuffer("RGBA", (width, height), pixels, "raw", "BGRA", 0, 1).convert("RGB")
        finally:
            _G32.DeleteObject(bitmap)
            _G32.DeleteDC(mem)
            _U32.ReleaseDC(None, screen)
    finally:
        _U32.CloseDesktop(desk)


def process_image(pid: int) -> str:
    """The full exe path of running process `pid`, or "" when it is gone."""
    handle = _K32.OpenProcess(PROCESS_TERMINATE_QUERY, False, pid)
    if not handle:
        return ""
    try:
        exit_code = wintypes.DWORD()
        if _K32.GetExitCodeProcess(handle, ctypes.byref(exit_code)) and exit_code.value != 259:  # STILL_ACTIVE
            return ""
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if not _K32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return ""
        return buf.value
    finally:
        _K32.CloseHandle(handle)


def under(path: str, folder: str) -> bool:
    """Whether `path` lies inside `folder` (case-insensitive on Windows)."""
    root = os.path.normcase(os.path.abspath(folder)) + os.sep
    return bool(path) and os.path.normcase(os.path.abspath(path)).startswith(root)


def terminate(pid: int, required_dir: str) -> bool:
    """Kills `pid` only if its exe lives under `required_dir` (never the player's own game); whether it was."""
    if not under(process_image(pid), required_dir):
        return False
    handle = _K32.OpenProcess(PROCESS_TERMINATE_QUERY | SYNCHRONIZE, False, pid)
    try:
        killed = bool(handle and _K32.TerminateProcess(handle, 0))
        if killed:
            _K32.WaitForSingleObject(handle, 30000)
        return killed
    finally:
        if handle:
            _K32.CloseHandle(handle)
