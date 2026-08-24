# LLM Council Transcript: Mematikan Ubah Harga pada Item Diskon/Promo (GoFood, GrabFood, ShopeeFood)

**Timestamp**: 1787362720  
**Date**: 2026-08-22  
**Question**: Bagaimana strategi, arsitektur, dan mitigasi terbaik untuk mematikan (lock/disable) pengubahan harga pada item menu yang sedang memiliki harga coret / promo aktif (slash price) di seluruh platform (GoFood, GrabFood, ShopeeFood)?

---

## 1. Framed Question
User ingin mengunci pengubahan harga pada item menu di GoFood, GrabFood, dan ShopeeFood yang sedang berada dalam status promo/slash price (harga coret aktif). Sistem saat ini memiliki:
- Frontend (`EditHargaTab.jsx`, `ShopeeEditHargaTab.jsx`) yang membaca flag `is_in_promo`.
- Endpoint parser catalog Excel (`/api/outlets/{outlet_id}/menu-items`) yang mendeteksi promo via kolom 'Sedang promo', pembandingan `original_price > price`, dan riwayat audit trail kegagalan promo.
- Background worker push harga (`run_push_price_job` dan `run_push_c5_job`).

Keputusan yang perlu diuji:
1. Di layer mana saja penguncian harus dipasang (Frontend UI, Backend Validator, Engine Push Worker)?
2. Bagaimana membedakan pengubahan harga murni vs update atribut C5 non-harga (nama, foto, kategori)?
3. Bagaimana menangani edge case (false positive promo, bulk adjust massal)?

---

## 2. Advisor Perspectives

### The Contrarian
Mengunci harga promo hanya di Frontend adalah ilusi keamanan. Jika endpoint backend (`/api/jobs/push-price` dan `/api/jobs/push-c5`) tidak memvalidasi ulang payload, script batch tetap bisa meloloskan request ke API aplikator. Akibatnya fatal: di Grab/Shopee, merubah base price pada item promo dapat membatalkan campaign promo secara sepihak atau melempar error status code `400/409` yang menggagalkan seluruh batch transaksi. Risiko terbesar adalah **False Positive Lock**: jika Excel catalog usang, user terkunci. Solusi: Sediakan sinkronisasi auto-pull atau peringatan jelas.

### The First Principles Thinker
Secara fundamental, "Harga Dasar" (Base Price) dan "Harga Promo" (Slash Price) adalah dua entitas data berbeda di portal merchant. Portal aplikator melarang mutasi harga dasar saat campaign aktif karena diskon dihitung berdasarkan harga dasar tersebut. Mengubah harga dasar merusak kalkulasi diskon yang sudah disetujui konsumen. Solusi prinsip dasar: Filter item promo di domain model backend dan UI — setiap item yang memiliki delta `original_price > price` atau flag promo aktif otomatis ditandai `is_in_promo = true` dan mutasi harga ditolak secara deterministik.

### The Expansionist
Fitur proteksi harga promo ini jangan hanya menjadi rem pasif (disabled input), tetapi terapkan **Partial Field Push**: jika harga dikunci karena promo pada C5 push, izinkan pembaruan nama menu, deskripsi, foto, dan kategori tetap berjalan sukses 100%, sementara pembaruan harga diskip secara transparan dengan status log `SKIPPED_ACTIVE_PROMO`.

### The Outsider
Bagi staf operasional resto, input harga yang abu-abu tanpa penjelasan memicu kebingungan. UI harus transparan: badge ungu "PROMO AKTIF", harga coret visual, dan tooltip penjelasan. Aksi bulk adjustment ("Ubah Semua Harga +Rp 2.000") wajib otomatis mengecualikan item-item promo ini.

### The Executor
Implementasi teknis ringkas dan zero-breaking-change:
1. **Frontend UI**: Kunci input harga satuan `disabled={item.is_in_promo}` & filter di fungsi bulk adjust.
2. **Backend Entrypoint (`main.py`)**: Filter mutasi harga pada item promo di worker push agar aman dari payload bypass.
3. **Audit Trail**: Catat log `SKIPPED_ACTIVE_PROMO` saat harga diskip.

---

## 3. Council Verdict & Action Plan

1. **Where the Council Agrees**:
   - Item dengan slash price / harga promo aktif wajib dikunci pengubahan harganya.
   - Bulk adjustment otomatis mengecualikan item promo.
   - Penguncian harus 2 arah: UI input disabled + Backend Push pre-filter.

2. **Where the Council Clashes**:
   - Bypass manual saat promo aktif: **Verdict Ditolak**, karena API aplikator tetap akan melempar error 400 jika base price diubah saat diskon berjalan.

3. **The One Thing to Do First**:
   - Pastikan flag `is_in_promo` mengunci input harga satuan dan bulk adjust di kedua komponen frontend (`EditHargaTab.jsx` & `ShopeeEditHargaTab.jsx`), serta pasang filter skip harga pada worker backend.
