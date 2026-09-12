#!/usr/bin/env bash
# ==============================================================================
# Script Setup & Migrasi ke Podman untuk Foodmaster (Menu-Prod)
# ==============================================================================
set -e

CURRENT_USER=$(whoami)
echo "🚀 Memulai penyiapan Podman untuk user: ${CURRENT_USER}..."

# 1. Pastikan paket Podman & Podman-Compose terinstal
if ! command -v podman &> /dev/null; then
    echo "📦 Menginstal podman dan podman-compose via apt..."
    sudo apt-get update
    sudo apt-get install -y podman podman-compose
else
    echo "✅ Podman sudah terinstal: $(podman --version)"
fi

# 2. Verifikasi SubUID & SubGID untuk rootless container
echo "🔍 Memeriksa konfigurasi subuid & subgid..."
if ! grep -q "^${CURRENT_USER}:" /etc/subuid 2>/dev/null; then
    echo "⚙️ Menambahkan alokasi SubUID/SubGID untuk ${CURRENT_USER}..."
    sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 "${CURRENT_USER}"
fi
echo "   SubUID: $(grep "^${CURRENT_USER}:" /etc/subuid 2>/dev/null || echo 'Belum terkonfigurasi')"
echo "   SubGID: $(grep "^${CURRENT_USER}:" /etc/subgid 2>/dev/null || echo 'Belum terkonfigurasi')"

# 3. Aktifkan Linger agar container tidak mati saat sesi SSH ditutup
echo "⚙️ Mengaktifkan loginctl lingering..."
sudo loginctl enable-linger "${CURRENT_USER}" 2>/dev/null || true

# 4. Validasi file konfigurasi docker-compose.yml dengan Podman
echo "🔍 Memvalidasi docker-compose.yml..."
if podman compose config > /dev/null 2>&1; then
    echo "✅ docker-compose.yml valid untuk Podman."
else
    echo "⚠️ Peringatan: podman compose config menghasilkan peringatan, namun tetap dapat dicoba saat build."
fi

echo ""
echo "=============================================================================="
echo "🎉 Penyiapan lingkungan Podman selesai!"
echo ""
echo "Langkah selanjutnya untuk migrasi container:"
echo "1. Hentikan container Docker lama:"
echo "   docker compose down"
echo ""
echo "2. Build dan jalankan dengan Podman:"
echo "   podman-compose up -d --build"
echo ""
echo "3. Cek status container:"
echo "   podman ps"
echo "   podman logs -f foodmaster-backend"
echo "=============================================================================="
