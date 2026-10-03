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
import zipfile
import binascii
import urllib.request

import numpy as np
from PIL import Image, ImageDraw, ImageFile, ImageFilter, ImageOps, ImageTk

try:
    import windnd
    _WINDND = True
except ImportError:
    _WINDND = False

# ── Design Tokens ─────────────────────────────────────────────────────────────
BG_APP         = "#14181E"  # Window background
BG_TITLEBAR    = "#1B1E24"  # Title bar
BG_PANEL       = "#1E242E"  # Main panels (INPUT FILES, OUTPUT SETTINGS), topbar, status
BG_INPUT       = "#2A313C"  # File cards, dropdown fields, path field, secondary buttons
BG_DROPZONE    = "#1A222B"  # Drag & drop zone fill (slightly tinted)
BORDER_SUBTLE  = "#2E3642"  # Panel borders, card borders (1px)
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

APP_TITLE = "UPSCALE"

INPUT_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
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

EXT_FORMAT = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP"}
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
    return os.path.isfile(_res("realesrgan-x4plus.bin"))


def _startupinfo():
    if sys.platform == "win32":
        si = subprocess.STARTUPINFO()
        si.dwFlags = subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        return si
    return None


_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) \
    if sys.platform == "win32" else 0


def _detect_vram_mb() -> int:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
            startupinfo=_startupinfo(), creationflags=_NO_WINDOW)
        if result.returncode == 0 and result.stdout.strip():
            return int(result.stdout.strip().split()[0])
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, IndexError):
        pass
    return 0


def _free_ram_mb() -> int:
    try:
        import ctypes
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
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
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


def _decide_engine(scale: int) -> tuple[str, str]:
    if scale == 1:
        return "lanczos", "AI skipped (scale=1)"
    if REAL_ESRGAN_BIN is None:
        return "lanczos", "AI binary not found"
    if not REAL_ESRGAN_MODEL:
        return "lanczos", "AI model not found"
    free = _free_ram_mb()
    if free < 2048:
        return "lanczos", f"Low RAM ({free} MB < 2048 MB)"
    return "ai", ""


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
    with Image.open(path) as opened:
        opened.load()
        fmt = (opened.format or "").upper()
        if fmt == "MPO":
            fmt = "JPEG"
        dpi = opened.info.get("dpi")
        image = opened.convert("RGB")
    if fmt not in FORMAT_EXT:
        fmt = EXT_FORMAT.get(os.path.splitext(path)[1].lower(), "PNG")
    return image, fmt, dpi


def _detect_enhance_params(image: Image.Image) -> dict:
    gray = image.convert("L")
    arr = np.asarray(gray, dtype=np.float32)

    lap = np.array([[0, 1, 0], [1, -4, 1], [0, 1, 0]], dtype=np.float32)
    from numpy.lib.stride_tricks import sliding_window_view
    windows = sliding_window_view(arr, (3, 3))
    edges = np.einsum("ijkl,kl->ij", windows, lap)
    edge_var = float(np.var(edges))

    std = float(np.std(arr))

    mean_val = float(np.mean(arr))
    contrast = float(np.percentile(arr, 95) - np.percentile(arr, 5))

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
    return out


def _auto_color_grade(image: Image.Image) -> Image.Image:
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


# ── Real-ESRGAN ───────────────────────────────────────────────────────────────

def upscale_realesrgan(image: Image.Image, scale: int, tile: int) -> Image.Image | None:
    if not REAL_ESRGAN_BIN:
        return None
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
        if tile > 0:
            cmd += ["-t", str(tile)]
        subprocess.run(cmd, capture_output=True, timeout=AI_TIMEOUT,
                       check=True, startupinfo=_startupinfo(),
                       creationflags=_NO_WINDOW)
        if os.path.isfile(out_path):
            result = Image.open(out_path).convert("RGB")
            os.unlink(out_path)
            os.unlink(in_path)
            return result
        os.unlink(in_path)
    except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired):
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
    image, src_fmt, src_dpi = load_rgb(src)
    if cancel.is_set():
        return "cancelled"

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

    image = _auto_color_grade(image)

    _gfpgan_available()

    params = _detect_enhance_params(image)
    image = enhance_image(image, params)

    engine, skip_reason = _decide_engine(opts["scale"])
    ai_ok = False

    if use_ai and engine == "ai":
        if _check_ai_usable():
            tile = _vram_tile if _vram_tile > 0 else 256
            try:
                result = upscale_realesrgan(image, opts["scale"], tile)
                if result is not None:
                    image = result
                    ai_ok = True
            except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired) as exc:
                skip_reason = f"AI failed ({type(exc).__name__})"

    if not ai_ok and opts["scale"] > 1:
        s = opts["scale"]
        image = image.resize((image.width * s, image.height * s), Image.LANCZOS)

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
    target_bytes = int(opts["target_mb"] * 1048576)
    pad_bytes = 0
    target_note = ""
    if target_bytes > 0:
        data, used, pad_bytes = fit_to_target(image, fmt, target_bytes, dpi)
        target_note = " (Target overrides quality)"
    else:
        data, used = encode_image(image, fmt, opts["quality"],
                                  opts["png_compress"], dpi)

    tmp = dst + ".part"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, dst)

    if not (os.path.isfile(dst) and os.path.getsize(dst) > 0):
        return f"FAILED: output missing or empty after write: {dst}"

    tag = f"c{used}" if fmt == "PNG" else f"q{used}"
    method = "AI Real-ESRGAN" if ai_ok else "Lanczos"
    note = f"{w}x{h} [{method}]"
    if skip_reason:
        note += f" ({skip_reason})"
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
        self.after_id = self.widget.after(400, self._show)

    def _show(self) -> None:
        self.after_id = None
        try:
            x = self.widget.winfo_pointerx() + 16
            y = self.widget.winfo_pointery() + 12
        except Exception:
            return
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        self.tip.configure(bg=TIP_BG)
        tk.Label(
            self.tip, text=self.text, bg=TIP_BG, fg=TIP_FG,
            justify="left", wraplength=440, padx=10, pady=7,
            font=("Segoe UI", -13), bd=0,
        ).pack()

    def _hide(self, _event=None) -> None:
        if self.after_id is not None:
            try:
                self.widget.after_cancel(self.after_id)
            except tk.TclError:
                pass
            self.after_id = None
        if self.tip is not None:
            self.tip.destroy()
            self.tip = None


# ── Dark titlebar (Windows) ───────────────────────────────────────────────────

def _dark_titlebar(root) -> None:
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        attr = 20
        value = ctypes.c_int(1)
        if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)) != 0:
            attr = 19
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass


# ── Custom Widgets ────────────────────────────────────────────────────────────

class CanvasSlider(tk.Frame):
    """
    Custom Canvas Slider matching spec:
    - 6px track (unfilled TRACK #3A4350, filled ACCENT #2FE6A7)
    - 18px circle knob (ACCENT fill with 3px BG_PANEL ring)
    - Value badge pill at right (min-width 56px, height 30px, ACCENT pill with dark bold text 13px/700)
    - Live drag and keyboard arrow keys support
    """
    def __init__(self, parent, variable: tk.IntVar, lo: int, hi: int,
                 badge_fmt: str = "{val}", discrete: bool = False,
                 bg: str = BG_PANEL, height: int = 34,
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
        self._dragging = False
        self._focused = False

        self.canvas = tk.Canvas(self, bg=bg, height=height, highlightthickness=0, takefocus=True)
        self.canvas.pack(fill="x", expand=True)

        self.canvas.bind("<Configure>", lambda _e: self._draw())
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Left>", self._on_dec)
        self.canvas.bind("<Down>", self._on_dec)
        self.canvas.bind("<Right>", self._on_inc)
        self.canvas.bind("<Up>", self._on_inc)
        self.canvas.bind("<FocusIn>", self._on_focus_in)
        self.canvas.bind("<FocusOut>", self._on_focus_out)

        self.variable.trace_add("write", lambda *_: self._draw())

    def bind(self, sequence=None, func=None, add=None):
        return self.canvas.bind(sequence, func, add=add)

    def configure(self, **kwargs):
        if "state" in kwargs:
            self._state = kwargs.pop("state")
            self._draw()
        if kwargs:
            super().configure(**kwargs)

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
        frac = max(0.0, min(1.0, (x - track_x0) / (track_x1 - track_x0)))
        raw_val = self.lo + frac * (self.hi - self.lo)
        val = int(round(raw_val))
        return max(self.lo, min(self.hi, val))

    def _draw(self) -> None:
        c = self.canvas
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 100:
            return

        cy = h // 2
        badge_w = 58
        badge_h = 30
        badge_x1 = w - 4
        badge_x0 = badge_x1 - badge_w
        badge_y0 = cy - badge_h // 2
        badge_y1 = cy + badge_h // 2

        track_x0 = 12
        track_x1 = badge_x0 - 18

        val = max(self.lo, min(self.hi, int(round(self.variable.get()))))
        frac = (val - self.lo) / (self.hi - self.lo) if self.hi > self.lo else 0.0
        knob_x = track_x0 + frac * (track_x1 - track_x0)

        is_disabled = (self._state == "disabled")
        track_unfill_col = "#242B35" if is_disabled else TRACK
        track_fill_col = "#3A4350" if is_disabled else ACCENT
        knob_fill_col = "#3A4350" if is_disabled else ACCENT
        knob_ring_col = self.bg_color
        badge_bg_col = "#242B35" if is_disabled else ACCENT
        badge_text_col = "#5A6472" if is_disabled else ACCENT_TEXT_ON

        # Unfilled track (6px round)
        c.create_line(track_x0, cy, track_x1, cy, width=6, capstyle="round", fill=track_unfill_col)
        # Filled track (6px round)
        if knob_x > track_x0:
            c.create_line(track_x0, cy, knob_x, cy, width=6, capstyle="round", fill=track_fill_col)

        # 18px circle knob with 3px BG_PANEL ring (12px outer radius masks the track)
        c.create_oval(knob_x - 12, cy - 12, knob_x + 12, cy + 12, fill=knob_ring_col, outline="")
        c.create_oval(knob_x - 9, cy - 9, knob_x + 9, cy + 9, fill=knob_fill_col, outline="")

        if self._focused and not is_disabled:
            c.create_oval(knob_x - 13, cy - 13, knob_x + 13, cy + 13, outline=ACCENT, width=1)

        # Pill badge at right (min-width 56px, height 30px)
        r = badge_h / 2
        c.create_arc(badge_x0, badge_y0, badge_x0 + badge_h, badge_y1, start=90, extent=180, fill=badge_bg_col, outline="")
        c.create_arc(badge_x1 - badge_h, badge_y0, badge_x1, badge_y1, start=270, extent=180, fill=badge_bg_col, outline="")
        c.create_rectangle(badge_x0 + r, badge_y0, badge_x1 - r, badge_y1, fill=badge_bg_col, outline="")

        text_str = self._format_badge(val)
        c.create_text((badge_x0 + badge_x1) / 2, cy, text=text_str,
                      fill=badge_text_col, font=("Segoe UI", -13, "bold"))

        c.configure(cursor="arrow" if is_disabled else "hand2")

    def _on_click(self, event) -> None:
        if self._state == "disabled":
            return
        w = self.canvas.winfo_width()
        badge_x0 = w - 4 - 58
        track_x0 = 12
        track_x1 = badge_x0 - 18
        if event.x <= badge_x0:
            val = self._calc_val_from_x(event.x, track_x0, track_x1)
            self.variable.set(val)
            if self.on_change:
                self.on_change(val)
            self._dragging = True
            self.canvas.focus_set()

    def _on_drag(self, event) -> None:
        if self._state == "disabled" or not self._dragging:
            return
        w = self.canvas.winfo_width()
        badge_x0 = w - 4 - 58
        track_x0 = 12
        track_x1 = badge_x0 - 18
        val = self._calc_val_from_x(event.x, track_x0, track_x1)
        if val != self.variable.get():
            self.variable.set(val)
            if self.on_change:
                self.on_change(val)

    def _on_release(self, _event) -> None:
        self._dragging = False

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
        c = self.canvas
        c.delete("all")
        w = c.winfo_width()
        if w < 10:
            return
        cy = self.height // 2
        pad = self.height // 2
        c.create_line(pad, cy, w - pad, cy, width=self.height, capstyle="round", fill=TRACK)
        if self.maximum > 0 and self.value > 0:
            frac = min(1.0, max(0.0, self.value / self.maximum))
            fx = pad + frac * (w - 2 * pad)
            if fx > pad:
                c.create_line(pad, cy, fx, cy, width=self.height, capstyle="round", fill=ACCENT)


class CustomButton(tk.Frame):
    """
    Custom button conforming to spec:
    - primary: ACCENT bg, dark text, hover ACCENT_HOVER, 15px/800 font
    - outline / primary-outline: 1px TEXT_PRIMARY border, transparent BG_PANEL bg, TEXT_PRIMARY text, hover ACCENT
    - secondary: BORDER_SUBTLE border, BG_INPUT bg, TEXT_PRIMARY text, hover ACCENT, 14px/600 font
    """
    def __init__(self, parent, text: str, command=None, style: str = "secondary",
                 width: int | None = None, height: int = 40):
        self.btn_style = style
        self.cmd = command
        self._state = "normal"
        self._hover = False

        if style == "primary":
            border_col = ACCENT
            bg_col = ACCENT
            fg_col = ACCENT_TEXT_ON
            font_spec = ("Segoe UI", -15, "bold")
        elif style in ("outline", "primary-outline"):
            border_col = TEXT_PRIMARY
            bg_col = BG_PANEL
            fg_col = TEXT_PRIMARY
            font_spec = ("Segoe UI", -14, "bold")
        else:
            border_col = BORDER_SUBTLE
            bg_col = BG_INPUT
            fg_col = TEXT_PRIMARY
            font_spec = ("Segoe UI", -14, "bold")

        self.normal_border = border_col
        self.normal_bg = bg_col
        self.normal_fg = fg_col

        super().__init__(parent, bg=border_col, padx=1, pady=1)

        self.btn = tk.Button(
            self, text=text, command=self._on_click,
            bg=bg_col, fg=fg_col, activebackground=bg_col,
            activeforeground=ACCENT if style != "primary" else ACCENT_TEXT_ON,
            relief="flat", bd=0, font=font_spec,
            cursor="hand2"
        )
        if width:
            self.btn.configure(width=width)
        pad_x = 28 if style == "primary" else 18
        pad_y = 11 if style == "primary" else 7
        self.btn.pack(fill="both", expand=True, padx=pad_x, pady=pad_y)

        self.btn.bind("<Enter>", self._on_enter)
        self.btn.bind("<Leave>", self._on_leave)

    def bind(self, sequence=None, func=None, add=None):
        return self.btn.bind(sequence, func, add=add)

    def _on_enter(self, _e):
        if self._state == "disabled":
            return
        self._hover = True
        if self.btn_style == "primary":
            self.btn.configure(bg=ACCENT_HOVER)
            super().configure(bg=ACCENT_HOVER)
        elif self.btn_style in ("outline", "primary-outline"):
            super().configure(bg=ACCENT)
            self.btn.configure(fg=ACCENT, bg=BG_PANEL)
        else:
            super().configure(bg=ACCENT)
            self.btn.configure(fg=ACCENT, bg=BG_INPUT)

    def _on_leave(self, _e):
        if self._state == "disabled":
            return
        self._hover = False
        if self.btn_style == "primary":
            self.btn.configure(bg=ACCENT)
            super().configure(bg=ACCENT)
        else:
            super().configure(bg=self.normal_border)
            self.btn.configure(fg=self.normal_fg, bg=self.normal_bg)

    def _on_click(self):
        if self._state != "disabled" and self.cmd:
            self.cmd()

    def configure(self, **kwargs):
        if "state" in kwargs:
            st = kwargs.pop("state")
            self._state = st
            if st == "disabled":
                self.btn.configure(state="disabled", cursor="arrow")
                if self.btn_style == "primary":
                    self.btn.configure(bg="#1A3B2F", fg="#4E7864")
                    super().configure(bg="#1A3B2F")
                elif self.btn_style in ("outline", "primary-outline"):
                    self.btn.configure(bg=BG_PANEL, fg="#5A6472")
                    super().configure(bg=BORDER_SUBTLE)
                else:
                    self.btn.configure(bg=BG_INPUT, fg="#5A6472")
                    super().configure(bg=BORDER_SUBTLE)
            else:
                self.btn.configure(state="normal", cursor="hand2")
                if self.btn_style == "primary":
                    self.btn.configure(bg=ACCENT, fg=ACCENT_TEXT_ON)
                    super().configure(bg=ACCENT)
                else:
                    self.btn.configure(bg=self.normal_bg, fg=self.normal_fg)
                    super().configure(bg=self.normal_border)
        if kwargs:
            super().configure(**kwargs)


class CircleCloseButton(tk.Canvas):
    """Circular 32px ✕ button with hover background DANGER_HOVER and white icon."""
    def __init__(self, parent, command=None, size: int = 32):
        super().__init__(parent, width=size, height=size, bg=BG_INPUT, highlightthickness=0, cursor="hand2")
        self.command = command
        self.size = size
        self._hover = False
        self._draw()
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)

    def _draw(self) -> None:
        self.delete("all")
        s = self.size
        r = s / 2
        bg_col = DANGER_HOVER if self._hover else BG_INPUT
        fg_col = "#FFFFFF" if self._hover else TEXT_SECONDARY
        if self._hover:
            self.create_oval(1, 1, s - 1, s - 1, fill=bg_col, outline="")
        self.create_text(r, r, text="✕", fill=fg_col, font=("Segoe UI", -12, "bold"))

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
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1280x900")
        self.minsize(1280, 900)
        self.configure(bg=BG_APP)
        self.cancel_event = threading.Event()
        self.events: queue.Queue = queue.Queue()
        self.running = False
        self.total = 0
        self.processed = 0
        self.files: list[str] = []
        self._thumb_cache: dict[str, ImageTk.PhotoImage] = {}
        self._dropzone_hover = False

        self.out_dir = tk.StringVar()
        self.scale = tk.IntVar(value=1)
        self.scale.trace_add("write", lambda *_: (self._update_output_hint(),
                                                  self._update_est_time(),
                                                  self._update_status_ready()))
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
        self.after(80, self._drain)

    # ── Style ─────────────────────────────────────────────────────────────────
    def _style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        self.option_add("*Font", ("Segoe UI", -13))

        # Combobox styling
        style.configure("Custom.TCombobox",
                        fieldbackground=BG_INPUT, background=BG_INPUT,
                        foreground=TEXT_PRIMARY, arrowcolor=TEXT_SECONDARY,
                        bordercolor=BORDER_SUBTLE, darkcolor=BG_INPUT,
                        lightcolor=BG_INPUT, selectbackground=BG_INPUT,
                        selectforeground=TEXT_PRIMARY, padding=(12, 8),
                        font=("Segoe UI", -14))
        style.map("Custom.TCombobox",
                  fieldbackground=[("readonly", BG_INPUT)],
                  foreground=[("readonly", TEXT_PRIMARY)],
                  selectbackground=[("readonly", BG_INPUT)],
                  selectforeground=[("readonly", TEXT_PRIMARY)],
                  bordercolor=[("focus", ACCENT)],
                  arrowcolor=[("hover", ACCENT), ("!hover", TEXT_SECONDARY)])

        # Scrollbar styling
        style.configure("Vertical.TScrollbar",
                        background=BORDER_SUBTLE, troughcolor=BG_PANEL,
                        bordercolor=BG_PANEL, arrowcolor=TEXT_SECONDARY)

        # Popup listbox styling
        self.option_add("*TCombobox*Listbox.background", BG_INPUT)
        self.option_add("*TCombobox*Listbox.foreground", TEXT_PRIMARY)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.option_add("*TCombobox*Listbox.selectForeground", ACCENT_TEXT_ON)
        self.option_add("*TCombobox*Listbox.font", ("Segoe UI", -13))

    # ── Layout ────────────────────────────────────────────────────────────────
    def _make_row_label(self, parent: tk.Widget, text: str) -> tk.Label:
        lbl_box = tk.Frame(parent, bg=BG_PANEL, width=170, height=40)
        lbl_box.pack_propagate(False)
        lbl_box.pack(side="left")
        lbl = tk.Label(lbl_box, text=text, fg=TEXT_PRIMARY, bg=BG_PANEL,
                       font=("Segoe UI", -14, "bold"), anchor="w")
        lbl.pack(fill="both", expand=True)
        return lbl

    def _build(self) -> None:
        # Main root container with page padding: 20px
        main_container = tk.Frame(self, bg=BG_APP, padx=20, pady=20)
        main_container.pack(fill="both", expand=True)

        # ── 1. Top Info Bar (Engine pill + About) ──────────────────────────────
        topbar = tk.Frame(main_container, bg=BG_PANEL, highlightbackground=BORDER_SUBTLE,
                          highlightthickness=1, padx=16, pady=12)
        topbar.pack(side="top", fill="x", pady=(0, 14))

        # Left: Engine pill
        top_left = tk.Frame(topbar, bg=BG_PANEL)
        top_left.pack(side="left")
        tk.Label(top_left, text="Engine:", fg=TEXT_SECONDARY, bg=BG_PANEL,
                 font=("Segoe UI", -14, "bold")).pack(side="left")
        pill_frame = tk.Frame(top_left, bg=BG_INPUT, highlightbackground=BORDER_SUBTLE,
                              highlightthickness=1, padx=16, pady=8)
        pill_frame.pack(side="left", padx=(10, 0))
        self.engine_label = tk.Label(pill_frame, text="AI Real-ESRGAN",
                                     fg=TEXT_GREEN, bg=BG_INPUT,
                                     font=("Segoe UI", -14, "bold"))
        self.engine_label.pack()

        # Right: About button
        self.btn_about = CustomButton(topbar, text="About ⓘ",
                                      command=self._show_about, style="secondary",
                                      height=36)
        self.btn_about.pack(side="right")

        # ── 2. Bottom Status Bar (Pinned at bottom, flex-shrink 0) ─────────────
        bottom_bar = tk.Frame(main_container, bg=BG_PANEL, highlightbackground=BORDER_SUBTLE,
                              highlightthickness=1, padx=18, pady=14)
        bottom_bar.pack(side="bottom", fill="x", pady=(14, 0))
        bottom_bar.columnconfigure(0, weight=1)
        bottom_bar.columnconfigure(1, weight=0)

        # Left block: Status + Progress
        bot_left = tk.Frame(bottom_bar, bg=BG_PANEL)
        bot_left.grid(row=0, column=0, sticky="ew", padx=(0, 20))
        bot_left.columnconfigure(1, weight=1)

        status_line = tk.Frame(bot_left, bg=BG_PANEL)
        status_line.pack(fill="x", pady=(0, 8))
        self.status_prefix_label = tk.Label(status_line, text="Ready:",
                                            fg=TEXT_GREEN, bg=BG_PANEL,
                                            font=("Segoe UI", -13, "bold"))
        self.status_prefix_label.pack(side="left")
        self.status_text_label = tk.Label(status_line, text=" 0 files queued ",
                                          fg=TEXT_PRIMARY, bg=BG_PANEL, font=("Segoe UI", -13))
        self.status_text_label.pack(side="left")
        self.status_dot_label = tk.Label(status_line, text="●", fg=ACCENT,
                                         bg=BG_PANEL, font=("Segoe UI", -13))
        self.status_dot_label.pack(side="left")

        prog_line = tk.Frame(bot_left, bg=BG_PANEL)
        prog_line.pack(fill="x")
        self.pct_label = tk.Label(prog_line, text="0%", fg=TEXT_PRIMARY, bg=BG_PANEL,
                                  font=("Segoe UI", -13, "bold"), width=5, anchor="w")
        self.pct_label.pack(side="left")
        self.progress = CustomProgressBar(prog_line, bg=BG_PANEL, height=8)
        self.progress.pack(side="left", fill="x", expand=True)

        # Right block: Cancel / Open Output Folder / START UPSCALE
        bot_right = tk.Frame(bottom_bar, bg=BG_PANEL)
        bot_right.grid(row=0, column=1, sticky="e")

        self.cancel_button = CustomButton(bot_right, text="⊕ Cancel",
                                          command=self.cancel, style="secondary", height=44)
        self.cancel_button.pack(side="left", padx=(0, 10))
        Tooltip(self.cancel_button,
                "Cancel. If running, waits for current image then stops.\n"
                "If idle, resets progress.")

        self.open_button = CustomButton(bot_right, text="📁 Open Output Folder",
                                        command=self.open_output, style="secondary", height=44)
        self.open_button.pack(side="left", padx=(0, 10))
        Tooltip(self.open_button, "Open the output folder in File Explorer.")

        self.start_button = CustomButton(bot_right, text="🚀 START UPSCALE",
                                         command=self.start, style="primary", height=48)
        self.start_button.pack(side="left")
        Tooltip(self.start_button,
                "Start processing the entire file list.\n"
                "Processes one image at a time. Uses a background thread\n"
                "so the UI stays responsive. Writes .part then renames.")

        # ── 3. Main Two-Column Grid (1fr to 1.15fr, gap 16px) ─────────────────
        grid = tk.Frame(main_container, bg=BG_APP)
        grid.pack(side="top", fill="both", expand=True)
        grid.columnconfigure(0, weight=100)
        grid.columnconfigure(1, weight=115)
        grid.rowconfigure(0, weight=1)

        # ── Left Panel: INPUT FILES ───────────────────────────────────────────
        left_panel = tk.Frame(grid, bg=BG_PANEL, highlightbackground=BORDER_SUBTLE,
                              highlightthickness=1, padx=20, pady=20)
        left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        # Section Header: 🖼 INPUT FILES
        lp_hdr = tk.Frame(left_panel, bg=BG_PANEL)
        lp_hdr.pack(fill="x", pady=(0, 16))
        tk.Label(lp_hdr, text="🖼", fg=ACCENT, bg=BG_PANEL,
                 font=("Segoe UI", -16)).pack(side="left", padx=(0, 8))
        tk.Label(lp_hdr, text="INPUT FILES", fg=TEXT_PRIMARY, bg=BG_PANEL,
                 font=("Segoe UI", -15, "bold")).pack(side="left")

        # Drop Zone (Height 240px, dashed 2px --border-dashed, bg-dropzone)
        self.dropzone = tk.Canvas(left_panel, height=240, bg=BG_DROPZONE,
                                  highlightthickness=0, cursor="hand2")
        self.dropzone.pack(fill="x", pady=(0, 14))
        self.dropzone.bind("<Button-1>", lambda _e: self.add_files())
        self.dropzone.bind("<Configure>", lambda _e: self._draw_dropzone())
        self.dropzone.bind("<Enter>", lambda _e: self._hover_dropzone(True))
        self.dropzone.bind("<Leave>", lambda _e: self._hover_dropzone(False))

        # Action Buttons Row (pinned at panel bottom)
        btns_row = tk.Frame(left_panel, bg=BG_PANEL)
        btns_row.pack(side="bottom", fill="x")

        self.btn_add_files = CustomButton(btns_row, text="＋ Add Files",
                                          command=self.add_files, style="outline")
        self.btn_add_files.pack(side="left", padx=(0, 10))
        Tooltip(self.btn_add_files,
                "Select JPG, JPEG, PNG, or WebP images.\n"
                "Multiple files can be selected (Ctrl / Shift).")

        self.btn_add_folder = CustomButton(btns_row, text="＋ Add Folder",
                                           command=self.add_folder, style="secondary")
        self.btn_add_folder.pack(side="left", padx=(0, 10))
        Tooltip(self.btn_add_folder,
                "Scan current folder for JPG, JPEG, PNG, WebP files.\n"
                "Does not recurse into subfolders.")

        self.btn_clear = CustomButton(btns_row, text="🗑 Clear All",
                                      command=self.clear_files, style="secondary")
        self.btn_clear.pack(side="left")
        Tooltip(self.btn_clear, "Clear the entire file list.")

        # File Cards scroll container (flex: 1, min-height: 0, overflow-y: auto)
        cards_outer = tk.Frame(left_panel, bg=BG_PANEL)
        cards_outer.pack(side="top", fill="both", expand=True, pady=(0, 14))

        self.cards_canvas = tk.Canvas(cards_outer, bg=BG_PANEL, highlightthickness=0)
        self.cards_canvas.pack(side="left", fill="both", expand=True)

        self.cards_scroll = ttk.Scrollbar(cards_outer, orient="vertical",
                                          command=self.cards_canvas.yview,
                                          style="Vertical.TScrollbar")
        # Scrollbar is NOT packed on launch (auto overflow only)
        self.cards_canvas.configure(yscrollcommand=self._on_cards_scroll_set)

        self.cards_inner = tk.Frame(self.cards_canvas, bg=BG_PANEL)
        self.cards_window = self.cards_canvas.create_window((0, 0), window=self.cards_inner, anchor="nw")
        self.cards_inner.bind("<Configure>", self._on_cards_inner_configure)
        self.cards_canvas.bind("<Configure>", self._on_cards_canvas_configure)
        self.cards_canvas.bind("<MouseWheel>", lambda e: self.cards_canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))
        self.cards_inner.bind("<MouseWheel>", lambda e: self.cards_canvas.yview_scroll(-1 if e.delta > 0 else 1, "units"))

        # ── Right Panel: OUTPUT SETTINGS ──────────────────────────────────────
        right_panel = tk.Frame(grid, bg=BG_PANEL, highlightbackground=BORDER_SUBTLE,
                               highlightthickness=1, padx=20, pady=20)
        right_panel.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        # Section Header: 📁 OUTPUT SETTINGS
        rp_hdr = tk.Frame(right_panel, bg=BG_PANEL)
        rp_hdr.pack(fill="x", pady=(0, 20))
        tk.Label(rp_hdr, text="📁", fg=ACCENT, bg=BG_PANEL,
                 font=("Segoe UI", -16)).pack(side="left", padx=(0, 8))
        tk.Label(rp_hdr, text="OUTPUT SETTINGS", fg=TEXT_PRIMARY, bg=BG_PANEL,
                 font=("Segoe UI", -15, "bold")).pack(side="left")

        # 1. Format row
        f_row = tk.Frame(right_panel, bg=BG_PANEL)
        f_row.pack(fill="x", pady=(0, 16))
        self._make_row_label(f_row, "Format:")
        self.fmt_combo = ttk.Combobox(f_row, textvariable=self.fmt,
                                      values=["Default", "JPG", "PNG"],
                                      state="readonly", style="Custom.TCombobox")
        self.fmt_combo.current(0)
        self.fmt_combo.pack(side="left", fill="x", expand=True)
        self.fmt_combo.bind("<<ComboboxSelected>>", lambda _e: self._sync_quality())
        Tooltip(self.fmt_combo,
                "Default = preserve original format (JPG->JPG, PNG->PNG, WebP->JPG).\n"
                "JPG = convert all to JPEG (smaller, lossy).\n"
                "PNG = convert all to PNG (lossless, larger).")

        # 2. DPI row
        dpi_row = tk.Frame(right_panel, bg=BG_PANEL)
        dpi_row.pack(fill="x", pady=(0, 16))
        self._make_row_label(dpi_row, "DPI:")
        self.dpi_combo = ttk.Combobox(dpi_row, textvariable=self.dpi,
                                      values=["Default", "150", "300"],
                                      state="readonly", style="Custom.TCombobox")
        self.dpi_combo.current(0)
        self.dpi_combo.pack(side="left", fill="x", expand=True)
        Tooltip(self.dpi_combo,
                "DPI written into the output file.\n"
                "Default = keep the original DPI.\n"
                "150 / 300 = force that resolution.")

        # 3. Quality area (Image Quality / PNG Compression)
        self._quality_area = tk.Frame(right_panel, bg=BG_PANEL)
        self._quality_area.pack(fill="x")

        self._jpeg_frame = tk.Frame(self._quality_area, bg=BG_PANEL)
        self._make_row_label(self._jpeg_frame, "Image Quality:")
        self.quality_scale = CanvasSlider(self._jpeg_frame, variable=self.quality,
                                          lo=1, hi=100, badge_fmt="{val}%", bg=BG_PANEL)
        self.quality_scale.pack(side="left", fill="x", expand=True)
        Tooltip(self.quality_scale,
                "JPEG quality: 1 = smallest, most artifacts. 100 = largest, minimal compression.\n"
                "Default 92. Below 70 will show visible noise; above 95 adds little quality.")

        self._png_frame = tk.Frame(self._quality_area, bg=BG_PANEL)
        self._make_row_label(self._png_frame, "PNG Compression:")
        self.png_scale = CanvasSlider(self._png_frame, variable=self.png_compress,
                                      lo=0, hi=9, badge_fmt="{val}/9", bg=BG_PANEL)
        self.png_scale.pack(side="left", fill="x", expand=True)
        Tooltip(self.png_scale,
                "0 = no compression (fast, large file). 9 = max compression (slow, small file).\n"
                "Default 6. Only applies when output is PNG.")

        # 4. Target Size (MB) row
        tgt_row = tk.Frame(right_panel, bg=BG_PANEL)
        tgt_row.pack(fill="x", pady=(0, 2))
        self._make_row_label(tgt_row, "Target Size (MB):")
        tgt_box = tk.Frame(tgt_row, bg=BORDER_SUBTLE, padx=1, pady=1, width=110, height=44)
        tgt_box.pack_propagate(False)
        tgt_box.pack(side="left")
        self.target_entry = tk.Entry(tgt_box, textvariable=self.target_mb,
                                     bg=BG_INPUT, fg=TEXT_PRIMARY, insertbackground=ACCENT,
                                     relief="flat", bd=0, font=("Segoe UI", -14))
        self.target_entry.pack(fill="both", expand=True, padx=10, pady=8)
        Tooltip(self.target_entry,
                "Limit output file size per image in megabytes.\n"
                "Enter a number: 1.5 / 4 / 12. Leave empty = feature disabled.\n"
                "Target overrides quality sliders when set.\n"
                "JPG: lowers quality. PNG: raises compression level.\n"
                "If still too large, gently downscales (max 3 rounds, -10% each).")

        self.target_err_label = tk.Label(right_panel, text="", fg=ERROR_FG, bg=BG_PANEL,
                                         font=("Segoe UI", -12), anchor="w")
        self.target_err_label.pack(fill="x", padx=(170, 0), pady=(0, 6))

        self.target_mb.trace_add("write", self._sync_target_override)

        # 5. Scale row (no separate OPTIONS section)
        scale_row = tk.Frame(right_panel, bg=BG_PANEL)
        scale_row.pack(fill="x", pady=(0, 6))
        self._make_row_label(scale_row, "Scale:")
        self.scale_slider = CanvasSlider(scale_row, variable=self.scale,
                                         lo=MIN_SCALE, hi=MAX_SCALE, badge_fmt="{val}x",
                                         discrete=True, bg=BG_PANEL,
                                         on_change=lambda _: (self._update_output_hint(),
                                                              self._update_est_time(),
                                                              self._update_status_ready()))
        self.scale_slider.pack(side="left", fill="x", expand=True)
        Tooltip(self.scale_slider,
                "1 = keep original size, enhance + auto-analyze only.\n"
                "2-8 = upscale. If AI (Real-ESRGAN) is available, uses AI;\n"
                "otherwise falls back to Lanczos. Output > 120 MP auto-clamped.\n"
                "AI mode auto-pads to multiple of 4.")

        # Helper line centered below scale
        self.scale_hint_label = tk.Label(right_panel, textvariable=self.output_hint,
                                         fg=TEXT_SECONDARY, bg=BG_PANEL, font=("Segoe UI", -13))
        self.scale_hint_label.pack(fill="x", pady=(0, 16))

        # 6. Output Folder row
        out_row = tk.Frame(right_panel, bg=BG_PANEL)
        out_row.pack(fill="x", pady=(0, 16))
        self._make_row_label(out_row, "Output Folder:")
        out_box = tk.Frame(out_row, bg=BORDER_SUBTLE, padx=1, pady=1)
        out_box.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.out_entry = tk.Entry(out_box, textvariable=self.out_dir, bg=BG_INPUT,
                                  fg=TEXT_PRIMARY, insertbackground=ACCENT, relief="flat",
                                  bd=0, font=("Segoe UI", -13))
        self.out_entry.pack(fill="x", padx=14, pady=10)
        self.btn_browse = CustomButton(out_row, text="📁 Browse…",
                                       command=self.pick_output, style="secondary")
        self.btn_browse.pack(side="right")

        # Drag-and-drop hookup
        if _WINDND:
            try:
                windnd.hook_dropfiles(self, func=self._on_drop)
            except Exception:
                pass

        self._sync_target_override()

    # ── Dropzone & Cards ──────────────────────────────────────────────────────
    def _hover_dropzone(self, hovering: bool) -> None:
        self._dropzone_hover = hovering
        self._draw_dropzone()

    def _draw_dropzone(self) -> None:
        c = self.dropzone
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 50 or h < 50:
            return

        border_col = ACCENT if self._dropzone_hover else BORDER_DASHED
        dash_pat = None if self._dropzone_hover else (8, 6)
        fill_col = "#1E2A36" if self._dropzone_hover else BG_DROPZONE
        c.create_rectangle(6, 6, w - 6, h - 6, outline=border_col, width=2,
                           dash=dash_pat, fill=fill_col)

        cy = h // 2
        icx, icy = w // 2, cy - 32
        # Cloud upload outline icon (accent, 44px)
        c.create_oval(icx - 22, icy - 8, icx - 6, icy + 12, outline=ACCENT, width=2)
        c.create_oval(icx - 12, icy - 22, icx + 12, icy + 4, outline=ACCENT, width=2)
        c.create_oval(icx + 4, icy - 10, icx + 22, icy + 12, outline=ACCENT, width=2)
        c.create_line(icx - 16, icy + 12, icx + 16, icy + 12, fill=ACCENT, width=2)
        # Up arrow
        c.create_line(icx, icy + 14, icx, icy - 8, fill=ACCENT, width=2)
        c.create_polygon(icx - 6, icy - 4, icx, icy - 14, icx + 6, icy - 4, fill=ACCENT, outline=ACCENT)

        # Drag & drop text (17px weight 700 / 13px secondary)
        c.create_text(w // 2, cy + 20, text="Drag & drop images here",
                      fill=TEXT_PRIMARY, font=("Segoe UI", -17, "bold"))
        c.create_text(w // 2, cy + 46, text="or click to browse • supports JPG, PNG, WEBP",
                      fill=TEXT_SECONDARY, font=("Segoe UI", -13))

    def _on_drop(self, files) -> None:
        paths = [f.decode("utf-8", errors="replace") if isinstance(f, bytes) else f
                 for f in files]
        self._append_paths(paths)

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
        if REAL_ESRGAN_BIN and REAL_ESRGAN_MODEL:
            self.engine_label.configure(text="AI Real-ESRGAN")
        else:
            self.engine_label.configure(text="Lanczos")

    def _show_about(self) -> None:
        messagebox.showinfo(
            "About UPSCALE",
            "UPSCALE v1.0\n\n"
            "AI-powered image upscaler.\n\n"
            "Engines:\n"
            "  - AI Real-ESRGAN (ncnn-vulkan)\n"
            "  - Lanczos (fallback)\n\n"
            "Features:\n"
            "  - Auto color grade (gray-world WB + CLAHE-lite)\n"
            "  - Auto enhance (unsharp mask + detail)\n"
            "  - Target size fitting (1-24 MB)\n"
            "  - Batch processing\n\n"
            "Built with Python + Tkinter + Pillow + NumPy")

    # ── File List ─────────────────────────────────────────────────────────────
    def add_files(self) -> None:
        patterns = " ".join(f"*{ext}" for ext in sorted(INPUT_EXTS))
        paths = filedialog.askopenfilenames(
            title="Select images",
            filetypes=[("Images", patterns), ("All files", "*.*")])
        self._append_paths(paths)

    def add_folder(self) -> None:
        folder = filedialog.askdirectory(title="Select folder")
        if not folder:
            return
        try:
            found = [os.path.join(folder, n) for n in sorted(os.listdir(folder))
                     if os.path.splitext(n)[1].lower() in INPUT_EXTS
                     and os.path.isfile(os.path.join(folder, n))]
        except OSError as error:
            messagebox.showerror("Error", f"Cannot read folder:\n{error}")
            return
        if not found:
            messagebox.showinfo("No images",
                                "This folder contains no JPG/JPEG/PNG/WebP files.")
            return
        self._append_paths(found)

    def _append_paths(self, paths) -> None:
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
        else:
            self._update_status_ready()

    def _on_cards_inner_configure(self, _e=None) -> None:
        self.cards_canvas.configure(scrollregion=self.cards_canvas.bbox("all"))
        self._check_cards_overflow()

    def _on_cards_canvas_configure(self, e) -> None:
        self.cards_canvas.itemconfig(self.cards_window, width=e.width)
        self._check_cards_overflow()

    def _on_cards_scroll_set(self, first, last) -> None:
        if not self.files:
            if hasattr(self, "cards_scroll") and self.cards_scroll.winfo_ismapped():
                self.cards_scroll.pack_forget()
            return
        try:
            f, l = float(first), float(last)
            if f <= 0.001 and l >= 0.999:
                if hasattr(self, "cards_scroll") and self.cards_scroll.winfo_ismapped():
                    self.cards_scroll.pack_forget()
            else:
                if hasattr(self, "cards_scroll") and not self.cards_scroll.winfo_ismapped():
                    self.cards_scroll.pack(side="right", fill="y")
        except (ValueError, TypeError):
            pass
        if hasattr(self, "cards_scroll"):
            self.cards_scroll.set(first, last)

    def _check_cards_overflow(self) -> None:
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

    def remove_at(self, index: int) -> None:
        if 0 <= index < len(self.files):
            self.files.pop(index)
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
        self._refresh_cards()
        self._update_output_hint()
        self._update_est_time()
        self._update_status_ready()
        self.progress.configure(value=0)
        self.pct_label.configure(text="0%")
        if not self.running:
            self.start_button.configure(state="disabled")

    def _refresh_cards(self) -> None:
        for child in self.cards_inner.winfo_children():
            child.destroy()
        if not self.files:
            if hasattr(self, "cards_scroll") and self.cards_scroll.winfo_ismapped():
                self.cards_scroll.pack_forget()
            self.cards_canvas.configure(scrollregion=(0, 0, 0, 0))
            self.cards_canvas.yview_moveto(0)
            return
        for i, path in enumerate(self.files):
            self._make_card(i, path)

    def _make_card(self, index: int, path: str) -> None:
        card = tk.Frame(self.cards_inner, bg=BG_INPUT,
                        highlightbackground=BORDER_SUBTLE, highlightthickness=1,
                        padx=10, pady=12)
        card.pack(fill="x", pady=(0, 10))
        card.columnconfigure(1, weight=1)

        # 44x44px Thumbnail with 8px radius
        thumb = self._get_thumb(path)
        if thumb:
            lbl_thumb = tk.Label(card, image=thumb, bg=BG_INPUT, width=44, height=44)
            lbl_thumb.image = thumb
            lbl_thumb.grid(row=0, column=0, rowspan=2, padx=(0, 12))
        else:
            tk.Label(card, text="🖼", bg=BG_INPUT, fg=TEXT_SECONDARY,
                     width=4, height=2, font=("Segoe UI", 12)).grid(
                row=0, column=0, rowspan=2, padx=(0, 12))

        # Filename (14px/600/primary) over meta line (12px/secondary)
        name = os.path.basename(path)
        size_str = self._get_size_str(path)
        tk.Label(card, text=name, bg=BG_INPUT, fg=TEXT_PRIMARY,
                 font=("Segoe UI", -14, "bold"), anchor="w").grid(
            row=0, column=1, sticky="w")
        tk.Label(card, text=size_str, bg=BG_INPUT, fg=TEXT_SECONDARY,
                 font=("Segoe UI", -13), anchor="w").grid(
            row=1, column=1, sticky="w")

        # Circular ✕ button (32px)
        x_btn = CircleCloseButton(card, command=lambda idx=index: self.remove_at(idx), size=32)
        x_btn.grid(row=0, column=2, rowspan=2, padx=(8, 0))

    def _get_thumb(self, path: str) -> ImageTk.PhotoImage | None:
        if path in self._thumb_cache:
            return self._thumb_cache[path]
        try:
            with Image.open(path) as img:
                img = img.convert("RGBA")
                w, h = img.size
                scale = max(44 / w, 44 / h)
                nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
                img = img.resize((nw, nh), Image.LANCZOS)
                left = (nw - 44) // 2
                top = (nh - 44) // 2
                img = img.crop((left, top, left + 44, top + 44))

                mask = Image.new("L", (44, 44), 0)
                draw = ImageDraw.Draw(mask)
                draw.rounded_rectangle((0, 0, 44, 44), radius=8, fill=255)
                img.putalpha(mask)

                photo = ImageTk.PhotoImage(img)
                self._thumb_cache[path] = photo
                return photo
        except Exception:
            return None

    def _get_size_str(self, path: str) -> str:
        try:
            with Image.open(path) as img:
                w, h = img.size
            if os.path.isfile(path):
                sz_bytes = os.path.getsize(path)
                sz_mb = sz_bytes / 1048576
                if sz_mb >= 1.0:
                    sz_str = f"{sz_mb:.1f} MB"
                else:
                    sz_str = f"{sz_bytes / 1024:.0f} KB"
                return f"{w}×{h} • {sz_str}"
            return f"{w}×{h}"
        except Exception:
            return ""

    # ── Output / Options ──────────────────────────────────────────────────────
    def pick_output(self) -> None:
        chosen = filedialog.askdirectory(title="Select output folder")
        if chosen:
            self.out_dir.set(chosen)

    def open_output(self) -> None:
        target = self.out_dir.get().strip()
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

        if show_jpeg:
            self._jpeg_frame.pack(in_=self._quality_area, fill="x", pady=(0, 16))
        else:
            self._jpeg_frame.pack_forget()

        if show_png:
            self._png_frame.pack(in_=self._quality_area, fill="x", pady=(0, 16))
        else:
            self._png_frame.pack_forget()

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
        try:
            with Image.open(self.files[0]) as img:
                w, h = img.size
            s = int(round(self.scale.get()))
            if s <= 1:
                self.output_hint.set(f"Output: {w}×{h} • no change")
            else:
                mult = s * s
                self.output_hint.set(f"Output: {w * s}×{h * s} • ~{mult}x pixels")
        except Exception:
            self.output_hint.set("Output: — (select images to preview)")

    def _update_est_time(self) -> None:
        n = len(self.files)
        if n == 0:
            self.est_time.set("")
            return
        use_ai = int(round(self.scale.get())) > 1 and REAL_ESRGAN_BIN is not None
        per = 8 if use_ai else 1.5
        total = n * per
        if total < 60:
            self.est_time.set(f"~{int(total)}s")
        else:
            self.est_time.set(f"~{int(total // 60)}m {int(total % 60)}s")

    def _update_status_ready(self) -> None:
        n = len(self.files)
        if n == 0:
            self.status_prefix_label.configure(text="Ready:", fg=TEXT_GREEN)
            self.status_text_label.configure(text=" 0 files queued ", fg=TEXT_PRIMARY)
            self.status_dot_label.configure(text="●", fg=ACCENT)
            self.status.set("Ready: 0 files queued ●")
        else:
            est = self.est_time.get()
            est_str = f" • Est. time: {est}" if est else ""
            self.status_prefix_label.configure(text="Ready:", fg=TEXT_GREEN)
            self.status_text_label.configure(text=f" {n} files queued{est_str} ", fg=TEXT_PRIMARY)
            self.status_dot_label.configure(text="●", fg=ACCENT)
            self.status.set(f"Ready: {n} files queued{est_str} ●")

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
        use_ai = opts["scale"] > 1 and REAL_ESRGAN_BIN is not None

        self.total = len(tasks)
        self.processed = 0
        self.cancel_event.clear()
        self.running = True
        self.progress.configure(maximum=self.total, value=0)
        self.pct_label.configure(text="0%")

        ai_info = " [AI]" if use_ai else ""
        self.status_prefix_label.configure(text="Processing:", fg=TEXT_GREEN)
        self.status_text_label.configure(text=f" 0/{self.total}{ai_info} ", fg=TEXT_PRIMARY)
        self.status_dot_label.configure(fg=ACCENT)
        self.status.set(f"Processing 0/{self.total}{ai_info}")
        self._set_running(True)

        t = threading.Thread(target=self._run_batch,
                             args=(tasks, opts, use_ai),
                             daemon=True, name="upscale-worker")
        t.start()

    def _set_running(self, running: bool) -> None:
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

    def cancel(self) -> None:
        if self.running:
            self.cancel_event.set()
            self.status_prefix_label.configure(text="Cancelling:", fg=ERROR_FG)
            self.status_text_label.configure(text=" waiting for current file to finish... ", fg=TEXT_SECONDARY)
            self.status_dot_label.configure(fg=ERROR_FG)
            self.status.set("Cancelling — waiting for current file to finish...")
        else:
            self.progress.configure(value=0)
            self.pct_label.configure(text="0%")
            self._update_status_ready()

    # ── Worker ────────────────────────────────────────────────────────────────
    def _run_batch(self, tasks, opts, use_ai) -> None:
        for idx, (src, dst) in enumerate(tasks, 1):
            if self.cancel_event.is_set():
                self.events.put(("done", idx - 1))
                return
            name = os.path.basename(src)
            try:
                info = process_file(src, dst, opts, self.cancel_event, use_ai)
            except Exception as error:
                info = f"ERROR {type(error).__name__}: {error}"
            self.events.put(("item", name, info))
        gc.collect()
        self.events.put(("done", len(tasks)))

    # ── UI Pump ───────────────────────────────────────────────────────────────
    def _drain(self) -> None:
        finished = False
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "item":
                    _, name, info = event
                    self.processed += 1
                    self.progress.configure(value=self.processed)
                    pct = int(self.processed / self.total * 100) if self.total else 0
                    self.pct_label.configure(text=f"{pct}%")
                    colour = ERROR_FG if info.startswith(("ERROR", "FAILED")) else TEXT_PRIMARY
                    self.status_prefix_label.configure(text="Processing:", fg=TEXT_GREEN)
                    self.status_text_label.configure(
                        text=f" {self.processed}/{self.total} • {name} ", fg=colour)
                    self.status_dot_label.configure(fg=ACCENT)
                    self.status.set(f"{self.processed}/{self.total}  {name}  ->  {info}")
                else:
                    finished = True
                    self._finish(event[1])
        except queue.Empty:
            pass
        if finished and self.running:
            self._apply_finish()
        self.after(80, self._drain)

    def _finish(self, processed: int) -> None:
        if self.cancel_event.is_set():
            self.final_state = "Cancelled"
        elif processed < self.total:
            self.final_state = "Stopped"
        else:
            self.final_state = "Done"
        self.final_processed = processed

    def _apply_finish(self) -> None:
        self.running = False
        self._set_running(False)
        state = getattr(self, "final_state", "Done")
        processed = getattr(self, "final_processed", self.processed)
        left = self.total - processed
        if state == "Cancelled":
            prefix = "Cancelled:"
            text = f" {processed}/{self.total} processed"
            if left:
                text += f" • {left} remaining "
            self.status_prefix_label.configure(text=prefix, fg=ERROR_FG)
            self.status_text_label.configure(text=text, fg=TEXT_SECONDARY)
            self.status_dot_label.configure(fg=ERROR_FG)
        else:
            prefix = "Done:"
            text = f" {processed}/{self.total} processed "
            self.status_prefix_label.configure(text=prefix, fg=TEXT_GREEN)
            self.status_text_label.configure(text=text, fg=TEXT_PRIMARY)
            self.status_dot_label.configure(fg=ACCENT)

        icon = {"Done": "OK ", "Cancelled": "STOP "}.get(state, "")
        log_text = f"{icon}{state}: {processed}/{self.total} processed"
        if state == "Cancelled" and left:
            log_text += f" — {left} remaining in list"
        self.status.set(log_text)


if __name__ == "__main__":
    App().mainloop()
