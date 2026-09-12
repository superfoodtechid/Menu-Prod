#!/usr/bin/env bash
# ==============================================================================
# Script Setup & Migrasi ke Podman untuk Foodmaster (Menu-Prod)
# ==============================================================================
set -e

CURRENT_USER=$(whoami)
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "🚀 Memulai penyiapan Podman untuk user: ${CURRENT_USER} di ${PROJECT_DIR}..."

# 1. Pastikan paket Podman & Podman-Compose terinstal
if ! command -v podman &> /dev/null; then
    echo "📦 Menginstal podman dan podman-compose via apt..."
    sudo apt-get update
    sudo apt-get install -y podman podman-compose
else
    echo "✅ Podman sudah terinstal: $(podman --version)"
fi

# 2. Konfigurasi unqualified-search-registries agar 'docker.io' dikenali secara default
echo "⚙️ Memeriksa konfigurasi registry di /etc/containers/registries.conf..."
if ! grep -q 'unqualified-search-registries' /etc/containers/registries.conf 2>/dev/null || ! grep -q 'docker.io' /etc/containers/registries.conf 2>/dev/null; then
    echo "   Menambahkan docker.io ke unqualified-search-registries..."
    echo 'unqualified-search-registries = ["docker.io"]' | sudo tee -a /etc/containers/registries.conf > /dev/null
    echo "✅ Konfigurasi registry diperbarui."
else
    echo "✅ docker.io sudah terdaftar di registries.conf."
fi

# 3. Verifikasi SubUID & SubGID untuk rootless container
echo "🔍 Memeriksa konfigurasi subuid & subgid..."
if ! grep -q "^${CURRENT_USER}:" /etc/subuid 2>/dev/null; then
    echo "⚙️ Menambahkan alokasi SubUID/SubGID untuk ${CURRENT_USER}..."
    sudo usermod --add-subuids 100000-165535 --add-subgids 100000-165535 "${CURRENT_USER}"
fi
echo "   SubUID: $(grep "^${CURRENT_USER}:" /etc/subuid 2>/dev/null || echo 'Belum terkonfigurasi')"
echo "   SubGID: $(grep "^${CURRENT_USER}:" /etc/subgid 2>/dev/null || echo 'Belum terkonfigurasi')"

# 4. Aktifkan Linger agar container tidak mati saat sesi SSH ditutup
echo "⚙️ Mengaktifkan loginctl lingering..."
sudo loginctl enable-linger "${CURRENT_USER}" 2>/dev/null || true

# 5. Perbaiki kepemilikan file proyek dari bekas run Docker root
echo "⚙️ Memperbaiki kepemilikan file proyek untuk ${CURRENT_USER}..."
sudo chown -R "${CURRENT_USER}:${CURRENT_USER}" "${PROJECT_DIR}"
echo "✅ Izin file proyek diperbarui."

# 6. Validasi file konfigurasi docker-compose.yml dengan Podman
echo "🔍 Memvalidasi docker-compose.yml..."
cd "${PROJECT_DIR}"
if podman compose config > /dev/null 2>&1; then
    echo "✅ docker-compose.yml valid untuk Podman."
else
    echo "⚠️ Peringatan: podman compose config menghasilkan catatan, namun siap dicoba saat build."
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
