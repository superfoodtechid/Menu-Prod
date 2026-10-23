# Ingatan Komprehensif Proyek Menu | 2026-10-22 09:00

Dokumen ini disusun sebagai memori komprehensif seluruh arsitektur, basis pengetahuan bisnis, detail teknis tri-platform (GoFood, GrabFood, ShopeeFood), skema data, integrasi Google Workspace, pipeline ekspor/impor C5, server produksi, serta riwayat penyelesaian masalah (troubleshooting history).

---

## 1. Ikhtisar & Tujuan Proyek

**FoodMaster Menu** (sebelumnya Superfood Menu Management) adalah platform automasi manajemen katalog menu multi-platform (OFD - Online Food Delivery) untuk ratusan outlet kuliner terpusat (multi-brand & multi-owner).

### Fungsi Inti Sistem:
1. **Penyelarasan & Sinkronisasi Merchant Master (Google Sheets):**
   - Mengambil data outlet dari master spreadsheet Google Sheets (`https://docs.google.com/spreadsheets/d/...`).
   - Menyimpan pemetaan `Owner`, `Brand`, `Nama Outlet`, `Store ID (SID)`, link outlet, serta kredensial akun ke database lokal SQLite.
2. **Penarikan Menu Multi-Platform (Pull Pipeline):**
   - Menarik struktur menu aktif (kategori, nama item, varian/modifier, harga, ketersediaan, visibilitas, dan link foto) dari GoFood, GrabFood, dan ShopeeFood.
   - Mengunduh foto menu dan mengunggahnya ke hierarki folder terstruktur di Google Drive secara otomatis.
   - Menghasilkan file katalog per outlet dalam format spreadsheet standar industri: **`O.C5 .xlsx`**.
3. **Penggabungan Master Menu (C5 Combiner):**
   - Menggabungkan katalog beberapa outlet yang dipilih menjadi satu file master C5.
   - Memulihkan dan memetakan harga offline (`Offline Price (Rp)`) dari database lokal dan riwayat Google Drive.
   - Mengunggah file kombinasi C5 langsung ke folder Google Drive milik Owner terkait.
4. **Pembaruan Massal ke Platform (Push Pipeline):**
   - Membaca file C5 `.xlsx` yang telah disunting harga/nama/foto/kategori.
   - Menghitung perbedaan (*diff preview*) terhadap data menu baseline.
   - Menerapkan batasan kenaikan bertahap (*step push*) pada platform yang membatasi lonjakan harga drastis (GoFood/Grab).
   - Memperbarui nama item, harga diskon (*slash price*), kategori, foto, hingga pembuatan item baru secara headless atau direct API.

---

## 2. Arsitektur Tri-Platform (Spesifikasi Teknis & Solusi Tantangan)

### A. GoFood (Gojek / GoBiz Portal)
- **Metode Ekstraksi (Pull):**
  - Menggunakan kombinasi **Direct REST API** dengan token autentikasi sesi GoBiz dan **CDP Network Intercept**.
  - Menyimpan baseline snapshot ke `/app/Gofood/API/menu-response-{SID}.json` dan `modifier-response-{SID}.json`.
- **Logika Push (`Gofood/push_c5.py`):**
  - **Item Baru (`tambah_item`):** Jika baris di C5 tidak memiliki `Item ID`, sistem memanggil endpoint pembuatan item baru (`POST /v2/menu_groups/{group_id}/menu_items`).
  - **Pencegahan Step Push pada Item Baru:** Item baru tidak memiliki riwayat harga lama, sehingga **tidak boleh terkena step push**. Item baru langsung dipush dengan harga final.
  - **Isolasi Duplikasi Nama:** Jika ada 2 item dengan nama yang sama (satu memiliki ID dan satu baru tanpa ID), item baru diproses independen tanpa tertukar atau menimpa ID item yang sudah ada.
  - **Aturan Step Push Harga:** Perubahan harga pada item lama yang melonjak drastis dibagi menjadi langkah-langkah kenaikan bertahap (maksimum ~20-30% per langkah) sesuai batas kepatuhan GoBiz API dengan jeda interval aman.
  - **Perlindungan Promo:** Jika item sedang terikat promo aktif, perubahan harga disesuaikan agar tidak melanggar syarat promo berjalan.

### B. GrabFood (Grab Merchant Portal)
- **Metode Ekstraksi (Pull):**
  - Menggunakan Playwright Chromium headless untuk mengakses Grab Merchant Portal.
  - Menangani alur SSO Grab, validasi sesi, dan deteksi redirect login.
  - Mengidentifikasi struktur Modifier Group (Single Choice, Multi Choice, Min/Max Select) dan ekstraksi harga promo/slash price.
- **Logika Push (`grab/core/push_c5.py`):**
  - Validasi CSRF Token dan header stealth.
  - Menjaga urutan kategori dan item (*Category & Item Weights / Sort Order*) agar susunan di aplikasi konsumen sesuai dengan urutan baris di C5.
  - Dukungan pelepasan kaitan promo (*promo detach*) bila perubahan harga bertabrakan dengan campaign promo aktif.

### C. ShopeeFood (Shopee Partner Portal)
- **Tantangan Utama:** Proteksi login ketat (CAPTCHA puzzle slider, SMS/WhatsApp OTP, dan akun nomor HP tanpa password).
- **Arsitektur Solusi Akun Tanpa Password:**
  - Operator menggunakan script lokal `shopee_session_exporter.py` di PC lokal dengan browser visual untuk login sekali dan memverifikasi OTP/CAPTCHA.
  - Token, cookie multi-domain (`partner.business.accounts.shopee.co.id` dan `partner.shopee.co.id`), serta Chrome profile ringan diekstrak dan diunggah ke server backend.
  - Server melakukan multi-domain cookie injection secara headless.
  - Mengakses halaman `business-hours-settings` secara otomatis di latar belakang untuk me-refresh token sesi sehingga masa aktif token diperpanjang (30 menit interval).
- **Pengoptimalan Performa:**
  - Fast session restore melalui Chromium CDP (Chrome DevTools Protocol) dengan bendera lean (disable GPU, disable extensions, memory-optimized).
- **Logika Push (`shopee/core/push_c5.py`):**
  - Validasi hash foto Shopee (`photo_hash` / `image_id`) untuk mencegah kegagalan upload aset visual.
  - Pembaruan harga reguler dan slash price.

---

## 3. Integrasi Google Workspace (Drive & Apps Script)

### Hierarki Penyimpanan Google Drive
Semua output katalog dan aset foto disimpan di bawah `GDRIVE_FOLDER_ID` (Root Folder) dengan struktur:
```text
Root Folder (GDRIVE_FOLDER_ID)
└── {Owner Name} /
    ├── C5. {timestamp} {Owner Name}.xlsx    (File Kombinasi C5)
    └── Foto Menu /
        └── {Platform} /
            └── {Listing Name} - {SID} /
                ├── {Item Name} - {Item ID}.jpg
                └── ...
```

### Dual-Engine Sinkronisasi Foto (`menu_core/gdrive_service.py`)
1. **Google Apps Script Web App Engine (Rekomendasi Utama):**
   - Dibuat untuk mengatasi pembatasan GCP Organization Policy (`iam.disableServiceAccountKeyCreation`) yang memblokir pembuatan Service Account Key lokal.
   - Script `google_apps_script.js` dideploy sebagai Web App.
   - Backend Python mengirim payload JSON berisi nama folder dan file foto (base64 atau download URL) via HTTP POST ke endpoint `GDRIVE_APPSCRIPT_URL`.
   - **Syarat Wajib:** Setelan deployment Apps Script **"Who has access"** harus **"Anyone"** agar backend headless tidak terhalang redirect autentikasi Google (HTTP 401 Unauthorized).
   - Menghasilkan tautan Google Drive publik yang langsung disematkan ke kolom `Photo Link` di file C5.
2. **Google Service Account Engine (Fallback Tradisional):**
   - Menggunakan library `google-api-python-client` jika file JSON Service Account tersedia pada `GOOGLE_APPLICATION_CREDENTIALS`.

---

## 4. Standar Format File C5 (`O.C5 .xlsx`)

Sistem sepenuhnya terstandarisasi menggunakan template `O.C5 .xlsx` (`menu_core/c5_template_helper.py`):

### Struktur Sheet 1: `Item`
- Baris 1: Header Nama Kolom
- Baris 2: Baris Terproteksi (*Protected Formula / Reference Row*)
- Baris 3 dst: Data Item Menu

Daftar Kolom Standar:
1. `OFD` (GoFood / GrabFood / ShopeeFood)
2. `Outlet Name`
3. `Outlet Short Name`
4. `Outlet Link`
5. `SID` (Store ID)
6. `Category ID`
7. `Category`
8. `Item ID`
9. `Item`
10. `Photo Link` (Tautan Google Drive atau tautan CDN platform)
11. `Description`
12. `Keyword`
13. `Item Name Improvement`
14. `Design Improvement`
15. `Total Sold`
16. `Total Modifier Group`
17. `Total Modifier`
18. `Availability` (`Available` / `Unavailable`)
19. `Visibility` (`Show` / `Hide`)
20. `Offline Price (Rp)`
21. `Offline Adjustment (Rp)`
22. `Current Fake Price (Rp)` (Harga coret lama)
23. `Current Real Price (Rp)` (Harga jual efektif saat ini)
24. `Current Adjustment (Rp)`
25. `New Markup (%)`
26. `New Adjustment (Rp)`
27. `New Slash Price (%)`
28. `Notes`

### Struktur Sheet 2: `Modifier`
Memetakan hubungan antara Item dengan grup varian/topping, pilihan modifier, harga ekstra, batas minimal/maksimal pilihan, serta status ketersediaan.

---

## 5. Spesifikasi Server Produksi & Arsitektur Kontainer

### Informasi Akses Server:
- **Alamat IP:** `38.103.171.236`
- **Username:** `root`
- **Lokasi Kode:** `/home/radi/foodmaster-menu`
- **Port Publik & Internal:**
  - Frontend Web UI: `http://38.103.171.236:3000` (dipetakan ke port `80` Nginx)
  - Backend API: `http://38.103.171.236:8000` dan `http://38.103.171.236:18800` (Uvicorn FastAPI)

### Detail Layanan Docker (`docker-compose.yml`):
```yaml
services:
  backend:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: foodmaster-backend
    restart: unless-stopped
    init: true
    shm_size: '2gb'
    userns_mode: keep-id
    environment:
      - HOME=/tmp
      - SE_CACHE_PATH=/tmp/.cache/selenium
      - WDM_DIR=/tmp/.wdm
    ports:
      - "127.0.0.1:8000:8000"
      - "127.0.0.1:18800:8000"
    volumes:
      - ./.env:/app/.env:ro
      - ./data:/app/data
      - ./main.py:/app/main.py
      - ./login_gofood.py:/app/login_gofood.py
      - ./Gofood:/app/Gofood
      - ./shopee:/app/shopee
      - ./grab:/app/grab
      - ./menu_core:/app/menu_core
      - ./src:/app/src
      - ./src/shopee-omzet-automation/data:/app/src/shopee-omzet-automation/data
    networks:
      - foodmaster-network

  frontend:
    build:
      context: ./web
      dockerfile: Dockerfile
    container_name: foodmaster-frontend
    restart: unless-stopped
    ports:
      - "127.0.0.1:3000:80"
    depends_on:
      - backend
    networks:
      - foodmaster-network
```

---

## 6. Prosedur Perawatan & Panduan Operasional (*Cheat Sheet*)

### 1. Update Kode dari GitHub ke Server
```bash
# 1. Masuk ke folder repo di server
cd /home/radi/foodmaster-menu

# 2. Ambil update dari cabang main
git pull origin main

# 3. Restart backend & frontend (volume mount otomatis memperbarui kode Python tanpa perlu build ulang jika tidak ada paket baru)
docker compose restart backend frontend

# 4. Jika ada perubahan library Python atau Dockerfile, lakukan build ulang:
docker compose up -d --build
```

### 2. Memeriksa Status & Log Sistem
```bash
# Cek kontainer yang berjalan
docker ps

# Cek log backend realtime
docker logs -f --tail 100 foodmaster-backend

# Cek log frontend
docker logs --tail 50 foodmaster-frontend
```

### 3. Menguji Eksekusi Modul Langsung di dalam Kontainer
```bash
# Tes modul sinkronisasi foto Google Drive
docker exec -it foodmaster-backend python3 -c "from menu_core.gdrive_service import sync_menu_photos_to_drive; print(sync_menu_photos_to_drive)"

# Tes koneksi database
docker exec -it foodmaster-backend python3 -c "import sqlite3; conn = sqlite3.connect('/app/data/foodmaster.db'); print('DB Connected:', conn.total_changes)"
```

### 4. Troubleshooting Masalah Umum

| Gejala Masalah | Penyebab Utama | Solusi Tindakan |
|---|---|---|
| Foto menu di file C5 masih berupa link Gojek/Shopee/Grab (bukan link Google Drive) | Apps Script merespons `HTTP 401 Unauthorized` | Buka Google Apps Script > Deploy > Manage deployments > Edit > Ubah **Who has access** menjadi **Anyone** > Deploy. |
| Job pull Shopee macet / meminta OTP | Token sesi Shopee kadaluarsa | Jalankan `python shopee_session_exporter.py` di PC lokal, login visual, lalu upload sesi baru via API/Web. |
| Container backend gagal restart (*Address already in use*) | Zombie process Uvicorn atau Port binding tabrakan | `docker compose down` diikuti `docker compose up -d`. |
| Push GoFood gagal pada item baru | Kategori baru belum ada atau payload V2 tidak sesuai | Pastikan kolom `Category` terisi valid di C5. Sistem akan otomatis membuat kategori jika belum ada. |
| Perubahan harga ditolak platform | Lonjakan harga melebihi batas regulasi platform | Fitur *step push* akan membagi kenaikan secara otomatis menjadi beberapa tahap. Jalankan push step lanjutan pada jadwal berikutnya. |

---

## 7. Indeks File Penting dalam Proyek

- **Logika Inti Menu & Drive:**
  - `menu_core/gdrive_service.py` : Sinkronisasi foto menu ke Google Drive.
  - `menu_core/c5_combiner.py` : Logika penggabungan katalog outlet ke C5 master.
  - `menu_core/c5_template_helper.py` : Builder dan validator struktur `O.C5 .xlsx`.
  - `google_apps_script.js` : Engine Apps Script sisi cloud Google.
- **Platform Integrations:**
  - `menu_core/gofood.py` & `Gofood/push_c5.py` : Driver GoFood.
  - `menu_core/grab.py` & `grab/core/push_c5.py` : Driver GrabFood.
  - `shopee/core/pull.py` & `shopee/core/push_c5.py` : Driver ShopeeFood.
- **Dokumentasi Terkait:**
  - `push.md` : Dokumentasi alur Menu Push C5.
  - `PROSEDUR_PENGUJIAN_DAN_DAFTAR_API.md` : Prosedur sesi Shopee & katalog API backend.
  - `.agents/rules.md` : Panduan baku desain frontend & anti-slop.

# 3. Restart backend & frontend (volume mount otomatis memperbarui kode Python tanpa perlu build ulang jika tidak ada paket baru)
docker compose restart backend frontend

# 4. Jika ada perubahan library Python atau Dockerfile, lakukan build ulang:
docker compose up -d --build
```

### 2. Memeriksa Status & Log Sistem
```bash
# Cek kontainer yang berjalan
docker ps

# Cek log backend realtime
docker logs -f --tail 100 foodmaster-backend

# Cek log frontend
docker logs --tail 50 foodmaster-frontend
```

### 3. Menguji Eksekusi Modul Langsung di dalam Kontainer
```bash
# Tes modul sinkronisasi foto Google Drive
docker exec -it foodmaster-backend python3 -c "from menu_core.gdrive_service import sync_menu_photos_to_drive; print(sync_menu_photos_to_drive)"

# Tes koneksi database
docker exec -it foodmaster-backend python3 -c "import sqlite3; conn = sqlite3.connect('/app/data/foodmaster.db'); print('DB Connected:', conn.total_changes)"
```

### 4. Troubleshooting Masalah Umum

| Gejala Masalah | Penyebab Utama | Solusi Tindakan |
|---|---|---|
| Foto menu di file C5 masih berupa link Gojek/Shopee/Grab (bukan link Google Drive) | Apps Script merespons `HTTP 401 Unauthorized` | Buka Google Apps Script > Deploy > Manage deployments > Edit > Ubah **Who has access** menjadi **Anyone** > Deploy. |
| Job pull Shopee macet / meminta OTP | Token sesi Shopee kadaluarsa | Jalankan `python shopee_session_exporter.py` di PC lokal, login visual, lalu upload sesi baru via API/Web. |
| Container backend gagal restart (*Address already in use*) | Zombie process Uvicorn atau Port binding tabrakan | `docker compose down` diikuti `docker compose up -d`. |
| Push GoFood gagal pada item baru | Kategori baru belum ada atau payload V2 tidak sesuai | Pastikan kolom `Category` terisi valid di C5. Sistem akan otomatis membuat kategori jika belum ada. |
| Perubahan harga ditolak platform | Lonjakan harga melebihi batas regulasi platform | Fitur *step push* akan membagi kenaikan secara otomatis menjadi beberapa tahap. Jalankan push step lanjutan pada jadwal berikutnya. |

---

## 7. Indeks File Penting dalam Proyek

- **Logika Inti Menu & Drive:**
  - `menu_core/gdrive_service.py` : Sinkronisasi foto menu ke Google Drive.
  - `menu_core/c5_combiner.py` : Logika penggabungan katalog outlet ke C5 master.
  - `menu_core/c5_template_helper.py` : Builder dan validator struktur `O.C5 .xlsx`.
  - `google_apps_script.js` : Engine Apps Script sisi cloud Google.
- **Platform Integrations:**
  - `menu_core/gofood.py` & `Gofood/push_c5.py` : Driver GoFood.
  - `menu_core/grab.py` & `grab/core/push_c5.py` : Driver GrabFood.
  - `shopee/core/pull.py` & `shopee/core/push_c5.py` : Driver ShopeeFood.
- **Dokumentasi Terkait:**
  - `push.md` : Dokumentasi alur Menu Push C5.
  - `PROSEDUR_PENGUJIAN_DAN_DAFTAR_API.md` : Prosedur sesi Shopee & katalog API backend.
  - `.agents/rules.md` : Panduan baku desain frontend & anti-slop.

