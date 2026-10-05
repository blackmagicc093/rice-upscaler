# Rice Upscaler

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-blue.svg)](https://www.microsoft.com/windows)
[![Python](https://img.shields.io/badge/Python-3.10%2B-green.svg)](https://www.python.org/)
[![Architecture](https://img.shields.io/badge/Architecture-x64-lightgrey.svg)]()

**Rice Upscaler** is a Windows desktop application for AI-powered image upscaling up to 8×. It combines **DAT (Dual Aggregation Transformer)** via DirectML and **Real-ESRGAN** via ncnn-Vulkan with intelligent hardware cascade, exact target-size fitting, batch processing, and 100% offline privacy. Includes a Cloudflare Worker landing page with live download statistics.

---

## ✨ Features | Tính năng

| Feature / Tính năng | Description / Mô tả |
|:---|:---|
| **Multi-Engine Cascade / Cascade đa engine** | DAT (DirectML) → Real-ESRGAN (Vulkan) → Lanczos (CPU) automatic fallback |
| **Scale 1×–8× & DPI** | Integer scaling slider; output DPI presets: Default / 150 / 300 |
| **Target Size Control / Khống chế dung lượng đích** | Exact file size 1–24 MB via binary search + byte padding (JPEG/PNG) |
| **Format Support / Hỗ trợ định dạng** | Input: JPG, PNG, WEBP, HEIC/HEIF · Output: JPG (1–100%), PNG (0–9) |
| **Batch Queue / Xử lý hàng loạt** | Drag-and-drop, Windows Long Path (>260 chars), Unicode, live thumbnails |
| **GPU Acceleration / Tăng tốc GPU** | NVIDIA, AMD, Intel via Vulkan 1.1+ & DirectX 12 DirectML; adaptive VRAM tiling |
| **100% Offline / 100% Ngoại tuyến** | Zero cloud, zero telemetry, zero accounts — all inference runs locally |
| **Live Download Stats / Thống kê tải thực tế** | Cloudflare Worker + KV counter (total, per-country, last download) |
| **R2 Distribution / Phân phối R2** | High-speed direct downloads from Cloudflare R2 bucket |

---

## 🖼️ Screenshots | Ảnh chụp màn hình

> Add screenshots here: landing page, download page with live counter, settings panel.

---

## 📁 Project Structure | Cấu trúc dự án

```
UPSCALE/
├── src/
│   └── main.py                 # Main Python application (Tkinter GUI)
├── web/                        # Cloudflare Worker (landing + download + stats)
│   ├── index.js                # Worker entry point (API, routing, KV/R2)
│   ├── templates.js            # HTML templates (EN/VI, stats, pages)
│   ├── icon.js                 # Base64-encoded app icon
│   ├── wrangler.toml.example   # Template config (copy to wrangler.toml)
│   ├── package.json            # npm scripts (dev, deploy, kv:create, r2:create)
│   ├── DEPLOY-VI.md            # Vietnamese deploy guide
│   └── INFRA.md                # Infrastructure reference (template only)
├── tools/                      # Bundled binaries & models (gitignored)
│   ├── realesrgan-ncnn-vulkan.exe
│   ├── realesrgan-x4plus.bin/.param
│   ├── realesr-animevideov3-x2/x3/x4.bin/.param
│   └── models/
│       └── DAT_light_x4.onnx
├── assets/
│   ├── icon/                   # App icons (rice.png, rice.ico, etc.)
│   └── forest/                 # Tkinter forest-dark theme
├── dist/                       # Build output (gitignored)
│   └── RiceUpscaler.exe
├── build/                      # PyInstaller artifacts (gitignored)
├── RiceUpscaler.spec           # PyInstaller spec
├── requirements.txt            # Python dependencies
├── LICENSE                     # MIT License
└── README.md                   # This file
```

> **Note:** `tools/`, `dist/`, `build/`, `web/wrangler.toml`, `web/node_modules/`, `web/.wrangler/` are gitignored. See `.gitignore` for full list.

---

## 🚀 Quick Start | Bắt đầu nhanh

### Prerequisites | Yêu cầu hệ thống

- **Windows 10/11 (64-bit)** — Version 1607+
- **Python 3.10+** — [python.org](https://www.python.org/downloads/)
- **GPU (optional but recommended)** — NVIDIA GTX 900+ / AMD RX 400+ / Intel UHD 620+ / Arc
  - DirectML (DAT) or Vulkan 1.1+ (Real-ESRGAN)
- **RAM** — 4 GB minimum (2 GB free for AI), 8–16 GB recommended

### Installation | Cài đặt

```bash
# 1. Clone repository
git clone https://github.com/<your-username>/RiceUpscaler.git
cd RiceUpscaler

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Run the application
python src/main.py
```

> The bundled binaries in `tools/` and models in `tools/models/` are included in the repo (or downloaded via release). PyInstaller bundles them into the standalone `.exe`.

---

## 🔨 Build Executable | Build file thực thi

Using PyInstaller with the provided spec:

```bash
# Install PyInstaller if not present
pip install pyinstaller

# Build
pyinstaller RiceUpscaler.spec

# Output: dist/RiceUpscaler.exe (standalone, ~200-300 MB with models)
```

The spec file configures:
- Hidden imports for `onnxruntime`, `ncnn`, `pillow_heif`, `numpy`, `windnd`
- Bundled `tools/` binaries and `tools/models/` ONNX/param files
- `assets/icon/rice.ico` as application icon
- `assets/forest/` theme resources
- UPX compression (optional, disable if antivirus false positives)

---

## ☁️ Web Deployment (Cloudflare Worker) | Triển khai Web

The `web/` directory contains a Cloudflare Worker providing:
- Landing page (EN/VI)
- Download page with **live real-time counter** (KV)
- Direct `.exe` downloads from **R2 Storage**
- REST API: `GET /api/stats` → `{ total, countries, last }`

### Setup | Thiết lập

```bash
cd web
npm install          # Install Wrangler
cp wrangler.toml.example wrangler.toml
# Edit wrangler.toml: fill in YOUR_KV_NAMESPACE_ID, optionally custom domain
```

### Create Resources | Tạo tài nguyên

```bash
# Create KV namespace for download stats
npm run kv:create
# → Copy the returned ID into wrangler.toml (kv_namespaces.id)

# Create R2 bucket for releases
npm run r2:create
```

### Upload Release | Tải lên bản phát hành

```bash
# Build the exe first (see Build section above)
# Then upload to R2:
npx wrangler r2 object put riceupscale-releases/RiceUpscaler-v1.0.0.exe \
  --file="../dist/RiceUpscaler.exe" --remote
```

### Local Development | Phát triển cục bộ

```bash
npm run dev
# Opens http://localhost:8787
```

### Deploy | Triển khai

```bash
npm run deploy
# → https://riceupscale-web.<your-subdomain>.workers.dev
# Or your custom domain if configured
```

### Custom Domain (Optional) | Tên miền riêng

```bash
npx wrangler custom-domain add yourdomain.com
# Or via Cloudflare Dashboard: Workers & Pages → riceupscale-web → Settings → Domains & Routes
```

### Monitor Stats | Theo dõi thống kê

```bash
# Total downloads
npx wrangler kv key get --binding=RICEUPSCALE_KV "total"

# Per-country breakdown
npx wrangler kv key get --binding=RICEUPSCALE_KV "countries"

# Last download
npx wrangler kv key get --binding=RICEUPSCALE_KV "last"

# Real-time logs
npx wrangler tail
```

---

## 🧪 Verification | Kiểm tra

### Python Syntax Check

```bash
python -m py_compile src/main.py
```

### Node/Worker Syntax Check

```bash
cd web
node --check index.js
node --check templates.js
node --check icon.js
```

### Lint / Typecheck (Optional)

```bash
# Python (if ruff/mypy configured)
ruff check src/
mypy src/

# JS (if eslint configured)
npx eslint web/*.js
```

---

## 📜 License | Giấy phép

This project is licensed under the **MIT License** — see [LICENSE](LICENSE) for details.

Dự án được phát hành dưới giấy phép **MIT** — xem [LICENSE](LICENSE) để biết chi tiết.

---

## 🙏 Third-Party Libraries | Thư viện bên thứ ba

| Library / Thư viện | License / Giấy phép | Purpose / Mục đích |
|:---|:---|:---|
| Real-ESRGAN (xinntao) | BSD-3-Clause | Anime/photo upscaling models |
| ncnn (Tencent) | BSD-3-Clause | Vulkan inference engine |
| onnxruntime / onnxruntime-directml | MIT | DAT ONNX inference on DirectML |
| Pillow (PIL) | HPND | Image loading/saving/processing |
| pillow_heif | MIT | HEIC/HEIF support |
| NumPy | BSD-3-Clause | Numerical operations |
| windnd | MIT | Windows drag-and-drop |
| PyInstaller | GPL-2.0 (runtime exception) | Executable bundling |
| forest-dark theme | MIT | Modern Tkinter theme |
| Plus Jakarta Sans / JetBrains Mono | SIL OFL 1.1 / OFL 1.1 | Web fonts (via Google Fonts) |

---

## 🌐 Links | Liên kết

- **Issues / Báo lỗi**: GitHub Issues
- **Releases / Bản phát hành**: GitHub Releases
- **Live Demo / Demo trực tuyến**: `https://your-domain.workers.dev` (after deploy)

---

## 👤 Author | Tác giả

**Rice Upscaler** — Open-source offline AI image upscaler for Windows.

---

<div align="center">

**Made with ❤️ for the open-source community** · **Được tạo với ❤️ cho cộng đồng mã mở**

</div>