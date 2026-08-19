import { useState, useEffect, useRef } from "react";
import PlatformBadge from "./PlatformBadge";

export default function MenuPushTab({ API_BASE_URL, API_SECRET_KEY }) {
  const [parsing, setParsing] = useState(false);
  const [parseResult, setParseResult] = useState(null);
  const [errorMsg, setErrorMsg] = useState("");

  // Platform selection (gofood / grab)
  const [targetPlatform, setTargetPlatform] = useState("gofood");

  // Multi-Select Store IDs (SID)
  const [selectedSids, setSelectedSids] = useState([]);

  // Table Filters
  const [filterMode, setFilterMode] = useState("changed"); // 'changed' | 'all' | 'price' | 'name' | 'category' | 'photo'
  const [searchQuery, setSearchQuery] = useState("");

  // Push Execution State
  const [triggering, setTriggering] = useState(false);
  const [activeJob, setActiveJob] = useState(null);
  const pollingRef = useRef(null);

  // Handle File Select & Upload to /api/jobs/parse-c5
  const handleFileUpload = async (uploadedFile) => {
    if (!uploadedFile) return;
    setParsing(true);
    setErrorMsg("");
    setParseResult(null);
    setSelectedSids([]);

    const formData = new FormData();
    formData.append("file", uploadedFile);

    try {
      const res = await fetch(`${API_BASE_URL}/api/jobs/parse-c5`, {
        method: "POST",
        headers: {
          "X-API-Key": API_SECRET_KEY || ""
        },
        body: formData
      });

      if (res.ok) {
        const data = await res.json();
        setParseResult(data);
        // Automatically select all detected SIDs by default
        if (data.stores && data.stores.length > 0) {
          setSelectedSids(data.stores.map((s) => s.sid));
        }
      } else {
        const errData = await res.json();
        setErrorMsg(errData.detail || "Gagal mengurai file Excel C5.");
      }
    } catch (err) {
      console.error("Error parsing C5 file:", err);
      setErrorMsg("Terjadi kesalahan jaringan saat mengunggah file C5.");
    } finally {
      setParsing(false);
    }
  };

  // Toggle Single Store ID (SID) selection
  const toggleSid = (sid) => {
    setSelectedSids((prev) =>
      prev.includes(sid) ? prev.filter((id) => id !== sid) : [...prev, sid]
    );
  };

  // Select All / Deselect All SIDs
  const toggleAllSids = () => {
    if (!parseResult || !parseResult.stores) return;
    if (selectedSids.length === parseResult.stores.length) {
      setSelectedSids([]);
    } else {
      setSelectedSids(parseResult.stores.map((s) => s.sid));
    }
  };

  // Poll active Job status
  useEffect(() => {
    if (!activeJob || ["SUCCESS", "FAILED"].includes(activeJob.status)) {
      if (pollingRef.current) clearInterval(pollingRef.current);
      return;
    }

    pollingRef.current = setInterval(async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/api/jobs/${activeJob.id}`, {
          headers: { "X-API-Key": API_SECRET_KEY || "" }
        });
        if (res.ok) {
          const updatedJob = await res.json();
          setActiveJob(updatedJob);
          if (["SUCCESS", "FAILED"].includes(updatedJob.status)) {
            clearInterval(pollingRef.current);
          }
        }
      } catch (err) {
        console.error("Error polling job status:", err);
      }
    }, 1500);

    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, [activeJob, API_BASE_URL, API_SECRET_KEY]);

  // Handle Trigger Push C5
  const handleTriggerPush = async () => {
    if (!parseResult || selectedSids.length === 0) return;

    if (parseResult.summary?.has_validation_errors) {
      alert("File C5 memiliki kesalahan validasi! Terdapat ketidakcocokan nama kategori untuk Category ID yang sama. Silakan perbaiki file C5 Anda.");
      return;
    }

    // Filter items belonging to selected SIDs that have changes
    const targetItems = parseResult.items.filter(
      (item) => selectedSids.includes(item.sid) && item.is_changed
    );

    if (targetItems.length === 0) {
      alert("Tidak ada perubahan item yang terdeteksi pada Store ID yang dipilih.");
      return;
    }

    setTriggering(true);
    setErrorMsg("");

    try {
      const res = await fetch(`${API_BASE_URL}/api/jobs/push-c5`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-API-Key": API_SECRET_KEY || ""
        },
        body: JSON.stringify({
          platform: targetPlatform,
          selected_sids: selectedSids,
          updates: targetItems.map((item) => ({
            sid: item.sid,
            outlet_name: item.outlet_name,
            item_id: item.item_id,
            category_id: item.category_id,
            category: item.category,
            item_name: item.item_name,
            item_name_new: item.item_name_new,
            photo_link: item.photo_link,
            current_fake_price: item.baseline_price,
            new_fake_price: item.new_fake_price,
            changes: item.change_types
          }))
        })
      });

      if (res.ok) {
        const job = await res.json();
        setActiveJob(job);
      } else {
        const errData = await res.json();
        setErrorMsg(errData.detail || "Gagal memicu push C5 GoFood.");
      }
    } catch (err) {
      console.error("Error triggering push C5:", err);
      setErrorMsg("Gagal terhubung ke server saat memicu Push GoFood.");
    } finally {
      setTriggering(false);
    }
  };

  // Filter items for table preview based on selected SIDs, filterMode, and search query
  const filteredItems = (parseResult?.items || []).filter((item) => {
    if (selectedSids.length > 0 && !selectedSids.includes(item.sid)) return false;

    if (filterMode === "changed" && !item.is_changed) return false;
    if (filterMode === "new_item" && !item.is_new_item) return false;
    if (filterMode === "new_category" && !item.is_new_category) return false;
    if (filterMode === "delete_item" && !item.is_deleted_item) return false;
    if (filterMode === "step_push" && !item.price_warning) return false;
    if (filterMode === "price" && !item.changes?.price_changed) return false;
    if (filterMode === "name" && !item.changes?.name_changed) return false;
    if (filterMode === "category" && !item.changes?.category_changed) return false;
    if (filterMode === "photo" && !item.changes?.photo_changed) return false;
    if (filterMode === "description" && !item.changes?.description_changed) return false;
    if (filterMode === "invalid" && item.is_valid !== false) return false;

    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const matchName = item.item_name?.toLowerCase().includes(q);
      const matchId = item.item_id?.toLowerCase().includes(q);
      const matchCat = item.category?.toLowerCase().includes(q);
      const matchStore = item.outlet_name?.toLowerCase().includes(q) || item.sid?.toLowerCase().includes(q);
      return matchName || matchId || matchCat || matchStore;
    }

    return true;
  });

  const fmtCurrency = (val) => {
    if (val === null || val === undefined || val === "") return "-";
    return `Rp ${Number(val).toLocaleString("id-ID")}`;
  };

  return (
    <main className="space-y-6">
      {/* Header Banner */}
      <div className="surface-card flex flex-col gap-4 p-6 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-4">
          <div className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl text-white shadow-lg transition-all ${
            targetPlatform === "grab"
              ? "bg-gradient-to-br from-emerald-600 to-green-800 shadow-emerald-900/20"
              : "bg-gradient-to-br from-red-600 to-red-800 shadow-red-900/20"
          } dark:from-zinc-800 dark:to-zinc-950 dark:border dark:border-zinc-700`}>
            <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
            </svg>
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-xl font-bold text-slate-900 dark:text-white">Menu Push C5</h2>
            </div>
            <p className="mt-0.5 text-[14px] text-slate-500 dark:text-zinc-400">
              Unggah file C5 (`.xlsx`), pilih cabang Store ID (`SID`), dan apply perubahan item menu.
            </p>
          </div>
        </div>

        {parseResult && (
          <button
            type="button"
            onClick={() => {
              setParseResult(null);
              setSelectedSids([]);
              setActiveJob(null);
            }}
            className="self-start rounded-xl border border-slate-200 bg-white px-4 py-2 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-200 dark:hover:bg-zinc-800 sm:self-auto"
          >
            ↺ Unggah File Baru
          </button>
        )}
      </div>

      {/* Upload Dropzone Section */}
      {!parseResult && (
        <section className="surface-card p-8 text-center">
          <div
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              if (e.dataTransfer.files && e.dataTransfer.files[0]) {
                handleFileUpload(e.dataTransfer.files[0]);
              }
            }}
            className="mx-auto flex max-w-2xl flex-col items-center justify-center rounded-3xl border-2 border-dashed border-red-200 bg-red-50/30 px-6 py-12 transition hover:border-red-400 dark:border-zinc-800 dark:bg-zinc-950/40"
          >
            <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-red-100 text-red-600 dark:bg-zinc-900 dark:text-red-400">
              <svg className="h-8 w-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 13h6m-3-3v6m5 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            </div>
            <h3 className="text-lg font-bold text-slate-900 dark:text-white">Pilih atau Seret File Excel C5 (`.xlsx`)</h3>
            <p className="mt-1 max-w-sm text-[14px] text-slate-500 dark:text-zinc-400">
              Sistem akan otomatis mengurai sheet `Item`, mendeteksi Store ID (`SID`), lalu membandingkan dengan data PULL terakhir untuk mendeteksi perubahan nama, harga, foto, & kategori.
            </p>

            <label className="mt-6 inline-flex cursor-pointer items-center gap-2 rounded-xl bg-red-700 px-5 py-2.5 text-sm font-semibold text-white shadow-md shadow-red-900/15 transition hover:bg-red-800 dark:bg-white dark:text-black dark:shadow-none">
              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
              </svg>
              <span>{parsing ? "Mengunggah & Mengurai..." : "Pilih File C5"}</span>
              <input
                type="file"
                accept=".xlsx,.xls"
                disabled={parsing}
                onChange={(e) => e.target.files?.[0] && handleFileUpload(e.target.files[0])}
                className="hidden"
              />
            </label>

            {parsing && (
              <div className="mt-4 flex items-center gap-2 text-xs font-semibold text-red-600 dark:text-red-400">
                <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                <span>Membaca sheet Item & mengekstrak Store ID...</span>
              </div>
            )}

            {errorMsg && (
              <div className="mt-4 rounded-xl border border-red-200 bg-red-50 p-3 text-xs font-bold text-red-700 dark:border-red-900 dark:bg-red-950/50 dark:text-red-400">
                ⚠️ {errorMsg}
              </div>
            )}
          </div>
        </section>
      )}

      {/* Parse Result & Multi-Select Store ID Panel */}
      {parseResult && (
        <div className="space-y-6">
          {/* Summary Cards — selalu tampil 3 utama, sisanya hanya jika > 0 */}
          {(() => {
            const s = parseResult.summary;
            const itemCount = (s.new_items_count || 0) + (s.name_changes || 0);
            const attrCount = (s.category_changes || 0) + (s.photo_changes || 0) + (s.description_changes || 0);

            const dynamicCards = [
              itemCount > 0 && {
                label: "Item", value: itemCount,
                sub: [s.new_items_count > 0 && `+${s.new_items_count} baru`, s.name_changes > 0 && `${s.name_changes} nama`].filter(Boolean).join(", "),
                cls: "border-slate-200/80 bg-white dark:border-zinc-800 dark:bg-zinc-900/80",
                valCls: "text-slate-900 dark:text-white",
                labelCls: "text-slate-400 dark:text-zinc-500",
                subCls: "text-slate-400 dark:text-zinc-500",
              },
              (s.new_categories_count || 0) > 0 && {
                label: "Kategori Baru", value: s.new_categories_count,
                sub: "Buat Kategori",
                cls: "border-slate-200/80 bg-white dark:border-zinc-800 dark:bg-zinc-900/80",
                valCls: "text-slate-900 dark:text-white",
                labelCls: "text-slate-400 dark:text-zinc-500",
                subCls: "text-slate-400 dark:text-zinc-500",
              },
              (s.deleted_items_count || 0) > 0 && {
                label: "Hapus Item", value: s.deleted_items_count,
                sub: "Tidak Ada di C5",
                cls: "border-rose-500/40 bg-rose-500/5 dark:border-rose-500/30 dark:bg-rose-500/10",
                valCls: "text-rose-600 dark:text-rose-400",
                labelCls: "text-rose-600 dark:text-rose-400",
                subCls: "text-rose-600/70 dark:text-rose-400/70",
              },
              (s.price_changes || 0) > 0 && {
                label: "Harga", value: s.price_changes,
                sub: "Harga Berubah",
                cls: "border-slate-200/80 bg-white dark:border-zinc-800 dark:bg-zinc-900/80",
                valCls: "text-slate-900 dark:text-white",
                labelCls: "text-slate-400 dark:text-zinc-500",
                subCls: "text-slate-400 dark:text-zinc-500",
              },
              (s.price_warning_count || 0) > 0 && {
                label: "Step Push", value: s.price_warning_count,
                sub: "Harga >15%",
                cls: "border-amber-500/40 bg-amber-500/5 dark:border-amber-500/30 dark:bg-amber-500/10",
                valCls: "text-amber-600 dark:text-amber-400",
                labelCls: "text-amber-600 dark:text-amber-400",
                subCls: "text-amber-600/70 dark:text-amber-400/70",
              },
              attrCount > 0 && {
                label: "Atribut", value: attrCount,
                sub: [s.category_changes > 0 && `${s.category_changes} kat`, s.photo_changes > 0 && `${s.photo_changes} foto`, s.description_changes > 0 && `${s.description_changes} desc`].filter(Boolean).join(", "),
                cls: "border-slate-200/80 bg-white dark:border-zinc-800 dark:bg-zinc-900/80",
                valCls: "text-slate-900 dark:text-white",
                labelCls: "text-slate-400 dark:text-zinc-500",
                subCls: "text-slate-400 dark:text-zinc-500",
              },
            ].filter(Boolean);

            return (
              <div className="flex flex-wrap gap-3">
                {/* 3 kartu tetap */}
                <div className="min-w-[110px] flex-1 rounded-xl border border-slate-200/80 bg-white p-3.5 shadow-xs dark:border-zinc-800 dark:bg-zinc-900/80">
                  <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400 dark:text-zinc-500">Store ID (SID)</p>
                  <p className="mt-1 text-xl font-extrabold text-slate-900 dark:text-white">{s.total_stores}</p>
                  <p className="mt-0.5 text-[11px] text-slate-400 dark:text-zinc-500">{selectedSids.length} Dipilih</p>
                </div>
                <div className="min-w-[110px] flex-1 rounded-xl border border-slate-200/80 bg-white p-3.5 shadow-xs dark:border-zinc-800 dark:bg-zinc-900/80">
                  <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400 dark:text-zinc-500">Total Item</p>
                  <p className="mt-1 text-xl font-extrabold text-slate-900 dark:text-white">{s.total_items}</p>
                  <p className="mt-0.5 text-[11px] text-slate-400 dark:text-zinc-500">Dalam C5</p>
                </div>
                <div className="min-w-[110px] flex-1 rounded-xl border border-amber-500/40 bg-amber-500/5 p-3.5 shadow-xs dark:border-amber-500/30 dark:bg-amber-500/10">
                  <p className="text-[10px] font-bold uppercase tracking-wider text-amber-600 dark:text-amber-400">Total Perubahan</p>
                  <p className="mt-1 text-xl font-extrabold text-amber-600 dark:text-amber-400">{s.total_changes}</p>
                  <p className="mt-0.5 text-[11px] text-amber-600/70 dark:text-amber-400/70">Terdeteksi</p>
                </div>

                {/* Kartu dinamis — hanya muncul jika > 0 */}
                {dynamicCards.map((card) => (
                  <div key={card.label} className={`min-w-[110px] flex-1 rounded-xl border p-3.5 shadow-xs ${card.cls}`}>
                    <p className={`text-[10px] font-bold uppercase tracking-wider ${card.labelCls}`}>{card.label}</p>
                    <p className={`mt-1 text-xl font-extrabold ${card.valCls}`}>{card.value}</p>
                    <p className={`mt-0.5 text-[11px] ${card.subCls}`}>{card.sub}</p>
                  </div>
                ))}
              </div>
            );
          })()}

          {/* Validation Error Alert Banner */}
          {parseResult.summary?.has_validation_errors && (
            <div className="rounded-2xl border-2 border-red-500 bg-red-50 p-5 shadow-sm dark:border-red-900 dark:bg-red-950/40">
              <div className="flex items-start gap-3">
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-red-600 text-white font-extrabold text-lg shadow-md shadow-red-900/20">
                  ⚠️
                </div>
                <div>
                  <h4 className="text-sm font-extrabold text-red-900 dark:text-red-200">
                    File C5 Tidak Valid: Terdapat Ketidakcocokan Nama Kategori pada Category ID yang Sama
                  </h4>
                  <ul className="mt-2 list-disc list-inside space-y-1 text-xs text-red-800 dark:text-red-300">
                    {parseResult.summary.validation_error_messages?.map((msg, idx) => (
                      <li key={idx} className="font-semibold">{msg}</li>
                    ))}
                  </ul>
                  <p className="mt-2.5 text-[11px] text-red-700 dark:text-red-400 font-medium">
                    💡 <strong>Syarat:</strong> Jika Anda ingin mengubah nama kategori, SELURUH baris item di file C5 yang terikat pada Category ID yang sama harus diubah dengan nama kategori yang identik.
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Multi-Select Store ID Section */}
          <section className="surface-card p-6">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between border-b border-slate-100 pb-4 dark:border-zinc-800">
              <div>
                <h3 className="text-base font-bold text-slate-900 dark:text-white">
                  Pilih Store ID (SID) untuk di-Push ke {targetPlatform === "grab" ? "GrabFood" : "GoFood"}
                </h3>
                <p className="mt-0.5 text-xs text-slate-500 dark:text-zinc-400">
                  File C5 ini berisi {parseResult.stores.length} Store ID. Centang store yang ingin Anda terapkan perubahannya.
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={toggleAllSids}
                  className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-semibold text-slate-700 transition hover:bg-slate-100 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-200 dark:hover:bg-zinc-800"
                >
                  {selectedSids.length === parseResult.stores.length ? "Batal Pilih Semua" : "Pilih Semua Store ID"}
                </button>
              </div>
            </div>

            <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {parseResult.stores.map((store) => {
                const isSelected = selectedSids.includes(store.sid);
                return (
                  <label
                    key={store.sid}
                    className={`flex cursor-pointer items-center justify-between rounded-2xl border p-4 transition ${isSelected
                        ? "border-red-300 bg-red-50/50 shadow-xs dark:border-red-800 dark:bg-red-950/20"
                        : "border-slate-200 bg-white hover:border-slate-300 dark:border-zinc-800 dark:bg-zinc-900"
                      }`}
                  >
                    <div className="flex items-center gap-3">
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => toggleSid(store.sid)}
                        className="h-4 w-4 rounded border-slate-300 text-red-600 focus:ring-red-500 dark:border-zinc-700"
                      />
                      <div>
                        <p className="text-xs font-bold text-slate-900 dark:text-white">{store.name}</p>
                        <p className="text-[11px] font-mono text-slate-400 dark:text-zinc-500">SID: {store.sid}</p>
                      </div>
                    </div>
                    <div className="text-right">
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-600 dark:bg-zinc-800 dark:text-zinc-300">
                        {store.item_count} item
                      </span>
                      {store.changed_count > 0 && (
                        <p className="mt-1 text-[10px] font-bold text-amber-600 dark:text-amber-400">
                          ⚡ {store.changed_count} berubah
                        </p>
                      )}
                    </div>
                  </label>
                );
              })}
            </div>
          </section>

          {/* Action & Status Tracker Panel */}
          <section className="surface-card p-6">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="text-lg font-bold text-slate-900 dark:text-white">Eksekusi Push Menu {targetPlatform === "grab" ? "GrabFood" : "GoFood"}</h3>
                  <PlatformBadge platform={targetPlatform} size="sm" />
                </div>
                <p className="mt-0.5 text-xs text-slate-500 dark:text-zinc-400">
                  Akan mendorong perubahan pada {selectedSids.length} Store ID yang dipilih ke portal {targetPlatform === "grab" ? "Grab Merchant" : "GoFood Merchant"}.
                </p>
              </div>

              <button
                type="button"
                onClick={handleTriggerPush}
                disabled={triggering || selectedSids.length === 0}
                className={`inline-flex items-center justify-center gap-2 rounded-xl px-6 py-3 text-sm font-bold text-white transition shadow-md ${selectedSids.length > 0 && !triggering
                    ? targetPlatform === "grab"
                      ? "bg-emerald-700 hover:bg-emerald-800 shadow-emerald-900/20 dark:bg-emerald-600 dark:hover:bg-emerald-500"
                      : "bg-red-700 hover:bg-red-800 shadow-red-900/20 dark:bg-white dark:text-black"
                    : "cursor-not-allowed bg-slate-300 text-slate-500 dark:bg-zinc-800 dark:text-zinc-600"
                  }`}
              >
                {triggering ? (
                  <>
                    <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    <span>Mengantrekan Push...</span>
                  </>
                ) : (
                  <>
                    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                    <span>Push Perubahan ke {targetPlatform === "grab" ? "GrabFood" : "GoFood"} ({selectedSids.length} Store ID)</span>
                  </>
                )}
              </button>
            </div>

            {/* Active Job Progress Tracker */}
            {activeJob && (
              <div className="mt-6 rounded-2xl border border-red-100 bg-red-50/40 p-5 dark:border-zinc-800 dark:bg-zinc-950/60">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="flex h-3 w-3 rounded-full bg-red-600 animate-ping" />
                    <span className="text-xs font-bold uppercase tracking-wider text-red-700 dark:text-red-400">
                      Status Push: {activeJob.status}
                    </span>
                  </div>
                  <span className="text-xs font-mono font-bold text-slate-600 dark:text-zinc-300">
                    {activeJob.progress_pct}%
                  </span>
                </div>

                <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-red-100 dark:bg-zinc-800">
                  <div
                    className="h-full bg-gradient-to-r from-red-600 to-red-500 transition-all duration-500 dark:from-red-500 dark:to-red-400"
                    style={{ width: `${activeJob.progress_pct}%` }}
                  />
                </div>

                <p className="mt-2 text-xs font-semibold text-slate-700 dark:text-zinc-300">
                  📍 {activeJob.current_step}
                </p>

                {activeJob.status === "SUCCESS" && (
                  <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-xs font-bold text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300">
                    🎉 Push Perubahan C5 {activeJob.payload?.platform === "grab" || targetPlatform === "grab" ? "GrabFood" : "GoFood"} Selesai
                    <p className="mt-1 font-normal text-emerald-700 dark:text-emerald-400">
                      {activeJob.result_metadata?.success_count ?? 0} item berhasil
                      {(activeJob.result_metadata?.fail_count ?? 0) > 0
                        ? `, ${activeJob.result_metadata.fail_count} gagal`
                        : ""}{" "}
                      pada {activeJob.result_metadata?.selected_sids?.length || 0} Store ID.
                    </p>
                  </div>
                )}

                {activeJob.status === "FAILED" && (
                  <div className="mt-4 rounded-xl border border-red-200 bg-red-50 p-4 text-xs font-bold text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">
                    Push Perubahan C5 {activeJob.payload?.platform === "grab" || targetPlatform === "grab" ? "GrabFood" : "GoFood"} Gagal
                    <p className="mt-1 font-normal text-red-700 dark:text-red-400">
                      {activeJob.current_step}
                    </p>
                  </div>
                )}
              </div>
            )}
          </section>

          {/* Table Filters & Search */}
          <section className="surface-card p-6">
            <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between border-b border-slate-100 pb-4 dark:border-zinc-800">
              <div className="flex flex-wrap items-center gap-1.5">
                {[
                  ["changed", "Item Berubah"],
                  ["all", "Semua Item"],
                  ["new_item", "Item Baru"],
                  ["new_category", "Kategori Baru"],
                  ["delete_item", "Hapus Item"],
                  ["step_push", "⚠️ >15% Step Push"],
                  ["invalid", "Tidak Valid"],
                  ["price", "Price Change"],
                  ["name", "Nama Item"],
                  ["category", "Kategori"],
                  ["photo", "Foto Link"],
                  ["description", "Deskripsi"]
                ].map(([mode, label]) => (
                  <button
                    key={mode}
                    type="button"
                    onClick={() => setFilterMode(mode)}
                    className={`rounded-xl px-3 py-1.5 text-xs font-bold transition ${filterMode === mode
                        ? "bg-slate-900 text-white dark:bg-white dark:text-black"
                        : mode === "invalid" && parseResult?.summary?.has_validation_errors
                          ? "bg-red-100 text-red-700 hover:bg-red-200 dark:bg-red-950/60 dark:text-red-300"
                          : "bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-zinc-800 dark:text-zinc-400 dark:hover:bg-zinc-700"
                      }`}
                  >
                    {label}
                  </button>
                ))}
              </div>

              <div className="relative min-w-[240px]">
                <input
                  type="text"
                  placeholder="Cari item, category, atau SID..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-full rounded-xl border border-slate-200 bg-slate-50 py-1.5 pl-9 pr-3 text-xs font-semibold text-slate-800 placeholder:text-slate-400 focus:outline-none dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-100"
                />
                <svg className="absolute left-3 top-2 h-4 w-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                </svg>
              </div>
            </div>

            {/* Change Preview Table */}
            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-50 text-[11px] font-bold uppercase tracking-wider text-slate-500 dark:bg-zinc-900 dark:text-zinc-400">
                  <tr>
                    <th className="px-4 py-3">Store ID / Outlet</th>
                    <th className="px-4 py-3">Kategori</th>
                    <th className="px-4 py-3">Nama Item</th>
                    <th className="px-4 py-3">Foto Link</th>
                    <th className="px-4 py-3">Harga Baseline</th>
                    <th className="px-4 py-3">New Fake Price</th>
                    <th className="px-4 py-3 text-center">Status Perubahan</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-zinc-800 font-medium">
                  {filteredItems.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="py-12 text-center text-slate-400 dark:text-zinc-500">
                        Tidak ada item C5 yang cocok dengan filter.
                      </td>
                    </tr>
                  ) : (
                    filteredItems.map((item, idx) => (
                      <tr
                        key={`${item.sid}-${item.item_id}-${idx}`}
                        className={`transition ${item.is_valid === false
                            ? "bg-red-50/70 hover:bg-red-100/60 dark:bg-red-950/20 dark:hover:bg-red-950/40"
                            : item.is_new_item
                              ? "bg-teal-50/40 hover:bg-teal-50/70 dark:bg-teal-950/20 dark:hover:bg-teal-950/40"
                              : item.is_changed
                                ? "bg-amber-50/30 hover:bg-amber-50/60 dark:bg-amber-950/10 dark:hover:bg-amber-950/20"
                                : "hover:bg-slate-50 dark:hover:bg-zinc-900/50"
                          }`}
                      >
                        <td className="px-4 py-3 font-semibold text-slate-900 dark:text-white">
                          <div>{item.outlet_name}</div>
                          <div className="text-[10px] font-mono text-slate-400">{item.sid}</div>
                        </td>
                        <td className="px-4 py-3 text-slate-700 dark:text-zinc-300">
                          {item.is_new_category ? (
                            <span className="font-semibold text-slate-900 dark:text-white">{item.category}</span>
                          ) : item.changes?.category_changed ? (
                            <div className="flex flex-col gap-0.5">
                              <span className="text-[10px] text-slate-400 line-through dark:text-zinc-500">{item.baseline_category || "-"}</span>
                              <span className="font-semibold text-slate-900 dark:text-white">{item.category}</span>
                            </div>
                          ) : (
                            <span>{item.category || "-"}</span>
                          )}
                        </td>
                        <td className="px-4 py-3 font-semibold text-slate-900 dark:text-white">
                          {item.is_new_item ? (
                            <span className="font-semibold text-slate-900 dark:text-white">{item.item_name_new || item.item_name}</span>
                          ) : item.changes?.name_changed ? (
                            <div className="flex items-center gap-1.5">
                              <span className="text-[11px] text-slate-400 line-through dark:text-zinc-500">{item.baseline_name || item.item_name}</span>
                              <span className="text-[10px] text-slate-400 dark:text-zinc-500">→</span>
                              <span className="font-semibold text-slate-900 dark:text-white">{item.item_name_new || item.item_name}</span>
                            </div>
                          ) : (
                            <span>{item.item_name}</span>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          {item.changes?.photo_changed ? (
                            <div className="flex flex-col gap-0.5 max-w-[160px]">
                              {item.baseline_photo && (
                                <span className="text-[10px] text-slate-400 line-through truncate" title={item.baseline_photo}>
                                  {item.baseline_photo}
                                </span>
                              )}
                              <a href={item.photo_link} target="_blank" rel="noreferrer" className="text-[11px] font-bold text-pink-600 hover:underline truncate" title={item.photo_link}>
                                📷 {item.photo_link}
                              </a>
                            </div>
                          ) : (
                            <span className="text-slate-500 truncate max-w-[140px] block" title={item.photo_link || "-"}>
                              {item.photo_link ? (typeof item.photo_link === "string" && item.photo_link.startsWith("http") ? "📷 Ada Link Foto" : item.photo_link) : "-"}
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-slate-600 dark:text-zinc-400">
                          {item.baseline_found && !item.is_new_item ? fmtCurrency(item.baseline_price) : <span className="text-[11px] text-slate-400 dark:text-zinc-500">Item Baru</span>}
                        </td>
                        <td className="px-4 py-3">
                          {item.changes?.price_changed || item.is_new_item ? (
                            <span className="rounded-md bg-emerald-100 px-2 py-0.5 font-extrabold text-emerald-800 border border-emerald-200 dark:bg-emerald-950/60 dark:text-emerald-300 dark:border-emerald-800">
                              {fmtCurrency(item.new_fake_price)}
                            </span>
                          ) : (
                            <span className="text-slate-400 dark:text-zinc-500">
                              {item.new_fake_price !== null && item.new_fake_price !== undefined ? fmtCurrency(item.new_fake_price) : "(Kosong)"}
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-center">
                          {item.is_valid === false ? (
                            <span title={item.validation_error} className="cursor-help rounded-md bg-red-500/10 border border-red-500/30 px-2 py-0.5 text-[10px] font-bold text-red-600 dark:text-red-400">
                              Tidak Valid
                            </span>
                          ) : item.is_changed ? (
                            <div className="flex flex-wrap items-center justify-center gap-1">
                              {item.is_new_item && (
                                <span className="rounded-md bg-teal-500/10 border border-teal-500/30 px-1.5 py-0.5 text-[10px] font-semibold text-teal-700 dark:text-teal-300">
                                  Item Baru
                                </span>
                              )}
                              {item.is_new_category && (
                                <span className="rounded-md bg-indigo-500/10 border border-indigo-500/30 px-1.5 py-0.5 text-[10px] font-semibold text-indigo-700 dark:text-indigo-300">
                                  Kat Baru
                                </span>
                              )}
                              {item.is_deleted_item && (
                                <span className="rounded-md bg-rose-500/10 border border-rose-500/30 px-1.5 py-0.5 text-[10px] font-semibold text-rose-700 dark:text-rose-300">
                                  Hapus Item
                                </span>
                              )}
                              {item.changes?.price_changed && !item.is_new_item && (
                                <span className="rounded-md bg-emerald-500/10 border border-emerald-500/30 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-700 dark:text-emerald-300">
                                  Price
                                </span>
                              )}
                              {item.price_warning && (
                                <span title={`Perubahan harga ${item.price_diff_percent}% (>15%). Akan di-push secara bertahap.`} className="rounded-md bg-amber-500/10 border border-amber-500/30 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700 dark:text-amber-300">
                                  ⚠️ &gt;15% Step Push
                                </span>
                              )}
                              {item.changes?.name_changed && !item.is_new_item && (
                                <span className="rounded-md bg-blue-500/10 border border-blue-500/30 px-1.5 py-0.5 text-[10px] font-semibold text-blue-700 dark:text-blue-300">
                                  Nama
                                </span>
                              )}
                              {item.changes?.category_changed && (
                                <span className="rounded-md bg-purple-100 px-1.5 py-0.5 text-[10px] font-bold text-purple-700 dark:bg-purple-900/50 dark:text-purple-300">
                                  Kategori
                                </span>
                              )}
                              {item.changes?.photo_changed && (
                                <span className="rounded-md bg-pink-100 px-1.5 py-0.5 text-[10px] font-bold text-pink-700 dark:bg-pink-900/50 dark:text-pink-300">
                                  Foto
                                </span>
                              )}
                              {item.changes?.description_changed && (
                                <span className="rounded-md bg-cyan-100 px-1.5 py-0.5 text-[10px] font-bold text-cyan-700 dark:bg-cyan-900/50 dark:text-cyan-300">
                                  Deskripsi
                                </span>
                              )}
                              {item.changes?.other_changed && (
                                <span className="rounded-md bg-slate-200 px-1.5 py-0.5 text-[10px] font-bold text-slate-700 dark:bg-zinc-800 dark:text-zinc-300">
                                  Lainnya
                                </span>
                              )}
                            </div>
                          ) : (
                            <span className="text-[11px] text-slate-400 dark:text-zinc-600">Tidak ada perubahan</span>
                          )}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      )}
    </main>
  );
}
