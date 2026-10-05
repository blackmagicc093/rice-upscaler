# Rice Upscaler

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-blue.svg)](https://www.microsoft.com/windows)
[![Python](https://img.shields.io/badge/Python-3.10%2B-green.svg)](https://www.python.org/)
[![Architecture](https://img.shields.io/badge/Architecture-x64-lightgrey.svg)]()

**Rice Upscaler** is a free, open-source Windows desktop application for AI-powered image upscaling up to 8×. It combines **DAT (Dual Aggregation Transformer)** via DirectML and **Real-ESRGAN** via ncnn-Vulkan with intelligent hardware cascade, exact target-size fitting, batch processing, and 100% offline privacy.

---

## ✨ Features

| Feature | Description |
|:---|:---|
| **Multi-Engine Cascade** | DAT (DirectML) → Real-ESRGAN (Vulkan) → Lanczos (CPU), switching automatically based on hardware and resolution |
| **Scale 1×–8× & DPI** | Integer upscaling from 1× to 8×; output DPI options: Default / 150 / 300 DPI for print-ready results |
| **Target Size Control** | Fits output files to an exact size of 1–24 MB using binary search and byte padding (JPEG/PNG) |
| **Format Support** | Input: JPG, PNG, WEBP, HEIC/HEIF · Output: JPG (quality 1–100%), PNG (compression 0–9) |
| **Batch Queue** | Drag-and-drop file lists, Windows Long Path (>260 characters) support, Unicode paths, and thumbnail preview |
| **GPU Acceleration** | Compatible with NVIDIA GeForce, AMD Radeon, and Intel UHD/Arc via Vulkan 1.1+ and DirectX 12 DirectML; adaptive VRAM tiling |
| **100% Offline** | No cloud uploads, no telemetry, no account required — all AI inference runs locally on your machine |

---

## 📁 Project Structure

```
rice-upscaler/
├── src/
│   └── main.py                 # Main application source (Tkinter GUI, inference cascade)
├── tools/                      # Executables and heavy AI models (gitignored)
│   ├── realesrgan-ncnn-vulkan.exe
│   ├── realesrgan-x4plus.bin / .param
│   ├── realesrgan-x4plus-anime.bin / .param
│   ├── realesr-animevideov3-x2/x3/x4.bin / .param
│   ├── vcomp140.dll
│   └── models/
│       └── DAT_light_x4.onnx
├── assets/
│   ├── icon/                   # Application icons (rice.ico, icon-new.ico, etc.)
│   └── forest/                 # ttk Forest Dark & Forest Light themes
├── dist/                       # Packaging output directory (gitignored)
│   └── RiceUpscaler.exe
├── build/                      # PyInstaller temporary files (gitignored)
├── RiceUpscaler.spec           # PyInstaller packaging configuration
├── requirements.txt            # Python dependencies
├── LICENSE                     # MIT License
└── README.md                   # Documentation
```

---

## 📦 Downloading Heavy Models

Due to their large size, the binaries and model weights in the `tools/` directory are excluded from the repository (`.gitignore`). Prepare the following files before running or packaging:

### 1. Real-ESRGAN NCNN Vulkan
- **Download**: Go to the [Real-ESRGAN Releases](https://github.com/xinntao/Real-ESRGAN/releases) page and download the Windows release (e.g., `realesrgan-ncnn-vulkan-*-windows.zip`).
- **Setup**: Extract the archive and place the following files directly into the `tools/` folder:
  - `realesrgan-ncnn-vulkan.exe`
  - `realesrgan-x4plus.bin` & `realesrgan-x4plus.param`
  - `realesrgan-x4plus-anime.bin` & `realesrgan-x4plus-anime.param`
  - `realesr-animevideov3-x2.bin`, `realesr-animevideov3-x3.bin`, `realesr-animevideov3-x4.bin` (& `.param`)
  - `vcomp140.dll`

### 2. DAT (Dual Aggregation Transformer) ONNX
- **Download**: Download the `DAT_light_x4.onnx` model from the [zhengchen1999/DAT](https://github.com/zhengchen1999/DAT) repository or its releases.
- **Setup**: Place the file at:
  ```
  tools/models/DAT_light_x4.onnx
  ```

---

## 🚀 Getting Started

### Prerequisites
- **Operating System**: Windows 10 / 11 (64-bit), version 1607 or later
- **Python**: Python 3.10 or newer ([python.org](https://www.python.org/downloads/))
- **GPU (recommended)**: NVIDIA (GTX 900+), AMD (RX 400+), or Intel (UHD 620+ / Arc) with Vulkan 1.1+ or DirectX 12 support
- **RAM**: Minimum 4 GB (8–16 GB recommended)

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/blackmagicc093/rice-upscaler
cd rice-upscaler

# 2. Create a virtual environment (recommended)
python -m venv .venv
.venv\Scripts\activate

# 3. Install the dependencies
pip install -r requirements.txt
```

### Running the Application

Once all models are in place under `tools/`:

```bash
python src/main.py
```

---

## 🔨 Build Executable

The application can be packaged into a standalone executable with PyInstaller:

```bash
# 1. Install PyInstaller
pip install pyinstaller

# 2. Build using the provided spec file
pyinstaller RiceUpscaler.spec
```

When the build finishes, the standalone `.exe` will be located at `dist/RiceUpscaler.exe`. It bundles the GUI, the AI models from `tools/`, and the application icon.

---

## 🧪 Verification

Check the Python syntax with:

```bash
python -m py_compile src/main.py
```

---

## 📜 License

This project is distributed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

---

## 🙏 Third-Party Credits

- [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) (xinntao) — Image and video restoration models (BSD-3-Clause)
- [DAT (Dual Aggregation Transformer)](https://github.com/zhengchen1999/DAT) (zhengchen1999) — Image super-resolution Transformer architecture
- [ncnn](https://github.com/Tencent/ncnn) (Tencent) — Vulkan-optimized neural network inference framework
- [onnxruntime / DirectML](https://github.com/microsoft/DirectML) (Microsoft) — ONNX inference acceleration via DirectX 12
- [Pillow & pillow-heif](https://github.com/python-pillow/Pillow) — Image format and HEIC handling
- [windnd](https://github.com/hasenbanck/windnd) — File drag-and-drop interaction on Windows
- [Forest Tkinter Theme](https://github.com/rdbende/Forest-ttk-theme) (rdbende) — Modern dark/light themes for Tkinter
