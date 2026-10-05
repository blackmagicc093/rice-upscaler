# Rice Upscaler

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-blue.svg)](https://www.microsoft.com/windows)
[![Python](https://img.shields.io/badge/Python-3.10%2B-green.svg)](https://www.python.org/)
[![Architecture](https://img.shields.io/badge/Architecture-x64-lightgrey.svg)]()

**Rice Upscaler** is a free, open-source Windows desktop application for AI-powered image upscaling up to 8×. It combines **DAT (Dual Aggregation Transformer)** via DirectML and **Real-ESRGAN** via ncnn-Vulkan with intelligent hardware cascade, exact target-size fitting, batch processing, and 100% offline privacy.

**Rice Upscaler** là ứng dụng desktop chạy trên Windows chuyên phóng đại và phục chế chi tiết ảnh bằng AI lên tới 8×. Phần mềm kết hợp mạng nơ-ron **DAT** (DirectML) và **Real-ESRGAN** (Vulkan) với cơ chế tự động điều phối phần cứng thông minh, khống chế chính xác dung lượng file đầu ra, xử lý hàng loạt và bảo mật ngoại tuyến 100%.

---

## ✨ Features | Tính năng chính

| Feature / Tính năng | Description / Mô tả |
|:---|:---|
| **Multi-Engine Cascade / Điều phối đa engine** | DAT (DirectML) → Real-ESRGAN (Vulkan) → Lanczos (CPU) tự động chuyển đổi theo phần cứng và độ phân giải |
| **Scale 1×–8× & DPI** | Tùy chọn phóng to nguyên số 1× đến 8×; thiết lập DPI đầu ra: Mặc định / 150 / 300 DPI chuẩn in ấn |
| **Target Size Control / Khống chế dung lượng đích** | Khống chế chính xác dung lượng tệp 1–24 MB bằng thuật toán tìm kiếm nhị phân và byte padding (JPEG/PNG) |
| **Format Support / Hỗ trợ định dạng** | Đầu vào: JPG, PNG, WEBP, HEIC/HEIF · Đầu ra: JPG (chất lượng 1–100%), PNG (nén 0–9) |
| **Batch Queue / Xử lý hàng loạt** | Kéo thả danh sách tệp, hỗ trợ Windows Long Path (>260 ký tự), đường dẫn Unicode, xem trước hình thu nhỏ |
| **GPU Acceleration / Tăng tốc GPU** | Tương thích NVIDIA GeForce, AMD Radeon, Intel UHD/Arc qua Vulkan 1.1+ và DirectX 12 DirectML; chia mảng VRAM thích ứng |
| **100% Offline / Ngoại tuyến hoàn toàn** | Không tải lên đám mây, không thu thập dữ liệu (telemetry), không cần tài khoản — toàn bộ suy luận AI chạy trên máy cục bộ |

---

## 📁 Project Structure | Cấu trúc dự án

```
rice-upscaler/
├── src/
│   └── main.py                 # Mã nguồn ứng dụng chính (Tkinter GUI, inference cascade)
├── tools/                      # Công cụ thực thi và mô hình AI nặng (gitignored)
│   ├── realesrgan-ncnn-vulkan.exe
│   ├── realesrgan-x4plus.bin / .param
│   ├── realesrgan-x4plus-anime.bin / .param
│   ├── realesr-animevideov3-x2/x3/x4.bin / .param
│   ├── vcomp140.dll
│   └── models/
│       └── DAT_light_x4.onnx
├── assets/
│   ├── icon/                   # Biểu tượng ứng dụng (rice.ico, icon-new.ico, etc.)
│   └── forest/                 # Giao diện ttk Forest Dark & Forest Light
├── dist/                       # Thư mục đầu ra khi đóng gói (gitignored)
│   └── RiceUpscaler.exe
├── build/                      # Tệp tạm của PyInstaller (gitignored)
├── RiceUpscaler.spec           # Cấu hình đóng gói PyInstaller
├── requirements.txt            # Thư viện Python phụ thuộc
├── LICENSE                     # Giấy phép MIT
└── README.md                   # Tài liệu hướng dẫn
```

---

## 📦 Heavy Models & Binaries | Kênh tải mô hình AI nặng

Do kích thước lớn, các tệp nhị phân và trọng số mô hình trong thư mục `tools/` được loại trừ khỏi kho mã nguồn (`.gitignore`). Cần chuẩn bị các tệp sau trước khi chạy hoặc đóng gói:

### 1. Real-ESRGAN NCNN Vulkan
- **Tải về**: Truy cập [Real-ESRGAN Releases](https://github.com/xinntao/Real-ESRGAN/releases) và tải bản phát hành Windows (ví dụ: `realesrgan-ncnn-vulkan-*-windows.zip`).
- **Thao tác**: Giải nén và đặt các tệp sau trực tiếp vào thư mục `tools/`:
  - `realesrgan-ncnn-vulkan.exe`
  - `realesrgan-x4plus.bin` & `realesrgan-x4plus.param`
  - `realesrgan-x4plus-anime.bin` & `realesrgan-x4plus-anime.param`
  - `realesr-animevideov3-x2.bin`, `realesr-animevideov3-x3.bin`, `realesr-animevideov3-x4.bin` (& `.param`)
  - `vcomp140.dll`

### 2. DAT (Dual Aggregation Transformer) ONNX
- **Tải về**: Tải mô hình `DAT_light_x4.onnx` từ kho [zhengchen1999/DAT](https://github.com/zhengchen1999/DAT) hoặc các bản phát hành của dự án.
- **Thao tác**: Đặt tệp vào thư mục:
  ```
  tools/models/DAT_light_x4.onnx
  ```

---

## 🚀 Getting Started | Cài đặt & Chạy từ Clone

### Yêu cầu hệ thống (Prerequisites)
- **Hệ điều hành**: Windows 10 / 11 (64-bit), phiên bản 1607 trở lên
- **Python**: Python 3.10 trở lên ([python.org](https://www.python.org/downloads/))
- **GPU (khuyến nghị)**: NVIDIA (GTX 900+), AMD (RX 400+), Intel (UHD 620+ / Arc) hỗ trợ Vulkan 1.1+ hoặc DirectX 12
- **RAM**: Tối thiểu 4 GB (khuyến nghị 8–16 GB)

### Cài đặt môi trường

```bash
# 1. Clone repository
git clone https://github.com/blackmagicc093/rice-upscaler.git
cd rice-upscaler

# 2. Khởi tạo môi trường ảo (khuyến nghị)
python -m venv .venv
.venv\Scripts\activate

# 3. Cài đặt các thư viện phụ thuộc
pip install -r requirements.txt
```

### Chạy ứng dụng

Sau khi đã đặt đủ các mô hình trong `tools/`:

```bash
python src/main.py
```

---

## 🔨 Build Executable | Đóng gói tệp thực thi (.exe)

Ứng dụng có thể được đóng gói thành tệp thực thi độc lập bằng PyInstaller:

```bash
# 1. Cài đặt PyInstaller
pip install pyinstaller

# 2. Thực hiện đóng gói với file spec đi kèm
pyinstaller RiceUpscaler.spec
```

Sau khi hoàn tất, tệp `.exe` độc lập sẽ nằm trong thư mục `dist/RiceUpscaler.exe`. Tệp này đã tích hợp sẵn toàn bộ giao diện, mô hình AI trong `tools/` và biểu tượng ứng dụng.

---

## 🧪 Verification | Kiểm tra cú pháp

Kiểm tra cú pháp Python:

```bash
python -m py_compile src/main.py
```

---

## 📜 License | Giấy phép

Dự án được phân phối dưới giấy phép **MIT License** — xem tệp [LICENSE](LICENSE) để biết chi tiết.

---

## 🙏 Third-Party Credits | Thư viện & Công trình kế thừa

- [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) (xinntao) — Mô hình phục chế ảnh và video (BSD-3-Clause)
- [DAT (Dual Aggregation Transformer)](https://github.com/zhengchen1999/DAT) (zhengchen1999) — Kiến trúc Transformer siêu phân giải ảnh
- [ncnn](https://github.com/Tencent/ncnn) (Tencent) — Framework suy luận nơ-ron tối ưu hóa cho Vulkan
- [onnxruntime / DirectML](https://github.com/microsoft/DirectML) (Microsoft) — Tăng tốc suy luận ONNX qua DirectX 12
- [Pillow & pillow-heif](https://github.com/python-pillow/Pillow) — Xử lý các định dạng hình ảnh và HEIC
- [windnd](https://github.com/hasenbanck/windnd) — Tương tác kéo thả tệp trên Windows
- [Forest Tkinter Theme](https://github.com/rdbende/Forest-ttk-theme) (rdbende) — Giao diện dark/light hiện đại cho Tkinter