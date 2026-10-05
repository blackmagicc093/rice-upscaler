import contextlib
import ctypes
import gc
import io
import math
import os
import queue
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import tkinter.font as tkfont
import zipfile
import binascii
import urllib.request
import platform
import webbrowser

import numpy as np
from PIL import Image, ImageDraw, ImageFile, ImageFilter, ImageFont, ImageOps, ImageTk

# HEIC/HEIF support
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except Exception:
    pass

_fix_win32_ctypes_called = False


def _fix_win32_ctypes() -> None:
    global _fix_win32_ctypes_called
    if _fix_win32_ctypes_called:
        return
    _fix_win32_ctypes_called = True
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes
        u32 = getattr(ctypes.windll, "user32", None)
        if not u32:
            return
        is_64 = sys.maxsize > 2**32
        ptr_t = ctypes.c_uint64 if is_64 else ctypes.c_ulong

        for fn_name in ("GetWindowLongPtrW", "GetWindowLongPtrA", "SetWindowLongPtrW", "SetWindowLongPtrA",
                        "CallWindowProcW", "CallWindowProcA", "GetWindowLongW", "GetWindowLongA",
                        "SetWindowLongW", "SetWindowLongA"):
            if hasattr(u32, fn_name):
                getattr(u32, fn_name).restype = ptr_t

        for fn_name in ("SetWindowLongPtrW", "SetWindowLongPtrA", "SetWindowLongW", "SetWindowLongA"):
            if hasattr(u32, fn_name):
                fn = getattr(u32, fn_name)
                fn.restype = ctypes.c_void_p
                fn.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]

        for fn_name in ("GetWindowLongPtrW", "GetWindowLongPtrA", "GetWindowLongW", "GetWindowLongA"):
            if hasattr(u32, fn_name):
                fn = getattr(u32, fn_name)
                fn.restype = ctypes.c_void_p
                fn.argtypes = [wintypes.HWND, ctypes.c_int]

        if hasattr(u32, "GetParent"):
            u32.GetParent.argtypes = [wintypes.HWND]
            u32.GetParent.restype = wintypes.HWND
        if hasattr(u32, "GetAncestor"):
            u32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            u32.GetAncestor.restype = wintypes.HWND
    except Exception:
        pass


def _setup_windows_dll_path() -> None:
    """Ensure tools directory containing VC++ runtime / OpenMP DLLs (e.g. vcomp140.dll) is in PATH & DLL search."""
    if sys.platform != "win32":
        return
    try:
        tools_dir = _res()
        if os.path.isdir(tools_dir):
            curr_path = os.environ.get("PATH", "")
            if tools_dir not in curr_path:
                os.environ["PATH"] = tools_dir + os.pathsep + curr_path
            if hasattr(os, "add_dll_directory"):
                try:
                    os.add_dll_directory(tools_dir)
                except Exception:
                    pass
    except Exception:
        pass


def _to_long_path(path: str) -> str:
    """Ensure file paths work on Windows even when exceeding MAX_PATH (260 chars) without crashing."""
    if sys.platform != "win32" or not isinstance(path, str) or not path:
        return path
    if path.startswith("\\\\?\\") or path.startswith("\\\\.\\"):
        return path
    try:
        norm = os.path.abspath(path)
        if len(norm) >= 240:
            if norm.startswith("\\\\"):
                return "\\\\?\\UNC\\" + norm[2:]
            return "\\\\?\\" + norm
        return norm
    except Exception:
        return path


_fix_win32_ctypes()
_setup_windows_dll_path()

def _show_crash_dialog(title: str, message: str) -> None:
    try:
        messagebox.showerror(title, message)
        return
    except Exception:
        pass
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)
    except Exception:
        pass

_prevent_auto_exit = False


def _global_except_hook(exc_type, exc_value, exc_traceback) -> None:
    if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    import traceback
    err_lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
    err_text = "".join(err_lines)
    try:
        sys.stderr.write(err_text)
        sys.stderr.flush()
    except Exception:
        pass
    short_err = f"{exc_type.__name__}: {exc_value}\n\nTraceback:\n{''.join(err_lines[-4:])}"
    _show_crash_dialog("Application Crash", short_err)
    if _prevent_auto_exit:
        return
    sys.__excepthook__(exc_type, exc_value, exc_traceback)

def _thread_except_hook(args) -> None:
    _global_except_hook(args.exc_type, args.exc_value, args.exc_traceback)

sys.excepthook = _global_except_hook
if hasattr(threading, "excepthook"):
    threading.excepthook = _thread_except_hook

ENABLE_WINDND = os.environ.get("RICE_UPSCALER_DISABLE_DND", os.environ.get("RICE_UPSCALE_DISABLE_DND", os.environ.get("UPSCALE_DISABLE_DND", "0"))) != "1"
try:
    import windnd
    _WINDND = True
    # Patch windnd internal drop hook to support Windows long paths (>260 chars) & unicode safely
    try:
        from windnd import windnd as _w_int
        _orig_hook = _w_int.hook_dropfiles

        def _patched_hook_dropfiles(tkwindow_or_winfoid, func=_w_int._func, force_unicode=True):
            import platform as _p
            import ctypes as _ct
            from ctypes.wintypes import DWORD as _DWORD
            _hwnd = tkwindow_or_winfoid.winfo_id() if getattr(tkwindow_or_winfoid, "winfo_id", None) else tkwindow_or_winfoid
            if _p.architecture()[0] == "32bit":
                _GetLong = _ct.windll.user32.GetWindowLongW
                _SetLong = _ct.windll.user32.SetWindowLongW
                _argt = _DWORD
            else:
                _GetLong = getattr(_ct.windll.user32, "GetWindowLongPtrW", None) or _ct.windll.user32.GetWindowLongPtrA
                _SetLong = getattr(_ct.windll.user32, "SetWindowLongPtrW", None) or _ct.windll.user32.SetWindowLongPtrA
                _argt = _ct.c_uint64
            _proto = _ct.WINFUNCTYPE(_argt, _argt, _argt, _argt, _argt)
            _WM_DROP = 0x233
            _GWL_WND = -4
            _create_buf = _ct.create_unicode_buffer if force_unicode else _ct.c_buffer
            _func_Drag = _ct.windll.shell32.DragQueryFileW if force_unicode else _ct.windll.shell32.DragQueryFile

            for _i in range(200):
                if f"old_wndproc_{_i}" not in _w_int.__dict__:
                    _old, _new = f"old_wndproc_{_i}", f"new_wndproc_{_i}"
                    break

            def _py_drop(hwnd, msg, wp, lp):
                if msg == _WM_DROP:
                    try:
                        _cnt = _func_Drag(_argt(wp), -1, None, None)
                        _fls = []
                        for _j in range(_cnt):
                            _sz = _create_buf(32768)
                            _func_Drag(_argt(wp), _j, _sz, _ct.sizeof(_sz))
                            _fls.append(_sz.value)
                        func(_fls)
                    except Exception:
                        pass
                    finally:
                        try:
                            _ct.windll.shell32.DragFinish(_argt(wp))
                        except Exception:
                            pass
                _oldp = _w_int.__dict__.get(_old)
                if _oldp:
                    return _ct.windll.user32.CallWindowProcW(*map(_argt, (_oldp, hwnd, msg, wp, lp)))
                return 0

            _w_int.__dict__[_old] = None
            _w_int.__dict__[_new] = _proto(_py_drop)
            _ct.windll.shell32.DragAcceptFiles(_hwnd, True)
            _w_int.__dict__[_old] = _GetLong(_hwnd, _GWL_WND)
            _SetLong(_hwnd, _GWL_WND, _w_int.__dict__[_new])

        windnd.hook_dropfiles = _patched_hook_dropfiles
        _w_int.hook_dropfiles = _patched_hook_dropfiles
    except Exception:
        pass
except Exception:
    _WINDND = False

# ── Design Tokens ─────────────────────────────────────────────────────────────
BG_APP         = "#14181E"  # Window background
BG_TITLEBAR    = "#1B1E24"  # Title bar
BG_PANEL       = "#1E242E"  # Main panels (INPUT FILES, OUTPUT SETTINGS), topbar, status
BG_INPUT       = "#2A313C"  # File cards, dropdown fields, path field, secondary buttons
BG_DROPZONE    = "#1A222B"  # Drag & drop zone fill (slightly tinted)
BORDER_SUBTLE  = "#2E3642"  # Panel borders, card borders (1px)
BORDER_INPUT   = "#3A4350"  # Textbox/dropdown/button borders (1px) — visibly lighter than panel
BORDER_DASHED  = "#35E0A6"  # Drop zone dashed border (2px, dash 8px / gap 6px, radius 12px)
ACCENT         = "#2FE6A7"  # Primary mint-green: slider fill, value badges, START button, icons
ACCENT_HOVER   = "#25C98F"  # START button hover
ACCENT_TEXT_ON = "#0B0F14"  # Text/icons on top of accent (dark)
TRACK          = "#3A4350"  # Slider track (unfilled part), gray
TEXT_PRIMARY   = "#F2F5F7"  # Headings, labels, values
TEXT_SECONDARY = "#9AA4B2"  # Helper text, meta info, placeholders
TEXT_GREEN     = "#2FE6A7"  # Engine name text, status "Ready" text
DANGER_HOVER   = "#E5484D"  # X (remove file) button hover
ERROR_FG       = "#FF6B6B"  # Error messages / warning
OK             = "#2FE6A7"
FOCUS_GLOW_BG  = "#1E3531"  # 3px focus glow ring: rgba(47,230,167,.15) on #1E242E
# Inset shadow tokens removed per spec §1b / Section 0 item 11 (inputs are flat)



def _hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    h = hex_str.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


# Compatibility aliases
BG       = BG_APP
FG       = TEXT_PRIMARY
MUTED    = TEXT_SECONDARY
ENTRY_BG = BG_INPUT
BTN_BG   = BG_INPUT
CARD_BG  = BG_PANEL
LINE     = BORDER_SUBTLE
TIP_BG   = BG_INPUT
TIP_FG   = TEXT_PRIMARY

APP_TITLE = "Rice Upscaler"

INPUT_EXTS = {".jpg", ".jpeg", ".heic", ".png", ".webp"}
JPEG_EXTS  = {".jpg", ".jpeg"}
PNG_EXTS   = {".png"}

MIN_SCALE, MAX_SCALE = 1, 8
MAX_OUTPUT_MP = 120
AI_TIMEOUT = 300
CARD_PAD = 12
TARGET_MIN_MB, TARGET_MAX_MB = 1, 24
FIT_MAX_ROUNDS = 3
FIT_SHRINK = 0.9

ImageFile.LOAD_TRUNCATED_IMAGES = True
Image.MAX_IMAGE_PIXELS = 400_000_000

EXT_FORMAT = {".jpg": "JPEG", ".jpeg": "JPEG", ".heic": "JPEG", ".png": "PNG", ".webp": "WEBP"}
FORMAT_EXT = {"JPEG": ".jpg", "PNG": ".png"}

REAL_ESRGAN_URL = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-windows.zip"


# ── Resource resolution (single-exe + dev) ────────────────────────────────────

def _res(*parts: str) -> str:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, "tools", *parts)
    here = os.path.dirname(os.path.abspath(__file__))
    dist_candidate = os.path.join(here, "..", "dist", "tools", *parts)
    if os.path.exists(dist_candidate):
        return dist_candidate
    return os.path.join(here, "..", "tools", *parts)


# ── Engine bootstrap ──────────────────────────────────────────────────────────

def _find_realesrgan_bin() -> str | None:
    exe = "realesrgan-ncnn-vulkan.exe"
    candidate = _res(exe)
    if os.path.isfile(candidate):
        return candidate
    return shutil.which("realesrgan-ncnn-vulkan") or shutil.which(exe)


def _find_realesrgan_model() -> bool:
    return (os.path.isfile(_res("models", "realesrgan-x4plus.bin")) or
            os.path.isfile(_res("realesrgan-x4plus.bin")))


def _startupinfo():
    if sys.platform == "win32":
        si = subprocess.STARTUPINFO()
        si.dwFlags = subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        return si
    return None


_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) \
    if sys.platform == "win32" else 0


_vram_cache: dict | None = None


def _detect_vram_mb() -> int:
    global _vram_cache
    if _vram_cache is not None:
        return _vram_cache.get("vram_mb", 2048)

    vram_mb = 0

    # 1) Try nvidia-smi
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
            startupinfo=_startupinfo(), creationflags=_NO_WINDOW)
        if result.returncode == 0 and result.stdout.strip():
            vram_mb = int(result.stdout.strip().split()[0])
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, IndexError):
        pass

    # 2) Fallback to native DXGI adapter query (works for NVIDIA, AMD, Intel on Win10/11)
    if vram_mb == 0 and sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class LUID(ctypes.Structure):
                _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

            class DXGI_ADAPTER_DESC(ctypes.Structure):
                _fields_ = [
                    ("Description", wintypes.WCHAR * 128),
                    ("VendorId", wintypes.UINT),
                    ("DeviceId", wintypes.UINT),
                    ("SubSysId", wintypes.UINT),
                    ("Revision", wintypes.UINT),
                    ("DedicatedVideoMemory", ctypes.c_size_t),
                    ("DedicatedSystemMemory", ctypes.c_size_t),
                    ("SharedSystemMemory", ctypes.c_size_t),
                    ("AdapterLuid", LUID),
                ]

            class GUID(ctypes.Structure):
                _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                            ("Data3", wintypes.WORD), ("Data4", ctypes.c_byte * 8)]

            dxgi = getattr(ctypes.windll, "dxgi", None)
            if dxgi and hasattr(dxgi, "CreateDXGIFactory1"):
                pFactory = ctypes.c_void_p()
                iid_factory = GUID(0x770aae78, 0xf26f, 0x4dba,
                                   (ctypes.c_byte * 8)(0xa8, 0x29, 0x25, 0x3c, 0x83, 0xd1, 0xb3, 0x87))
                if dxgi.CreateDXGIFactory1(ctypes.byref(iid_factory), ctypes.byref(pFactory)) == 0 and pFactory.value:
                    vtable = ctypes.cast(pFactory, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
                    enum_adapters1 = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.UINT, ctypes.c_void_p)(vtable[12])
                    release_factory = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtable[2])
                    idx = 0
                    while True:
                        pAdapter = ctypes.c_void_p()
                        if enum_adapters1(pFactory, idx, ctypes.byref(pAdapter)) != 0:
                            break
                        idx += 1
                        avtable = ctypes.cast(pAdapter, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
                        get_desc = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p)(avtable[8])
                        release_adapter = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(avtable[2])
                        desc = DXGI_ADAPTER_DESC()
                        if get_desc(pAdapter, ctypes.byref(desc)) == 0:
                            mb = int(desc.DedicatedVideoMemory / (1024 * 1024))
                            if mb > vram_mb:
                                vram_mb = mb
                        release_adapter(pAdapter)
                    release_factory(pFactory)
        except Exception:
            pass

    # 3) Fallback to WMI Win32_VideoController (Windows)
    if vram_mb == 0 and sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.ole32.CoInitialize(None)
        except Exception:
            pass
        try:
            import wmi
            c = wmi.WMI()
            for controller in c.Win32_VideoController():
                ram = getattr(controller, "AdapterRAM", None)
                if ram:
                    val = int(ram)
                    if val < 0:
                        val += (1 << 32)
                    vram_mb = max(vram_mb, int(val / 1048576))
        except Exception:
            pass

    # 4) Default fallback
    if vram_mb == 0:
        vram_mb = 2048

    _vram_cache = {"vram_mb": vram_mb}
    return vram_mb


def _free_ram_mb() -> int:
    try:
        import ctypes
        from ctypes import wintypes
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        k32 = ctypes.windll.kernel32
        k32.GlobalMemoryStatusEx.argtypes = [ctypes.c_void_p]
        k32.GlobalMemoryStatusEx.restype = wintypes.BOOL
        if k32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return int(stat.ullAvailPhys / 1048576)
    except Exception:
        pass
    return 4096


def _tile_for_vram(vram_mb: int) -> int:
    if vram_mb >= 8000:
        return 512
    if vram_mb >= 4000:
        return 256
    return 0


REAL_ESRGAN_BIN = _find_realesrgan_bin()
REAL_ESRGAN_MODEL = _find_realesrgan_model()
_vram = _detect_vram_mb()
_vram_tile = _tile_for_vram(_vram)


def _check_ai_usable() -> bool:
    return (REAL_ESRGAN_BIN is not None
            and REAL_ESRGAN_MODEL
            and _free_ram_mb() >= 2048)


def _find_dat_model() -> str | None:
    """Recursively find a DAT ONNX model in the tools dir (case-insensitive).
    Files with 'light' in the name are preferred."""
    try:
        tools_dir = _res()
        if not os.path.isdir(tools_dir):
            return None
        fallback = None
        for root, _dirs, files in os.walk(tools_dir):
            for f in files:
                lf = f.lower()
                if lf.startswith("dat") and lf.endswith(".onnx"):
                    path = os.path.join(root, f)
                    if "light" in lf:
                        return path
                    if fallback is None:
                        fallback = path
        return fallback
    except Exception:
        return None


def _dat_models_exist() -> bool:
    return _find_dat_model() is not None


def _decide_engine(scale: int, image: Image.Image | None = None) -> tuple[str, str]:
    if scale == 1:
        return "lanczos", "AI skipped (scale=1)"

    vram = _detect_vram_mb()
    img_mp = (image.width * image.height / 1_000_000) if image else 0

    # Try DAT first (ONNX + DirectML) when models exist
    dat_model = _find_dat_model()
    if dat_model is not None:
        is_light = "light" in os.path.basename(dat_model).lower()
        min_vram = 4000 if is_light else 6000
        if vram >= min_vram:
            try:
                import onnxruntime as ort  # noqa: F401
                providers = ort.get_available_providers()
                if "DmlExecutionProvider" in providers:
                    if is_light and vram < 8000 and img_mp > 10:
                        pass
                    else:
                        return "dat", ""
            except Exception:
                pass
        # Fall through to Real-ESRGAN if DAT cannot run

    # Fallback to Real-ESRGAN
    if REAL_ESRGAN_BIN is not None and REAL_ESRGAN_MODEL:
        free = _free_ram_mb()
        if free >= 2048:
            return "ai", ""
        return "lanczos", f"Low RAM ({free} MB < 2048 MB)"
    if REAL_ESRGAN_BIN is None:
        return "lanczos", "AI binary not found"
    return "lanczos", "AI model not found"


# ── Image Analysis ────────────────────────────────────────────────────────────

def pad_to_multiple(image: Image.Image, multiple: int) -> Image.Image:
    if multiple < 2:
        return image
    w, h = image.size
    pw, ph = (-w) % multiple, (-h) % multiple
    if pw == 0 and ph == 0:
        return image
    arr = np.asarray(image, dtype=np.uint8)
    if ph:
        arr = np.pad(arr, ((0, ph), (0, 0), (0, 0)), mode="edge")
    if pw:
        arr = np.pad(arr, ((0, 0), (0, pw), (0, 0)), mode="edge")
    return Image.fromarray(arr, "RGB")


def load_rgb(path: str) -> tuple[Image.Image, str, tuple | None]:
    p = _to_long_path(path)
    with Image.open(p) as opened:
        opened.load()
        fmt = (opened.format or "").upper()
        if fmt == "MPO":
            fmt = "JPEG"
        dpi = opened.info.get("dpi")
        image = opened.convert("RGB")
    if fmt not in FORMAT_EXT:
        fmt = EXT_FORMAT.get(os.path.splitext(path)[1].lower(), "PNG")
    return image, fmt, dpi


def load_image_with_alpha(path: str) -> tuple[Image.Image, str, tuple | None, Image.Image | None]:
    """Load image preserving alpha channel if present. Returns (rgb_image, fmt, dpi, alpha_or_None)."""
    p = _to_long_path(path)
    with Image.open(p) as opened:
        try:
            opened = ImageOps.exif_transpose(opened)
        except Exception:
            pass
        opened.load()
        fmt = (opened.format or "").upper()
        if fmt == "MPO":
            fmt = "JPEG"
        dpi = opened.info.get("dpi")
        has_alpha = opened.mode in ("RGBA", "LA", "PA") or (opened.mode == "P" and "transparency" in opened.info)
        if has_alpha:
            alpha = opened.getchannel("A") if opened.mode in ("RGBA", "LA", "PA") else opened.convert("RGBA").getchannel("A")
            image = opened.convert("RGB")
        else:
            alpha = None
            image = opened.convert("RGB")
    if fmt not in FORMAT_EXT:
        fmt = EXT_FORMAT.get(os.path.splitext(path)[1].lower(), "PNG")
    return image, fmt, dpi, alpha


def _is_illustration(image: Image.Image) -> bool:
    """Detect illustration: low noise + dense edges. Skip WB/CLAHE to avoid halo/darkening."""
    gray = image.convert("L")
    w, h = gray.size
    if w < 3 or h < 3:
        return False
    arr = np.asarray(gray, dtype=np.float32)
    std = float(np.std(arr))
    if std >= 60:
        return False
    step = max(h // 512, w // 512, 1)
    sample_arr = arr[::step, ::step] if step > 1 else arr
    if sample_arr.shape[0] < 3 or sample_arr.shape[1] < 3:
        return False
    lap = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float32)
    from numpy.lib.stride_tricks import sliding_window_view
    windows = sliding_window_view(sample_arr, (3, 3))
    edges = np.einsum("ijkl,kl->ij", windows, lap)
    edge_var = float(np.var(edges))
    return edge_var >= 150


def _detect_enhance_params(image: Image.Image) -> dict:
    gray = image.convert("L")
    w, h = gray.size
    if w < 3 or h < 3:
        return {
            "radius": 0, "percent": 0, "threshold": 0,
            "auto": False, "detail": 0, "noise": 0, "auto_cutoff": 0.0
        }
    arr = np.asarray(gray, dtype=np.float32)
    step = max(h // 512, w // 512, 1)
    sample_arr = arr[::step, ::step] if step > 1 else arr
    if sample_arr.shape[0] >= 3 and sample_arr.shape[1] >= 3:
        lap = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float32)
        from numpy.lib.stride_tricks import sliding_window_view
        windows = sliding_window_view(sample_arr, (3, 3))
        edges = np.einsum("ijkl,kl->ij", windows, lap)
        edge_var = float(np.var(edges))
    else:
        edge_var = 100.0

    std = float(np.std(sample_arr))

    mean_val = float(np.mean(sample_arr))
    contrast = float(np.percentile(sample_arr, 95) - np.percentile(sample_arr, 5))

    is_noisy = std >= 80
    is_low_contrast = contrast < 80
    is_bright = mean_val > 200
    is_dark = mean_val < 50

    if edge_var < 50:
        mode = "blur_heavy"
    elif edge_var < 150:
        mode = "blur_mild"
    elif is_noisy:
        mode = "noisy"
    elif is_low_contrast:
        mode = "low_contrast"
    elif is_dark:
        mode = "dark"
    elif is_bright:
        mode = "bright"
    else:
        mode = "normal"

    return {
        "blur_heavy":    {"radius": 2.5, "percent": 140, "threshold": 2, "auto": True,  "detail": 1, "noise": 0, "auto_cutoff": 1.0},
        "blur_mild":     {"radius": 2.0, "percent": 110, "threshold": 3, "auto": True,  "detail": 1, "noise": 0, "auto_cutoff": 0.5},
        "noisy":         {"radius": 0,   "percent": 0,   "threshold": 0, "auto": False, "detail": 1, "noise": 1, "auto_cutoff": 0},
        "low_contrast":  {"radius": 2.0, "percent": 120, "threshold": 3, "auto": True,  "detail": 1, "noise": 0, "auto_cutoff": 1.5},
        "dark":          {"radius": 2.0, "percent": 120, "threshold": 3, "auto": True,  "detail": 1, "noise": 0, "auto_cutoff": 2.0},
        "bright":        {"radius": 1.5, "percent": 80,  "threshold": 4, "auto": True,  "detail": 0, "noise": 0, "auto_cutoff": 0.3},
        "normal":        {"radius": 2.0, "percent": 110, "threshold": 3, "auto": True,  "detail": 1, "noise": 0, "auto_cutoff": 0.5},
    }[mode]


def enhance_image(image: Image.Image, params: dict) -> Image.Image:
    if params["noise"] > 0:
        image = image.filter(ImageFilter.MedianFilter(size=3))
    if params["radius"] > 0:
        image = image.filter(ImageFilter.UnsharpMask(
            radius=params["radius"], percent=params["percent"],
            threshold=params["threshold"]))
    for _ in range(params["detail"]):
        image = image.filter(ImageFilter.DETAIL)
    if params["auto"]:
        cutoff = params.get("auto_cutoff", 0.5)
        if cutoff > 0:
            image = ImageOps.autocontrast(image, cutoff=cutoff)
    return image


# ── Auto Quality Top-up ────────────────────────────────────────────────────────

def _detect_color_cast(image: Image.Image) -> float:
    if image.mode != "RGB":
        image = image.convert("RGB")
    arr = np.asarray(image, dtype=np.float32)
    h, w = arr.shape[:2]
    step = max(h // 200, w // 200, 1)
    arr = arr[::step, ::step]
    means = arr.reshape(-1, 3).mean(axis=0)
    overall = means.mean()
    if overall < 1.0:
        return 0.0
    return float(np.std(means) / overall)


def _gray_world_wb(image: Image.Image) -> Image.Image:
    if image.mode != "RGB":
        image = image.convert("RGB")
    arr = np.asarray(image, dtype=np.float32)
    means = arr.reshape(-1, 3).mean(axis=0)
    gray = means.mean()
    scale = np.array([gray / m if m > 1.0 else 1.0 for m in means])
    scale = np.clip(scale, 0.7, 1.4)
    arr = arr * scale
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    return Image.fromarray(arr, "RGB")


def _clahe_lite(channel: np.ndarray, tile_size: int = 32,
                clip_limit: float = 2.0) -> np.ndarray:
    try:
        import cv2
        grid_w = max(2, min(16, channel.shape[1] // tile_size))
        grid_h = max(2, min(16, channel.shape[0] // tile_size))
        clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(grid_w, grid_h))
        return clahe.apply(channel)
    except Exception:
        pass
    h, w = channel.shape
    out = np.empty_like(channel)
    for i in range(0, h, tile_size):
        for j in range(0, w, tile_size):
            tile = channel[i:i + tile_size, j:j + tile_size]
            hist, _ = np.histogram(tile, bins=256, range=(0, 255))
            climit = tile.size * clip_limit / 100.0
            excess = np.maximum(hist - climit, 0)
            hist = np.minimum(hist, climit)
            hist = hist + excess.sum() / 256.0
            cdf = hist.cumsum()
            cdf -= cdf.min()
            denom = cdf.max()
            if denom > 0:
                cdf = cdf * 255.0 / denom
            else:
                cdf = np.arange(256, dtype=np.float64)
            out[i:i + tile_size, j:j + tile_size] = cdf[tile.astype(np.int32)]
    try:
        diff = out.astype(np.float32) - channel.astype(np.float32)
        diff_img = Image.fromarray(diff).filter(ImageFilter.GaussianBlur(radius=tile_size // 4))
        smoothed = channel.astype(np.float32) + np.asarray(diff_img)
        return np.clip(smoothed, 0, 255).astype(np.uint8)
    except Exception:
        return out


def _auto_color_grade(image: Image.Image) -> Image.Image:
    if image.mode != "RGB":
        image = image.convert("RGB")
    cast = _detect_color_cast(image)
    if cast > 0.20:
        image = _gray_world_wb(image)
    gray = image.convert("L")
    arr = np.asarray(gray, dtype=np.float32)
    contrast = float(np.percentile(arr, 95) - np.percentile(arr, 5))
    if contrast < 80:
        lab = image.convert("LAB")
        l, a, b = lab.split()
        l_arr = np.asarray(l, dtype=np.uint8)
        l_eq = _clahe_lite(l_arr)
        l_img = Image.fromarray(l_eq, "L")
        image = Image.merge("LAB", [l_img, a, b]).convert("RGB")
    return image


def _gfpgan_available() -> bool:
    try:
        import torch  # noqa: F401
        return True
    except ImportError:
        return False


# ── DAT Inference (Threaded + Timeout + Tiling + Feather Blend) ─────────────────

DAT_TILE_SIZE = 64
DAT_OVERLAP = 16
DAT_BASE_TIMEOUT = 60  # seconds
DAT_PER_MP_TIMEOUT = 30  # seconds per megapixel
DAT_MAX_TIMEOUT = 300  # hard cap

_dat_session = None
_dat_session_path = None
_dat_session_lock = threading.Lock()


def _get_dat_session(model_path: str):
    global _dat_session, _dat_session_path
    with _dat_session_lock:
        if _dat_session is not None and _dat_session_path == model_path:
            return _dat_session
        try:
            import onnxruntime as ort
            providers = [p for p in ["DmlExecutionProvider", "CPUExecutionProvider"]
                         if p in ort.get_available_providers()]
            if not providers:
                providers = ort.get_available_providers()
            sess = ort.InferenceSession(model_path, providers=providers)
            _dat_session = sess
            _dat_session_path = model_path
            return _dat_session
        except Exception:
            return None


def _run_dat_with_timeout(image: Image.Image, scale: int, timeout_s: float) -> Image.Image | None:
    """Run DAT inference with timeout, exact 64x64 tiling, and smooth feather blend."""
    model_path = _find_dat_model()
    if not model_path:
        return None

    result_queue = queue.Queue()

    def worker():
        try:
            sess = _get_dat_session(model_path)
            if sess is None:
                result_queue.put(("error", "Failed to init ONNX session"))
                return
            input_name = sess.get_inputs()[0].name
            output_name = sess.get_outputs()[0].name

            w, h = image.size
            tile_size = DAT_TILE_SIZE
            overlap = DAT_OVERLAP

            if w <= tile_size and h <= tile_size:
                pad_r = tile_size - w
                pad_b = tile_size - h
                img_arr = np.asarray(image.convert("RGB"), dtype=np.uint8)
                if pad_r > 0 or pad_b > 0:
                    img_arr = np.pad(img_arr, ((0, pad_b), (0, pad_r), (0, 0)), mode="edge")
                arr = np.transpose(img_arr.astype(np.float32) / 255.0, (2, 0, 1))[None, ...]
                out = sess.run([output_name], {input_name: arr})[0]
                out_arr = np.transpose(np.squeeze(out, 0), (1, 2, 0))
                out_arr = np.clip(out_arr * 255.0, 0, 255).astype(np.uint8)
                res_img = Image.fromarray(out_arr, "RGB")
                res_img = res_img.crop((0, 0, w * 4, h * 4))
                if scale != 4:
                    res_img = res_img.resize((w * scale, h * scale), Image.LANCZOS)
                result_queue.put(("success", res_img))
                return

            stride = tile_size - overlap
            xs = list(range(0, max(1, w - tile_size), stride))
            if not xs or xs[-1] != max(0, w - tile_size):
                xs.append(max(0, w - tile_size))
            ys = list(range(0, max(1, h - tile_size), stride))
            if not ys or ys[-1] != max(0, h - tile_size):
                ys.append(max(0, h - tile_size))

            canvas = np.zeros((h * 4, w * 4, 3), dtype=np.float32)
            weights = np.zeros((h * 4, w * 4), dtype=np.float32)
            fade = overlap * 4

            img_rgb = image.convert("RGB")
            for y in ys:
                for x in xs:
                    tile = img_rgb.crop((x, y, x + tile_size, y + tile_size))
                    arr = np.transpose(np.asarray(tile, dtype=np.float32) / 255.0, (2, 0, 1))[None, ...]
                    out = sess.run([output_name], {input_name: arr})[0]
                    out_tile = np.transpose(np.squeeze(out, 0), (1, 2, 0)) * 255.0

                    mask = np.ones((256, 256), dtype=np.float32)
                    if x > 0:
                        mask[:, :fade] *= np.linspace(0, 1, fade)
                    if x + tile_size < w:
                        mask[:, -fade:] *= np.linspace(1, 0, fade)
                    if y > 0:
                        mask[:fade, :] *= np.linspace(0, 1, fade)[:, None]
                    if y + tile_size < h:
                        mask[-fade:, :] *= np.linspace(1, 0, fade)[:, None]

                    ox, oy = x * 4, y * 4
                    canvas[oy:oy + 256, ox:ox + 256] += out_tile * mask[:, :, None]
                    weights[oy:oy + 256, ox:ox + 256] += mask

            res = canvas / np.maximum(weights[:, :, None], 1e-6)
            out_img = Image.fromarray(np.clip(res, 0, 255).astype(np.uint8), "RGB")
            if scale != 4:
                out_img = out_img.resize((w * scale, h * scale), Image.LANCZOS)
            result_queue.put(("success", out_img))
        except Exception as e:
            result_queue.put(("error", str(e)))

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout=timeout_s)
    if t.is_alive():
        return None
    try:
        status, data = result_queue.get_nowait()
        if status == "success":
            return data
    except queue.Empty:
        pass
    return None


def upscale_dat(image: Image.Image, scale: int) -> Image.Image | None:
    """Upscale using DAT ONNX models via onnxruntime-directml with timeout & tiling."""
    try:
        import onnxruntime as ort  # noqa: F401
    except Exception:
        return None

    # Calculate timeout: 60s base + 30s/MP, capped at 300s
    mp = (image.width * image.height) / 1_000_000
    timeout_s = min(DAT_BASE_TIMEOUT + DAT_PER_MP_TIMEOUT * mp, DAT_MAX_TIMEOUT)
    
    return _run_dat_with_timeout(image, scale, timeout_s)


# ── Real-ESRGAN ───────────────────────────────────────────────────────────────

def upscale_realesrgan(image: Image.Image, scale: int, tile: int) -> Image.Image | None:
    if not REAL_ESRGAN_BIN:
        return None
    in_path = None
    out_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_in:
            in_path = tmp_in.name
        out_path = in_path.replace(".png", "_out.png")
        image.save(in_path)
        cmd = [
            REAL_ESRGAN_BIN,
            "-i", in_path, "-o", out_path,
            "-s", str(scale),
            "-n", "realesrgan-x4plus",
        ]
        models_dir = _res("models")
        if os.path.isdir(models_dir) and (os.path.isfile(os.path.join(models_dir, "realesrgan-x4plus.bin")) or
                                          os.path.isfile(os.path.join(models_dir, "realesrgan-x4plus.param"))):
            cmd += ["-m", models_dir]
        if tile > 0:
            cmd += ["-t", str(tile)]
        subprocess.run(cmd, capture_output=True, timeout=AI_TIMEOUT,
                       check=True, startupinfo=_startupinfo(),
                       creationflags=_NO_WINDOW)
        if os.path.isfile(out_path):
            result = Image.open(out_path).convert("RGB")
            return result
    except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired):
        pass
    finally:
        for p in (out_path, in_path):
            if p and os.path.isfile(p):
                try:
                    os.unlink(p)
                except Exception:
                    pass
    return None


# ── Encoding ──────────────────────────────────────────────────────────────────

def encode_image(image: Image.Image, fmt: str, quality: int,
                 png_compress: int, dpi: tuple | None = None
                 ) -> tuple[bytes, int]:
    buf = io.BytesIO()
    save_kwargs: dict = {}
    if isinstance(dpi, tuple):
        save_kwargs["dpi"] = dpi
    if fmt == "JPEG":
        if image.mode != "RGB":
            image = image.convert("RGB")
        image.save(buf, format="JPEG", quality=quality, optimize=True,
                   progressive=True, **save_kwargs)
        return buf.getvalue(), quality
    image.save(buf, format="PNG", compress_level=png_compress,
               optimize=False, **save_kwargs)
    return buf.getvalue(), png_compress


def _pad_to_exact_jpeg(data: bytes, target: int) -> bytes:
    target = int(target)
    pad_needed = target - len(data)
    if pad_needed <= 0 or pad_needed < 4:
        return data
    MAX_PAYLOAD = 65533
    com_prefix = b"\xFF\xFE"
    n = max(1, -(-pad_needed // (MAX_PAYLOAD + 4)))
    total_payload = pad_needed - n * 4
    per_seg = total_payload // n
    extra = total_payload % n
    segments = []
    for i in range(n):
        sz = per_seg + (1 if i < extra else 0)
        payload = bytes(np.random.randint(1, 255, size=max(sz, 0), dtype=np.uint8))
        seg = com_prefix + struct.pack(">H", sz + 2) + payload
        segments.append(seg)
    eoi_pos = data.rfind(b"\xFF\xD9")
    if eoi_pos >= 0:
        result = data[:eoi_pos] + b"".join(segments) + data[eoi_pos:]
    else:
        result = data + b"".join(segments)
    return result


def _pad_to_exact_png(data: bytes, target: int) -> bytes:
    target = int(target)
    pad_needed = target - len(data)
    if pad_needed <= 0:
        return data
    key = b"Description"
    fixed = 12 + len(key) + 1
    val_len = pad_needed - fixed
    if val_len < 1:
        val_len = 1
    val = bytes(np.random.randint(0x20, 0x7E, size=val_len, dtype=np.uint8))
    chunk_data = key + b"\x00" + val
    length = struct.pack(">I", len(chunk_data))
    crc = struct.pack(">I", binascii.crc32(b"tEXt" + chunk_data) & 0xFFFFFFFF)
    chunk = length + b"tEXt" + chunk_data + crc
    result = bytearray(data)
    iend_pos = data.find(b"IEND")
    if iend_pos >= 0:
        result[iend_pos - 4:iend_pos - 4] = chunk
    else:
        result.extend(chunk)
    return bytes(result)


def _pad_to_exact(data: bytes, target: int, fmt: str) -> bytes:
    if fmt == "JPEG":
        return _pad_to_exact_jpeg(data, target)
    return _pad_to_exact_png(data, target)


def _fit_at_size(image: Image.Image, fmt: str, target_bytes: int,
                 dpi: tuple | None) -> tuple[bytes, int] | None:
    if fmt == "JPEG":
        lo, hi = 1, 100
        best: tuple[bytes, int] | None = None
        while lo <= hi:
            mid = (lo + hi) // 2
            data, _ = encode_image(image, fmt, mid, 0, dpi)
            if len(data) <= target_bytes:
                best = (data, mid)
                lo = mid + 1
            else:
                hi = mid - 1
        return best
    for level in range(0, 10):
        data, _ = encode_image(image, fmt, 0, level, dpi)
        if len(data) <= target_bytes:
            return data, level
    return None


def fit_to_target(image: Image.Image, fmt: str, target_bytes: int,
                  dpi: tuple | None = None) -> tuple[bytes, int, int]:
    current = image
    fitted = _fit_at_size(current, fmt, target_bytes, dpi)
    rounds = 0
    while fitted is None and rounds < FIT_MAX_ROUNDS:
        rounds += 1
        w, h = max(1, int(current.width * FIT_SHRINK)), \
            max(1, int(current.height * FIT_SHRINK))
        current = current.resize((w, h), Image.LANCZOS)
        fitted = _fit_at_size(current, fmt, target_bytes, dpi)
    if fitted is None:
        if fmt == "JPEG":
            data, _ = encode_image(current, fmt, 1, 0, dpi)
            used = 1
        else:
            data, _ = encode_image(current, fmt, 0, 9, dpi)
            used = 9
    else:
        data, used = fitted
    padded = _pad_to_exact(data, target_bytes, fmt)
    return padded, used, len(padded) - len(data)


# ── Process Single File ───────────────────────────────────────────────────────

def process_file(src: str, dst: str, opts: dict, cancel: threading.Event,
                 use_ai: bool) -> str:
    image, src_fmt, src_dpi, alpha = load_image_with_alpha(src)
    if cancel.is_set():
        return "cancelled"

    orig_w, orig_h = image.size

    dpi_setting = str(opts.get("dpi", "Default"))
    if dpi_setting == "Default":
        dpi = src_dpi
    else:
        try:
            dpi = (int(dpi_setting), int(dpi_setting))
        except ValueError:
            dpi = None

    pad_multiple = 4 if (use_ai or opts["scale"] > 1) else 1
    image = pad_to_multiple(image, pad_multiple)

    # Illustration gating: skip WB/CLAHE for illustrations (low noise + dense edges)
    is_illust = _is_illustration(image)
    if not is_illust:
        image = _auto_color_grade(image)

    _gfpgan_available()

    params = _detect_enhance_params(image)
    if is_illust:
        # Light sharpen only, skip heavy processing to avoid halo/darkening
        image = image.filter(ImageFilter.UnsharpMask(radius=1.0, percent=60, threshold=3))
    else:
        image = enhance_image(image, params)

    engine, skip_reason = _decide_engine(opts["scale"], image)
    ai_ok = False
    method = "Lanczos"
    fallback_reason = ""

    if use_ai and engine == "dat":
        try:
            result = upscale_dat(image, opts["scale"])
            if result is not None:
                image = result
                ai_ok = True
                dat_model = _find_dat_model()
                is_light = bool(dat_model and "light" in os.path.basename(dat_model).lower())
                method = "DAT-light (ONNX/DirectML)" if is_light else "DAT (ONNX/DirectML)"
            else:
                fallback_reason = "DAT timeout/failed"
        except Exception as exc:
            fallback_reason = f"DAT error ({type(exc).__name__})"

    # Fallback 1: Real-ESRGAN
    if use_ai and not ai_ok and (engine == "dat" or engine == "ai"):
        if _check_ai_usable():
            tile = _vram_tile if _vram_tile > 0 else 256
            try:
                result = upscale_realesrgan(image, opts["scale"], tile)
                if result is not None:
                    image = result
                    ai_ok = True
                    method = "AI Real-ESRGAN"
                    if fallback_reason:
                        fallback_reason += " -> Real-ESRGAN"
                else:
                    if fallback_reason:
                        fallback_reason += " -> Real-ESRGAN failed"
                    else:
                        fallback_reason = "Real-ESRGAN failed"
            except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired) as exc:
                if fallback_reason:
                    fallback_reason += f" -> Real-ESRGAN error ({type(exc).__name__})"
                else:
                    fallback_reason = f"Real-ESRGAN error ({type(exc).__name__})"

    # Fallback 2: Lanczos (always works)
    if not ai_ok and opts["scale"] > 1:
        s = opts["scale"]
        image = image.resize((image.width * s, image.height * s), Image.LANCZOS)
        method = "Lanczos"
        if fallback_reason:
            fallback_reason += " -> Lanczos"
        else:
            fallback_reason = "Lanczos fallback"

    # Crop off any padding added by pad_to_multiple
    s = opts["scale"]
    exact_w, exact_h = orig_w * s, orig_h * s
    if image.size != (exact_w, exact_h):
        if image.width >= exact_w and image.height >= exact_h:
            image = image.crop((0, 0, exact_w, exact_h))
        else:
            image = image.resize((exact_w, exact_h), Image.LANCZOS)

    w, h = image.size
    mp = w * h / 1_000_000
    if mp > MAX_OUTPUT_MP:
        ratio = math.sqrt(MAX_OUTPUT_MP / mp)
        w, h = max(1, int(w * ratio)), max(1, int(h * ratio))
        image = image.resize((w, h), Image.LANCZOS)

    fmt = src_fmt if opts["fmt"] == "Default" else {"JPG": "JPEG", "PNG": "PNG"}[opts["fmt"]]
    if not dst:
        stem = os.path.splitext(os.path.basename(src))[0]
        ext = ".jpg" if fmt == "JPEG" else ".png"
        dst = os.path.join(os.path.dirname(src), f"{stem}_upscaled{ext}")

    # Re-attach alpha for PNG output or composite on white for JPEG BEFORE encoding & fitting
    final_image = image
    if alpha is not None:
        alpha_resized = alpha.resize((w, h), Image.LANCZOS)
        if fmt == "PNG":
            final_image = image.convert("RGBA")
            final_image.putalpha(alpha_resized)
        elif fmt == "JPEG":
            bg = Image.new("RGB", (w, h), (255, 255, 255))
            bg.paste(image, mask=alpha_resized)
            final_image = bg
    elif fmt == "JPEG" and final_image.mode != "RGB":
        final_image = final_image.convert("RGB")

    target_bytes = int(opts["target_mb"] * 1048576)
    pad_bytes = 0
    target_note = ""
    if target_bytes > 0:
        data, used, pad_bytes = fit_to_target(final_image, fmt, target_bytes, dpi)
        target_note = " (Target overrides quality)"
    else:
        data, used = encode_image(final_image, fmt, opts["quality"],
                                  opts["png_compress"], dpi)

    safe_dst = _to_long_path(dst)
    tmp = safe_dst + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, safe_dst)

    if not (os.path.isfile(safe_dst) and os.path.getsize(safe_dst) > 0):
        return f"FAILED: output missing or empty after write: {dst}"

    tag = f"c{used}" if fmt == "PNG" else f"q{used}"
    note = f"{w}x{h} [{method}]"
    if fallback_reason:
        note += f" (fallback: {fallback_reason})"
    if w * h / 1_000_000 > MAX_OUTPUT_MP * 0.999:
        note += " (clamped)"
    note += target_note
    achieved_mb = len(data) / 1048576
    pad_info = f" +{pad_bytes}B pad" if pad_bytes > 0 else ""
    return f"{tag} {fmt} {achieved_mb:.2f}MB{pad_info} {note}  {dst}"


# ── Tooltip ───────────────────────────────────────────────────────────────────

class Tooltip:
    def __init__(self, widget: tk.Widget, text: str) -> None:
        self.widget = widget
        self.text = text
        self.tip: tk.Toplevel | None = None
        self.after_id: str | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _schedule(self, _event=None) -> None:
        self._hide()
        try:
            self.after_id = self.widget.after(400, self._show)
        except Exception:
            self.after_id = None

    def _show(self) -> None:
        self.after_id = None
        try:
            if not self.widget.winfo_exists():
                return
            x = self.widget.winfo_pointerx() + 16
            y = self.widget.winfo_pointery() + 12
            self.tip = tk.Toplevel(self.widget)
            self.tip.wm_overrideredirect(True)
            self.tip.wm_geometry(f"+{x}+{y}")
            self.tip.configure(bg=TIP_BG)
            tk.Label(
                self.tip, text=self.text, bg=TIP_BG, fg=TIP_FG,
                justify="left", wraplength=440, padx=10, pady=7,
                font=("Segoe UI", -13), bd=0,
            ).pack()
        except Exception:
            self.tip = None

    def _hide(self, _event=None) -> None:
        try:
            if self.after_id is not None:
                try:
                    self.widget.after_cancel(self.after_id)
                except Exception:
                    pass
                self.after_id = None
            if self.tip is not None:
                try:
                    self.tip.destroy()
                except Exception:
                    pass
                self.tip = None
        except Exception:
            pass


# ── DPI awareness (Windows) ───────────────────────────────────────────────────

def _enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes
        # 1. Windows 10 1703+ / Windows 11: SetProcessDpiAwarenessContext (Per-Monitor V2)
        u32 = getattr(ctypes.windll, "user32", None)
        if u32 and hasattr(u32, "SetProcessDpiAwarenessContext"):
            try:
                u32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
                u32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
                # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
                if u32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
                    return
                # Fallback to DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE = -3
                if u32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-3)):
                    return
            except Exception:
                pass

        # 2. Windows 8.1 / Windows 10: shcore.SetProcessDpiAwareness
        shcore = getattr(ctypes.windll, "shcore", None)
        if shcore and hasattr(shcore, "SetProcessDpiAwareness"):
            try:
                shcore.SetProcessDpiAwareness.argtypes = [ctypes.c_int]
                shcore.SetProcessDpiAwareness.restype = ctypes.c_long
                # 2 = PROCESS_PER_MONITOR_DPI_AWARE
                if shcore.SetProcessDpiAwareness(2) == 0:
                    return
                # 1 = PROCESS_SYSTEM_DPI_AWARE
                if shcore.SetProcessDpiAwareness(1) == 0:
                    return
            except Exception:
                pass

        # 3. Windows Vista/7 legacy fallback: user32.SetProcessDPIAware
        if u32 and hasattr(u32, "SetProcessDPIAware"):
            try:
                u32.SetProcessDPIAware.restype = wintypes.BOOL
                u32.SetProcessDPIAware()
            except Exception:
                pass
    except Exception:
        pass


def _apply_real_dpi_scaling(root: tk.Tk) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes
        dpi = 0
        u32 = getattr(ctypes.windll, "user32", None)

        # 1. Try GetDpiForWindow (Windows 10 1607+ / Windows 11) for accurate Per-Monitor DPI
        if u32 and hasattr(u32, "GetDpiForWindow"):
            try:
                hwnd = root.winfo_id()
                if hwnd:
                    target_hwnd = hwnd
                    if hasattr(u32, "GetAncestor"):
                        u32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
                        u32.GetAncestor.restype = wintypes.HWND
                        parent = u32.GetAncestor(hwnd, 2)  # GA_ROOT = 2
                        if parent:
                            target_hwnd = parent
                    u32.GetDpiForWindow.argtypes = [wintypes.HWND]
                    u32.GetDpiForWindow.restype = wintypes.UINT
                    d = int(u32.GetDpiForWindow(target_hwnd))
                    if d > 0:
                        dpi = d
            except Exception:
                pass

        # 2. Try GetDpiForSystem (Windows 10 1607+ / Windows 11)
        if not dpi and u32 and hasattr(u32, "GetDpiForSystem"):
            try:
                u32.GetDpiForSystem.restype = wintypes.UINT
                d = int(u32.GetDpiForSystem())
                if d > 0:
                    dpi = d
            except Exception:
                pass

        # 3. Try shcore.GetDpiForMonitor (Windows 8.1 / Win10)
        if not dpi:
            try:
                shcore = getattr(ctypes.windll, "shcore", None)
                if shcore and hasattr(shcore, "GetDpiForMonitor") and u32 and hasattr(u32, "MonitorFromWindow"):
                    hwnd = root.winfo_id()
                    hmonitor = u32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST = 2
                    if hmonitor:
                        dpi_x = wintypes.UINT()
                        dpi_y = wintypes.UINT()
                        if shcore.GetDpiForMonitor(hmonitor, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y)) == 0:
                            if dpi_x.value > 0:
                                dpi = int(dpi_x.value)
            except Exception:
                pass

        # 4. Fallback to GDI GetDeviceCaps(hdc, LOGPIXELSX = 88)
        if not dpi and u32:
            try:
                gdi32 = getattr(ctypes.windll, "gdi32", None)
                if gdi32:
                    u32.GetDC.argtypes = [wintypes.HWND]
                    u32.GetDC.restype = wintypes.HDC
                    u32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
                    u32.ReleaseDC.restype = ctypes.c_int
                    gdi32.GetDeviceCaps.argtypes = [wintypes.HDC, ctypes.c_int]
                    gdi32.GetDeviceCaps.restype = ctypes.c_int
                    hdc = u32.GetDC(0)
                    if hdc:
                        try:
                            d = int(gdi32.GetDeviceCaps(hdc, 88))
                            if d > 0:
                                dpi = d
                        finally:
                            u32.ReleaseDC(0, hdc)
            except Exception:
                pass

        if dpi and dpi > 0:
            root.tk.call("tk", "scaling", dpi / 72.0)
    except Exception:
        pass


# ── Dark titlebar (Windows) ───────────────────────────────────────────────────

def _dark_titlebar(root) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes
        u32 = getattr(ctypes.windll, "user32", None)
        if not u32:
            return

        hwnd = root.winfo_id()
        if not hwnd:
            return

        target_hwnd = hwnd
        if hasattr(u32, "GetAncestor"):
            u32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            u32.GetAncestor.restype = wintypes.HWND
            ancestor = u32.GetAncestor(hwnd, 2)  # GA_ROOT = 2
            if ancestor:
                target_hwnd = ancestor
        elif hasattr(u32, "GetParent"):
            u32.GetParent.argtypes = [wintypes.HWND]
            u32.GetParent.restype = wintypes.HWND
            parent = u32.GetParent(hwnd)
            if parent:
                target_hwnd = parent

        dwmapi = getattr(ctypes.windll, "dwmapi", None)
        if not dwmapi or not hasattr(dwmapi, "DwmSetWindowAttribute"):
            return

        DwmSetWindowAttribute = dwmapi.DwmSetWindowAttribute
        DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        DwmSetWindowAttribute.restype = ctypes.c_long

        value = ctypes.c_int(1)
        success = False
        # 20: DWMWA_USE_IMMERSIVE_DARK_MODE (Windows 11 & Windows 10 2004+)
        # 19: DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1 (Windows 10 1903/1909)
        for attr in (20, 19):
            if DwmSetWindowAttribute(target_hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                success = True
                break

        # On Windows 10, trigger frame changed redraw so the title bar visibly updates immediately
        if success and hasattr(u32, "SetWindowPos"):
            u32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
            u32.SetWindowPos.restype = wintypes.BOOL
            # SWP_NOSIZE (1) | SWP_NOMOVE (2) | SWP_NOZORDER (4) | SWP_FRAMECHANGED (0x0020) = 0x0027
            u32.SetWindowPos(target_hwnd, 0, 0, 0, 0, 0, 0x0027)
    except Exception:
        pass


# ── Custom Widgets ────────────────────────────────────────────────────────────

class CanvasSlider(tk.Frame):
    """
    Custom Canvas Slider matching spec:
    - 8px track (unfilled TRACK #3A4350, filled ACCENT #2FE6A7)
    - 20px circle knob (ACCENT fill with 3px BG_PANEL ring)
    - Soft cyan/green halo on hover/drag/focus (spec §1c.5: 0 0 0 6px rgba(47,230,167,.12))
    - Value badge pill at right (min-width 56px, height 30px, ACCENT pill with dark bold text 13px/700)
    - Integer coordinates, live drag and keyboard arrow keys support
    """
    def __init__(self, parent, variable: tk.IntVar, lo: int, hi: int,
                 badge_fmt: str = "{val}", discrete: bool = False,
                 bg: str = BG_PANEL, height: int = 36,
                 on_change=None):
        super().__init__(parent, bg=bg)
        self.variable = variable
        self.lo = lo
        self.hi = hi
        self.badge_fmt = badge_fmt
        self.discrete = discrete
        self.bg_color = bg
        self.on_change = on_change
        self._state = "normal"
        self._hover = False
        self._dragging = False
        self._focused = False

        self.canvas = tk.Canvas(self, bg=bg, height=height, highlightthickness=0,
                                borderwidth=0, relief="flat", takefocus=True)
        self.canvas.pack(fill="x", expand=True)

        self.canvas.bind("<Configure>", lambda _e: self._draw())
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Enter>", self._on_enter)
        self.canvas.bind("<Leave>", self._on_leave)
        self.canvas.bind("<Left>", self._on_dec)
        self.canvas.bind("<Down>", self._on_dec)
        self.canvas.bind("<Right>", self._on_inc)
        self.canvas.bind("<Up>", self._on_inc)
        self.canvas.bind("<FocusIn>", self._on_focus_in)
        self.canvas.bind("<FocusOut>", self._on_focus_out)

        self.variable.trace_add("write", lambda *_: self._draw())

    _badge_cache: dict = {}
    _knob_cache: dict = {}
    _track_cache: dict = {}

    def _get_badge_image(self, bg_col: str, w: int, h: int):
        key = (bg_col, w, h)
        if key in self._badge_cache:
            return self._badge_cache[key]
        scale = 3
        sw, sh = w * scale, h * scale
        img = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        col = (*_hex_to_rgb(bg_col), 255)
        # Spec §1b & Section 0 item 10: border: none (background + radius only)
        d.rounded_rectangle((0, 0, sw - 1, sh - 1), radius=sh // 2, fill=col, outline=None)
        img = img.resize((w, h), Image.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        self._badge_cache[key] = photo
        return photo

    def _get_track_image(self, w: int, h: int, cy: int, track_x0: int, track_x1: int,
                          knob_x: int, unfill_col: str, fill_col: str):
        scale = 3
        sw, sh = w * scale, h * scale
        img = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        r = 4 * scale
        tx0 = (track_x0 - 4) * scale
        tx1 = (track_x1 + 4) * scale
        ty0 = (cy - 4) * scale
        ty1 = (cy + 4) * scale

        unfill_rgb = (*_hex_to_rgb(unfill_col), 255)
        fill_rgb = (*_hex_to_rgb(fill_col), 255)

        # 1. Unfilled track with symmetrical round caps (AA at 3x)
        d.rounded_rectangle((tx0, ty0, tx1, ty1), radius=r, fill=unfill_rgb)

        # 2. Filled track with matching rounded caps + seamless knob join (AA at 3x)
        if knob_x >= track_x1:
            d.rounded_rectangle((tx0, ty0, tx1, ty1), radius=r, fill=fill_rgb)
        elif knob_x > track_x0:
            fill_right = knob_x * scale
            # Left cap + body + right cap aligned to knob center
            cap = 2 * r
            d.rounded_rectangle((tx0, ty0, min(fill_right, tx0 + cap), ty1), radius=r, fill=fill_rgb)
            if fill_right > tx0 + cap:
                d.rectangle((tx0 + r, ty0, fill_right, ty1), fill=fill_rgb)
            # Right rounded cap at knob position
            if fill_right > tx0 + r:
                cap_left = max(tx0 + r, fill_right - cap)
                d.rounded_rectangle((cap_left, ty0, fill_right, ty1), radius=r, fill=fill_rgb)

        img = img.resize((w, h), Image.LANCZOS)
        return ImageTk.PhotoImage(img)

    def _get_knob_image(self, fill_col: str, ring_col: str, halo: bool):
        key = (fill_col, ring_col, halo)
        if key in self._knob_cache:
            return self._knob_cache[key]
        size = 36
        scale = 3
        ss = size * scale
        img = Image.new("RGBA", (ss, ss), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        center = ss / 2.0
        if halo:
            hr = 17 * scale
            d.ellipse((center - hr, center - hr, center + hr, center + hr),
                      fill=(47, 230, 167, 35), outline=None)
        rr = 11 * scale
        d.ellipse((center - rr, center - rr, center + rr, center + rr),
                  fill=(*_hex_to_rgb(ring_col), 255), outline=None)
        kr = 8 * scale
        d.ellipse((center - kr, center - kr, center + kr, center + kr),
                  fill=(*_hex_to_rgb(fill_col), 255), outline=None)
        img = img.resize((size, size), Image.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        self._knob_cache[key] = photo
        return photo

    def bind(self, sequence=None, func=None, add=None):
        return self.canvas.bind(sequence, func, add=add)

    def configure(self, **kwargs):
        if "state" in kwargs:
            self._state = kwargs.pop("state")
            self._draw()
        if kwargs:
            super().configure(**kwargs)

    def _on_enter(self, _e) -> None:
        self._hover = True
        self._draw()

    def _on_leave(self, _e) -> None:
        self._hover = False
        self._draw()

    def _on_focus_in(self, _e) -> None:
        self._focused = True
        self._draw()

    def _on_focus_out(self, _e) -> None:
        self._focused = False
        self._draw()

    def _format_badge(self, val: int) -> str:
        return self.badge_fmt.format(val=val)

    def _calc_val_from_x(self, x: int, track_x0: int, track_x1: int) -> int:
        if track_x1 <= track_x0:
            return self.lo
        frac = max(0.0, min(1.0, (x - track_x0) / float(track_x1 - track_x0)))
        raw_val = self.lo + frac * (self.hi - self.lo)
        val = int(round(raw_val))
        return max(self.lo, min(self.hi, val))

    def _draw(self) -> None:
        try:
            c = self.canvas
            c.delete("all")
            w = int(c.winfo_width())
            h = int(c.winfo_height())
            if w < 100:
                return

            cy = int(h // 2)
            badge_w = 52
            badge_h = 26
            badge_x1 = int(w - 4)
            badge_x0 = int(badge_x1 - badge_w)
            badge_y0 = int(cy - badge_h // 2)
            badge_y1 = int(cy + badge_h // 2)

            track_x0 = 16
            track_x1 = int(badge_x0 - 18)

            val = max(self.lo, min(self.hi, int(round(self.variable.get()))))
            frac = float((val - self.lo) / (self.hi - self.lo)) if self.hi > self.lo else 0.0
            knob_x = int(round(track_x0 + frac * (track_x1 - track_x0)))

            is_disabled = (self._state == "disabled")
            track_unfill_col = "#242B35" if is_disabled else TRACK
            track_fill_col = "#3A4350" if is_disabled else ACCENT
            knob_fill_col = "#3A4350" if is_disabled else ACCENT
            knob_ring_col = self.bg_color
            badge_bg_col = "#242B35" if is_disabled else ACCENT
            badge_text_col = "#5A6472" if is_disabled else ACCENT_TEXT_ON

            # Anti-aliased track (symmetrical rounded caps + seamless knob fill, no jaggies)
            track_img = self._get_track_image(w, h, cy, track_x0, track_x1, knob_x, track_unfill_col, track_fill_col)
            self._track_ref = track_img
            c.create_image(0, 0, anchor="nw", image=track_img)

            # 20px knob + 3px ring + soft halo on hover/drag/focus (spec §1c.5, anti-aliased)
            has_halo = (self._hover or self._dragging or self._focused) and not is_disabled
            knob_img = self._get_knob_image(knob_fill_col, knob_ring_col, has_halo)
            self._knob_ref = knob_img
            c.create_image(knob_x, cy, image=knob_img)

            # Pill badge at right (min-width 52px, height 26px) - border: none (background + radius only)
            badge_img = self._get_badge_image(badge_bg_col, badge_w, badge_h)
            self._badge_ref = badge_img
            c.create_image(badge_x0, badge_y0, anchor="nw", image=badge_img)

            text_str = self._format_badge(val)
            c.create_text(int((badge_x0 + badge_x1) // 2), cy, text=text_str,
                          fill=badge_text_col, font=("Segoe UI", -12, "bold"))

            c.configure(cursor="arrow" if is_disabled else "hand2")
        except Exception:
            pass

    def _on_click(self, event) -> None:
        if self._state == "disabled":
            return
        w = int(self.canvas.winfo_width())
        badge_x0 = int(w - 4 - 52)
        track_x0 = 16
        track_x1 = int(badge_x0 - 18)
        if event.x <= badge_x0:
            val = self._calc_val_from_x(event.x, track_x0, track_x1)
            self.variable.set(val)
            if self.on_change:
                self.on_change(val)
            self._dragging = True
            self.canvas.focus_set()
            self._draw()

    def _on_drag(self, event) -> None:
        if self._state == "disabled" or not self._dragging:
            return
        w = int(self.canvas.winfo_width())
        badge_x0 = int(w - 4 - 52)
        track_x0 = 16
        track_x1 = int(badge_x0 - 18)
        val = self._calc_val_from_x(event.x, track_x0, track_x1)
        if val != self.variable.get():
            self.variable.set(val)
            if self.on_change:
                self.on_change(val)
        else:
            self._draw()

    def _on_release(self, event) -> None:
        self._dragging = False
        cw = int(self.canvas.winfo_width())
        ch = int(self.canvas.winfo_height())
        if not (0 <= event.x <= cw and 0 <= event.y <= ch):
            self._hover = False
        self._draw()

    def _on_dec(self, _event) -> None:
        if self._state == "disabled":
            return
        val = max(self.lo, self.variable.get() - 1)
        self.variable.set(val)
        if self.on_change:
            self.on_change(val)

    def _on_inc(self, _event) -> None:
        if self._state == "disabled":
            return
        val = min(self.hi, self.variable.get() + 1)
        self.variable.set(val)
        if self.on_change:
            self.on_change(val)


class CustomProgressBar(tk.Frame):
    """Clean Canvas Progressbar: 8px height, TRACK background, ACCENT fill, radius full."""
    def __init__(self, parent, bg: str = BG_PANEL, height: int = 8):
        super().__init__(parent, bg=bg)
        self.maximum = 100
        self.value = 0
        self.height = height
        self.canvas = tk.Canvas(self, bg=bg, height=height, highlightthickness=0)
        self.canvas.pack(fill="x", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self._draw())

    def configure(self, **kwargs):
        if "value" in kwargs:
            self.value = kwargs.pop("value")
        if "maximum" in kwargs:
            self.maximum = kwargs.pop("maximum")
        self._draw()
        if kwargs:
            super().configure(**kwargs)

    def _draw(self) -> None:
        try:
            c = self.canvas
            c.delete("all")
            w = int(c.winfo_width())
            h = self.height
            if w < 10:
                return
            scale = 3
            sw, sh = w * scale, h * scale
            img = Image.new("RGBA", (sw, sh), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            r = sh // 2
            d.rounded_rectangle((0, 0, sw - 1, sh - 1), radius=r, fill=(*_hex_to_rgb(TRACK), 255))
            if self.maximum > 0 and self.value > 0:
                frac = min(1.0, max(0.0, self.value / float(self.maximum)))
                fw = int(round(sw * frac))
                if fw > 0:
                    d.rounded_rectangle((0, 0, min(sw - 1, max(fw, 2 * r)), sh - 1), radius=r, fill=(*_hex_to_rgb(ACCENT), 255))
            img = img.resize((w, h), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            self._bar_ref = photo
            c.create_image(0, 0, anchor="nw", image=photo)
        except Exception:
            pass


class CustomButton(tk.Frame):
    """
    Custom button conforming to spec:
    - 1px subtle border: BORDER_SUBTLE (#2E3642)
    - highlightthickness: 0 on both frame and button
    - no focus ring (takefocus=False)
    - icon-text vertical center: grid layout with equal height and symmetric padding
    - font icon = font text: Segoe UI, -12, bold
    - uniform padding: dynamic pady based on height, padx=12 (14 for primary)
    """
    _icon_cache: dict = {}

    def __init__(self, parent, text: str, command=None, style: str = "secondary",
                 height: int = 36, width: int | None = None, bg: str = BG_PANEL):
        self.btn_style = style
        self.cmd = command
        self._state = "normal"
        self._hover = False
        self.btn_text = text
        self.btn_height = height

        if style == "primary":
            border_col = ACCENT
            bg_col = ACCENT
            fg_col = ACCENT_TEXT_ON
            self.font = tkfont.Font(family="Segoe UI", size=-12, weight="bold")
        elif style in ("outline", "primary-outline"):
            border_col = BORDER_SUBTLE
            bg_col = BG_PANEL
            fg_col = TEXT_PRIMARY
            self.font = tkfont.Font(family="Segoe UI", size=-12, weight="bold")
        else:
            border_col = BORDER_SUBTLE
            bg_col = BG_INPUT
            fg_col = TEXT_PRIMARY
            self.font = tkfont.Font(family="Segoe UI", size=-12, weight="bold")

        self.normal_border = border_col
        self.normal_bg = bg_col
        self.normal_fg = fg_col

        super().__init__(parent, bg=border_col, padx=1, pady=1,
                         highlightthickness=0, bd=0, relief="flat")

        py = max(2, (height - 2 - 16) // 2)
        px = 14 if style == "primary" else 12

        self.btn = tk.Frame(self, bg=bg_col, padx=px, pady=py, cursor="hand2")
        self.btn.pack(fill="both", expand=True)

        self.btn.grid_rowconfigure(0, weight=1)
        self.btn.grid_columnconfigure(0, weight=1)
        self.btn.grid_columnconfigure(3, weight=1)

        self.lbl_icon = tk.Label(self.btn, bg=bg_col, anchor="center", bd=0, padx=0, pady=0)
        self.lbl_text = tk.Label(self.btn, bg=bg_col, fg=fg_col, font=self.font,
                                 anchor="center", bd=0, padx=0, pady=0)

        self._parse_text(text)
        self._update_display()

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)

    def _parse_text(self, text: str):
        parts = text.split(" ", 1)
        if len(parts) == 2 and (ord(parts[0][0]) > 127 or not parts[0].isalnum()):
            self._icon_char = parts[0]
            self._label_text = parts[1]
        else:
            self._icon_char = None
            self._label_text = text

    @classmethod
    def _get_icon_photo(cls, char: str, color_hex: str, size: int = 16):
        key = (char, color_hex, size)
        if key in cls._icon_cache:
            return cls._icon_cache[key]
        try:
            font_path = "C:/Windows/Fonts/seguiemj.ttf"
            if not os.path.exists(font_path):
                return None
            s = 3
            ss = size * s
            font = ImageFont.truetype(font_path, 12 * s)
            bbox = font.getbbox(char)
            gw = bbox[2] - bbox[0]
            gh = bbox[3] - bbox[1]
            img = Image.new("RGBA", (ss, ss), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            ox = (ss - gw) // 2 - bbox[0]
            oy = (ss - gh) // 2 - bbox[1]
            rgb = _hex_to_rgb(color_hex)
            d.text((ox, oy), char, font=font, fill=(*rgb, 255))
            img = img.resize((size, size), Image.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            cls._icon_cache[key] = photo
            return photo
        except Exception:
            return None

    def _update_display(self):
        if self._state == "disabled":
            fg = "#4E7864" if self.btn_style == "primary" else "#5A6472"
            bg = "#1A3B2F" if self.btn_style == "primary" else self.normal_bg
            border = BORDER_SUBTLE
            cur = "arrow"
        elif self._hover:
            fg = ACCENT_TEXT_ON if self.btn_style == "primary" else ACCENT
            bg = ACCENT_HOVER if self.btn_style == "primary" else self.normal_bg
            border = ACCENT_HOVER if self.btn_style == "primary" else ACCENT
            cur = "hand2"
        else:
            fg = self.normal_fg
            bg = self.normal_bg
            border = self.normal_border
            cur = "hand2"

        super().configure(bg=border)
        self.btn.configure(bg=bg, cursor=cur)
        self.lbl_icon.configure(bg=bg, cursor=cur)
        self.lbl_text.configure(bg=bg, fg=fg, cursor=cur, text=self._label_text)

        if self._icon_char:
            photo = self._get_icon_photo(self._icon_char, fg, size=16)
            if photo:
                self.lbl_icon.configure(image=photo, text="")
                self.lbl_icon.image = photo
            else:
                self.lbl_icon.configure(image="", text=self._icon_char, fg=fg,
                                        font=("Segoe UI Emoji", -12))
            self.lbl_icon.grid(row=0, column=1, sticky="ns", padx=(0, 6))
            self.lbl_text.grid(row=0, column=2, sticky="ns")
        else:
            self.lbl_icon.grid_forget()
            self.lbl_text.grid(row=0, column=1, sticky="ns")

    def _is_inside(self):
        try:
            x = self.winfo_pointerx()
            y = self.winfo_pointery()
            wx = self.winfo_rootx()
            wy = self.winfo_rooty()
            ww = self.winfo_width()
            wh = self.winfo_height()
            return (wx <= x <= wx + ww) and (wy <= y <= wy + wh)
        except Exception:
            return False

    def _on_enter(self, _e):
        if self._state == "disabled":
            return
        if not self._hover:
            self._hover = True
            self._update_display()

    def _on_leave(self, _e):
        if self._state == "disabled":
            return
        if not self._is_inside():
            self._hover = False
            self._update_display()

    def _on_click(self, _e=None):
        if self._state != "disabled" and self.cmd:
            self.cmd()

    def bind(self, sequence=None, func=None, add=None):
        for w in (self.btn, self.lbl_icon, self.lbl_text):
            try:
                w.bind(sequence, func, add=add)
            except Exception:
                pass
        return super().bind(sequence, func, add=add)

    def configure(self, **kwargs):
        if "state" in kwargs:
            self._state = kwargs.pop("state")
            self._update_display()
        if "text" in kwargs:
            self.btn_text = kwargs.pop("text")
            self._parse_text(self.btn_text)
            self._update_display()
        if kwargs:
            super().configure(**kwargs)

    def config(self, **kwargs):
        self.configure(**kwargs)

    def cget(self, key):
        if key == "state":
            return self._state
        if key == "text":
            return self.btn_text
        return super().cget(key)

    def __getitem__(self, key):
        return self.cget(key)

    def focus_set(self):
        super().focus_set()

    def invoke(self):
        self._on_click()


class StyledEntryBox(tk.Frame):
    """
    Flat entry container:
    - 1px border: BORDER_INPUT (#3A4350), ACCENT (#2FE6A7) on focus
    - background: BG_INPUT (#2A313C)
    - flat tk.Entry: relief="flat", borderwidth=0, highlightthickness=0
    - text foreground: TEXT_PRIMARY (#F2F5F7)
    - placeholder foreground: TEXT_SECONDARY (#9AA4B2)
    """
    def __init__(self, parent, textvariable=None, width: int = 110, height: int = 36,
                 font=("Segoe UI", -12), bg: str = BG_PANEL, placeholder: str = ""):
        self.placeholder = placeholder
        self.var = textvariable
        super().__init__(parent, bg=BORDER_INPUT, padx=1, pady=1,
                         highlightthickness=0, bd=0, relief="flat")
        if width:
            self.configure(width=width)
        self.configure(height=height)
        self.pack_propagate(False)

        self._inner = tk.Frame(self, bg=BG_INPUT, padx=8, pady=4)
        self._inner.pack(fill="both", expand=True)

        self.entry = tk.Entry(
            self._inner, textvariable=self.var, bg=BG_INPUT, fg=TEXT_PRIMARY,
            insertbackground=ACCENT, selectbackground=ACCENT, selectforeground=ACCENT_TEXT_ON,
            relief="flat", bd=0, borderwidth=0, highlightthickness=0, font=font
        )
        self.entry.pack(fill="both", expand=True)

        self._inner.bind("<Button-1>", lambda _e: self.entry.focus_set())
        self.entry.bind("<FocusIn>", self._on_focus_in, add="+")
        self.entry.bind("<FocusOut>", self._on_focus_out, add="+")

        if self.placeholder:
            if self.var is not None:
                self.var.trace_add("write", self._check_var)
            self._update_placeholder()

    def _on_focus_in(self, _e=None):
        self.configure(bg=ACCENT)
        if self.placeholder and self.entry.get() == self.placeholder:
            if self.var is not None:
                self.var.set("")
            else:
                self.entry.delete(0, "end")
            self.entry.configure(fg=TEXT_PRIMARY)

    def _on_focus_out(self, _e=None):
        self.configure(bg=BORDER_INPUT)
        if self.placeholder and not self.entry.get().strip():
            self._show_placeholder()

    def _show_placeholder(self):
        self.entry.configure(fg=TEXT_SECONDARY)
        if self.var is not None:
            self.var.set(self.placeholder)
        else:
            self.entry.delete(0, "end")
            self.entry.insert(0, self.placeholder)

    def _check_var(self, *_a):
        val = self.var.get() if self.var else ""
        if val == self.placeholder:
            self.entry.configure(fg=TEXT_SECONDARY)
        elif val:
            self.entry.configure(fg=TEXT_PRIMARY)

    def _update_placeholder(self):
        val = self.entry.get().strip()
        if not val or val == self.placeholder:
            self._show_placeholder()
        else:
            self.entry.configure(fg=TEXT_PRIMARY)


_CHIP_CACHE: dict = {}

def _render_chip_image(icon_type: str, bg_panel: str = BG_PANEL) -> ImageTk.PhotoImage:
    key = (icon_type, bg_panel)
    if key in _CHIP_CACHE:
        return _CHIP_CACHE[key]
    scale = 4
    w, h = 34 * scale, 34 * scale
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    r = 10 * scale
    bg_mint = (47, 230, 167, int(255 * 0.12))
    border_mint = (47, 230, 167, int(255 * 0.30))
    accent = (47, 230, 167, 255)

    # 34x34 chip: 10px radius, 1px border
    d.rounded_rectangle((scale // 2, scale // 2, w - scale // 2 - 1, h - scale // 2 - 1),
                        radius=r, fill=bg_mint, outline=border_mint, width=scale)

    # Centered 18px vector icon inside 34x34 (bbox 8..26)
    ox, oy = 8 * scale, 8 * scale
    s = scale

    if icon_type == "input":
        # stacked-photos glyph: two overlapping rounded rectangles, mountain + sun
        d.rounded_rectangle((ox + 4 * s, oy + 0 * s, ox + 17 * s, oy + 12 * s),
                            radius=2 * s, fill=None, outline=accent, width=max(1, int(1.2 * s)))
        panel_rgb = _hex_to_rgb(bg_panel)
        front_fill = (round(panel_rgb[0] * 0.88 + 47 * 0.12),
                      round(panel_rgb[1] * 0.88 + 230 * 0.12),
                      round(panel_rgb[2] * 0.88 + 167 * 0.12), 255)
        d.rounded_rectangle((ox + 0 * s, oy + 4 * s, ox + 13 * s, oy + 16 * s),
                            radius=2 * s, fill=front_fill, outline=accent, width=max(1, int(1.2 * s)))
        d.ellipse((ox + 3 * s, oy + 7 * s, ox + 5 * s, oy + 9 * s), fill=accent)
        d.line([(ox + 2 * s, oy + 14 * s), (ox + 5 * s, oy + 10 * s), (ox + 8 * s, oy + 13 * s),
                (ox + 10 * s, oy + 11 * s), (ox + 12 * s, oy + 14 * s)],
               fill=accent, width=max(1, int(1.2 * s)))
    else:
        # sliders-horizontal glyph: three horizontal lines with circular knobs at different positions
        line_w = max(1, int(1.2 * s))
        # line 1
        d.line([(ox + 1 * s, oy + 3 * s), (ox + 17 * s, oy + 3 * s)], fill=accent, width=line_w)
        d.ellipse((ox + 5 * s - 2 * s, oy + 3 * s - 2 * s, ox + 5 * s + 2 * s, oy + 3 * s + 2 * s), fill=accent)
        # line 2
        d.line([(ox + 1 * s, oy + 9 * s), (ox + 17 * s, oy + 9 * s)], fill=accent, width=line_w)
        d.ellipse((ox + 13 * s - 2 * s, oy + 9 * s - 2 * s, ox + 13 * s + 2 * s, oy + 9 * s + 2 * s), fill=accent)
        # line 3
        d.line([(ox + 1 * s, oy + 15 * s), (ox + 17 * s, oy + 15 * s)], fill=accent, width=line_w)
        d.ellipse((ox + 8 * s - 2 * s, oy + 15 * s - 2 * s, ox + 8 * s + 2 * s, oy + 15 * s + 2 * s), fill=accent)

    final = Image.new("RGBA", (w, h), (*_hex_to_rgb(bg_panel), 255))
    final = Image.alpha_composite(final, img)
    final = final.resize((34, 34), Image.LANCZOS)
    photo = ImageTk.PhotoImage(final.convert("RGB"))
    _CHIP_CACHE[key] = photo
    return photo


class HeaderChip(tk.Canvas):
    """34x34px chip (nen rgba mint .12, vien mint .30, icon 18px ve bang canvas)."""
    def __init__(self, parent, icon_type: str, bg: str = BG_PANEL):
        super().__init__(parent, width=34, height=34, bg=bg,
                         highlightthickness=0, borderwidth=0, relief="flat")
        self.icon_type = icon_type
        self.parent_bg = bg
        self._img_ref = _render_chip_image(icon_type, bg)
        self.create_image(0, 0, anchor="nw", image=self._img_ref)


class SectionHeader(tk.Frame):
    """
    Section header:
    - Chip 34px
    - Gap 10px
    - Title 13px bold
    """
    def __init__(self, parent, title: str, icon_type: str, bg: str = BG_PANEL):
        super().__init__(parent, bg=bg, bd=0, relief="flat")
        self.chip = HeaderChip(self, icon_type=icon_type, bg=bg)
        self.chip.pack(side="left", padx=(0, 10))
        self.title_canvas = tk.Canvas(self, height=32, bg=bg,
                                      highlightthickness=0, borderwidth=0, relief="flat")
        self.title_canvas.pack(side="left", fill="x", expand=True)
        self.title_text = title
        self._font = tkfont.Font(family="Segoe UI", size=-13, weight="bold")
        self.title_canvas.bind("<Configure>", lambda _e: self._draw_title())
        self._draw_title()

    def _draw_title(self) -> None:
        c = self.title_canvas
        c.delete("all")
        x = 0
        y = 16
        for ch in self.title_text:
            c.create_text(x, y, text=ch, font=self._font, fill=TEXT_PRIMARY, anchor="w")
            x += self._font.measure(ch) + 2


_DROPZONE_GLOW_CACHE = None
_DROPZONE_ICON_CACHE = None

def _get_dropzone_glow() -> ImageTk.PhotoImage:
    global _DROPZONE_GLOW_CACHE
    if _DROPZONE_GLOW_CACHE is not None:
        return _DROPZONE_GLOW_CACHE
    size = 120
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    center = size / 2.0
    max_r = size / 2.0
    for y in range(size):
        for x in range(size):
            dx = x - center
            dy = y - center
            dist = math.hypot(dx, dy)
            if dist < max_r:
                frac = dist / max_r
                if frac <= 0.70:
                    alpha = (1.0 - frac / 0.70) * 0.20
                else:
                    alpha = 0
                img.putpixel((x, y), (47, 230, 167, int(alpha * 255)))
    _DROPZONE_GLOW_CACHE = ImageTk.PhotoImage(img)
    return _DROPZONE_GLOW_CACHE


def _get_dropzone_icon() -> ImageTk.PhotoImage:
    global _DROPZONE_ICON_CACHE
    if _DROPZONE_ICON_CACHE is not None:
        return _DROPZONE_ICON_CACHE
    size = 56
    scale = 4
    ss = size * scale
    img = Image.new("RGBA", (ss, ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    accent = (47, 230, 167, 255)
    s = scale

    # Outer photo frame: from (4, 4) to (44, 44)
    x0, y0, x1, y1 = 4 * s, 4 * s, 44 * s, 44 * s
    d.rounded_rectangle((x0, y0, x1, y1), radius=5 * s, outline=accent, width=2 * s)

    # Sun: circle at (14, 15)
    d.ellipse((12 * s, 12 * s, 19 * s, 19 * s), fill=accent)

    # Mountain: polyline
    d.line([(8 * s, 38 * s), (19 * s, 24 * s), (27 * s, 33 * s), (33 * s, 27 * s), (40 * s, 36 * s)],
           fill=accent, width=2 * s)

    # Plus badge circle at bottom right: center (42, 42), radius 11
    bcx, bcy, br = 42 * s, 42 * s, 11 * s
    d.ellipse((bcx - br, bcy - br, bcx + br, bcy + br), fill=(26, 34, 43, 255), outline=accent, width=2 * s)

    # Plus icon lines inside badge
    pw = 6 * s
    d.line([(bcx - pw, bcy), (bcx + pw, bcy)], fill=accent, width=2 * s)
    d.line([(bcx, bcy - pw), (bcx, bcy + pw)], fill=accent, width=2 * s)

    img = img.resize((size, size), Image.LANCZOS)
    _DROPZONE_ICON_CACHE = ImageTk.PhotoImage(img)
    return _DROPZONE_ICON_CACHE


class CircleCloseButton(tk.Canvas):
    """Circular 28px ✕ button with hover background DANGER_HOVER and white icon."""
    _cache: dict = {}

    def __init__(self, parent, command=None, size: int = 28):
        super().__init__(parent, width=size, height=size, bg=BG_INPUT,
                         highlightthickness=0, borderwidth=0, relief="flat", cursor="hand2")
        self.command = command
        self.size = size
        self._hover = False
        self._img_ref = None
        self._draw()
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)

    @classmethod
    def _get_image(cls, size: int, hover: bool):
        key = (size, hover)
        if key in cls._cache:
            return cls._cache[key]
        scale = 3
        ss = size * scale
        img = Image.new("RGBA", (ss, ss), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        center = ss / 2.0

        bg_col = DANGER_HOVER if hover else BG_INPUT
        fg_col = "#FFFFFF" if hover else TEXT_SECONDARY

        if hover:
            r = (ss - 2 * scale) / 2.0
            d.ellipse((center - r, center - r, center + r, center + r),
                      fill=(*_hex_to_rgb(bg_col), 255), outline=None)

        cr = 4.2 * scale
        lw = max(1, int(round(1.6 * scale)))
        fg_rgb = (*_hex_to_rgb(fg_col), 255)
        d.line([(center - cr, center - cr), (center + cr, center + cr)], fill=fg_rgb, width=lw)
        d.line([(center - cr, center + cr), (center + cr, center - cr)], fill=fg_rgb, width=lw)

        img = img.resize((size, size), Image.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        cls._cache[key] = photo
        return photo

    def _draw(self) -> None:
        self.delete("all")
        photo = self._get_image(self.size, self._hover)
        self._img_ref = photo
        self.create_image(0, 0, anchor="nw", image=photo)

    def _on_enter(self, _e) -> None:
        self._hover = True
        self._draw()

    def _on_leave(self, _e) -> None:
        self._hover = False
        self._draw()

    def _on_click(self, _e) -> None:
        if self.command:
            self.command()


# ── Application ───────────────────────────────────────────────────────────────

class App(tk.Tk):
    def report_callback_exception(self, exc_type, exc_value, exc_traceback) -> None:
        if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
            return
        import traceback
        err_lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
        err_text = "".join(err_lines)
        try:
            sys.stderr.write(err_text)
            sys.stderr.flush()
        except Exception:
            pass
        short_err = f"{exc_type.__name__}: {exc_value}\n\nTraceback:\n{''.join(err_lines[-4:])}"
        _show_crash_dialog("UI Error", short_err)

    def __init__(self) -> None:
        _enable_dpi_awareness()
        super().__init__()
        _apply_real_dpi_scaling(self)
        self.title(APP_TITLE)
        self._last_open_dir: str | None = None
        self._window_icon_photo: ImageTk.PhotoImage | None = None
        self._set_app_icon()
        default_w = 960
        default_h = 700
        min_w = 900
        min_h = 620
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        pos_x = max(0, (screen_w - default_w) // 2)
        pos_y = max(0, (screen_h - default_h) // 2)
        self.geometry(f"{default_w}x{default_h}+{pos_x}+{pos_y}")
        self.minsize(min_w, min_h)
        self.configure(bg=BG_APP)
        self.cancel_event = threading.Event()
        self.events: queue.Queue = queue.Queue()
        self.running = False
        self.total = 0
        self.processed = 0
        self.files: list[str] = []
        self._thumb_cache: dict[str, ImageTk.PhotoImage] = {}
        self._meta_cache: dict[str, dict] = {}
        self._card_refs: dict[str, dict] = {}
        self._thumb_pending: set[str] = set()
        self._thumb_queue: queue.Queue = queue.Queue()
        self._images: list[ImageTk.PhotoImage] = []
        self._dropzone_hover = False
        self._dropzone_draw_timer: str | None = None
        self._dropzone_last_size: tuple[int, int] = (0, 0)
        self._drain_scheduled: bool = False
        self._drain_after_id: str | None = None
        self._about_open = False
        self._about_dialog: tk.Toplevel | None = None
        self._dnd_enabled = _WINDND and ENABLE_WINDND
        self._start_thumb_worker()

        self.out_dir = tk.StringVar()
        self.scale = tk.IntVar(value=1)
        self.scale.trace_add("write", self._on_scale_trace)
        self.quality = tk.IntVar(value=92)
        self.png_compress = tk.IntVar(value=6)
        self.target_mb = tk.StringVar(value="")
        self.fmt = tk.StringVar(value="Default")
        self.dpi = tk.StringVar(value="Default")
        self.status = tk.StringVar(value="Ready: 0 files queued ●")
        self.est_time = tk.StringVar(value="")
        self.output_hint = tk.StringVar(value="Output: — (select images to preview)")

        self._style()
        self._build()
        self.update_idletasks()
        _dark_titlebar(self)
        self._sync_quality()
        self._update_engine_label()
        self._update_output_hint()
        self._update_est_time()
        self._update_status_ready()
        self._schedule_drain(150)

    def _on_scale_trace(self, *_a) -> None:
        try:
            self._update_output_hint()
            self._update_est_time()
            self._update_status_ready()
        except Exception:
            pass

    def _set_app_icon(self) -> None:
        try:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            icon_ico = os.path.join(base_dir, "assets", "icon", "rice.ico")
            icon_png = os.path.join(base_dir, "assets", "icon", "rice.png")
            if not os.path.isfile(icon_ico):
                meipass = getattr(sys, "_MEIPASS", None)
                if meipass:
                    icon_ico = os.path.join(meipass, "assets", "icon", "rice.ico")
                    icon_png = os.path.join(meipass, "assets", "icon", "rice.png")

            if os.path.isfile(icon_ico):
                try:
                    self.iconbitmap(default=icon_ico)
                except Exception:
                    try:
                        self.iconbitmap(icon_ico)
                    except Exception:
                        pass

            img_to_load = icon_png if os.path.isfile(icon_png) else (icon_ico if os.path.isfile(icon_ico) else None)
            if img_to_load:
                try:
                    pil_icon = Image.open(img_to_load)
                    self._window_icon_photo = ImageTk.PhotoImage(pil_icon)
                    photos = []
                    for s in (16, 24, 32, 48, 64, 128, 256):
                        try:
                            photos.append(ImageTk.PhotoImage(pil_icon.resize((s, s), Image.LANCZOS)))
                        except Exception:
                            pass
                    self._window_icon_photos = photos if photos else [self._window_icon_photo]
                    self.iconphoto(False, *self._window_icon_photos)
                except Exception:
                    pass
        except Exception:
            pass

    def _get_safe_initialdir(self) -> str:
        last = getattr(self, "_last_open_dir", None)
        if last and isinstance(last, str) and os.path.isdir(last):
            norm = os.path.normpath(last)
            if not norm.startswith(("\\\\", "//")):
                return norm
        for candidate in [
            os.path.join(os.path.expanduser("~"), "Pictures"),
            os.path.join(os.path.expanduser("~"), "Desktop"),
            os.path.expanduser("~"),
            os.getcwd(),
        ]:
            if candidate and os.path.isdir(candidate):
                norm = os.path.normpath(candidate)
                if not norm.startswith(("\\\\", "//")):
                    return norm
        return ""

    @contextlib.contextmanager
    def _pause_windnd_during_dialog(self):
        hwnd = None
        set_long = None
        old_proc = None
        new_proc = None
        dnd_active = getattr(self, "_dnd_hook_active", False)
        if dnd_active:
            try:
                hwnd = self.winfo_id()
                ctypes.windll.shell32.DragAcceptFiles(hwnd, False)
                w_mod = sys.modules.get("windnd")
                if w_mod and hasattr(w_mod, "windnd"):
                    old_proc = getattr(w_mod.windnd, "old_wndproc_0", None)
                    new_proc = getattr(w_mod.windnd, "new_wndproc_0", None)
                is_64 = sys.maxsize > 2**32
                set_long = getattr(ctypes.windll.user32, "SetWindowLongPtrW" if is_64 else "SetWindowLongW", None) or \
                           getattr(ctypes.windll.user32, "SetWindowLongPtrA" if is_64 else "SetWindowLongA", None)
                if set_long and old_proc and hwnd:
                    set_long(hwnd, -4, old_proc)
            except Exception:
                pass
        try:
            yield
        finally:
            if dnd_active and hwnd:
                try:
                    if set_long and new_proc:
                        set_long(hwnd, -4, new_proc)
                    ctypes.windll.shell32.DragAcceptFiles(hwnd, True)
                except Exception:
                    pass


    def _on_cards_mousewheel(self, e) -> None:
        try:
            self.cards_canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")
        except Exception:
            pass

    def _on_fmt_selected(self, _e=None) -> None:
        try:
            self._sync_quality()
        except Exception:
            pass

    # ── Style ─────────────────────────────────────────────────────────────────
    def _style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        self.option_add("*Font", ("Segoe UI", -12))
        self.option_add("*highlightThickness", 0)
        self.option_add("*highlightBackground", BORDER_SUBTLE)
        self.option_add("*highlightColor", BORDER_SUBTLE)
        self.option_add("*borderWidth", 0)
        self.option_add("*relief", "flat")

        # Combobox styling with strictly 1px BORDER_SUBTLE and zero native borders
        style.configure("Custom.TCombobox",
                        fieldbackground=BG_INPUT, background=BG_INPUT,
                        foreground=TEXT_PRIMARY, arrowcolor=TEXT_SECONDARY,
                        bordercolor=BORDER_SUBTLE, darkcolor=BORDER_SUBTLE,
                        lightcolor=BORDER_SUBTLE, selectbackground=BG_INPUT,
                        selectforeground=TEXT_PRIMARY, padding=(10, 5),
                        font=("Segoe UI", -12),
                        borderwidth=1, relief="flat")
        style.map("Custom.TCombobox",
                  fieldbackground=[("readonly", BG_INPUT), ("disabled", BG_INPUT)],
                  background=[("readonly", BG_INPUT), ("disabled", BG_INPUT)],
                  foreground=[("readonly", TEXT_PRIMARY), ("disabled", TEXT_SECONDARY)],
                  selectbackground=[("readonly", BG_INPUT)],
                  selectforeground=[("readonly", TEXT_PRIMARY)],
                  bordercolor=[("readonly", BORDER_SUBTLE), ("disabled", BORDER_SUBTLE)],
                  lightcolor=[("readonly", BORDER_SUBTLE), ("disabled", BORDER_SUBTLE)],
                  darkcolor=[("readonly", BORDER_SUBTLE), ("disabled", BORDER_SUBTLE)],
                  arrowcolor=[("hover", ACCENT), ("!hover", TEXT_SECONDARY)])

        # Scrollbar styling
        style.configure("Vertical.TScrollbar",
                        background=BORDER_SUBTLE, troughcolor=BG_PANEL,
                        bordercolor=BG_PANEL, arrowcolor=TEXT_SECONDARY)

        # Popup listbox styling with 1px BORDER_SUBTLE (#2E3642)
        self.option_add("*TCombobox*Listbox.background", BG_INPUT)
        self.option_add("*TCombobox*Listbox.foreground", TEXT_PRIMARY)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.option_add("*TCombobox*Listbox.selectForeground", ACCENT_TEXT_ON)
        self.option_add("*TCombobox*Listbox.font", ("Segoe UI", -12))
        self.option_add("*TCombobox*Listbox.relief", "flat")
        self.option_add("*TCombobox*Listbox.borderWidth", "0")
        self.option_add("*TCombobox*Listbox.highlightThickness", "0")
        self.option_add("*TCombobox*Listbox.highlightBackground", BORDER_SUBTLE)
        self.option_add("*TCombobox*Listbox.highlightColor", BORDER_SUBTLE)

    # ── Layout ────────────────────────────────────────────────────────────────
    def _make_row_label(self, parent: tk.Widget, text: str) -> tk.Label:
        lbl_box = tk.Frame(parent, bg=BG_PANEL, width=145, height=36)
        lbl_box.pack_propagate(False)
        lbl_box.pack(side="left")
        lbl = tk.Label(lbl_box, text=text, fg=TEXT_PRIMARY, bg=BG_PANEL,
                       font=("Segoe UI", -12, "bold"), anchor="w")
        lbl.pack(fill="both", expand=True)
        return lbl

    def _build(self) -> None:
        # Main root container with page padding: 14px 12px
        main_container = tk.Frame(self, bg=BG_APP, padx=14, pady=12)
        main_container.pack(fill="both", expand=True)

        # ── 1. Top Info Bar (Engine pill + About) ──────────────────────────────
        topbar = tk.Frame(main_container, bg=BG_PANEL, highlightbackground=BORDER_SUBTLE,
                          highlightthickness=1, padx=14, pady=8, bd=0, relief="flat")
        topbar.pack(side="top", fill="x", pady=(0, 10))

        # Left: Engine pill
        top_left = tk.Frame(topbar, bg=BG_PANEL, bd=0, relief="flat")
        top_left.pack(side="left")
        tk.Label(top_left, text="Engine:", fg=TEXT_SECONDARY, bg=BG_PANEL,
                 font=("Segoe UI", -12, "bold"), bd=0, relief="flat").pack(side="left")
        pill_frame = tk.Frame(top_left, bg=BG_INPUT, highlightbackground=BORDER_SUBTLE,
                              highlightthickness=1, padx=12, pady=5, bd=0, relief="flat")
        pill_frame.pack(side="left", padx=(8, 0))
        self.engine_label = tk.Label(pill_frame, text="AI Real-ESRGAN",
                                     fg=TEXT_GREEN, bg=BG_INPUT,
                                     font=("Segoe UI", -12, "bold"), bd=0, relief="flat")
        self.engine_label.pack()

        # Right: About button
        self.btn_about = CustomButton(topbar, text="About ⓘ",
                                      command=self._show_about, style="secondary",
                                      height=34)
        self.btn_about.pack(side="right")

        # ── 2. Bottom Status Bar (Pinned at bottom, flex-shrink 0) ─────────────
        bottom_bar = tk.Frame(main_container, bg=BG_PANEL, highlightbackground=BORDER_SUBTLE,
                              highlightthickness=1, padx=14, pady=10, bd=0, relief="flat")
        bottom_bar.pack(side="bottom", fill="x", pady=(10, 0))
        bottom_bar.columnconfigure(0, weight=1)
        bottom_bar.columnconfigure(1, weight=0)

        # Left block: Status + Progress
        bot_left = tk.Frame(bottom_bar, bg=BG_PANEL)
        bot_left.grid(row=0, column=0, sticky="ew", padx=(0, 16))
        bot_left.columnconfigure(1, weight=1)

        status_line = tk.Frame(bot_left, bg=BG_PANEL)
        status_line.pack(fill="x", pady=(0, 5))
        self.status_prefix_label = tk.Label(status_line, text="Ready:",
                                            fg=TEXT_GREEN, bg=BG_PANEL,
                                            font=("Segoe UI", -12, "bold"))
        self.status_prefix_label.pack(side="left")
        self.status_text_label = tk.Label(status_line, text=" 0 files queued ",
                                          fg=TEXT_PRIMARY, bg=BG_PANEL, font=("Segoe UI", -12))
        self.status_text_label.pack(side="left")
        self.status_dot_label = tk.Label(status_line, text="●", fg=ACCENT,
                                         bg=BG_PANEL, font=("Segoe UI", -12))
        self.status_dot_label.pack(side="left")

        prog_line = tk.Frame(bot_left, bg=BG_PANEL)
        prog_line.pack(fill="x")
        self.pct_label = tk.Label(prog_line, text="0%", fg=TEXT_PRIMARY, bg=BG_PANEL,
                                  font=("Segoe UI", -12, "bold"), width=5, anchor="w")
        self.pct_label.pack(side="left")
        self.progress = CustomProgressBar(prog_line, bg=BG_PANEL, height=7)
        self.progress.pack(side="left", fill="x", expand=True)

        # Right block: Cancel / Open Output Folder / START UPSCALE
        bot_right = tk.Frame(bottom_bar, bg=BG_PANEL)
        bot_right.grid(row=0, column=1, sticky="e")

        self.cancel_button = CustomButton(bot_right, text="x Cancel",
                                          command=self.cancel, style="secondary", height=36)
        self.cancel_button.pack(side="left", padx=(0, 8))
        Tooltip(self.cancel_button, "Cancel processing after current image or reset progress.")

        self.open_button = CustomButton(bot_right, text="📁 Open Output Folder",
                                        command=self.open_output, style="secondary", height=36)
        self.open_button.pack(side="left", padx=(0, 8))
        Tooltip(self.open_button, "Open output folder in File Explorer.")

        self.start_button = CustomButton(bot_right, text="🚀 START UPSCALE",
                                         command=self.start, style="primary", height=42)
        self.start_button.pack(side="left")
        Tooltip(self.start_button, "Start upscaling queued images.")

        # ── 3. Main Two-Column Grid (compact left panel, gap 12px) ───────────
        grid = tk.Frame(main_container, bg=BG_APP)
        grid.pack(side="top", fill="both", expand=True)
        grid.columnconfigure(0, weight=36, minsize=310)
        grid.columnconfigure(1, weight=64)
        grid.rowconfigure(0, weight=1)

        # ── Left Panel: INPUT FILES ───────────────────────────────────────────
        left_panel = tk.Frame(grid, bg=BG_PANEL, highlightbackground=BORDER_SUBTLE,
                              highlightthickness=1, padx=14, pady=14, bd=0, relief="flat")
        left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        # Section Header: INPUT FILES
        self.left_hdr = SectionHeader(left_panel, title="INPUT FILES", icon_type="input", bg=BG_PANEL)
        self.left_hdr.pack(fill="x", pady=(0, 10))

        # Drop Zone (Height 170px)
        self.dropzone = tk.Canvas(left_panel, height=170, bg=BG_PANEL,
                                  highlightthickness=0, borderwidth=0, relief="flat", cursor="hand2")
        self.dropzone.pack(fill="x", pady=(0, 10))
        self.dropzone.bind("<Button-1>", lambda _e: self.add_files())
        self.dropzone.bind("<Configure>", self._on_dropzone_configure)
        self.dropzone.bind("<Enter>", lambda _e: self._hover_dropzone(True))
        self.dropzone.bind("<Leave>", lambda _e: self._hover_dropzone(False))

        # Action Buttons Row (pinned at panel bottom, 3 buttons divide full width)
        btns_row = tk.Frame(left_panel, bg=BG_PANEL, bd=0, relief="flat")
        btns_row.pack(side="bottom", fill="x")
        btns_row.columnconfigure(0, weight=1, uniform="btns")
        btns_row.columnconfigure(1, weight=1, uniform="btns")
        btns_row.columnconfigure(2, weight=1, uniform="btns")

        self.btn_add_files = CustomButton(btns_row, text="+ Add Files",
                                          command=self.add_files, style="outline", height=34)
        self.btn_add_files.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        Tooltip(self.btn_add_files, "Add image files (JPG, PNG, WebP, HEIC).")

        self.btn_add_folder = CustomButton(btns_row, text="+ Add Folder",
                                           command=self.add_folder, style="secondary", height=34)
        self.btn_add_folder.grid(row=0, column=1, sticky="ew", padx=(3, 3))
        Tooltip(self.btn_add_folder, "Add all images from a folder.")

        self.btn_clear = CustomButton(btns_row, text="🗑 Clear All",
                                      command=self.clear_files, style="secondary", height=34)
        self.btn_clear.grid(row=0, column=2, sticky="ew", padx=(3, 0))
        Tooltip(self.btn_clear, "Clear image queue.")

        # File Cards scroll container (flex: 1, min-height: 0, overflow-y: auto)
        cards_outer = tk.Frame(left_panel, bg=BG_PANEL, bd=0, relief="flat")
        cards_outer.pack(side="top", fill="both", expand=True, pady=(0, 10))

        self.cards_canvas = tk.Canvas(cards_outer, bg=BG_PANEL, highlightthickness=0,
                                      borderwidth=0, relief="flat")
        self.cards_canvas.pack(side="left", fill="both", expand=True)

        self.cards_scroll = ttk.Scrollbar(cards_outer, orient="vertical",
                                          command=self.cards_canvas.yview,
                                          style="Vertical.TScrollbar")
        # Scrollbar is NOT packed on launch (auto overflow only)
        self.cards_canvas.configure(yscrollcommand=self._on_cards_scroll_set)

        self.cards_inner = tk.Frame(self.cards_canvas, bg=BG_PANEL, bd=0, relief="flat")
        self.cards_window = self.cards_canvas.create_window((0, 0), window=self.cards_inner, anchor="nw")
        self.cards_inner.bind("<Configure>", self._on_cards_inner_configure)
        self.cards_canvas.bind("<Configure>", self._on_cards_canvas_configure)
        self.cards_canvas.bind("<MouseWheel>", self._on_cards_mousewheel)
        self.cards_inner.bind("<MouseWheel>", self._on_cards_mousewheel)

        # ── Right Panel: OUTPUT SETTINGS ──────────────────────────────────────
        right_panel = tk.Frame(grid, bg=BG_PANEL, highlightbackground=BORDER_SUBTLE,
                               highlightthickness=1, padx=14, pady=14, bd=0, relief="flat")
        right_panel.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        # Section Header: OUTPUT SETTINGS
        self.right_hdr = SectionHeader(right_panel, title="OUTPUT SETTINGS", icon_type="output", bg=BG_PANEL)
        self.right_hdr.pack(fill="x", pady=(0, 12))

        # 1. Format row
        f_row = tk.Frame(right_panel, bg=BG_PANEL, bd=0, relief="flat")
        f_row.pack(fill="x", pady=(0, 10))
        self._make_row_label(f_row, "Format:")
        self.fmt_combo = ttk.Combobox(f_row, textvariable=self.fmt,
                                      values=["Default", "JPG", "PNG"],
                                      state="readonly", style="Custom.TCombobox")
        self.fmt_combo.current(0)
        self.fmt_combo.pack(side="left", fill="x", expand=True)
        self.fmt_combo.bind("<<ComboboxSelected>>", self._on_fmt_selected)
        Tooltip(self.fmt_combo, "Output format: Default (JPEG, HEIC, WEBP to JPG) or JPG, or PNG.")

        # 2. DPI row
        dpi_row = tk.Frame(right_panel, bg=BG_PANEL, bd=0, relief="flat")
        dpi_row.pack(fill="x", pady=(0, 10))
        self._make_row_label(dpi_row, "DPI:")
        self.dpi_combo = ttk.Combobox(dpi_row, textvariable=self.dpi,
                                      values=["Default", "150", "300"],
                                      state="readonly", style="Custom.TCombobox")
        self.dpi_combo.current(0)
        self.dpi_combo.pack(side="left", fill="x", expand=True)
        Tooltip(self.dpi_combo, "Output DPI: Default, 150, or 300.")

        # 3. Quality area (Image Quality / PNG Compression)
        self._quality_area = tk.Frame(right_panel, bg=BG_PANEL)
        self._quality_area.pack(fill="x")

        self._jpeg_frame = tk.Frame(self._quality_area, bg=BG_PANEL)
        self._make_row_label(self._jpeg_frame, "JPG Quality:")
        self.quality_scale = CanvasSlider(self._jpeg_frame, variable=self.quality,
                                          lo=1, hi=100, badge_fmt="{val}%", bg=BG_PANEL)
        self.quality_scale.pack(side="left", fill="x", expand=True)
        Tooltip(self.quality_scale, "JPEG quality (1–100, default: 92).")

        self._png_frame = tk.Frame(self._quality_area, bg=BG_PANEL)
        self._make_row_label(self._png_frame, "PNG Compression:")
        self.png_scale = CanvasSlider(self._png_frame, variable=self.png_compress,
                                      lo=0, hi=9, badge_fmt="{val}/9", bg=BG_PANEL)
        self.png_scale.pack(side="left", fill="x", expand=True)
        Tooltip(self.png_scale, "PNG compression (0: fast, 9: smallest).")

        # 4. Target Size (MB) row
        tgt_row = tk.Frame(right_panel, bg=BG_PANEL)
        tgt_row.pack(fill="x", pady=(0, 2))
        self._make_row_label(tgt_row, "Target Size (MB):")
        self.target_box = StyledEntryBox(tgt_row, textvariable=self.target_mb,
                                         width=95, height=36, font=("Segoe UI", -12),
                                         placeholder="—")
        self.target_box.pack(side="left")
        self.target_entry = self.target_box.entry
        Tooltip(self.target_entry, "Max output size in MB (optional).")

        self.target_err_label = tk.Label(right_panel, text="", fg=ERROR_FG, bg=BG_PANEL,
                                         font=("Segoe UI", -11), anchor="w")
        self.target_err_label.pack(fill="x", padx=(145, 0), pady=(0, 4))

        self.target_mb.trace_add("write", self._sync_target_override)

        # 5. Scale row (no separate OPTIONS section)
        scale_row = tk.Frame(right_panel, bg=BG_PANEL)
        scale_row.pack(fill="x", pady=(0, 4))
        self._make_row_label(scale_row, "Scale:")
        self.scale_slider = CanvasSlider(scale_row, variable=self.scale,
                                         lo=MIN_SCALE, hi=MAX_SCALE, badge_fmt="{val}x",
                                         discrete=True, bg=BG_PANEL,
                                         on_change=lambda _: (self._update_output_hint(),
                                                              self._update_est_time(),
                                                              self._update_status_ready()))
        self.scale_slider.pack(side="left", fill="x", expand=True)
        Tooltip(self.scale_slider, "Upscale factor: 1x (enhance) to 8x (AI / DAT / Lanczos).")

        # Helper line centered below scale
        self.scale_hint_label = tk.Label(right_panel, textvariable=self.output_hint,
                                         fg=TEXT_SECONDARY, bg=BG_PANEL, font=("Segoe UI", -12))
        self.scale_hint_label.pack(fill="x", pady=(0, 10))

        # 6. Output Folder row
        out_row = tk.Frame(right_panel, bg=BG_PANEL)
        out_row.pack(fill="x", pady=(0, 10))
        self._make_row_label(out_row, "Output Folder:")
        self.out_box = StyledEntryBox(out_row, textvariable=self.out_dir,
                                      width=180, height=36, font=("Segoe UI", -12),
                                      placeholder="—")
        self.out_box.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.out_entry = self.out_box.entry
        self.btn_browse = CustomButton(out_row, text="📁 Browse…",
                                       command=self.pick_output, style="secondary", height=36)
        self.btn_browse.pack(side="right")

        # Drag-and-drop hookup with error fallback flag
        self._dnd_hook_active = False
        if getattr(self, "_dnd_enabled", False):
            try:
                self.update_idletasks()
                windnd.hook_dropfiles(self, func=self._on_drop)
                self._dnd_hook_active = True
            except Exception as e:
                self._dnd_enabled = False
                try:
                    sys.stderr.write(f"windnd hook error, disabled: {e}\n")
                except Exception:
                    pass

        self._sync_target_override()

    # ── Dropzone & Cards ──────────────────────────────────────────────────────
    def _hover_dropzone(self, hovering: bool) -> None:
        try:
            self._dropzone_hover = hovering
            if getattr(self, "_dropzone_draw_timer", None) is not None:
                try:
                    self.after_cancel(self._dropzone_draw_timer)
                except Exception:
                    pass
                self._dropzone_draw_timer = None
            self._draw_dropzone()
        except Exception:
            pass

    def _on_dropzone_configure(self, event=None) -> None:
        try:
            if event is not None:
                sz = (event.width, event.height)
                if sz == getattr(self, "_dropzone_last_size", (0, 0)):
                    return
                self._dropzone_last_size = sz
            if getattr(self, "_dropzone_draw_timer", None) is not None:
                try:
                    self.after_cancel(self._dropzone_draw_timer)
                except Exception:
                    pass
                self._dropzone_draw_timer = None
            self._dropzone_draw_timer = self.after(35, self._debounced_draw_dropzone)
        except Exception:
            pass

    def _debounced_draw_dropzone(self) -> None:
        try:
            self._dropzone_draw_timer = None
            self._draw_dropzone()
        except Exception:
            pass

    def _draw_dropzone(self) -> None:
        try:
            c = self.dropzone
            c.delete("all")
            w = c.winfo_width()
            h = c.winfo_height()
            if w < 50 or h < 50:
                return
            self._dropzone_last_size = (w, h)

            border_col = ACCENT if self._dropzone_hover else BORDER_DASHED
            dash_pat = () if self._dropzone_hover else (8, 6)
            fill_col = "#1E2A36" if self._dropzone_hover else BG_DROPZONE

            # Rounded rectangle path with radius 14px (spec §4a.2 & Section 0 item 11)
            # Drawn as ONE SINGLE continuous vector path with smooth corners
            r = 14
            x0, y0, x1, y1 = 2, 2, w - 3, h - 3
            steps = 12
            pts = []
            # Top-right corner arc (-pi/2 to 0)
            cx, cy = x1 - r, y0 + r
            for i in range(steps + 1):
                a = -math.pi / 2 + (math.pi / 2) * (i / steps)
                pts.extend([cx + r * math.cos(a), cy + r * math.sin(a)])
            # Bottom-right corner arc (0 to pi/2)
            cx, cy = x1 - r, y1 - r
            for i in range(steps + 1):
                a = 0 + (math.pi / 2) * (i / steps)
                pts.extend([cx + r * math.cos(a), cy + r * math.sin(a)])
            # Bottom-left corner arc (pi/2 to pi)
            cx, cy = x0 + r, y1 - r
            for i in range(steps + 1):
                a = math.pi / 2 + (math.pi / 2) * (i / steps)
                pts.extend([cx + r * math.cos(a), cy + r * math.sin(a)])
            # Top-left corner arc (pi to 3pi/2)
            cx, cy = x0 + r, y0 + r
            for i in range(steps + 1):
                a = math.pi + (math.pi / 2) * (i / steps)
                pts.extend([cx + r * math.cos(a), cy + r * math.sin(a)])

            # Single polygon for smooth fill
            c.create_polygon(pts, fill=fill_col, outline="")
            # Single continuous vector path for dashed border (2px stroke, closed)
            c.create_line(pts + pts[:2], fill=border_col, width=2, dash=dash_pat, joinstyle="round")

            cy = h // 2
            icx, icy = w // 2, cy - 25

            # 120px soft radial glow centered on icon (spec §4a.2 & Section 0 item 11)
            self._dropzone_glow_img = _get_dropzone_glow()
            c.create_image(icx, icy, image=self._dropzone_glow_img, anchor="center")

            # Clean 56px image-plus vector glyph (spec §4a.2 & Section 0 item 11)
            self._dropzone_icon_img = _get_dropzone_icon()
            c.create_image(icx, icy, image=self._dropzone_icon_img, anchor="center")

            # Drag & drop text (15px weight 700 / 12px secondary)
            c.create_text(w // 2, cy + 22, text="Drag & drop images here",
                          fill=TEXT_PRIMARY, font=("Segoe UI", -15, "bold"))
            c.create_text(w // 2, cy + 44, text="or click to browse • supports JPG, JPEG, HEIC, PNG, WEBP",
                          fill=TEXT_SECONDARY, font=("Segoe UI", -12))
        except Exception:
            pass

    def _on_drop(self, files) -> None:
        if not getattr(self, "_dnd_enabled", True):
            return
        try:
            paths = []
            for f in files:
                if isinstance(f, bytes):
                    try:
                        p = f.decode("utf-8")
                    except UnicodeDecodeError:
                        p = f.decode("mbcs", errors="replace")
                else:
                    p = str(f)
                paths.append(p)
            if paths:
                self.after(20, lambda p=paths: self._safe_append_paths(p))
        except Exception as e:
            self._dnd_enabled = False
            try:
                sys.stderr.write(f"windnd on_drop error, disabled: {e}\n")
            except Exception:
                pass

    def _safe_append_paths(self, paths: list[str]) -> None:
        try:
            self._append_paths(paths)
        except Exception:
            pass

    # ── Engine label ──────────────────────────────────────────────────────────
    def _update_engine_label(self) -> None:
        global REAL_ESRGAN_BIN, REAL_ESRGAN_MODEL
        if REAL_ESRGAN_BIN is None:
            os.makedirs(_res(), exist_ok=True)
            exe = _res("realesrgan-ncnn-vulkan.exe")
            if not os.path.isfile(exe):
                if messagebox.askyesno(
                        "AI engine missing",
                        "AI engine missing, download ~50MB from official "
                        "GitHub xinntao/Real-ESRGAN?"):
                    zip_path = _res("_realesrgan_dl.zip")
                    try:
                        urllib.request.urlretrieve(REAL_ESRGAN_URL, zip_path)
                        with zipfile.ZipFile(zip_path, "r") as zf:
                            for name in zf.namelist():
                                if name.endswith("/"):
                                    continue
                                basename = os.path.basename(name)
                                if not basename:
                                    continue
                                target = _res(basename)
                                with zf.open(name) as src_f, open(target, "wb") as dst_f:
                                    dst_f.write(src_f.read())
                        os.unlink(zip_path)
                    except Exception:
                        if os.path.isfile(zip_path):
                            try:
                                os.unlink(zip_path)
                            except OSError:
                                pass
            REAL_ESRGAN_BIN = _find_realesrgan_bin()
            REAL_ESRGAN_MODEL = _find_realesrgan_model()

        # Check for DAT models + VRAM
        if _dat_models_exist():
            vram = _detect_vram_mb()
            if vram >= 6000:
                try:
                    import onnxruntime as ort
                    providers = ort.get_available_providers()
                    if "DmlExecutionProvider" in providers:
                        self.engine_label.configure(text="DAT (ONNX/DirectML)")
                        return
                except Exception:
                    pass

        if REAL_ESRGAN_BIN and REAL_ESRGAN_MODEL:
            self.engine_label.configure(text="AI Real-ESRGAN")
        else:
            self.engine_label.configure(text="Lanczos")

    def _show_about(self) -> None:
        if getattr(self, "_about_open", False) and getattr(self, "_about_dialog", None) is not None:
            try:
                if self._about_dialog.winfo_exists():
                    self._about_dialog.lift()
                    self._about_dialog.focus_force()
                    return
            except Exception:
                pass

        self._about_open = True
        top = tk.Toplevel(self)
        self._about_dialog = top
        top.title("About Rice Upscaler")
        top.configure(bg=BG_PANEL)
        top.transient(self)
        top.resizable(False, False)
        if getattr(self, "_window_icon_photos", None):
            try:
                top.iconphoto(False, *self._window_icon_photos)
            except Exception:
                pass
        elif getattr(self, "_window_icon_photo", None) is not None:
            try:
                top.iconphoto(False, self._window_icon_photo)
            except Exception:
                pass

        about_text = (
            "Rice Upscaler v1.0\n\n"
            "AI-powered image upscaler.\n\n"
            "Home: https://riceupscaler.techomespace.com\n"
            "Thank you: https://riceupscaler.techomespace.com/thankyou\n"
            "Donate: https://riceupscaler.techomespace.com/donate"
        )

        w, h = 480, 480
        self.update_idletasks()
        rx = self.winfo_rootx()
        ry = self.winfo_rooty()
        rw = self.winfo_width()
        rh = self.winfo_height()
        x = max(0, rx + (rw - w) // 2)
        y = max(0, ry + (rh - h) // 2)
        top.geometry(f"{w}x{h}+{x}+{y}")
        top.update_idletasks()
        _dark_titlebar(top)

        content_frame = tk.Frame(top, bg=BG_PANEL, padx=20, pady=20)
        content_frame.pack(fill="both", expand=True)

        btn_row = tk.Frame(content_frame, bg=BG_PANEL)
        btn_row.pack(side="bottom", fill="x", pady=(14, 0))

        def copy_text():
            try:
                top.clipboard_clear()
                top.clipboard_append(about_text)
                top.update()
                btn_copy.configure(text="Copied!")
                def _reset_btn():
                    try:
                        if top.winfo_exists() and btn_copy.winfo_exists():
                            btn_copy.configure(text="Coppy")
                    except Exception:
                        pass
                top.after(1500, _reset_btn)
            except Exception:
                pass

        def _close_about(_e=None):
            self._about_open = False
            self._about_dialog = None
            try:
                top.destroy()
            except Exception:
                pass

        def _on_destroy(e):
            if e.widget == top:
                self._about_open = False
                self._about_dialog = None

        top.bind("<Destroy>", _on_destroy, add="+")

        btn_copy = CustomButton(btn_row, text="Coppy", command=copy_text,
                                style="secondary", height=32)
        btn_copy.pack(side="left")

        btn_close = CustomButton(btn_row, text="Exit", command=_close_about,
                                 style="primary", height=32)
        btn_close.pack(side="right")

        txt_frame = tk.Frame(content_frame, bg=BORDER_SUBTLE, padx=1, pady=1)
        txt_frame.pack(side="top", fill="both", expand=True)

        txt = tk.Text(
            txt_frame, bg=BG_INPUT, fg=TEXT_PRIMARY,
            insertbackground=ACCENT, selectbackground=ACCENT, selectforeground=ACCENT_TEXT_ON,
            relief="flat", bd=0, highlightthickness=0,
            font=("Segoe UI", -12), padx=12, pady=12,
            wrap="word"
        )
        txt.pack(fill="both", expand=True)
        txt.insert("1.0", about_text)

        title_pos = txt.search("Rice Upscaler v1.0", "1.0", stopindex=tk.END)
        if title_pos:
            txt.tag_add("title_tag", title_pos, f"{title_pos}+18c")
            txt.tag_config("title_tag", font=("Segoe UI", -13, "bold"), foreground=TEXT_PRIMARY)

        def _open_url(url: str):
            try:
                threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
            except Exception:
                try:
                    webbrowser.open(url)
                except Exception:
                    pass

        link_items = [
            ("link_thankyou", "https://riceupscaler.techomespace.com/thankyou"),
            ("link_donate", "https://riceupscaler.techomespace.com/donate"),
            ("link_home", "https://riceupscaler.techomespace.com"),
        ]
        for tag_name, url in link_items:
            pos = txt.search(url, "1.0", stopindex=tk.END)
            if pos:
                end_pos = f"{pos}+{len(url)}c"
                txt.tag_add(tag_name, pos, end_pos)
                txt.tag_config(tag_name, foreground=ACCENT, underline=False)
                txt.tag_bind(tag_name, "<Enter>", lambda e, tg=tag_name: (txt.config(cursor="hand2"), txt.tag_config(tg, foreground=ACCENT_HOVER)))
                txt.tag_bind(tag_name, "<Leave>", lambda e, tg=tag_name: (txt.config(cursor=""), txt.tag_config(tg, foreground=ACCENT)))
                txt.tag_bind(tag_name, "<Button-1>", lambda e, u=url: (_open_url(u), "break")[1])
                line_num = pos.split(".")[0]
                lbl_tag = f"lbl_{tag_name}"
                txt.tag_add(lbl_tag, f"{line_num}.0", pos)
                txt.tag_bind(lbl_tag, "<Enter>", lambda e, tg=tag_name: (txt.config(cursor="hand2"), txt.tag_config(tg, foreground=ACCENT_HOVER)))
                txt.tag_bind(lbl_tag, "<Leave>", lambda e, tg=tag_name: (txt.config(cursor=""), txt.tag_config(tg, foreground=ACCENT)))
                txt.tag_bind(lbl_tag, "<Button-1>", lambda e, u=url: (_open_url(u), "break")[1])

        txt.configure(state="disabled")

        top.protocol("WM_DELETE_WINDOW", _close_about)
        top.bind("<Escape>", _close_about)
        top.grab_set()

    # ── File List ─────────────────────────────────────────────────────────────
    def add_files(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            self.after(0, self.add_files)
            return
        try:
            init_dir = self._get_safe_initialdir()
            patterns = " ".join(f"*{ext}" for ext in sorted(INPUT_EXTS))
            with self._pause_windnd_during_dialog():
                paths = filedialog.askopenfilenames(
                    parent=self,
                    title="Select images",
                    initialdir=init_dir,
                    filetypes=[
                        ("Images", patterns),
                        ("JPG/JPEG", "*.jpg *.jpeg"),
                        ("HEIC", "*.heic"),
                        ("PNG", "*.png"),
                        ("WebP", "*.webp"),
                        ("All files", "*.*")
                    ]
                )
            if paths:
                first_dir = os.path.dirname(paths[0])
                if os.path.isdir(first_dir):
                    self._last_open_dir = first_dir
                self._append_paths(paths)
        except Exception:
            pass

    def add_folder(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            self.after(0, self.add_folder)
            return
        try:
            init_dir = self._get_safe_initialdir()
            with self._pause_windnd_during_dialog():
                folder = filedialog.askdirectory(parent=self, title="Select folder", initialdir=init_dir)
            if not folder:
                return
            if os.path.isdir(folder):
                self._last_open_dir = folder
            try:
                found = [os.path.join(folder, n) for n in sorted(os.listdir(folder))
                         if os.path.splitext(n)[1].lower() in INPUT_EXTS
                         and os.path.isfile(os.path.join(folder, n))]
            except OSError as error:
                messagebox.showerror("Error", f"Cannot read folder:\n{error}", parent=self)
                return
            if not found:
                messagebox.showinfo("No images",
                                    "This folder contains no JPG/JPEG/PNG/WebP files.", parent=self)
                return
            self._append_paths(found)
        except Exception:
            pass

    def _append_paths(self, paths) -> None:
        try:
            known = set(self.files)
            added = 0
            for p in paths:
                if p in known:
                    continue
                ext = os.path.splitext(p)[1].lower()
                if ext not in INPUT_EXTS:
                    continue
                known.add(p)
                self.files.append(p)
                added += 1
            if self.files:
                self._refresh_cards()
                self._update_output_hint()
                self._update_est_time()
                self._update_status_ready()
                if not self.running:
                    self._update_start_button_state(True)
                self._wake_drain()
            else:
                self._update_status_ready()
        except Exception:
            pass

    def _on_cards_inner_configure(self, _e=None) -> None:
        try:
            self.cards_canvas.configure(scrollregion=self.cards_canvas.bbox("all"))
            self._check_cards_overflow()
        except Exception:
            pass

    def _on_cards_canvas_configure(self, e) -> None:
        try:
            self.cards_canvas.itemconfig(self.cards_window, width=e.width)
            self._check_cards_overflow()
        except Exception:
            pass

    def _on_cards_scroll_set(self, first, last) -> None:
        try:
            if not self.files:
                if hasattr(self, "cards_scroll") and self.cards_scroll.winfo_ismapped():
                    self.cards_scroll.pack_forget()
                return
            f, l = float(first), float(last)
            if f <= 0.001 and l >= 0.999:
                if hasattr(self, "cards_scroll") and self.cards_scroll.winfo_ismapped():
                    self.cards_scroll.pack_forget()
            else:
                if hasattr(self, "cards_scroll") and not self.cards_scroll.winfo_ismapped():
                    self.cards_scroll.pack(side="right", fill="y")
            if hasattr(self, "cards_scroll"):
                self.cards_scroll.set(first, last)
        except (ValueError, TypeError, Exception):
            pass

    def _check_cards_overflow(self) -> None:
        try:
            if not self.files:
                if hasattr(self, "cards_scroll") and self.cards_scroll.winfo_ismapped():
                    self.cards_scroll.pack_forget()
                return
            bbox = self.cards_canvas.bbox("all")
            if not bbox:
                if hasattr(self, "cards_scroll") and self.cards_scroll.winfo_ismapped():
                    self.cards_scroll.pack_forget()
                return
            content_h = bbox[3] - bbox[1]
            visible_h = self.cards_canvas.winfo_height()
            if visible_h > 20 and content_h > visible_h:
                if hasattr(self, "cards_scroll") and not self.cards_scroll.winfo_ismapped():
                    self.cards_scroll.pack(side="right", fill="y")
            else:
                if hasattr(self, "cards_scroll") and self.cards_scroll.winfo_ismapped():
                    self.cards_scroll.pack_forget()
        except Exception:
            pass

    def remove_at(self, index: int) -> None:
        if 0 <= index < len(self.files):
            removed = self.files.pop(index)
            self._card_refs.pop(removed, None)
            self._thumb_pending.discard(removed)
            self._refresh_cards()
            self._update_output_hint()
            self._update_est_time()
            self._update_status_ready()
            self.progress.configure(value=0)
            self.pct_label.configure(text="0%")
            if not self.files and not self.running:
                self.start_button.configure(state="disabled")

    def clear_files(self) -> None:
        self.files.clear()
        self._card_refs.clear()
        self._thumb_pending.clear()
        self._refresh_cards()
        self._update_output_hint()
        self._update_est_time()
        self._update_status_ready()
        self.progress.configure(value=0)
        self.pct_label.configure(text="0%")
        if not self.running:
            self.start_button.configure(state="disabled")

    def _refresh_cards(self) -> None:
        self._card_refs.clear()
        for child in self.cards_inner.winfo_children():
            try:
                child.destroy()
            except Exception:
                pass
        if not self.files:
            if hasattr(self, "cards_scroll") and self.cards_scroll.winfo_ismapped():
                self.cards_scroll.pack_forget()
            self.cards_canvas.configure(scrollregion=(0, 0, 0, 0))
            self.cards_canvas.yview_moveto(0)
            return
        for i, path in enumerate(self.files):
            self._make_card(i, path)

    def _start_thumb_worker(self) -> None:
        t = threading.Thread(target=self._thumb_worker_loop, daemon=True, name="thumb-loader")
        t.start()

    def _thumb_worker_loop(self) -> None:
        while True:
            try:
                path = self._thumb_queue.get()
                if path is None:
                    break
                pil_thumb, dims, full_sz = self._generate_thumb_data(path)
                self.events.put(("thumb_loaded", path, pil_thumb, dims, full_sz))
            except Exception:
                pass
            finally:
                try:
                    self._thumb_queue.task_done()
                except Exception:
                    pass

    @staticmethod
    def _generate_thumb_data(path: str) -> tuple[Image.Image | None, tuple[int, int] | None, str]:
        pil_thumb = None
        dims = None
        w, h = 0, 0
        try:
            with Image.open(path) as img:
                w, h = img.size
                dims = (w, h)
                img = img.convert("RGBA")
                scale = max(40 / w, 40 / h) if w > 0 and h > 0 else 1
                nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
                img = img.resize((nw, nh), Image.LANCZOS)
                left = max(0, (nw - 40) // 2)
                top = max(0, (nh - 40) // 2)
                img = img.crop((left, top, left + 40, top + 40))

                mask = Image.new("L", (40, 40), 0)
                draw = ImageDraw.Draw(mask)
                draw.rounded_rectangle((0, 0, 40, 40), radius=6, fill=255)
                img.putalpha(mask)
                pil_thumb = img
        except Exception:
            pass

        full_sz = ""
        try:
            sz_str = ""
            if os.path.isfile(path):
                sz_bytes = os.path.getsize(path)
                sz_mb = sz_bytes / 1048576
                if sz_mb >= 1.0:
                    sz_str = f"{sz_mb:.1f} MB"
                else:
                    sz_str = f"{sz_bytes / 1024:.0f} KB"
            if w and h:
                full_sz = f"{w}×{h} • {sz_str}" if sz_str else f"{w}×{h}"
            else:
                full_sz = sz_str
        except Exception:
            pass

        return pil_thumb, dims, full_sz

    def _get_fast_size_str(self, path: str) -> str:
        try:
            if os.path.isfile(path):
                sz_bytes = os.path.getsize(path)
                sz_mb = sz_bytes / 1048576
                if sz_mb >= 1.0:
                    return f"— • {sz_mb:.1f} MB"
                return f"— • {sz_bytes / 1024:.0f} KB"
        except Exception:
            pass
        return "—"

    def _queue_thumb_load(self, path: str) -> None:
        if path not in self._thumb_pending and (path not in self._thumb_cache or path not in self._meta_cache):
            self._thumb_pending.add(path)
            self._thumb_queue.put(path)

    def _make_card(self, index: int, path: str) -> None:
        card = tk.Frame(self.cards_inner, bg=BG_INPUT,
                        highlightbackground=BORDER_SUBTLE, highlightthickness=1,
                        padx=10, pady=8, bd=0, relief="flat")
        card.pack(fill="x", pady=(0, 6))
        card.columnconfigure(1, weight=1)

        # 40x40px Thumbnail with 6px radius (lazy loaded)
        thumb = self._thumb_cache.get(path)
        if thumb:
            lbl_thumb = tk.Label(card, image=thumb, bg=BG_INPUT, width=40, height=40, bd=0, relief="flat")
            lbl_thumb.image = thumb
            lbl_thumb.grid(row=0, column=0, rowspan=2, padx=(0, 10))
        else:
            lbl_thumb = tk.Label(card, text="🖼", bg=BG_INPUT, fg=TEXT_SECONDARY,
                                 width=4, height=2, font=("Segoe UI", 11), bd=0, relief="flat")
            lbl_thumb.grid(row=0, column=0, rowspan=2, padx=(0, 10))
            self._queue_thumb_load(path)

        # Filename (13px bold) over meta line (12px secondary)
        name = os.path.basename(path)
        meta = self._meta_cache.get(path)
        if meta and meta.get("size_str"):
            size_str = meta["size_str"]
        else:
            size_str = self._get_fast_size_str(path)
            self._queue_thumb_load(path)

        tk.Label(card, text=name, bg=BG_INPUT, fg=TEXT_PRIMARY,
                 font=("Segoe UI", -13, "bold"), anchor="w", bd=0, relief="flat").grid(
            row=0, column=1, sticky="w")
        lbl_size = tk.Label(card, text=size_str, bg=BG_INPUT, fg=TEXT_SECONDARY,
                            font=("Segoe UI", -12), anchor="w", bd=0, relief="flat")
        lbl_size.grid(row=1, column=1, sticky="w")

        self._card_refs[path] = {"lbl_thumb": lbl_thumb, "lbl_size": lbl_size}

        # Circular ✕ button (28px)
        x_btn = CircleCloseButton(card, command=lambda idx=index: self.remove_at(idx), size=28)
        x_btn.grid(row=0, column=2, rowspan=2, padx=(8, 0))

    def _get_thumb(self, path: str) -> ImageTk.PhotoImage | None:
        if path in self._thumb_cache:
            return self._thumb_cache[path]
        self._queue_thumb_load(path)
        return None

    def _get_size_str(self, path: str) -> str:
        meta = self._meta_cache.get(path)
        if meta and meta.get("size_str"):
            return meta["size_str"]
        self._queue_thumb_load(path)
        return self._get_fast_size_str(path)

    # ── Output / Options ──────────────────────────────────────────────────────
    def pick_output(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            self.after(0, self.pick_output)
            return
        try:
            current = self.out_dir.get().strip()
            init_dir = current if (current and os.path.isdir(current)) else self._get_safe_initialdir()
            with self._pause_windnd_during_dialog():
                chosen = filedialog.askdirectory(parent=self, title="Select output folder", initialdir=init_dir)
            if chosen:
                self.out_dir.set(chosen)
                self._last_open_dir = chosen
        except Exception:
            pass

    def open_output(self) -> None:
        target = self.out_dir.get().strip()
        if target == "—":
            target = ""
        if not target:
            first = getattr(self, "first_dst", None)
            if first:
                target = os.path.dirname(first)
            elif self.files:
                target = os.path.dirname(self.files[0])
        if not target or not os.path.isdir(target):
            messagebox.showinfo("Output folder",
                                "No output folder set yet.")
            return
        try:
            os.startfile(target)
        except (OSError, AttributeError) as error:
            messagebox.showerror("Error", str(error))

    def _sync_quality(self) -> None:
        mode = self.fmt.get()
        show_jpeg = mode in ("Default", "JPG")
        show_png = mode in ("Default", "PNG")

        # Always forget both first, then re-pack in fixed order (JPEG → PNG)
        self._jpeg_frame.pack_forget()
        self._png_frame.pack_forget()

        if show_jpeg:
            self._jpeg_frame.pack(in_=self._quality_area, fill="x", pady=(0, 10))
        if show_png:
            self._png_frame.pack(in_=self._quality_area, fill="x", pady=(0, 10))

    def _update_start_button_state(self, can_start: bool) -> None:
        if not hasattr(self, "start_button"):
            return
        raw = self.target_mb.get().strip().replace(",", ".")
        if raw == "—":
            raw = ""
        if raw:
            try:
                v = float(raw)
                if not (TARGET_MIN_MB <= v <= TARGET_MAX_MB):
                    can_start = False
            except ValueError:
                can_start = False
        if not self.files:
            can_start = False
        self.start_button.configure(state="normal" if can_start else "disabled")

    def _sync_target_override(self, *_a) -> None:
        raw = self.target_mb.get().strip().replace(",", ".")
        if raw == "—":
            raw = ""
        has_target = bool(raw)
        state = "disabled" if has_target else "normal"
        if hasattr(self, "quality_scale"):
            self.quality_scale.configure(state=state)
        if hasattr(self, "png_scale"):
            self.png_scale.configure(state=state)

        valid = True
        if raw:
            try:
                val = float(raw)
                if not (TARGET_MIN_MB <= val <= TARGET_MAX_MB):
                    valid = False
            except ValueError:
                valid = False

        if hasattr(self, "target_err_label"):
            if raw and not valid:
                self.target_err_label.configure(
                    text=f"Must be between {TARGET_MIN_MB} and {TARGET_MAX_MB} MB")
            else:
                self.target_err_label.configure(text="")

        if not self.running and hasattr(self, "start_button"):
            self._update_start_button_state(len(self.files) > 0 and valid)

    def _update_output_hint(self) -> None:
        if not self.files:
            self.output_hint.set("Output: — (select images to preview)")
            return
        w, h = 0, 0
        first_path = self.files[0]
        meta = self._meta_cache.get(first_path)
        if meta and meta.get("dims"):
            w, h = meta["dims"]
        else:
            try:
                with Image.open(first_path) as img:
                    w, h = img.size
                    if first_path not in self._meta_cache:
                        self._meta_cache[first_path] = {"dims": (w, h), "size_str": self._get_fast_size_str(first_path)}
            except Exception:
                pass

        if w and h:
            s = int(round(self.scale.get()))
            if s <= 1:
                base = f"Output: {w}×{h} • no change"
            else:
                mult = s * s
                base = f"Output: {w * s}×{h * s} • ~{mult}x pixels"
            if len(self.files) > 1:
                base += f" +{len(self.files) - 1} more"
            self.output_hint.set(base)
        else:
            self.output_hint.set("Output: — (select images to preview)")

    def _update_est_time(self) -> None:
        n = len(self.files)
        if n == 0:
            self.est_time.set("")
            return
        # Check for DAT, AI, or Lanczos
        use_dat = False
        if _dat_models_exist():
            vram = _detect_vram_mb()
            if vram >= 6000:
                try:
                    import onnxruntime as ort
                    providers = ort.get_available_providers()
                    if "DmlExecutionProvider" in providers:
                        use_dat = True
                except Exception:
                    pass
        use_ai = int(round(self.scale.get())) > 1 and REAL_ESRGAN_BIN is not None
        per = 5 if use_dat else (8 if use_ai else 1.5)
        total = n * per
        if total < 60:
            self.est_time.set(f"~{int(total)}s")
        else:
            self.est_time.set(f"~{int(total // 60)}m {int(total % 60)}s")

    def _update_status_ready(self) -> None:
        n = len(self.files)
        if n == 0:
            txt = "Ready: 0 files queued"
            self.status_prefix_label.configure(text="Ready:", fg=TEXT_GREEN)
            self.status_text_label.configure(text=" 0 files queued ", fg=TEXT_PRIMARY)
            self.status_dot_label.configure(text="●", fg=ACCENT)
        else:
            est = self.est_time.get()
            est_str = f" • Est. {est}" if est else ""
            txt = f"Ready: {n} files queued{est_str}"
            self.status_prefix_label.configure(text="Ready:", fg=TEXT_GREEN)
            self.status_text_label.configure(text=f" {n} files queued{est_str} ", fg=TEXT_PRIMARY)
            self.status_dot_label.configure(text="●", fg=ACCENT)
        self.status.set(txt)

    def _read_options(self) -> dict:
        raw_target = self.target_mb.get().strip().replace(",", ".")
        if raw_target == "—":
            raw_target = ""
        target_mb = 0.0
        if raw_target:
            try:
                target_mb = float(raw_target)
            except ValueError:
                raise ValueError(f"Must be between {TARGET_MIN_MB} and {TARGET_MAX_MB} MB")
            if not (TARGET_MIN_MB <= target_mb <= TARGET_MAX_MB):
                raise ValueError(f"Must be between {TARGET_MIN_MB} and {TARGET_MAX_MB} MB")
        return {
            "scale": max(MIN_SCALE, min(MAX_SCALE, int(round(self.scale.get())))),
            "quality": max(1, min(100, int(round(self.quality.get())))),
            "png_compress": max(0, min(9, int(round(self.png_compress.get())))),
            "target_mb": target_mb,
            "fmt": self.fmt.get(),
            "dpi": self.dpi.get(),
        }

    # ── Run ───────────────────────────────────────────────────────────────────
    def start(self) -> None:
        try:
            if self.running:
                return
            if not self.files:
                messagebox.showwarning("No files", "Add at least one image first.")
                return
            try:
                opts = self._read_options()
            except ValueError as error:
                messagebox.showerror("Invalid options", str(error))
                return

            dest = self.out_dir.get().strip()
            if dest == "—":
                dest = ""
            if dest:
                try:
                    os.makedirs(dest, exist_ok=True)
                except OSError as error:
                    messagebox.showerror("Error", f"Cannot create output folder:\n{error}")
                    return

            tasks = []
            for src in list(self.files):
                stem = os.path.splitext(os.path.basename(src))[0]
                ext = ".jpg" if opts["fmt"] == "JPG" else (
                    ".png" if opts["fmt"] == "PNG" else
                    (".jpg" if os.path.splitext(src)[1].lower() in JPEG_EXTS else ".png"))
                name = f"{stem}_upscaled{ext}"
                dst = os.path.join(dest or os.path.dirname(src), name)
                tasks.append((src, dst))

            self.first_dst = tasks[0][1] if tasks else None

            # Determine engine: DAT > AI > Lanczos
            scale = opts["scale"]
            use_dat = False
            use_ai = False
            if scale > 1:
                if _dat_models_exist():
                    vram = _detect_vram_mb()
                    if vram >= 6000:
                        try:
                            import onnxruntime as ort
                            providers = ort.get_available_providers()
                            if "DmlExecutionProvider" in providers:
                                use_dat = True
                        except Exception:
                            pass
                if not use_dat:
                    use_ai = REAL_ESRGAN_BIN is not None

            self.total = len(tasks)
            self.processed = 0
            self.cancel_event.clear()
            self.running = True
            self.progress.configure(maximum=self.total, value=0)
            self.pct_label.configure(text="0%")

            if use_dat:
                ai_info = " [DAT]"
            elif use_ai:
                ai_info = " [AI]"
            else:
                ai_info = ""
            self.status_prefix_label.configure(text="Processing:", fg=TEXT_GREEN)
            self.status_text_label.configure(text=f" 0/{self.total}{ai_info} ", fg=TEXT_PRIMARY)
            self.status_dot_label.configure(fg=ACCENT)
            self.status.set(f"Processing 0/{self.total}{ai_info}")
            self._set_running(True)

            t = threading.Thread(target=self._run_batch,
                                 args=(tasks, opts, use_ai),
                                 daemon=True, name="rice-upscaler-worker")
            t.start()
            self._wake_drain()
        except Exception:
            pass

    def _set_running(self, running: bool) -> None:
        try:
            if running:
                self.start_button.configure(state="disabled")
                self.cancel_button.configure(state="normal")
                self.open_button.configure(state="normal")
                for name in ("btn_add_files", "btn_add_folder", "btn_clear"):
                    getattr(self, name).configure(state="disabled")
            else:
                self.cancel_button.configure(state="normal")
                self.open_button.configure(state="normal")
                for name in ("btn_add_files", "btn_add_folder", "btn_clear"):
                    getattr(self, name).configure(state="normal")
                self._update_start_button_state(len(self.files) > 0)
        except Exception:
            pass

    def cancel(self) -> None:
        try:
            if self.running:
                self.cancel_event.set()
                self.status_prefix_label.configure(text="Cancelling:", fg=ERROR_FG)
                self.status_text_label.configure(text=" waiting for current file to finish... ", fg=TEXT_SECONDARY)
                self.status_dot_label.configure(fg=ERROR_FG)
                self.status.set("Cancelling — waiting for current file to finish...")
                self._wake_drain()
            else:
                self.progress.configure(value=0)
                self.pct_label.configure(text="0%")
                self._update_status_ready()
        except Exception:
            pass

    # ── Worker ────────────────────────────────────────────────────────────────
    # Per-file total timeout (seconds) to prevent worker hangs
    FILE_TIMEOUT = 600  # 10 minutes hard cap per file

    def _run_batch(self, tasks, opts, use_ai) -> None:
        for idx, (src, dst) in enumerate(tasks, 1):
            if self.cancel_event.is_set():
                self.events.put(("done", idx - 1))
                return
            name = os.path.basename(src)
            try:
                # Run process_file with per-file timeout
                result_queue = queue.Queue()
                def worker():
                    try:
                        res = process_file(src, dst, opts, self.cancel_event, use_ai)
                        result_queue.put(("success", res))
                    except Exception as e:
                        result_queue.put(("error", e))
                
                t = threading.Thread(target=worker, daemon=True)
                t.start()
                t.join(timeout=self.FILE_TIMEOUT)
                if t.is_alive():
                    # Timeout - file took too long, mark as failed and continue
                    info = f"TIMEOUT: file exceeded {self.FILE_TIMEOUT}s limit, skipped"
                else:
                    try:
                        status, data = result_queue.get_nowait()
                        if status == "success":
                            info = data
                        else:
                            info = f"ERROR {type(data).__name__}: {data}"
                    except queue.Empty:
                        info = "ERROR: worker thread returned no result"
            except Exception as error:
                info = f"ERROR {type(error).__name__}: {error}"
            self.events.put(("item", name, info))
        gc.collect()
        self.events.put(("done", len(tasks)))

    # ── UI Pump ───────────────────────────────────────────────────────────────
    def _schedule_drain(self, delay: int = 150) -> None:
        try:
            if getattr(self, "_drain_scheduled", False):
                return
            if not self.winfo_exists():
                return
            self._drain_scheduled = True
            self._drain_after_id = self.after(delay, self._drain)
        except Exception:
            self._drain_scheduled = False
            self._drain_after_id = None

    def _wake_drain(self) -> None:
        try:
            if getattr(self, "_drain_after_id", None) is not None:
                try:
                    self.after_cancel(self._drain_after_id)
                except Exception:
                    pass
            self._drain_scheduled = False
            self._drain_after_id = None
            self._schedule_drain(20)
        except Exception:
            pass

    def _drain(self) -> None:
        self._drain_scheduled = False
        self._drain_after_id = None
        has_event = False
        finished = False
        try:
            while True:
                try:
                    event = self.events.get_nowait()
                except queue.Empty:
                    break
                has_event = True
                try:
                    etype = event[0]
                    if etype == "item":
                        _, name, info = event
                        self.processed += 1
                        self.progress.configure(value=self.processed)
                        pct = int(self.processed / self.total * 100) if self.total else 0
                        self.pct_label.configure(text=f"{pct}%")
                        is_err = info.startswith(("ERROR", "FAILED"))
                        colour = ERROR_FG if is_err else TEXT_PRIMARY
                        self.status_prefix_label.configure(text="Processing:", fg=TEXT_GREEN)
                        # Truncate filename to ~40 chars for single-line status
                        disp_name = name if len(name) <= 40 else name[:37] + "…"
                        self.status_text_label.configure(
                            text=f" {self.processed}/{self.total} • {disp_name} ", fg=colour)
                        self.status_dot_label.configure(fg=ACCENT)
                        # One-line status: "N/M • filename → result"
                        self.status.set(f"{self.processed}/{self.total} • {disp_name} → {info}")
                    elif etype == "thumb_loaded":
                        _, path, pil_thumb, dims, size_str = event
                        if path in self._thumb_pending:
                            self._thumb_pending.discard(path)
                        if dims:
                            self._meta_cache[path] = {"dims": dims, "size_str": size_str}
                            if self.files and self.files[0] == path:
                                self._update_output_hint()
                        if pil_thumb is not None:
                            try:
                                photo = ImageTk.PhotoImage(pil_thumb)
                                self._thumb_cache[path] = photo
                            except Exception:
                                photo = None
                        else:
                            photo = None

                        card_info = self._card_refs.get(path)
                        if card_info:
                            try:
                                lbl_thumb = card_info.get("lbl_thumb")
                                if lbl_thumb and lbl_thumb.winfo_exists() and photo:
                                    lbl_thumb.configure(image=photo, text="", width=40, height=40)
                                    lbl_thumb.image = photo
                                lbl_size = card_info.get("lbl_size")
                                if lbl_size and lbl_size.winfo_exists() and size_str:
                                    lbl_size.configure(text=size_str)
                            except Exception:
                                pass
                    else:
                        finished = True
                        self._finish(event[1])
                except Exception:
                    pass

            if finished and self.running:
                try:
                    self._apply_finish()
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            try:
                if self.winfo_exists():
                    delay = 20 if (self.running or has_event) else 150
                    self._schedule_drain(delay)
            except Exception:
                pass

    def _finish(self, processed: int) -> None:
        try:
            if self.cancel_event.is_set():
                self.final_state = "Cancelled"
            elif processed < self.total:
                self.final_state = "Stopped"
            else:
                self.final_state = "Done"
            self.final_processed = processed
        except Exception:
            pass

    def _apply_finish(self) -> None:
        try:
            self.running = False
            self._set_running(False)
            state = getattr(self, "final_state", "Done")
            processed = getattr(self, "final_processed", self.processed)
            left = self.total - processed
            if state == "Cancelled":
                prefix = "Cancelled:"
                text = f" {processed}/{self.total} processed"
                if left:
                    text += f" • {left} remaining"
                self.status_prefix_label.configure(text=prefix, fg=ERROR_FG)
                self.status_text_label.configure(text=text, fg=TEXT_SECONDARY)
                self.status_dot_label.configure(fg=ERROR_FG)
                self.status.set(f"Cancelled: {processed}/{self.total} processed" + (f" • {left} remaining" if left else ""))
            else:
                prefix = "Done:"
                text = f" {processed}/{self.total} processed"
                self.status_prefix_label.configure(text=prefix, fg=TEXT_GREEN)
                self.status_text_label.configure(text=text, fg=TEXT_PRIMARY)
                self.status_dot_label.configure(fg=ACCENT)
                self.status.set(f"Done: {processed}/{self.total} processed")
        except Exception:
            pass


def _cleanup_dnd_hook() -> None:
    global _WINDND
    if not _WINDND:
        return
    try:
        import windnd
        # Unhook all windows
        try:
            windnd.unhook_all()
        except Exception:
            pass
    except Exception:
        pass


if __name__ == "__main__":
    _fix_win32_ctypes()
    _enable_dpi_awareness()
    _prevent_auto_exit = True
    try:
        app = App()
        app.mainloop()
    except Exception as exc:
        _global_except_hook(type(exc), exc, exc.__traceback__)
    finally:
        _cleanup_dnd_hook()
