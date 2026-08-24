# Council Transcript: Pressure-Test Fitur Menu Push C5

**Timestamp:** 1787322742  
**Pertanyaan Asli:** "pressure-test menu push ini"

---

## Framed Question
Lakukan pengujian beban ekstrem, analisis kerentanan sistem, dan audit ketahanan (pressure-test) terhadap modul Menu Push C5 (GoFood & GrabFood, parsing Excel/GDrive, background execution job, API rate limits, multi-SID batching, dan fallback error handling). Di mana sistem ini akan patah saat skala produksi meningkat dan bagaimana mitigasinya?

---

## Advisor Responses

### Advisor 1: The Contrarian (Failure Modes & Edge Cases)
Titik rawan kritis:
1. **Memory Leak pada Headless Browser**: `_push_c5_gofood_for_merchant` membuka instance Playwright baru per merchant dalam perulangan SID. Jika user memilih 20 SID sekaligus dalam satu file C5, 20 browser context akan diluncurkan berturut-turut. Jika ada crash tak tertangkap, proses zombie Chromium akan memakan RAM server hingga OOM-kill.
2. **Kerapuhan Token Refresh di Tengah Batch**: Jika token GoFood kadaluarsa saat meng-update item ke-45 dari 100, sistem berisiko loop login berulang atau gagal massal pada item berikutnya tanpa auto-resume parsial yang mulus.
3. **Link GDrive Quota Exceeded**: Link Google Sheets publik yang diunduh berulang kali oleh banyak user secara paralel akan memicu captcha Google atau limit download Google Drive (HTTP 429).

### Advisor 2: The First Principles Thinker (Arsitektur & Integritas Data)
Esensi push menu adalah idempotensi dan atomisitas per item.
Saat ini audit trail dicatat di akhir, namun state push item di database belum memiliki snapshot checkpoint granular. Jika worker server restart/crash di tengah pengerjaan item ke-50, job berstatus FAILED tanpa penanda item mana yang sudah sukses masuk ke GoBiz dan mana yang belum. Solusi: Gunakan state checkpoint item-level (status per-item di database `AuditTrail` langsung di-commit realtime saat request API merchant berhasil).

### Advisor 3: The Expansionist (Skalabilitas & Volume Besar)
Jika sistem harus menangani 500 outlet secara bersamaan:
Kunci platform lock global `PLATFORM_LOCKS["gofood"]` saat ini membuat seluruh antrean push berjalan secara murni serial (*blocking FIFO*). Ini aman dari ban IP, tetapi menjadi bottleneck besar jika satu merchant butuh 3 menit (20 merchant = 1 jam tunggu). Push antartoko yang menggunakan kredensial/email berbeda seharusnya bisa berjalan paralel (sharded lock per account email, bukan per platform global).

### Advisor 4: The Outsider (User Experience & Resiliensi UI)
Di sisi frontend, jika koneksi internet terputus saat polling job atau saat proses download GDrive yang besar (>50MB), UI hanya menampilkan generic error tanpa opsi retry cerdas. UI juga perlu menampilkan item-level progress bar ("Mengupdate item 23/80: Ayam Goreng...") bukan hanya persen global agar operator tahu proses tidak hang.

### Advisor 5: The Executor (Perbaikan Segera & Proteksi Langsung)
Hal konkret yang wajib diperbaiki langsung:
1. Pastikan blok `try...finally` pada Playwright browser selalu memanggil `browser.close()` dan membunuh orphaned process `proc.kill()` agar tidak terjadi memory leak.
2. Batasi timeout download stream Google Drive maksimal 30 detik dengan batas ukuran file (misal max 15MB) untuk mencegah DoS server via link raksasa.
3. Tambahkan validasi header wajib (`Item Name Improvement` / `New Fake Price`) sebelum proses penguraian ratusan baris dimulai.

---

## Peer Review Summary

- **Strongest Point**: Peringatan Contrarian & Executor tentang pembersihan Playwright browser lifecycle dan mitigasi OOM pada multi-SID loop.
- **Blind Spot Caught**: Global Platform Lock vs Per-Account Sharding. Lock global membuat sistem sangat lambat jika ratusan outlet di-push bersamaan.

---

## Chairman Verdict

### Where the Council Agrees
1. Parsing engine & validasi C5 sudah sangat baik dan aman dari sisi logika perbandingan baseline.
2. Eksekusi Playwright dan session handling adalah area paling berisiko tinggi terhadap kebocoran resource memori (RAM/CPU) jika terjadi error di tengah jalan.
3. Status per-item harus dicatat seketika (realtime audit commit) agar jika terjadi kegagalan di tengah jalan, item yang sudah sukses tidak perlu di-push ulang.

### Where the Council Clashes
- *Global Platform Lock*: Apakah harus tetap global per platform atau dibuat per email akun.
- *Resolusi*: Tetap gunakan global lock untuk saat ini guna mencegah GoBiz rate-limiting IP server, lalu jadwalkan upgrade ke sharded email lock saat volume bertambah.

### The Recommendation
Fokuskan ketahanan sistem pada:
1. **Guaranteed Cleanup**: Pastikan Playwright browser selalu di-close secara agresif di block `finally`.
2. **Payload & Download Guard**: Validasi batas ukuran byte Google Drive (<20MB) dan timeout ketat.
3. **Realtime Item-Level Feedback**: Pastikan setiap item yang berhasil terupdate langsung disimpan di AuditTrail.

### The One Thing to Do First
Verifikasi dan perkuat blok pembersihan resource browser Playwright di `_push_c5_gofood_for_merchant` dan `run_push_c5_job` agar 100% aman dari proses zombie.
