# 🚀 Dokumentasi Fitur Menu Push C5 (GoFood)

Dokumen ini menjelaskan cakupan lengkap, arsitektur, dan alur kerja dari **Fitur Menu Push C5** pada aplikasi Superfood Menu Management.

---

## 📋 1. Ringkasan Fitur

Fitur **Menu Push C5** dirancang untuk mempermudah pembaruan menu secara massal (*bulk update*) dari file spreadsheet template C5 (`.xlsx`) ke platform Merchant GoFood (GoBiz Portal). 

Sistem secara otomatis:
1. Membaca file C5 `.xlsx` yang diunggah.
2. Membandingkan seluruh kolom C5 dengan baseline data menu terkini (`menu-response-<SID>.json`).
3. Melakukan **Validasi Konsistensi `Category ID`** untuk mencegah ketidakcocokan nama kategori.
4. Mendeteksi penambahan item baru tanpa `Item ID` (`tambah_item`) dan kategori baru (`new_categories`).
5. Menampilkan pratinjau perubahan (*diff preview*) yang interaktif di dashboard frontend.
6. Mem-push pembaruan (Nama Item, Harga, Foto Link, Deskripsi, Nama Kategori, Penambahan Item Baru & Kategori Baru) secara otomatis ke GoFood merchant backend.

---

## 🛠️ 2. Cakupan Perubahan yang Didukung (Coverage Scope)

| Komponen | Fitur | Keterangan & Alur Eksekusi |
|---|---|---|
| ✨ **Item Baru (`tambah_item`)** | Creation of New Items | Jika pada C5 terdapat nama item baru tanpa `Item ID` (atau belum ada di baseline GoFood), sistem otomatis membuat item baru via V2 API (`POST /v2/menu_groups/{group_id}/menu_items`). |
| 📂 **Kategori Baru (`new_categories`)** | Creation of New Categories | Jika nama kategori pada C5 terisi namun `Category ID` kosong, atau nama kategori belum ada di daftar kategori merchant, sistem otomatis membuat kategori baru via V2 API (`POST /v2/menu_groups/{group_id}/menus`) sebelum menautkan item (baru/lama) ke kategori tersebut. |
| 🛑 **Validasi Category ID** | Single Category Name per ID | Seluruh baris item yang memiliki `Category ID` sama **wajib** menggunakan nama kategori yang identik. Jika tidak, parser menandai file **TIDAK VALID**, menampilkan peringatan merah, dan memblokir eksekusi push. |
| 🏷️ **Nama Kategori** | Category Rename | Jika nama kategori diubah pada C5, sistem mengeksekusi V2 API GoFood (`PATCH /v2/menu_groups/{group_id}/menus/{category_id}`) untuk merename nama kategori pada merchant. |
| 📷 **Foto Link / Gambar** | Photo Link & Google Drive | Mendukung link gambar dari kolom `Photo Link` maupun link Google Drive dari kolom `Design Improvement`. URL foto baru dikirimkan ke payload `image_url` GoFood V2 PATCH / V1 PUT. |
| 📝 **Nama Item** | Item Name Improvement | Mengubah nama item menu jika kolom `Item Name Improvement` atau `Item` pada C5 berbeda dari nama baseline GoFood. |
| 💰 **Harga Item** | New Fake Price (Rp) | Mengubah harga item menu berdasarkan kolom `New Fake Price (Rp)` / `Current Fake Price (Rp)`. |
| ⚠️ **Step-Push Harga (>15%)** | Multi-Step Price Update | Jika perubahan harga **> 15%** dari baseline, parser memberikan peringatan `⚠️ >15% Step Push`. Runner akan memicu **push bertahap** (maks. 15% per tahap) secara berulang hingga mencapai harga target. |
| 📄 **Deskripsi Item** | Description Update | Memperbarui deskripsi item menu jika terdapat perbedaan pada kolom `Description`. |
| 🏪 **Multi-Store ID** | Push Banyak Store Sekaligus | Mendukung satu file C5 yang berisi beberapa Store ID (SID). Pengguna dapat memilih SID mana saja yang ingin di-push. |
| 🗑️ **Hapus Item (`delete_item`)** | Deletion of Missing Items | Jika item menu ada pada data baseline PULL GoFood tetapi **tidak ditemukan** (hilang `Item ID` dan `Item Name`) pada file C5 yang diunggah, sistem otomatis mendeteksi item tersebut untuk **dihapus** (`DELETE_ITEM`) via GoFood V2 API (`DELETE /v2/menu_groups/{group_id}/menu_items/{item_id}`). |
| 📊 **Audit Trail** | Record Log Eksekusi | Mencatat detail lengkap perubahan yang berhasil maupun gagal ke database `AuditTrail`. |

---

## 🖥️ 3. Tampilan & Fitur Frontend (`MenuPushTab.jsx`)

* **Grid Kartu Ringkasan**:
  - `Store ID (SID)`: Jumlah toko dalam file C5 dan toko yang dipilih.
  - `Total Item C5`: Jumlah total baris item.
  - `Total Perubahan`: Jumlah item yang mengalami perubahan atribut.
  - `✨ Item Baru`: Jumlah item baru tanpa `item_id` yang akan ditambahkan.
  - `📂 Kat Baru`: Jumlah kategori baru yang akan dibuat.
  - `Harga (Price)`, `Nama Item`, `Kat / Foto / Desc`: Rincian statistik perubahan per kategori.
* **Spanduk Error Validasi Merah**:
  - Muncul di bagian atas jika terdapat bentrok nama kategori pada `Category ID` yang sama, lengkap dengan rincian baris dan instruksi perbaikannya.
* **Filter Mode Tab Interaktif**:
  - `Item Berubah`: Menampilkan hanya item yang mengalami perubahan.
  - `Semua Item`: Menampilkan seluruh baris item C5.
  - `✨ Item Baru`: Menampilkan item baru tanpa `item_id`.
  - `📂 Kategori Baru`: Menampilkan item yang berada di kategori baru.
  - `⚠️ Tidak Valid`: Menyoroti baris-baris item yang mengalami kesalahan validasi.
  - `Price Change`, `Nama Item`, `Kategori`, `Foto Link`, `Deskripsi`: Filter khusus per jenis atribut perubahan.
* **Tabel Pratinjau Perubahan**:
  - Kolom lengkap: `Store ID / Outlet`, `Kategori`, `Nama Item`, `Foto Link`, `Harga Baseline`, `New Fake Price`, `Status Perubahan`.
  - Badge visual khusus: `✨ Item Baru` (teal) dan `📂 Kat Baru` (indigo).

---

## ⚙️ 4. Arsitektur API Backend (`main.py` & `Gofood/GO/actions`)

### Endpoints
* **`POST /api/jobs/parse-c5`**:
  - Menerima file upload C5 `.xlsx`.
  - Mengurai lembar kerja `Item`.
  - Mengisi baseline dari `Gofood/API/menu-response-<SID>.json`.
  - Menjalankan validasi konsistensi `Category ID`.
  - Mengidentifikasi `is_new_item` (`tambah_item`) dan `is_new_category` (`new_categories`).
  - Mengembalikan struktur JSON berisi daftar store, parsed items, dan summary statistik.

* **`POST /api/jobs/push-c5`**:
  - Menerima payload `selected_sids` dan array item yang akan diperbarui/ditambahkan.
  - Membuat `Job` background dengan jenis `PUSH_UPDATE`.
  - Menjalankan fungsi `run_push_c5_job` -> `_push_c5_gofood_for_merchant`.

### Modul Otomasi GoFood (`Gofood/GO/actions/_menu_api.py`)
* `create_category`: Request `POST` ke `/v2/menu_groups/{group_id}/menus` untuk membuat kategori baru.
* `create_menu_item`: Request `POST` ke `/v2/menu_groups/{group_id}/menu_items` untuk membuat item menu baru.
* `update_menu_item`: Request `PATCH` ke `/v2/menu_groups/{group_id}/menus/{menu_id}` untuk rename kategori atau update item.
* Fallback `V1 PUT`: Request `PUT` ke `/v1/restaurants/{rest_uuid}/menu_items/{item_id}` jika V2 mengalami gangguan.

---

## 🔒 5. Keamanan & Penanganan Eror Rate Limit

1. **Platform Lock (`PLATFORM_LOCKS["gofood"]`)**: Memastikan hanya 1 job push GoFood yang berjalan bersamaan untuk mencegah konflik per Sesi.
2. **Exponential Backoff & Rate Limit (HTTP 429)**: Mengurangi kecepatan request secara otomatis dan jeda *cooldown* jika GoFood API membatasi kuota request.
3. **Session Auto-Refresh**: Jika token login GoFood kadaluarsa, runner otomatis memicu re-login via `login_gofood.py`.
