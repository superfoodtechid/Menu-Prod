# Council Transcript: Solusi Tombol Push & UX saat Edit Banyak Item di Single Edit Mode

**Timestamp:** 1787541965  
**Tanggal:** 24 Agustus 2026  
**Pertanyaan:** "apabila item pada single edit ada banyak pengguna pasti akan ribet ketika akan melakukan tombol push karena harus scroll ke atas lagi"

---

## Framed Question
Pada mode Single Edit (`itemEditMode === "single"`), user mengedit harga item langsung pada input field di masing-masing baris tabel menu. Ketika outlet memiliki puluhan atau ratusan item, user meng-scroll jauh ke bawah tabel saat mengedit item di baris akhir, lalu terpaksa scroll jauh ke atas untuk menjangkau tombol Push/Terapkan harga.  
Bagaimana arsitektur UX/UI dan interaksi tombol Push terbaik agar alur kerja efisien, tidak melelahkan (ergonomis), tetap aman dari salah klik, dan konsisten di seluruh platform (Grab/GoFood/ShopeeFood)?

---

## Advisor Responses

### The Contrarian
Memindahkan tombol push ke setiap baris atau membuat floating button sembarangan justru berbahaya dan menambah clutter visual. Tombol push adalah tindakan berisiko tinggi (mengubah harga langsung ke API merchant). Jika diletakkan terlalu dekat dengan baris input, user rentan misklik sebelum selesai memeriksa item lainnya.  
Solusinya bukan menghilangkan sentralisasi tombol push, melainkan membuat floating status bar yang *hanya muncul ketika ada dirty state* (ada perubahan harga belum tersimpan). Floating bar ini harus non-intrusif, mengambang di bawah layar, memuat counter perubahan, indikator pelanggaran harga batas (violation warning), dan tombol Push + Reset.

### The First Principles Thinker
Akar masalah: pemisahan spasial yang terlalu jauh antara lokasi aksi (tabel baris 50) dan tombol konfirmasi aksi (toolbar di paling atas).  
Tujuan user:  
1. Mengetahui berapa item yang sudah diubah.  
2. Memastikan tidak ada markup harga yang melanggar ketentuan aplikator.  
3. Menjalankan sinkronisasi/push dalam 1 klik dari posisi viewport mana pun tanpa kehilangan konteks.  
Maka, kontrol konfirmasi harus mengikuti posisi viewport user (sticky/docked) selama kondisi `totalChanges > 0`, dengan umpan balik visual jelas mengenai apa saja yang siap di-push.

### The Expansionist
Jadikan ini momen perbaikan UX menyeluruh:  
1. `StickyBottomBar` global yang melayang halus (backdrop blur) di bagian bawah layar saat `totalChanges > 0`.  
2. Tambahkan shortcut navigasi cepat: indikator pill "Lihat item yang diubah" yang bisa otomatis me-scroll dan highlight baris yang diedit jika user ingin review cepat sebelum push.  
3. Floating action bar ini sekaligus menampung quick action: hitungan perubahan, peringatan validasi markup, reset harga, dan tombol konfirmasi push.

### The Outsider
Sebagai pengguna awam, jika saya mengubah 10 item di paling bawah lalu tidak melihat tombol simpan di dekat saya, saya panik atau lupa apakah perubahan tersimpan atau belum.  
Di aplikasi modern (seperti e-commerce checkout bar atau form builder), ketika ada draft perubahan yang belum di-submit, bottom bar selalu menempel di bawah layar: "X item diubah [Batal] [Simpan & Push]". Jelas, tidak membingungkan, dan tidak peduli seberapa panjang tabelnya.

### The Executor
Implementasi paling efisien dan stabil:  
1. Komponen `StickyBottomBar.jsx` sudah ada di codebase (`web/src/components/shared/StickyBottomBar.jsx`), tinggal dipastikan terpasang aktif di layout utama `EditHargaTab.jsx` dan `ShopeeEditHargaTab.jsx`.  
2. Pastikan `StickyBottomBar` dipasang di luar scroll container agar tetap melayang di `fixed bottom-4 left-4 right-4 z-40`.  
3. Hubungkan props `totalChanges`, `violationCount`, `onOpenPush`, `onReset`, `pushing`, dan `theme` ("red" untuk Grab/Gojek, "orange" untuk ShopeeFood).  
4. Tambahkan padding bottom pada container tabel (`pb-24`) agar konten tabel paling bawah tidak tertutup oleh floating bar saat bar muncul.

---

## Peer Review Summary

- **Strongest Response:** The Executor & The First Principles Thinker. Memanfaatkan komponen native yang sudah ada (`StickyBottomBar`) meminimalkan dif dan langsung menyelesaikan akar masalah tanpa menambah kompleksitas arsitektur.
- **Biggest Blind Spot:** The Contrarian mengingatkan agar floating bar tidak menutupi baris tabel terbawah (memerlukan safe bottom padding).
- **All Missed Point:** Perlu penyesuaian warna tema yang konsisten antara GoFood/Grab (merah) dan ShopeeFood (oranye) serta penanganan mode batch vs single edit.

---

## Council Verdict

### 1. Where the Council Agrees
- Tombol push tidak boleh ditaruh per baris karena push adalah operasi batch berisiko tinggi.
- Kontrol aksi simpan/push harus selalu terlihat di viewport melalui floating sticky bottom bar ketika ada perubahan harga (`totalChanges > 0`).
- Safe padding bottom di area tabel wajib disediakan agar baris paling bawah tidak terhalang.

### 2. Where the Council Clashes
- Menambah floating table row highlight vs sticky bar sederhana. Kesimpulan: Sticky bar sederhana adalah solusi tercepat, paling bersih, dan minim bug.

### 3. Blind Spots the Council Caught
- Pengecekan overlap UI: saat sticky bar muncul, floating navigation atau modal konfirmasi tidak boleh bertabrakan dengan z-index bar.

### 4. The Recommendation
Integrasikan `StickyBottomBar` secara penuh di `EditHargaTab.jsx` dan `ShopeeEditHargaTab.jsx` untuk mode Single Edit maupun Multi Edit, dilengkapi counter perubahan, validasi pelanggaran, dan tombol trigger modal push.

### 5. The One Thing to Do First
Pasang dan verifikasi komponen `StickyBottomBar` di `EditHargaTab.jsx` dan `ShopeeEditHargaTab.jsx` dengan bottom padding yang cukup pada tabel view.
