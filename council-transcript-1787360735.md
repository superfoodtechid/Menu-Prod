# Council Transcript: Fitur Push Menu C5 untuk ShopeeFood

**Timestamp:** 1787360735  
**Topik:** Penambahan Fitur Push Menu C5 ke ShopeeFood (Menyelaraskan dengan GoFood & Grab)

---

## 1. Tahap Analisis Independen 5 Penasihat

### 1. The Contrarian
- **Risiko Autentikasi & Sesi**: Shopee Food menggunakan hierarki akun multi-outlet (`merchantId`, `store_id`, `shopee_tob_token`). Jika store switching salah, pembaruan item masuk ke outlet yang salah.
- **Toleransi Kenaikan Harga**: Kenaikan harga drastis di Shopee (> 50% atau perubahan di luar batas threshold) dapat menyebabkan API `update_dish` me-reject payload tanpa error eksplisit selain code failure.
- **Unit Harga**: Shopee API menggunakan satuan cent (`price * 100000`). Kesalahan konversi harga akan berakibat fatal (harga menjadi 100.000x lipat atau 0).

### 2. The First Principles Thinker
- **Tujuan Inti**: Menerapkan diff C5 (nama, harga, kategori baru, item baru) ke ShopeeFood secara deterministik tanpa duplikasi kode.
- **Arsitektur**: Shopee sudah memiliki engine `shopee/core/push.py`, `shopee/core/client.py`, dan modul `item/create.py`, `item/edit.py`. C5 push Shopee hanya perlu mengorkestrasi modul-modul ini ke dalam wrapper yang konsisten dengan `push_c5_grab_for_merchant` dan `_push_c5_gofood_for_merchant`.

### 3. The Expansionist
- **Skalabilitas Multi-Platform**: Membuka jalan integrasi tri-platform yang simetris (`gofood`, `grab`, `shopee`).
- **Batching & Resiliency**: Mendukung batch delay dan auto-create kategori jika ada item C5 yang masuk ke kategori baru yang belum pernah terdaftar di Shopee Store.

### 4. The Outsider
- **Kejelasan Error & Audit Trail**: Hasil push harus menghasilkan log status terstandar (`SUCCESS`, `FAILED`, `error_message`, `applied`) agar UI dan tabel `audit_trail` menampilkan laporan real-time yang sama di semua platform.

### 5. The Executor
- **Langkah Konkret**:
  1. Buat modul `shopee/core/push_c5.py` dengan fungsi `push_c5_shopee_for_merchant(store_metadata, updates, progress_cb, headless)`.
  2. Tangani pembuatan kategori baru via `create_category` dan item baru via `create_dish`.
  3. Tangani update harga & nama via `update_dish` dengan proteksi step-push jika lonjakan harga signifikan.
  4. Sambungkan ke router job di `main.py` (`run_push_c5_job`) pada blok platform `shopee`.

---

## 2. Peer Review & Sintesis Chairman

### Kesepakatan Dewan (Consensus):
1. Gunakan modul `shopee/core/client.py` dan `shopee/core/push.py` yang sudah stabil untuk token browser session & switcher.
2. Gunakan konversi harga standar Shopee: `int(price * 100000)`.
3. Pasang fallback matching ID: cari by `item_id`, jika tidak ada fallback ke fuzzy/exact name match pada katalog store.
4. Integrasikan ke `run_push_c5_job` di `main.py` sehingga endpoint API `/api/jobs/push-c5` otomatis mendukung `platform: "shopee"`.

---

## 3. Tindakan Eksekusi (Action Items)
1. Buat file `shopee/core/push_c5.py`.
2. Edit `main.py` pada `run_push_c5_job` untuk memanggil `push_c5_shopee_for_merchant`.
3. Validasi kompilasi dan import.
