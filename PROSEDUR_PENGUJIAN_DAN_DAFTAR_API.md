# Panduan Prosedur Pengujian dan Dokumentasi API FoodMaster

Dokumen ini memuat panduan langkah demi langkah untuk pengujian sesi Shopee Partner tanpa password (nomor HP saja), serta daftar lengkap endpoint API yang tersedia pada proyek FoodMaster, termasuk API pengelolaan sesi dan sinkronisasi data.

---

## Bagian 1: Prosedur Pengujian Sesi Shopee Partner

Prosedur ini dirancang khusus untuk menangani akun Shopee Partner yang menggunakan nomor HP tanpa password. Akun jenis ini tidak dapat login otomatis mandiri di server data center (headless) karena terkena proteksi CAPTCHA slider dan verifikasi OTP.

### Alur Kerja Sistem
1. Operator menjalankan `shopee_session_exporter.py` di komputer lokal (browser Chrome terbuka secara visual).
2. Sesi login (cookie SSO, token dashboard, dan profil Chrome ringan) diekstrak dan diunggah ke server via API.
3. Server memulihkan sesi menggunakan injeksi multi-domain:
   - Menyuntikkan cookie autentikasi ke domain SSO (`partner.business.accounts.shopee.co.id`).
   - Menyuntikkan token dashboard ke domain Partner (`partner.shopee.co.id`).
   - Otomatis mendeteksi dan mengklik tombol **Lanjutkan dengan Shopee** jika layar persetujuan SSO muncul.
   - Membuka pengaturan jam operasional (`business-hours-settings`) untuk menerbitkan token baru yang berlaku 30 menit ke depan.

---

### Langkah-Langkah Pengujian Esok Hari

#### Langkah 1: Ekspor Sesi Segar dari Komputer Lokal
Jalankan perintah ini di terminal komputer lokal Anda (tempat Google Chrome biasa digunakan):
```bash
python shopee_session_exporter/shopee_session_exporter.py -p 6285183151531
```
*Catatan:*
- Ganti `6285183151531` dengan nomor HP akun Shopee yang ingin diuji jika berbeda.
- Chrome akan terbuka otomatis. Jika sesi di Chrome lokal masih aktif, proses akan selesai dalam hitungan detik.
- Jika diminta verifikasi CAPTCHA atau OTP WhatsApp/SMS, selesaikan langsung di jendela Chrome tersebut.
- Skrip akan otomatis mengunggah data sesi dan profil Chrome ringan ke server backend.

#### Langkah 2: Uji Validitas Sesi di Server (Tanpa Mengubah Harga Menu)
Sebelum menjalankan perubahan harga menu yang sebenarnya, jalankan salah satu dari dua metode pengujian diagnostik berikut:

**Opsi A (Melalui Endpoint API):**
Buka peramban (browser) atau gunakan `curl`:
```bash
curl -X GET "http://<IP-ATAU-DOMAIN-SERVER>:8000/api/shopee/test-session?identifier=6285183151531"
```
Respons sukses yang diharapkan:
```json
{
  "status": "SUCCESS",
  "identifier": "6285183151531",
  "session_file": "session_6285183151531.json",
  "direct_token_valid": true,
  "browser_restore_success": true,
  "new_token_extracted": true,
  "merchant_name": "SuperFood",
  "message": "Sesi Shopee valid dan aktif. Browser headless berhasil memulihkan sesi dan mengekstrak token segar."
}
```

**Opsi B (Melalui Skrip CLI di Server):**
Jalankan langsung di dalam container backend server:
```bash
docker exec -it foodmaster-backend python3 scripts/test_shopee_session.py -i 6285183151531
```
Skrip ini akan memverifikasi:
1. Keberadaan berkas sesi `session_6285183151531.json`.
2. Keberadaan direktori Chrome profile di server.
3. Uji token API langsung via HTTP request.
4. Peluncuran browser headless dan pemulihan sesi multi-domain.
5. Pembaruan token segar via jam operasional.

#### Langkah 3: Uji Push Harga Riil pada 1 Item Menu
Setelah status pada Langkah 2 bernilai `SUCCESS`:
1. Masuk ke antarmuka Web FoodMaster pada menu **Edit Harga**.
2. Pilih outlet Shopee terkait (`SuperFood`).
3. Pilih 1 item menu dan ubah harganya sebagai sampel pengujian.
4. Klik tombol **Push Harga**.
5. Amati proses eksekusi. Browser headless akan langsung menggunakan sesi aktif tanpa meminta input OTP.

---

## Bagian 2: Daftar Lengkap API Proyek FoodMaster

Berikut adalah seluruh endpoint API backend FastAPI yang tersedia pada proyek ini, dikelompokkan berdasarkan fungsinya.

### 1. API Pengelolaan Sesi (Session Management)

#### A. Melihat Status Sesi Seluruh Outlet
- **Method & Path:** `GET /api/sessions`
- **Fungsi:** Menampilkan daftar seluruh outlet aktif (Shopee, GoFood, GrabFood), status keberadaan berkas sesi, tanggal terakhir aktif, nomor HP, dan username.
- **Contoh Response:**
  ```json
  [
    {
      "id": "c2208ccd-6458-40b3-af77-526fae05a831",
      "store_id": "100234",
      "merchant_name": "SuperFood",
      "has_session": true,
      "session_file": "session_6285183151531.json",
      "last_active": "2026-09-23T08:30:00",
      "phone": "6285183151531",
      "username": "superfoodapp"
    }
  ]
  ```

#### B. Menghapus Sesi Berdasarkan Target Spesifik
- **Method & Path:** `DELETE /api/sessions/{target}`
- **Fungsi:** Menghapus seluruh berkas sesi (`session_*.json`) dan folder profil Chrome yang berkaitan dengan target. Target dapat berupa: `outlet_id` (UUID), `store_id`, nomor HP, username, atau nama file JSON.
- **Query Parameter Opsional:**
  - `platform`: membatasi platform (`shopee`, `gofood`, `grab`).
  - `confirm_all`: `true` untuk menghapus seluruh sesi di sistem.
- **Contoh Request:**
  ```bash
  curl -X DELETE "http://localhost:8000/api/sessions/6285183151531"
  ```
- **Contoh Response:**
  ```json
  {
    "status": "SUCCESS",
    "message": "Berhasil menghapus 2 berkas sesi dan 1 folder profil Chrome.",
    "target": "6285183151531",
    "deleted_files": [
      "/app/src/shopee-omzet-automation/data/session_6285183151531.json",
      "/app/shopee/data/session_6285183151531.json"
    ],
    "deleted_profiles": [
      "/app/src/shopee-omzet-automation/data/chrome_profile_6285183151531"
    ]
  }
  ```

#### C. Menghapus Sesi via Query Parameters
- **Method & Path:** `DELETE /api/sessions`
- **Query Parameters:**
  - `target`: String pencarian.
  - `outlet_id`: UUID outlet.
  - `username`: Username atau nomor HP.
  - `store_id`: ID toko merchant.
  - `confirm_all`: Boolean (`true` untuk menghapus semua sesi).

#### D. Menghapus Sesi via POST Body (Alternatif)
- **Method & Path:** `POST /api/sessions/delete`
- **Fungsi:** Alternatif jika peramban atau firewall lokal membatasi method HTTP `DELETE`.
- **Payload JSON:**
  ```json
  {
    "target": "6285183151531",
    "platform": "shopee"
  }
  ```

#### E. Alias Khusus Menghapus Sesi Shopee
- **Method & Path:** `DELETE /api/shopee/session/{target}`
- **Fungsi:** Menghapus sesi khusus platform Shopee.

#### F. Mengunggah Sesi Shopee dari Exporter Lokal
- **Method & Path:** `POST /api/shopee/upload-session`
- **Fungsi:** Menerima unggahan data sesi dari `shopee_session_exporter.py` termasuk token TOB, cookie SSO, dan arsip profil Chrome ringan (Base64).
- **Payload JSON:**
  ```json
  {
    "username": "6285183151531",
    "phone": "6285183151531",
    "store_id": "100234",
    "merchant_name": "SuperFood",
    "shopee_tob_token": "B:E...",
    "shopee_tob_entity_id": "100234",
    "extra_cookies": { "SPC_SI": "...", "ds": "..." },
    "profile_archive_base64": "<base64_string>"
  }
  ```

#### G. Mengunggah Berkas JSON Sesi Secara Langsung
- **Method & Path:** `POST /api/shopee/upload-session-file`
- **Content-Type:** `multipart/form-data`
- **Form Data:**
  - `file`: Berkas `session_*.json` dari komputer operator.
  - `username` (opsional): Kunci akun.
  - `merchant_name` (opsional): Nama resto.

#### H. Uji Diagnostik Sesi Shopee
- **Method & Path:** `GET /api/shopee/test-session` atau `POST /api/shopee/test-session`
- **Query Parameter:** `identifier` (contoh: `6285183151531` atau `superfoodapp`)
- **Fungsi:** Menguji pemulihan sesi multi-domain dan ekstraksi token baru tanpa mengubah data harga.

---

### 2. API Sinkronisasi & Refresh Data

#### A. Sinkronisasi Data Master dari Google Sheets
- **Method & Path:** `POST /api/sync-sheets`
- **Fungsi:** Mentrigger sinkronisasi data master outlet dari Google Sheets ke database lokal.
- **Proses yang Dijalankan:**
  - Mengunduh data CSV dari URL Google Sheets publik.
  - Memperbarui cache lokal `master_merchants_cache.csv`.
  - Melakukan forward-fill pada kolom merged (Owner, Status, Nama Outlet, Brand).
  - Memperbarui atau menambahkan data `Account` dan `Outlet` di database.
- **Contoh Request:**
  ```bash
  curl -X POST "http://localhost:8000/api/sync-sheets"
  ```
- **Contoh Response:**
  ```json
  {
    "status": "SUCCESS",
    "message": "Sinkronisasi berhasil.",
    "added_accounts": 1,
    "added_outlets": 3,
    "updated_outlets": 15
  }
  ```

#### B. Menarik Menu Terbaru dari Merchant Portal (Pull Data)
- **Method & Path:** `POST /api/jobs/pull`
- **Status Code:** `202 Accepted`
- **Query Parameter:** `outlet_id` (UUID)
- **Fungsi:** Menjalankan background worker untuk membuka portal merchant (Shopee Food, GoFood, atau GrabFood), mengekstrak daftar menu terbaru beserta harga, variasi, dan promo, lalu menyimpannya ke database dan cache.
- **Contoh Request:**
  ```bash
  curl -X POST "http://localhost:8000/api/jobs/pull?outlet_id=c2208ccd-6458-40b3-af77-526fae05a831"
  ```
- **Contoh Response:**
  ```json
  {
    "id": "5f9b1c2e-3d4a-4e8b-8a1c-9e2d3f4a5b6c",
    "outlet_id": "c2208ccd-6458-40b3-af77-526fae05a831",
    "job_type": "PULL",
    "platform": "shopee",
    "status": "PENDING",
    "progress_pct": 0,
    "current_step": "Job dijadwalkan"
  }
  ```

#### C. Mengambil Daftar Item Menu yang Tersimpan
- **Method & Path:** `GET /api/outlets/{outlet_id}/menu-items`
- **Fungsi:** Mengambil daftar menu aktif yang telah ter-cache untuk suatu outlet (nama item, harga resto, harga promo, status terkunci).
- **Contoh Response:**
  ```json
  [
    {
      "id": "item_12345",
      "name": "Paket Ayam Geprek",
      "category": "Makanan Utama",
      "price": 25000,
      "promo_price": 22000,
      "is_locked": false
    }
  ]
  ```

#### D. Memeriksa Status Cache Menu Outlet
- **Method & Path:** `GET /api/outlets/{outlet_id}/menu-cache-status`
- **Fungsi:** Mengetahui kapan terakhir kali menu di-pull dari merchant portal dan berapa jumlah item yang tersimpan di cache.

---

### 3. API Autentikasi Interaktif & Penanganan OTP Shopee

Endpoint ini digunakan jika browser headless di server memerlukan input OTP manual dari operator melalui Web UI FoodMaster:

#### A. Cek Status Tunggu OTP
- **Method & Path:** `GET /api/shopee/otp-status`
- **Query Parameter Opsional:** `username`
- **Respons saat menunggu:**
  ```json
  {
    "waiting": true,
    "username": "6285183151531",
    "phone": "6285183151531",
    "current_channel": "sms",
    "requested_at": "2026-09-23T08:45:00"
  }
  ```

#### B. Mengirim Kode OTP ke Browser
- **Method & Path:** `POST /api/shopee/submit-otp`
- **Payload:**
  ```json
  {
    "username": "6285183151531",
    "code": "123456",
    "channel": "sms"
  }
  ```

#### C. Memilih Saluran OTP (SMS / WhatsApp)
- **Method & Path:** `POST /api/shopee/select-otp-channel`
- **Payload:**
  ```json
  {
    "username": "6285183151531",
    "channel": "whatsapp"
  }
  ```

#### D. Mengirim Ulang OTP
- **Method & Path:** `POST /api/shopee/resend-otp`
- **Payload:**
  ```json
  {
    "username": "6285183151531",
    "channel": "whatsapp"
  }
  ```

#### E. Membatalkan Permintaan OTP
- **Method & Path:** `POST /api/shopee/cancel-otp`
- **Payload:**
  ```json
  {
    "username": "6285183151531"
  }
  ```
- **Efek:** Menghapus file permintaan OTP, membatalkan job yang sedang berjalan di database, dan mematikan instance browser Chrome aktif seketika.

---

### 4. API Eksekusi Job & Pembaruan Harga (Push Price)

#### A. Memicu Job Push Harga
- **Method & Path:** `POST /api/jobs/push-price`
- **Status Code:** `202 Accepted`
- **Payload:**
  ```json
  {
    "outlet_id": "c2208ccd-6458-40b3-af77-526fae05a831",
    "updates": [
      {
        "item_id": "3148482929458688",
        "category_id": "",
        "item_name": "Item A",
        "new_price": 18000.0
      }
    ]
  }
  ```

#### B. Memantau Status Job
- **Method & Path:** `GET /api/jobs/{job_id}`
- **Fungsi:** Polling status eksekusi job (status: `PENDING`, `RUNNING`, `COMPLETED`, `FAILED`, `CANCELLED`).

#### C. Membatalkan Job
- **Method & Path:** `POST /api/jobs/{job_id}/cancel`
- **Fungsi:** Membatalkan job secara instan dan menghentikan proses browser terkait.

#### D. Riwayat Jejak Audit Perubahan Harga
- **Method & Path:** `GET /api/audit-trails`
- **Fungsi:** Menampilkan riwayat log detail mengenai siapa, kapan, item apa, dan nilai harga yang diubah.
