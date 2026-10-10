import { useState, useEffect, useRef, useMemo } from "react";
import PlatformBadge from "./PlatformBadge";

const TERMINAL_JOB_STATUSES = new Set(["SUCCESS", "FAILED", "CANCELLED"]);
const CHANGE_LABELS = {
  NEW_ITEM: "Item baru",
  NEW_CATEGORY: "Kategori baru",
  DELETE_ITEM: "Hapus item",
  PRICE_CHANGE: "Harga",
  PRICE_WARNING_STEP_PUSH: "Step push >15%",
  NAME_CHANGE: "Nama",
  CATEGORY_CHANGE: "Kategori",
  PHOTO_CHANGE: "Foto",
  DESCRIPTION_CHANGE: "Deskripsi",
  OTHER_CHANGE: "Atribut lain",
  INVALID_NEW_ITEM_PRICE: "Harga item baru tidak valid",
};

function friendlyPushError(rawMessage) {
  if (!rawMessage) return "Push item ini belum berhasil. Periksa datanya lalu coba lagi.";
  const raw = String(rawMessage);
  const lower = raw.toLowerCase();
  let message = raw;
  // GoFood often wraps its useful validation message in a JSON response body.
  for (let i = 0; i < 3; i += 1) {
    try {
      const parsed = JSON.parse(message);
      const validation = parsed?.validation_errors;
      const validationMessage = validation && Object.values(validation)
        .map((value) => typeof value === "string" ? value : value?.message)
        .find(Boolean);
      message = validationMessage || parsed?.errors?.[0]?.message || parsed?.message || parsed?.detail || message;
      if (typeof message !== "string") message = JSON.stringify(message);
    } catch {
      break;
    }
  }
  const detail = message.toLowerCase();

  if ((detail.includes("description") || lower.includes("validation_errors.description")) &&
      (detail.includes("kata") || detail.includes("tidak bisa") || detail.includes("not allowed"))) {
    return "Deskripsi ditolak oleh GoFood. Coba gunakan deskripsi makanan yang lebih sederhana, lalu push ulang.";
  }
  if (detail.includes("harga tidak bisa rp0") || detail.includes("price") && (detail.includes("zero") || detail.includes("must be greater"))) {
    return "Harga item belum valid. Isi harga lebih dari Rp0 di file C5 lalu coba lagi.";
  }
  if (detail.includes("sibuk") || detail.includes("try again") || detail.includes("1-2 jam")) {
    return "Layanan merchant sedang sibuk. Tunggu sebentar lalu coba push kembali.";
  }
  if (detail.includes("promo") || detail.includes("promotion")) {
    return "Item sedang mengikuti promo sehingga perubahan ini belum dapat diterapkan.";
  }
  if (detail.includes("401") || detail.includes("403") || detail.includes("unauthorized") || detail.includes("token invalid")) {
    return "Sesi akun merchant perlu diperbarui. Login kembali, lalu ulangi push.";
  }
  if (detail.includes("404") || detail.includes("not found") || detail.includes("tidak ditemukan")) {
    return "Item atau kategori tidak ditemukan di menu merchant. Tarik menu terbaru lalu periksa kembali file C5.";
  }
  if (detail.includes("timeout") || detail.includes("timed out") || detail.includes("connection")) {
    return "Koneksi ke layanan merchant terputus atau terlalu lama. Coba lagi beberapa saat.";
  }
  // Never show raw JSON, response bodies, or implementation exceptions to users.
  if (message !== raw || /\b(?:traceback|validation_errors|GOFOOD_ERROR|HTTP\s*\d{3}|status['\"]?\s*:)/i.test(raw)) {
    return "Layanan merchant menolak perubahan ini. Periksa data item di C5; jika masih gagal, hubungi admin.";
  }
  return message;
}

export default function MenuPushTab({ API_BASE_URL, API_SECRET_KEY }) {
  const [parsing, setParsing] = useState(false);
  const [parseResult, setParseResult] = useState(null);
  const [errorMsg, setErrorMsg] = useState("");

  // Target platform for Push ('gofood' | 'grab' | 'shopee')
  const [selectedPlatforms, setSelectedPlatforms] = useState(["gofood"]);

  // Multi-Select Store IDs (SID)
  const [selectedSids, setSelectedSids] = useState([]);

  // Structured Table Filters
  const [changeTypeFilter, setChangeTypeFilter] = useState("all"); // 'all' | 'changed' | 'new_item' | 'new_category' | 'delete_item' | 'step_push' | 'invalid'
  const [attributeFilter, setAttributeFilter] = useState("all"); // 'all' | 'price' | 'name' | 'category' | 'photo' | 'description'
  const [searchQuery, setSearchQuery] = useState("");

  // Pagination
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  // Modal Image Preview & Diff Preview
  const [previewImage, setPreviewImage] = useState(null); // { url, name, sid }
  const [diffModalItem, setDiffModalItem] = useState(null);
  const [reportDetailItem, setReportDetailItem] = useState(null);

  // Push Execution State
  const [triggering, setTriggering] = useState(false);
  const [activeJobs, setActiveJobs] = useState([]);
  const [confirmJobs, setConfirmJobs] = useState(null);
  const [confirmSearch, setConfirmSearch] = useState("");
  const [reportData, setReportData] = useState(null);
  const [reportOpen, setReportOpen] = useState(false);
  const [reportSearch, setReportSearch] = useState("");
  const [reportFilter, setReportFilter] = useState("all");
  const pollingRef = useRef(null);
  const pollingBusyRef = useRef(false);
  const reportedBatchRef = useRef(null);

  // Input Mode ('file' | 'drive')
  const [inputMode, setInputMode] = useState("file");
  const [driveUrl, setDriveUrl] = useState("");

  const normalizePlatform = (value) => String(value || "")
    .toLowerCase()
    .replace(/[^a-z]/g, "");

  const storeMatchesPlatform = (store, platform) => {
    const normalized = normalizePlatform(store?.baseline_platform);
    const aliases = {
      gofood: ["gofood", "go"],
      grab: ["grab", "grabfood"],
      shopee: ["shopee", "shopeefood"],
    };
    return (aliases[platform] || []).some((alias) => normalized === alias);
  };

  const visibleStores = useMemo(() => {
    if (!parseResult?.stores) return [];
    return parseResult.stores.filter((store) => selectedPlatforms.some((platform) => storeMatchesPlatform(store, platform)));
  }, [parseResult, selectedPlatforms]);

  const handlePlatformChange = (platform) => {
    setSelectedPlatforms((prev) => {
      const isSelected = prev.includes(platform);
      if (isSelected && parseResult?.stores) {
        const removedSids = new Set(parseResult.stores
          .filter((store) => storeMatchesPlatform(store, platform))
          .map((store) => store.sid));
        setSelectedSids((sids) => sids.filter((sid) => !removedSids.has(sid)));
      }
      return isSelected
        ? prev.filter((value) => value !== platform)
        : [...prev, platform];
    });
    setCurrentPage(1);
  };

  // Handle File or GDrive Parse
  const handleParse = async ({ uploadedFile = null, gdriveLink = null } = {}) => {
    const fileToUpload = uploadedFile;
    const linkToFetch = gdriveLink !== null ? gdriveLink : driveUrl;

    if (!fileToUpload && (!linkToFetch || !linkToFetch.trim())) {
      setErrorMsg("Harap pilih file Excel C5 atau masukkan link Google Drive / Sheets.");
      return;
    }

    setParsing(true);
    setErrorMsg("");
    setParseResult(null);
    setSelectedSids([]);
    setConfirmJobs(null);
    setActiveJobs([]);
    setReportData(null);
    setReportOpen(false);
    reportedBatchRef.current = null;
    setCurrentPage(1);

    const formData = new FormData();
    if (fileToUpload) {
      formData.append("file", fileToUpload);
    } else if (linkToFetch && linkToFetch.trim()) {
      formData.append("drive_url", linkToFetch.trim());
    }

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
        // Detect the platform from the first store, then select only its SIDs.
        if (data.stores && data.stores.length > 0) {
          const firstStore = data.stores[0];
          let detectedPlatform = "gofood";
          if (storeMatchesPlatform(firstStore, "grab")) detectedPlatform = "grab";
          else if (storeMatchesPlatform(firstStore, "shopee")) detectedPlatform = "shopee";
          setSelectedPlatforms([detectedPlatform]);
          setSelectedSids(data.stores
            .filter((store) => storeMatchesPlatform(store, detectedPlatform))
            .map((store) => store.sid));
        }
      } else {
        const errData = await res.json();
        setErrorMsg(errData.detail || "Gagal mengurai file C5.");
      }
    } catch (err) {
      console.error("Error parsing C5:", err);
      setErrorMsg("Terjadi kesalahan jaringan saat memproses file C5.");
    } finally {
      setParsing(false);
    }
  };

  const handleFileUpload = (uploadedFile) => {
    if (!uploadedFile) return;
    handleParse({ uploadedFile });
  };

  const toggleSid = (sid) => {
    setSelectedSids((prev) =>
      prev.includes(sid) ? prev.filter((id) => id !== sid) : [...prev, sid]
    );
  };

  const toggleAllSids = () => {
    if (!visibleStores.length) return;
    const visibleSidSet = new Set(visibleStores.map((store) => store.sid));
    const allVisibleSelected = visibleStores.every((store) => selectedSids.includes(store.sid));
    if (allVisibleSelected) {
      setSelectedSids((prev) => prev.filter((sid) => !visibleSidSet.has(sid)));
    } else {
      setSelectedSids((prev) => [
        ...prev,
        ...visibleStores.map((store) => store.sid).filter((sid) => !prev.includes(sid)),
      ]);
    }
  };

  const plannedJobs = useMemo(() => {
    if (!parseResult?.stores || !parseResult?.items) return [];
    return selectedPlatforms.map((platform) => {
      const platformStores = parseResult.stores.filter((store) => storeMatchesPlatform(store, platform));
      const selectedPlatformSids = platformStores.map((store) => store.sid).filter((sid) => selectedSids.includes(sid));
      const sidSet = new Set(selectedPlatformSids);
      const items = parseResult.items.filter((item) => sidSet.has(item.sid) && item.is_changed);
      return { platform, sids: selectedPlatformSids, items };
    }).filter((job) => job.sids.length > 0 && job.items.length > 0);
  }, [parseResult, selectedPlatforms, selectedSids]);

  const hasRunningJobs = activeJobs.some((job) => !TERMINAL_JOB_STATUSES.has(job.status));

  // Poll every job created by a multi-platform push.
  useEffect(() => {
    if (!activeJobs.length || activeJobs.every((job) => TERMINAL_JOB_STATUSES.has(job.status))) {
      if (pollingRef.current) clearInterval(pollingRef.current);
      return;
    }

    pollingRef.current = setInterval(async () => {
      if (pollingBusyRef.current) return;
      pollingBusyRef.current = true;
      try {
        const updates = await Promise.all(activeJobs.filter((job) => !TERMINAL_JOB_STATUSES.has(job.status)).map(async (job) => {
          const res = await fetch(`${API_BASE_URL}/api/jobs/${job.id}`, {
            headers: { "X-API-Key": API_SECRET_KEY || "" }
          });
          return res.ok ? await res.json() : job;
        }));
        const byId = new Map(updates.map((job) => [job.id, job]));
        setActiveJobs((previous) => previous.map((job) => byId.get(job.id) || job));
      } catch (err) {
        console.error("Error polling job status:", err);
      } finally {
        pollingBusyRef.current = false;
      }
    }, 1500);

    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, [activeJobs, API_BASE_URL, API_SECRET_KEY]);

  // Load the complete per-item audit for each finished job, including batches over 100 items.
  useEffect(() => {
    if (!activeJobs.length || !activeJobs.every((job) => TERMINAL_JOB_STATUSES.has(job.status))) return;
    const batchKey = activeJobs.map((job) => job.id).join("|");
    if (reportedBatchRef.current === batchKey) return;
    reportedBatchRef.current = batchKey;

    Promise.all(activeJobs.map(async (job) => {
      try {
        const res = await fetch(`${API_BASE_URL}/api/jobs/${job.id}/audit-trails`, {
          headers: { "X-API-Key": API_SECRET_KEY || "" }
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return { job, items: await res.json(), error: null };
      } catch (error) {
        return { job, items: [], error: `Laporan item belum dapat dimuat (${error.message}).` };
      }
    })).then((jobs) => {
      setReportData(jobs);
      setReportSearch("");
      setReportFilter("all");
      setReportOpen(true);
    });
  }, [activeJobs, API_BASE_URL, API_SECRET_KEY]);

  const handleOpenConfirmation = () => {
    if (parseResult?.summary?.has_validation_errors) {
      setErrorMsg("File C5 memiliki data yang tidak valid. Perbaiki semua kesalahan yang ditampilkan sebelum push.");
      return;
    }
    if (!plannedJobs.length) {
      setErrorMsg("Tidak ada perubahan item pada Store ID dan aplikator yang dipilih.");
      return;
    }
    setErrorMsg("");
    setConfirmSearch("");
    setConfirmJobs(plannedJobs);
  };

  // Handle Trigger Push C5
  const handleTriggerPush = async () => {
    const jobsToCreate = confirmJobs;
    if (!jobsToCreate?.length || triggering || hasRunningJobs) return;

    setConfirmJobs(null);
    setTriggering(true);
    setErrorMsg("");
    setReportData(null);
    setReportOpen(false);
    reportedBatchRef.current = null;

    try {
      const responses = await Promise.all(jobsToCreate.map(async ({ platform, sids, items }) => {
        try {
          const res = await fetch(`${API_BASE_URL}/api/jobs/push-c5`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-API-Key": API_SECRET_KEY || ""
            },
            body: JSON.stringify({
              platform,
              selected_sids: sids,
              updates: items.map((item) => ({
                sid: item.sid,
                outlet_name: item.outlet_name,
                item_id: item.item_id,
                category_id: item.category_id,
                category: item.category,
                item_name: item.item_name,
                item_name_new: item.item_name_new,
                baseline_name: item.baseline_name,
                baseline_category: item.baseline_category,
                baseline_photo: item.baseline_photo,
                baseline_description: item.baseline_description,
                photo_link: item.photo_link,
                description: item.description,
                current_fake_price: item.baseline_price,
                new_fake_price: item.new_fake_price,
                changes: item.change_types
              }))
            })
          });
          if (!res.ok) {
            const error = await res.json().catch(() => ({}));
            return { error: `${platform}: ${error.detail || "Gagal memicu push C5."}` };
          }
          return { job: await res.json() };
        } catch (error) {
          return { error: `${platform}: ${error.message || "Gagal terhubung ke server."}` };
        }
      }));
      const jobs = responses.filter((result) => result.job).map((result) => result.job);
      const errors = responses.filter((result) => result.error).map((result) => result.error);
      if (jobs.length) setActiveJobs(jobs);
      if (errors.length) setErrorMsg(errors.join(" · "));
    } catch (err) {
      console.error("Error triggering push C5:", err);
      setErrorMsg("Gagal terhubung ke server saat memicu Push C5.");
    } finally {
      setTriggering(false);
    }
  };

  // Filter items
  const filteredItems = useMemo(() => {
    if (!parseResult?.items) return [];

    return parseResult.items.filter((item) => {
      // 1. Filter by selected Store IDs
      if (selectedSids.length > 0 && !selectedSids.includes(item.sid)) return false;

      // 2. Filter by Change Type
      if (changeTypeFilter === "changed" && !item.is_changed) return false;
      if (changeTypeFilter === "offline_price" && !item.changes?.offline_price_changed) return false;
      if (changeTypeFilter === "new_item" && !item.is_new_item) return false;
      if (changeTypeFilter === "new_category" && !item.is_new_category) return false;
      if (changeTypeFilter === "delete_item" && !item.is_deleted_item) return false;
      if (changeTypeFilter === "step_push" && !item.price_warning) return false;
      if (changeTypeFilter === "invalid" && item.is_valid !== false) return false;

      // 3. Filter by Attribute
      if (attributeFilter === "price" && !item.changes?.price_changed) return false;
      if (attributeFilter === "name" && !item.changes?.name_changed) return false;
      if (attributeFilter === "category" && !item.changes?.category_changed) return false;
      if (attributeFilter === "photo" && !item.changes?.photo_changed) return false;
      if (attributeFilter === "description" && !item.changes?.description_changed) return false;
      if (attributeFilter === "offline_price" && !item.changes?.offline_price_changed) return false;

      // 4. Text Search
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchName = item.item_name?.toLowerCase().includes(q) || item.item_name_new?.toLowerCase().includes(q);
        const matchId = String(item.item_id || "").toLowerCase().includes(q);
        const matchCat = item.category?.toLowerCase().includes(q);
        const matchStore = item.outlet_name?.toLowerCase().includes(q) || item.sid?.toLowerCase().includes(q);
        return matchName || matchId || matchCat || matchStore;
      }

      return true;
    });
  }, [parseResult, selectedSids, changeTypeFilter, attributeFilter, searchQuery]);

  // Reset to first page when filters change
  useEffect(() => {
    setCurrentPage(1);
  }, [changeTypeFilter, attributeFilter, searchQuery, selectedSids, pageSize]);

  // Paginated items
  const paginatedItems = useMemo(() => {
    if (pageSize === 0) return filteredItems;
    const startIndex = (currentPage - 1) * pageSize;
    return filteredItems.slice(startIndex, startIndex + pageSize);
  }, [filteredItems, currentPage, pageSize]);

  const totalPages = pageSize === 0 ? 1 : Math.ceil(filteredItems.length / pageSize) || 1;

  // Items ready to push count
  const readyToPushCount = useMemo(() => {
    if (!parseResult?.items) return 0;
    const visibleSidSet = new Set(visibleStores.map((store) => store.sid));
    return parseResult.items.filter(
      (item) => visibleSidSet.has(item.sid) && selectedSids.includes(item.sid) && item.is_changed
    ).length;
  }, [parseResult, selectedSids, visibleStores]);

  const confirmationItems = confirmJobs?.flatMap((job) => job.items.map((item) => ({ ...item, platform: job.platform }))) || [];
  const confirmationCategoryCount = new Set(confirmationItems
    .filter((item) => item.is_new_category)
    .map((item) => `${item.sid}:${String(item.category || "").trim().toLocaleLowerCase("id-ID")}`)).size;
  const filteredConfirmationItems = confirmationItems.filter((item) => {
    const query = confirmSearch.trim().toLocaleLowerCase("id-ID");
    return !query || [item.item_name_new, item.item_name, item.category, item.sid, item.outlet_name]
      .some((value) => String(value || "").toLocaleLowerCase("id-ID").includes(query));
  });
  const reportItems = reportData?.flatMap(({ job, items }) => items.map((item) => ({
    ...item,
    platform: job.platform,
    job_id: job.id,
    selected_sids: job.result_metadata?.selected_sids || job.payload?.selected_sids || [],
  }))) || [];
  const reportSuccessCount = reportData?.reduce((sum, { job }) => sum + (job.result_metadata?.success_count || 0), 0) || 0;
  const reportFailCount = reportData?.reduce((sum, { job }) => sum + (job.result_metadata?.fail_count || 0), 0) || 0;
  const filteredReportItems = reportItems.filter((item) => {
    if (reportFilter !== "all" && item.status !== reportFilter) return false;
    const query = reportSearch.trim().toLocaleLowerCase("id-ID");
    return !query || [item.item_name, item.item_id, item.field_changed, item.platform]
      .some((value) => String(value || "").toLocaleLowerCase("id-ID").includes(query));
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
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-slate-900 text-white dark:bg-white dark:text-black">
            <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
            </svg>
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-bold text-slate-900 dark:text-white">Menu Push C5</h2>
              <span className="rounded-md bg-slate-100 px-2 py-0.5 text-[11px] font-semibold text-slate-600 dark:bg-zinc-800 dark:text-zinc-300">
                Otomasi Multi-Store
              </span>
            </div>
            <p className="mt-0.5 text-xs text-slate-500 dark:text-zinc-400">
              Unggah file C5 (.xlsx), verifikasi perbandingan menu per Store ID, dan terapkan perubahan ke portal aplikator.
            </p>
          </div>
        </div>

        {parseResult && (
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                setParseResult(null);
                setSelectedSids([]);
                setActiveJobs([]);
                setConfirmJobs(null);
                setReportData(null);
                setReportOpen(false);
                reportedBatchRef.current = null;
              }}
              disabled={hasRunningJobs || triggering}
              className="secondary-action text-xs disabled:cursor-not-allowed disabled:opacity-50"
            >
              Ganti File C5
            </button>
          </div>
        )}
      </div>

      {/* Upload Dropzone Section */}
      {!parseResult && (
        <section className="surface-card p-6 sm:p-8 text-center">
          {/* Segmented Mode Switcher */}
          <div className="mb-6 inline-flex rounded-xl bg-slate-100 p-1 dark:bg-zinc-900 border border-slate-200/80 dark:border-zinc-800">
            <button
              type="button"
              onClick={() => setInputMode("file")}
              className={`flex items-center gap-2 rounded-lg px-4 py-2 text-xs font-semibold transition-all ${
                inputMode === "file"
                  ? "bg-white text-slate-900 shadow-sm dark:bg-zinc-800 dark:text-white"
                  : "text-slate-500 hover:text-slate-800 dark:text-zinc-400 dark:hover:text-zinc-200"
              }`}
            >
              <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 13h6m-3-3v6m5 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
              <span>Upload File Excel (.xlsx)</span>
            </button>
            <button
              type="button"
              onClick={() => setInputMode("drive")}
              className={`flex items-center gap-2 rounded-lg px-4 py-2 text-xs font-semibold transition-all ${
                inputMode === "drive"
                  ? "bg-white text-slate-900 shadow-sm dark:bg-zinc-800 dark:text-white"
                  : "text-slate-500 hover:text-slate-800 dark:text-zinc-400 dark:hover:text-zinc-200"
              }`}
            >
              <svg className="h-4 w-4 text-emerald-600 dark:text-emerald-400" viewBox="0 0 24 24" fill="currentColor">
                <path d="M19.35 10.04C18.67 6.59 15.64 4 12 4 9.11 4 6.6 5.64 5.35 8.04 2.34 8.36 0 10.91 0 14c0 3.31 2.69 6 6 6h13c2.76 0 5-2.24 5-5 0-2.64-2.05-4.78-4.65-4.96zM19 18H6c-2.21 0-4-1.79-4-4 0-2.05 1.53-3.76 3.56-3.97l1.07-.11.5-.95C8.08 7.14 9.94 6 12 6c2.62 0 4.88 1.86 5.39 4.43l.3 1.5 1.53.11c1.56.1 2.78 1.41 2.78 2.96 0 1.65-1.35 3-3 3z" />
              </svg>
              <span>Link Google Drive / GSheets</span>
            </button>
          </div>

          {inputMode === "drive" ? (
            <div className="mx-auto flex max-w-xl flex-col items-center justify-center rounded-2xl border-2 border-dashed border-slate-200 bg-slate-50/50 px-6 py-10 dark:border-zinc-800 dark:bg-zinc-950/40">
              <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-emerald-50 text-emerald-600 dark:bg-zinc-900 dark:text-emerald-400">
                <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
                </svg>
              </div>
              <h3 className="text-sm font-bold text-slate-900 dark:text-white">Tempel Link Google Drive / Sheets C5</h3>
              <p className="mt-1 max-w-sm text-xs text-slate-500 dark:text-zinc-400">
                Pastikan akses link telah disetel agar dapat dibuka oleh siapa saja dengan link.
              </p>

              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  handleParse();
                }}
                className="mt-5 w-full max-w-md space-y-3"
              >
                <input
                  type="url"
                  value={driveUrl}
                  onChange={(e) => setDriveUrl(e.target.value)}
                  placeholder="https://docs.google.com/spreadsheets/d/..."
                  disabled={parsing}
                  required
                  className="field-control text-xs"
                />

                <button
                  type="submit"
                  disabled={parsing || !driveUrl.trim()}
                  className="primary-action w-full text-xs"
                >
                  {parsing ? "Mengunduh & Memproses C5..." : "Ambil & Pratinjau Perubahan"}
                </button>
              </form>
            </div>
          ) : (
            <div
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                if (e.dataTransfer.files && e.dataTransfer.files[0]) {
                  handleFileUpload(e.dataTransfer.files[0]);
                }
              }}
              className="mx-auto flex max-w-xl flex-col items-center justify-center rounded-2xl border-2 border-dashed border-slate-200 bg-slate-50/50 px-6 py-10 transition hover:border-slate-300 dark:border-zinc-800 dark:bg-zinc-950/40"
            >
              <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-slate-100 text-slate-600 dark:bg-zinc-900 dark:text-zinc-400">
                <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 13h6m-3-3v6m5 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
              </div>
              <h3 className="text-sm font-bold text-slate-900 dark:text-white">Pilih atau Tarik File Excel C5 (.xlsx)</h3>
              <p className="mt-1 max-w-sm text-xs text-slate-500 dark:text-zinc-400">
                Sistem akan membaca sheet Item, mendeteksi Store ID, dan membandingkannya dengan data katalog terkini.
              </p>

              <label className="mt-5 inline-flex cursor-pointer items-center gap-2 primary-action text-xs">
                <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                </svg>
                <span>{parsing ? "Memproses File..." : "Pilih File C5"}</span>
                <input
                  type="file"
                  accept=".xlsx,.xls"
                  disabled={parsing}
                  onChange={(e) => e.target.files?.[0] && handleFileUpload(e.target.files[0])}
                  className="hidden"
                />
              </label>

              {parsing && (
                <div className="mt-4 flex items-center gap-2 text-xs font-semibold text-slate-600 dark:text-zinc-400">
                  <svg className="h-4 w-4 animate-spin text-slate-800 dark:text-zinc-200" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  <span>Membaca sheet Item & mengekstrak perubahan...</span>
                </div>
              )}

              {errorMsg && (
                <div className="mt-4 rounded-xl border border-red-200 bg-red-50 p-3 text-xs font-semibold text-red-700 dark:border-red-900 dark:bg-red-950/50 dark:text-red-300">
                  {errorMsg}
                </div>
              )}
            </div>
          )}
          <p className="mx-auto mt-4 max-w-2xl text-xs text-slate-500 dark:text-zinc-400">
            Untuk foto Drive, tempel link folder Drive publik hanya pada kolom <strong>Photo Link</strong> di baris item. Nama file harus sama dengan nama item, misalnya <strong>Ayam Rica-Rica.jpg</strong>. Kolom link di atas khusus untuk file C5.
          </p>
        </section>
      )}

      {/* Parse Result & Multi-Select Store ID Panel */}
      {parseResult && (
        <div className="space-y-6">
          {/* Validation Error Alert Banner */}
          {parseResult.summary?.has_validation_errors && (
            <div className="rounded-xl border border-red-300 bg-red-50 p-4 shadow-sm dark:border-red-900/60 dark:bg-red-950/40">
              <div className="flex items-start gap-3">
                <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-red-600 text-white font-bold text-xs">
                  !
                </div>
                <div>
                  <h4 className="text-xs font-bold text-red-900 dark:text-red-200">
                    File C5 Tidak Valid: periksa data yang bermasalah
                  </h4>
                  <ul className="mt-1.5 list-disc list-inside space-y-0.5 text-xs text-red-800 dark:text-red-300">
                    {parseResult.summary.validation_error_messages?.map((msg, idx) => (
                      <li key={idx}>{msg}</li>
                    ))}
                  </ul>
                  <p className="mt-2 text-[11px] text-red-700 dark:text-red-400">
                    Perbaiki semua baris yang ditandai sebelum menjalankan push.
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Clean Metric Ribbon */}
          {(() => {
            const s = parseResult.summary || {};
            return (
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
                <div className="surface-card p-3.5">
                  <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400 dark:text-zinc-500">Store Terpilih</p>
                  <p className="mt-1 text-lg font-bold text-slate-900 dark:text-white">
                    {selectedSids.length} <span className="text-xs font-normal text-slate-400">/ {s.total_stores}</span>
                  </p>
                  <p className="text-[11px] text-slate-400">Store ID Aktif</p>
                </div>

                <div className="surface-card p-3.5">
                  <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400 dark:text-zinc-500">Total Item</p>
                  <p className="mt-1 text-lg font-bold text-slate-900 dark:text-white">{s.total_items}</p>
                  <p className="text-[11px] text-slate-400">Di seluruh C5</p>
                </div>

                <div className="surface-card p-3.5 border-amber-300 dark:border-amber-800/60 bg-amber-50/20 dark:bg-amber-950/10">
                  <p className="text-[10px] font-bold uppercase tracking-wider text-amber-700 dark:text-amber-400">Item Berubah</p>
                  <p className="mt-1 text-lg font-bold text-amber-700 dark:text-amber-300">{s.total_changes}</p>
                  <p className="text-[11px] text-amber-600/80 dark:text-amber-400/80">Perlu di-push</p>
                </div>

                <div className="surface-card p-3.5">
                  <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400 dark:text-zinc-500">Item Baru</p>
                  <p className="mt-1 text-lg font-bold text-teal-700 dark:text-teal-400">{s.new_items_count || 0}</p>
                  <p className="text-[11px] text-slate-400">Belum di katalog</p>
                </div>

                <div className="surface-card p-3.5">
                  <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400 dark:text-zinc-500">Update Harga</p>
                  <p className="mt-1 text-lg font-bold text-slate-900 dark:text-white">{s.price_changes || 0}</p>
                  <p className="text-[11px] text-slate-400">
                    {s.price_warning_count > 0 ? `${s.price_warning_count} step push` : "Perubahan harga"}
                  </p>
                </div>

                <div className="surface-card p-3.5">
                  <p className="text-[10px] font-bold uppercase tracking-wider text-slate-400 dark:text-zinc-500">Foto & Atribut</p>
                  <p className="mt-1 text-lg font-bold text-slate-900 dark:text-white">
                    {(s.photo_changes || 0) + (s.category_changes || 0) + (s.name_changes || 0)}
                  </p>
                  <p className="text-[11px] text-slate-400">
                    {s.photo_changes || 0} foto, {s.category_changes || 0} kat
                  </p>
                </div>
              </div>
            );
          })()}

          {/* Compact Store ID Grid (3 Columns) */}
          <section className="surface-card p-5">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between border-b border-slate-100 pb-3 dark:border-zinc-800">
              <div>
                <h3 className="text-sm font-bold text-slate-900 dark:text-white">
                  Pilih Store ID (SID) untuk Eksekusi Push
                </h3>
                <p className="text-xs text-slate-500 dark:text-zinc-400">
                  Centang Store ID yang ingin diterapkan perubahannya ({selectedSids.length} dari {visibleStores.length} dipilih).
                </p>
              </div>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={toggleAllSids}
                  className="secondary-action text-xs py-1.5 px-3"
                >
                  {visibleStores.length > 0 && visibleStores.every((store) => selectedSids.includes(store.sid))
                    ? "Batal Pilih Semua"
                    : "Pilih Semua Store ID"}
                </button>
              </div>
            </div>

            <div className="mt-3 grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
              {visibleStores.length === 0 ? (
                <p className="col-span-full rounded-xl border border-dashed border-slate-200 px-4 py-6 text-center text-xs text-slate-500 dark:border-zinc-800 dark:text-zinc-400">
                  Tidak ada Store ID untuk aplikator yang dipilih pada hasil parse ini.
                </p>
              ) : visibleStores.map((store) => {
                const isSelected = selectedSids.includes(store.sid);
                return (
                  <label
                    key={store.sid}
                    className={`flex cursor-pointer items-start justify-between rounded-xl border p-3 transition ${
                      isSelected
                        ? "border-slate-400 bg-slate-50/70 shadow-xs dark:border-zinc-600 dark:bg-zinc-800/40"
                        : "border-slate-200 bg-white hover:border-slate-300 dark:border-zinc-800 dark:bg-zinc-900/60"
                    }`}
                  >
                    <div className="flex items-start gap-2.5 min-w-0">
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => toggleSid(store.sid)}
                        className="mt-0.5 h-4 w-4 rounded border-slate-300 accent-slate-900 dark:border-zinc-700"
                      />
                      <div className="min-w-0">
                        <p className="text-xs font-bold text-slate-900 dark:text-white truncate" title={store.name}>
                          {store.name}
                        </p>
                        <p className="text-[11px] font-mono text-slate-400 dark:text-zinc-500 truncate">
                          {store.sid}
                        </p>
                        {store.baseline_found === false ? (
                          <span className="mt-1 inline-block rounded bg-amber-100 px-1.5 py-0.2 text-[9px] font-bold text-amber-800 dark:bg-amber-950/60 dark:text-amber-300">
                            No Baseline (Item Baru)
                          </span>
                        ) : (
                          store.baseline_file && (
                            <div className="mt-1 space-y-0.5">
                              <p className="text-[9.5px] font-mono text-slate-500 dark:text-zinc-400 truncate max-w-[190px]" title={store.baseline_file}>
                                📁 {store.baseline_file}
                              </p>
                              {store.baseline_pulled_at && (
                                <p className="text-[9px] text-slate-400 dark:text-zinc-500 truncate" title={`Waktu Tarik: ${store.baseline_pulled_at}`}>
                                  Tarikan: {store.baseline_pulled_at}
                                </p>
                              )}
                            </div>
                          )
                        )}
                      </div>
                    </div>

                    <div className="text-right shrink-0 ml-2">
                      <span className="inline-block rounded-md bg-slate-100 px-2 py-0.5 text-[10px] font-semibold text-slate-600 dark:bg-zinc-800 dark:text-zinc-300">
                        {store.item_count} item
                      </span>
                      {store.changed_count > 0 && (
                        <p className="mt-1 text-[10px] font-bold text-amber-600 dark:text-amber-400">
                          {store.changed_count} berubah
                        </p>
                      )}
                    </div>
                  </label>
                );
              })}
            </div>
          </section>

          {/* Action Bar (Push Execution) */}
          <section className="surface-card p-5 transition duration-200 hover:-translate-y-0.5 hover:border-slate-300 hover:shadow-lg dark:hover:border-zinc-700 dark:hover:shadow-zinc-950/40">
            {errorMsg && <div role="alert" className="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-xs font-semibold text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">{errorMsg}</div>}
            {(parseResult.summary?.photo_resolution_errors_count || 0) > 0 && (
              <div role="alert" className="mb-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300">
                {parseResult.summary.photo_resolution_errors_count} foto Drive belum ditemukan. Periksa nama file, izin akses folder, dan detail item sebelum push. Link folder tidak akan dikirim sebagai foto.
              </div>
            )}
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <div className="space-y-1.5">
                <div className="flex items-center gap-2">
                  <h3 className="text-sm font-bold text-slate-900 dark:text-white">Eksekusi Push Menu C5</h3>
                  {selectedPlatforms.map((platform) => <PlatformBadge key={platform} platform={platform} size="sm" />)}
                </div>

                {/* Target Platform Segmented Control */}
                <div className="flex items-center gap-1 pt-1">
                  <span className="text-xs text-slate-500 dark:text-zinc-400 mr-2">Target Platform:</span>
                  {[
                    ["gofood", "GoFood"],
                    ["grab", "GrabFood"],
                    ["shopee", "ShopeeFood"],
                  ].map(([pKey, pLabel]) => (
                    <button
                      key={pKey}
                      type="button"
                      onClick={() => handlePlatformChange(pKey)}
                      className={`rounded-lg px-2.5 py-1 text-xs font-semibold transition ${
                        selectedPlatforms.includes(pKey)
                          ? "bg-slate-900 text-white dark:bg-white dark:text-black"
                          : "bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-zinc-800 dark:text-zinc-400"
                      }`}
                    >
                      {pLabel}
                    </button>
                  ))}
                </div>

                <p className="text-xs text-slate-500 dark:text-zinc-400">
                  Akan mendorong perubahan pada <strong>{readyToPushCount} item</strong> dari <strong>{selectedSids.length} Store ID</strong> terpilih di <strong>{selectedPlatforms.length} aplikator</strong>.
                </p>
              </div>

              <div className="shrink-0">
                <button
                  type="button"
                  onClick={handleOpenConfirmation}
                  disabled={triggering || hasRunningJobs || parseResult?.summary?.has_validation_errors || selectedPlatforms.length === 0 || visibleStores.length === 0 || selectedSids.length === 0 || readyToPushCount === 0}
                  className="primary-action text-xs px-5 py-3 w-full sm:w-auto"
                >
                  {triggering ? (
                    <span className="flex items-center gap-2">
                      <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                      </svg>
                      <span>Mengantrekan Push...</span>
                    </span>
                  ) : (
                    <span>
                      Tinjau {readyToPushCount} Perubahan Sebelum Push
                    </span>
                  )}
                </button>
              </div>
            </div>

            {/* Active Job Progress Tracker */}
            {activeJobs.length > 0 && (
              <div className="mt-5 space-y-3">
                {activeJobs.map((job) => <div key={job.id} className="rounded-xl border border-slate-200 bg-slate-50/60 p-4 dark:border-zinc-800 dark:bg-zinc-900/40">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className={`h-2.5 w-2.5 rounded-full ${TERMINAL_JOB_STATUSES.has(job.status) ? "bg-slate-400" : "bg-emerald-500 animate-pulse"}`} />
                    <span className="text-xs font-bold uppercase tracking-wider text-slate-800 dark:text-zinc-200">
                      {job.platform}: {job.status}
                    </span>
                  </div>
                  <span className="text-xs font-mono font-bold text-slate-700 dark:text-zinc-300">
                    {job.progress_pct}%
                  </span>
                </div>

                <div className="mt-2.5 h-2 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-zinc-800">
                  <div
                    className="h-full bg-slate-900 transition-all duration-300 dark:bg-white"
                    style={{ width: `${job.progress_pct}%` }}
                  />
                </div>

                <p className="mt-2 text-xs font-medium text-slate-600 dark:text-zinc-300">
                  {job.status === "FAILED" ? friendlyPushError(job.error_message || job.current_step) : job.current_step}
                </p>

                {job.status === "SUCCESS" && (
                  <div className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-xs font-semibold text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300">
                    Push selesai: {job.result_metadata?.success_count ?? 0} item berhasil
                    {(job.result_metadata?.fail_count ?? 0) > 0
                      ? `, ${job.result_metadata.fail_count} gagal`
                      : ""}{" "}
                    pada {job.result_metadata?.selected_sids?.length || 0} Store ID.
                  </div>
                )}

                {job.status === "FAILED" && (
                  <div className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3 text-xs font-semibold text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">
                    Push belum berhasil: {friendlyPushError(job.error_message || job.current_step)}
                  </div>
                )}
                </div>)}
                {reportData && <button type="button" onClick={() => setReportOpen(true)} className="secondary-action text-xs">
                  Lihat Laporan per Item
                </button>}
              </div>
            )}
          </section>

          {/* Table Filters & Search */}
          <section className="surface-card p-5">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between border-b border-slate-100 pb-3 dark:border-zinc-800">
              {/* Filter Row 1: Change Types */}
              <div className="flex flex-wrap items-center gap-1.5">
                {[
                  ["all", `Semua Item (${parseResult?.items?.length || 0})`],
                  ["changed", `Ada Perubahan (${parseResult?.summary?.total_changes || 0})`],
                  ["offline_price", `Harga Offline (${parseResult?.summary?.offline_price_changes || 0})`],
                  ["new_item", `Item Baru (${parseResult?.summary?.new_items_count || 0})`],
                  ["new_category", `Kategori Baru (${parseResult?.summary?.new_categories_count || 0})`],
                  ["delete_item", `Hapus Item (${parseResult?.summary?.deleted_items_count || 0})`],
                  ["step_push", `Step Push >15% (${parseResult?.summary?.price_warning_count || 0})`],
                  ["invalid", `Tidak Valid (${parseResult?.summary?.validation_errors_count || 0})`],
                ].map(([mode, label]) => {
                  const isActive = changeTypeFilter === mode;
                  return (
                    <button
                      key={mode}
                      type="button"
                      onClick={() => setChangeTypeFilter(mode)}
                      className={`rounded-lg px-2.5 py-1.5 text-xs font-semibold transition ${
                        isActive
                          ? "bg-slate-900 text-white dark:bg-white dark:text-black"
                          : "bg-slate-100 text-slate-600 hover:bg-slate-200 dark:bg-zinc-800 dark:text-zinc-400 dark:hover:bg-zinc-700"
                      }`}
                    >
                      {label}
                    </button>
                  );
                })}
              </div>

              {/* Filter Row 2: Search & Attribute filter */}
              <div className="flex items-center gap-2">
                <select
                  value={attributeFilter}
                  onChange={(e) => setAttributeFilter(e.target.value)}
                  className="rounded-lg border border-slate-200 bg-white py-1.5 px-2.5 text-xs font-semibold text-slate-700 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200"
                >
                  <option value="all">Semua Atribut</option>
                  <option value="price">Hanya Perubahan Harga</option>
                  <option value="name">Hanya Perubahan Nama</option>
                  <option value="category">Hanya Perubahan Kategori</option>
                  <option value="photo">Hanya Perubahan Foto</option>
                  <option value="description">Hanya Perubahan Deskripsi</option>
                  <option value="offline_price">Hanya Perubahan Harga Offline</option>
                </select>

                <div className="relative min-w-[200px]">
                  <input
                    type="text"
                    placeholder="Cari item, SID, atau kategori..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="w-full rounded-lg border border-slate-200 bg-white py-1.5 pl-8 pr-3 text-xs text-slate-800 placeholder:text-slate-400 focus:outline-none dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
                  />
                  <svg className="absolute left-2.5 top-2 h-3.5 w-3.5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                  </svg>
                </div>
              </div>
            </div>

            {/* Table Header Info & Page Size */}
            <div className="mt-3 flex items-center justify-between text-xs text-slate-500 dark:text-zinc-400 px-1">
              <span>
                Menampilkan <strong>{filteredItems.length}</strong> item yang sesuai filter
              </span>
              <div className="flex items-center gap-2">
                <span>Per halaman:</span>
                <select
                  value={pageSize}
                  onChange={(e) => setPageSize(Number(e.target.value))}
                  className="rounded border border-slate-200 bg-white py-0.5 px-2 text-xs font-semibold text-slate-700 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200"
                >
                  <option value={25}>25</option>
                  <option value={50}>50</option>
                  <option value={100}>100</option>
                  <option value={0}>Semua</option>
                </select>
              </div>
            </div>

            {/* Change Preview Table */}
            <div className="mt-2.5 overflow-x-auto rounded-xl border border-slate-200 dark:border-zinc-800">
              <table className="w-full text-left text-xs border-collapse">
                <thead className="bg-slate-50 text-[11px] font-bold uppercase tracking-wider text-slate-600 border-b border-slate-200 dark:bg-zinc-900 dark:text-zinc-400 dark:border-zinc-800">
                  <tr>
                    <th className="px-3.5 py-2.5">Store ID / Outlet</th>
                    <th className="px-3.5 py-2.5">Kategori</th>
                    <th className="px-3.5 py-2.5">Nama Item</th>
                    <th className="px-3.5 py-2.5 text-center">Foto</th>
                    <th className="px-3.5 py-2.5">Harga Baseline</th>
                    <th className="px-3.5 py-2.5">Harga Baru (C5)</th>
                    <th className="px-3.5 py-2.5 text-center">Status Perubahan</th>
                    <th className="px-3.5 py-2.5 text-center">Perbandingan</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-zinc-800 font-medium">
                  {paginatedItems.length === 0 ? (
                    <tr>
                      <td colSpan={8} className="py-10 text-center text-slate-400 dark:text-zinc-500">
                        Tidak ada item yang cocok dengan filter.
                      </td>
                    </tr>
                  ) : (
                    paginatedItems.map((item, idx) => (
                      <tr
                        key={`${item.sid}-${item.item_id}-${idx}`}
                        className={`transition hover:bg-slate-50/70 dark:hover:bg-zinc-900/50 ${
                          item.is_valid === false
                            ? "bg-red-50/30 dark:bg-red-950/10"
                            : item.is_new_item
                            ? "bg-teal-50/20 dark:bg-teal-950/10"
                            : item.is_changed
                            ? "bg-amber-50/20 dark:bg-amber-950/10"
                            : item.changes?.offline_price_changed
                            ? "bg-sky-50/30 dark:bg-sky-950/10"
                            : ""
                        }`}
                      >
                        {/* Store ID / Outlet */}
                        <td className="px-3.5 py-2.5">
                          <div className="font-semibold text-slate-900 dark:text-white truncate max-w-[180px]" title={item.outlet_name}>
                            {item.outlet_name}
                          </div>
                          <div className="text-[10px] font-mono text-slate-400 dark:text-zinc-500">
                            {item.sid}
                          </div>
                        </td>

                        {/* Kategori */}
                        <td className="px-3.5 py-2.5 text-slate-700 dark:text-zinc-300">
                          {item.is_new_category ? (
                            <span className="font-semibold text-teal-700 dark:text-teal-300">{item.category || item.baseline_category || "-"}</span>
                          ) : item.changes?.category_changed ? (
                            <div className="flex flex-col gap-0.5">
                              <span className="text-[10px] text-slate-400 line-through dark:text-zinc-500">{item.baseline_category || "-"}</span>
                              <span className="font-semibold text-slate-900 dark:text-white">{item.category || item.baseline_category || "-"}</span>
                            </div>
                          ) : (
                            <span>{item.category || item.baseline_category || "-"}</span>
                          )}
                        </td>

                        {/* Nama Item */}
                        <td className="px-3.5 py-2.5">
                          {item.is_new_item ? (
                            <span className="font-semibold text-teal-700 dark:text-teal-300">
                              {item.item_name_new || item.item_name || item.baseline_name || "-"}
                            </span>
                          ) : item.changes?.name_changed ? (
                            <div className="flex flex-col gap-0.5">
                              <span className="text-[10px] text-slate-400 line-through dark:text-zinc-500">
                                {item.baseline_name || item.item_name || "-"}
                              </span>
                              <span className="font-semibold text-slate-900 dark:text-white">
                                {item.item_name_new || item.item_name || item.baseline_name || "-"}
                              </span>
                            </div>
                          ) : (
                            <span className="font-medium text-slate-800 dark:text-zinc-200">
                              {item.item_name || item.baseline_name || "-"}
                            </span>
                          )}
                        </td>

                        {/* Foto Thumbnail & Preview */}
                        <td className="px-3.5 py-2.5 text-center">
                          {item.photo_link && typeof item.photo_link === "string" && item.photo_link.startsWith("http") ? (
                            <div className="inline-flex items-center gap-1.5">
                              <button
                                type="button"
                                onClick={() => setPreviewImage({ url: item.photo_link, name: item.item_name, sid: item.sid })}
                                className="group relative h-9 w-9 overflow-hidden rounded-lg border border-slate-200 bg-slate-100 hover:border-slate-400 transition dark:border-zinc-700 dark:bg-zinc-800 shrink-0"
                                title="Klik untuk pratinjau gambar"
                              >
                                <img
                                  src={item.photo_link}
                                  alt={item.item_name}
                                  className="h-full w-full object-cover transition group-hover:scale-105"
                                  onError={(e) => {
                                    e.currentTarget.style.display = "none";
                                    e.currentTarget.parentElement.innerHTML = `<span class="text-[9px] text-slate-400 p-0.5 block leading-tight">Link</span>`;
                                  }}
                                />
                              </button>
                              {item.changes?.photo_changed && (
                                <span className="rounded bg-purple-100 px-1 py-0.2 text-[9px] font-bold text-purple-700 dark:bg-purple-950/60 dark:text-purple-300">
                                  Baru
                                </span>
                              )}
                            </div>
                          ) : (
                            <span className="text-slate-400 dark:text-zinc-600">-</span>
                          )}
                        </td>

                        {/* Harga Baseline */}
                        <td className="px-3.5 py-2.5 text-slate-600 dark:text-zinc-400 whitespace-nowrap">
                          {item.baseline_found && !item.is_new_item ? (
                            fmtCurrency(item.baseline_price)
                          ) : (
                            <span className="text-[11px] text-slate-400 dark:text-zinc-500">Item Baru</span>
                          )}
                        </td>

                        {/* Harga Baru (C5) */}
                        <td className="px-3.5 py-2.5 whitespace-nowrap">
                          {item.changes?.price_changed || item.is_new_item ? (
                            <div className="flex items-center gap-1.5">
                              <span className="font-bold text-slate-900 dark:text-white">
                                {fmtCurrency(item.new_fake_price)}
                              </span>
                              {item.price_diff_percent !== undefined && item.price_diff_percent !== null && (
                                <span
                                  className={`rounded px-1.5 py-0.2 text-[10px] font-bold ${
                                    item.price_warning
                                      ? "bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300"
                                      : "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300"
                                  }`}
                                  title={item.price_warning ? "Kenaikan harga > 15%" : "Perubahan harga"}
                                >
                                  {item.price_diff_percent > 0 ? `+${item.price_diff_percent}%` : `${item.price_diff_percent}%`}
                                </span>
                              )}
                            </div>
                          ) : (
                            <span className="text-slate-400 dark:text-zinc-500">
                              {item.new_fake_price !== null && item.new_fake_price !== undefined
                                ? fmtCurrency(item.new_fake_price)
                                : "-"}
                            </span>
                          )}
                        </td>

                        {/* Status Perubahan */}
                        <td className="px-3.5 py-2.5 text-center">
                          {item.is_valid === false ? (
                            <span className="rounded-md bg-red-100 px-2 py-0.5 text-[10px] font-bold text-red-700 dark:bg-red-950/60 dark:text-red-300" title={item.validation_error}>
                              Tidak Valid
                            </span>
                          ) : item.is_changed || item.changes?.offline_price_changed ? (
                            <div className="inline-flex flex-wrap items-center justify-center gap-1">
                              {item.is_new_item && (
                                <span className="rounded bg-teal-100 px-1.5 py-0.5 text-[10px] font-semibold text-teal-800 dark:bg-teal-950/60 dark:text-teal-300">
                                  Baru
                                </span>
                              )}
                              {item.is_new_category && (
                                <span className="rounded bg-indigo-100 px-1.5 py-0.5 text-[10px] font-semibold text-indigo-800 dark:bg-indigo-950/60 dark:text-indigo-300">
                                  Kat Baru
                                </span>
                              )}
                              {item.is_deleted_item && (
                                <span className="rounded bg-rose-100 px-1.5 py-0.5 text-[10px] font-semibold text-rose-800 dark:bg-rose-950/60 dark:text-rose-300">
                                  Hapus
                                </span>
                              )}
                              {item.changes?.price_changed && !item.is_new_item && (
                                <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300">
                                  Harga
                                </span>
                              )}
                              {item.price_warning && (
                                <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-800 dark:bg-amber-950/60 dark:text-amber-300" title="Kenaikan >15%">
                                  Step Push
                                </span>
                              )}
                              {item.changes?.name_changed && !item.is_new_item && (
                                <span className="rounded bg-blue-100 px-1.5 py-0.5 text-[10px] font-semibold text-blue-800 dark:bg-blue-950/60 dark:text-blue-300">
                                  Nama
                                </span>
                              )}
                              {item.changes?.photo_changed && (
                                <span className="rounded bg-purple-100 px-1.5 py-0.5 text-[10px] font-semibold text-purple-800 dark:bg-purple-950/60 dark:text-purple-300">
                                  Foto
                                </span>
                              )}
                              {item.changes?.category_changed && !item.is_new_category && (
                                <span className="rounded bg-indigo-100 px-1.5 py-0.5 text-[10px] font-semibold text-indigo-800 dark:bg-indigo-950/60 dark:text-indigo-300">
                                  Kategori
                                </span>
                              )}
                              {item.changes?.description_changed && (
                                <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-800 dark:bg-amber-950/60 dark:text-amber-300">
                                  Deskripsi
                                </span>
                              )}
                              {item.changes?.offline_price_changed && (
                                <span className="rounded bg-sky-100 px-1.5 py-0.5 text-[10px] font-semibold text-sky-800 dark:bg-sky-950/60 dark:text-sky-300">
                                  Harga Offline
                                </span>
                              )}
                            </div>
                          ) : (
                            <span className="text-[11px] text-slate-400 dark:text-zinc-600">Sama</span>
                          )}
                        </td>

                        {/* Perbandingan / Diff Action */}
                        <td className="px-3.5 py-2.5 text-center">
                          {item.is_changed || item.changes?.offline_price_changed ? (
                            <button
                              type="button"
                              onClick={() => setDiffModalItem(item)}
                              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-xs font-semibold text-slate-700 shadow-2xs hover:bg-slate-50 hover:border-slate-300 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-200 dark:hover:bg-zinc-700 transition"
                              title="Bandingkan rincian Sebelum vs Sesudah"
                            >
                              <svg className="h-3.5 w-3.5 text-slate-500 dark:text-zinc-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" />
                              </svg>
                              <span>Lihat Diff</span>
                            </button>
                          ) : (
                            <span className="text-[11px] text-slate-400 dark:text-zinc-600">-</span>
                          )}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            {/* Pagination Controls */}
            {pageSize > 0 && totalPages > 1 && (
              <div className="mt-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between text-xs text-slate-600 dark:text-zinc-400">
                <span>
                  Halaman <strong>{currentPage}</strong> dari <strong>{totalPages}</strong>
                </span>
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                    disabled={currentPage === 1}
                    className="secondary-action py-1 px-2.5 text-xs disabled:opacity-40"
                  >
                    Sebelumnya
                  </button>
                  {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                    let pageNum;
                    if (totalPages <= 5) {
                      pageNum = i + 1;
                    } else if (currentPage <= 3) {
                      pageNum = i + 1;
                    } else if (currentPage >= totalPages - 2) {
                      pageNum = totalPages - 4 + i;
                    } else {
                      pageNum = currentPage - 2 + i;
                    }
                    return (
                      <button
                        key={pageNum}
                        type="button"
                        onClick={() => setCurrentPage(pageNum)}
                        className={`h-7 w-7 rounded-lg text-xs font-semibold transition ${
                          currentPage === pageNum
                            ? "bg-slate-900 text-white dark:bg-white dark:text-black"
                            : "bg-slate-100 text-slate-700 hover:bg-slate-200 dark:bg-zinc-800 dark:text-zinc-300"
                        }`}
                      >
                        {pageNum}
                      </button>
                    );
                  })}
                  <button
                    type="button"
                    onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                    disabled={currentPage === totalPages}
                    className="secondary-action py-1 px-2.5 text-xs disabled:opacity-40"
                  >
                    Selanjutnya
                  </button>
                </div>
              </div>
            )}
          </section>
        </div>
      )}

      {confirmJobs && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-xs" role="presentation" onClick={() => setConfirmJobs(null)}>
          <div role="dialog" aria-modal="true" aria-labelledby="c5-confirm-title" className="surface-card flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden p-5 shadow-2xl" onClick={(event) => event.stopPropagation()}>
            <div className="flex items-start justify-between gap-4">
              <div>
                <h3 id="c5-confirm-title" className="text-lg font-bold text-slate-900 dark:text-white">Tinjau perubahan menu</h3>
                <p className="mt-1 text-xs text-slate-600 dark:text-zinc-400">
                  {confirmationItems.length} item pada {confirmJobs.reduce((sum, job) => sum + job.sids.length, 0)} Store ID · {confirmationCategoryCount} kategori baru · {confirmJobs.length} aplikator
                </p>
              </div>
              <button type="button" onClick={() => setConfirmJobs(null)} aria-label="Tutup konfirmasi" className="secondary-action px-2 py-1 text-sm">✕</button>
            </div>
            <p className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300">
              Periksa daftar ini sebelum push. Kategori baru dengan nama sama pada satu Store ID dibuat sekali, lalu dipakai oleh item terkait.
            </p>
            <input type="search" value={confirmSearch} onChange={(event) => setConfirmSearch(event.target.value)} placeholder="Cari nama item, kategori, atau Store ID" aria-label="Cari perubahan yang akan dipush" className="field-control mt-3 text-xs" />
            <div className="mt-3 min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
              {filteredConfirmationItems.length === 0 && <p className="p-6 text-center text-xs text-slate-500">Tidak ada item yang cocok dengan pencarian.</p>}
              {filteredConfirmationItems.map((item, index) => {
                const itemKey = `${item.platform}-${item.sid}-${item.item_id || item.item_name}-${item.row_number ?? index}`;
                return (
                  <button
                    key={itemKey}
                    type="button"
                    onClick={() => setDiffModalItem(item)}
                    className="flex w-full flex-wrap items-center justify-between gap-2 rounded-xl border border-slate-200 p-3 text-left transition-colors hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:border-zinc-800 dark:hover:bg-zinc-900/60"
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block text-xs font-bold text-slate-900 dark:text-white">{item.item_name_new || item.item_name || "Item tanpa nama"}</span>
                      <span className="mt-0.5 block text-[11px] text-slate-500 dark:text-zinc-400">{item.platform} · {item.sid} · {item.category || "Tanpa kategori"}</span>
                    </span>
                    <span className="flex flex-wrap items-center justify-end gap-1">
                      {(item.change_types || []).map((change) => <span key={change} className="rounded-md bg-slate-100 px-2 py-0.5 text-[10px] font-semibold text-slate-700 dark:bg-zinc-800 dark:text-zinc-200">{CHANGE_LABELS[change] || change}</span>)}
                      <span className="ml-1 rounded-md bg-slate-100 px-2 py-1 text-[10px] font-semibold text-slate-600 dark:bg-zinc-800 dark:text-zinc-300">Rincian</span>
                    </span>
                  </button>
                );
              })}
            </div>
            <div className="mt-4 flex flex-wrap justify-end gap-2 border-t border-slate-200 pt-4 dark:border-zinc-800">
              <button type="button" onClick={() => setConfirmJobs(null)} className="secondary-action text-xs">Batal</button>
              <button type="button" onClick={handleTriggerPush} disabled={triggering || hasRunningJobs} className="primary-action text-xs disabled:opacity-50">Ya, push {confirmationItems.length} item</button>
            </div>
          </div>
        </div>
      )}

      {reportOpen && reportData && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-xs" role="presentation" onClick={() => setReportOpen(false)}>
          <div role="dialog" aria-modal="true" aria-labelledby="c5-report-title" className="surface-card flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden p-5 shadow-2xl" onClick={(event) => event.stopPropagation()}>
            <div className="flex items-start justify-between gap-4">
              <div>
                <h3 id="c5-report-title" className="text-lg font-bold text-slate-900 dark:text-white">Laporan push menu</h3>
                <p className="mt-1 text-xs text-slate-600 dark:text-zinc-400">{reportSuccessCount} berhasil · {reportFailCount} gagal · {reportData.length} job selesai</p>
              </div>
              <button type="button" onClick={() => setReportOpen(false)} aria-label="Tutup laporan" className="secondary-action px-2 py-1 text-sm">✕</button>
            </div>
            {reportData.map(({ job, error }) => (error || job.status === "FAILED" || job.status === "CANCELLED") && (
              <p key={job.id} className="mt-3 rounded-lg border border-red-200 bg-red-50 p-3 text-xs text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">
                {job.platform}: {friendlyPushError(error || job.error_message || job.current_step || job.status)}
              </p>
            ))}
            <div className="mt-3 flex flex-wrap gap-2">
              <input type="search" value={reportSearch} onChange={(event) => setReportSearch(event.target.value)} placeholder="Cari item atau perubahan" aria-label="Cari laporan item" className="field-control min-w-[180px] flex-1 text-xs" />
              <select value={reportFilter} onChange={(event) => setReportFilter(event.target.value)} aria-label="Filter status laporan" className="field-control w-auto text-xs">
                <option value="all">Semua ({reportItems.length})</option>
                <option value="SUCCESS">Berhasil ({reportItems.filter((item) => item.status === "SUCCESS").length})</option>
                <option value="FAILED">Gagal ({reportItems.filter((item) => item.status === "FAILED").length})</option>
              </select>
            </div>
            <div className="mt-3 min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
              {filteredReportItems.length === 0 && <p className="p-6 text-center text-xs text-slate-500">{reportItems.length ? "Tidak ada item yang cocok dengan filter." : "Belum ada hasil per item untuk job ini."}</p>}
              {filteredReportItems.map((item) => (
                <button key={item.id} type="button" onClick={() => setReportDetailItem(item)} aria-label={`Lihat rincian ${item.item_name || "item"}`} className="w-full rounded-xl border border-slate-200 p-3 text-left transition-colors hover:border-slate-300 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:border-zinc-800 dark:hover:border-zinc-700 dark:hover:bg-zinc-900/60">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="text-xs font-bold text-slate-900 dark:text-white">{item.item_name || "Item tanpa nama"}</p>
                    <p className="mt-0.5 text-[11px] text-slate-500 dark:text-zinc-400">{item.platform} · {item.selected_sids.join(", ") || "Store ID tidak tersedia"} · {item.item_id || "Item baru"}</p>
                    </div>
                    <span className={`rounded-md px-2 py-0.5 text-[10px] font-bold ${item.status === "SUCCESS" ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300" : "bg-red-100 text-red-800 dark:bg-red-950/50 dark:text-red-300"}`}>{item.status === "SUCCESS" ? "Berhasil" : "Gagal"}</span>
                  </div>
                  <p className="mt-1 text-[11px] text-slate-600 dark:text-zinc-300">{String(item.field_changed || "").split(", ").map((change) => CHANGE_LABELS[change] || change).join(", ")}</p>
                  {item.error_message && <p className="mt-1 text-[11px] text-red-700 dark:text-red-300">{friendlyPushError(item.error_message)}</p>}
                  <p className="mt-2 text-[10px] font-semibold text-blue-700 dark:text-blue-300">Klik untuk melihat rincian</p>
                </button>
              ))}
            </div>
            <div className="mt-4 flex justify-end border-t border-slate-200 pt-4 dark:border-zinc-800">
              <button type="button" onClick={() => setReportOpen(false)} className="secondary-action text-xs">Tutup laporan</button>
            </div>
          </div>
        </div>
      )}

      {reportDetailItem && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/70 p-4 backdrop-blur-xs" role="presentation" onClick={() => setReportDetailItem(null)}>
          <div role="dialog" aria-modal="true" aria-labelledby="c5-report-detail-title" className="surface-card w-full max-w-xl overflow-hidden p-5 shadow-2xl" onClick={(event) => event.stopPropagation()}>
            <div className="flex items-start justify-between gap-4 border-b border-slate-200 pb-3 dark:border-zinc-800">
              <div className="min-w-0">
                <h3 id="c5-report-detail-title" className="text-base font-bold text-slate-900 dark:text-white">Rincian hasil push</h3>
                <p className="mt-1 text-xs text-slate-500 dark:text-zinc-400">{reportDetailItem.item_name || "Item tanpa nama"} · {reportDetailItem.platform}</p>
              </div>
              <button type="button" onClick={() => setReportDetailItem(null)} aria-label="Tutup rincian" className="secondary-action px-2 py-1 text-sm">✕</button>
            </div>
            <div className="mt-4 space-y-3 text-xs">
              <div className="flex flex-wrap gap-x-5 gap-y-2 text-slate-600 dark:text-zinc-300">
                <span>Store ID: <strong className="font-mono">{reportDetailItem.selected_sids.join(", ") || "-"}</strong></span>
                <span>Item ID: <strong className="font-mono">{reportDetailItem.item_id || "Item baru"}</strong></span>
                <span>Perubahan: <strong>{String(reportDetailItem.field_changed || reportDetailItem.change_type || "-").split(", ").map((change) => CHANGE_LABELS[change] || change).join(", ")}</strong></span>
                <span>Status: <strong className={reportDetailItem.status === "SUCCESS" ? "text-emerald-700 dark:text-emerald-300" : "text-red-700 dark:text-red-300"}>{reportDetailItem.status === "SUCCESS" ? "Berhasil" : "Gagal"}</strong></span>
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 dark:border-zinc-800 dark:bg-zinc-900/50">
                  <p className="text-[10px] font-bold uppercase tracking-wide text-slate-500 dark:text-zinc-400">Sebelum</p>
                  <p className="mt-1 break-words text-slate-800 dark:text-zinc-200">{reportDetailItem.old_value ?? "(Kosong / item baru)"}</p>
                </div>
                <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 dark:border-zinc-800 dark:bg-zinc-900/50">
                  <p className="text-[10px] font-bold uppercase tracking-wide text-slate-500 dark:text-zinc-400">Sesudah</p>
                  <p className="mt-1 break-words text-slate-800 dark:text-zinc-200">{reportDetailItem.new_value ?? "-"}</p>
                </div>
              </div>
              {reportDetailItem.error_message && <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300"><p className="font-bold">Keterangan</p><p className="mt-1">{friendlyPushError(reportDetailItem.error_message)}</p></div>}
              <p className="text-[10px] text-slate-400 dark:text-zinc-500">Job: <span className="font-mono">{reportDetailItem.job_id}</span></p>
            </div>
            <div className="mt-4 flex justify-end border-t border-slate-200 pt-3 dark:border-zinc-800">
              <button type="button" onClick={() => setReportDetailItem(null)} className="secondary-action text-xs">Tutup</button>
            </div>
          </div>
        </div>
      )}

      {/* Modal Image Preview */}
      {previewImage && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-xs"
          onClick={() => setPreviewImage(null)}
        >
          <div
            className="surface-card relative max-w-lg w-full overflow-hidden p-5 shadow-2xl animate-scale-up"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-slate-100 pb-3 dark:border-zinc-800">
              <div className="min-w-0 pr-4">
                <h4 className="text-sm font-bold text-slate-900 dark:text-white truncate">
                  {previewImage.name}
                </h4>
                <p className="text-[11px] font-mono text-slate-400 dark:text-zinc-500">
                  Store ID: {previewImage.sid}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setPreviewImage(null)}
                className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-zinc-800 dark:hover:text-white"
              >
                <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <div className="mt-4 flex items-center justify-center overflow-hidden rounded-xl bg-slate-100 dark:bg-zinc-950 max-h-[380px]">
              <img
                src={previewImage.url}
                alt={previewImage.name}
                className="max-h-[380px] w-auto object-contain"
              />
            </div>

            <div className="mt-4 flex items-center justify-between pt-1">
              <a
                href={previewImage.url}
                target="_blank"
                rel="noreferrer"
                className="text-xs font-semibold text-slate-600 hover:text-slate-900 dark:text-zinc-400 dark:hover:text-white underline"
              >
                Buka Gambar di Tab Baru
              </a>
              <button
                type="button"
                onClick={() => setPreviewImage(null)}
                className="secondary-action text-xs py-1.5 px-4"
              >
                Tutup
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Side-by-Side Diff Modal (Sebelum vs Sesudah) */}
      {diffModalItem && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-xs overflow-y-auto"
          onClick={() => setDiffModalItem(null)}
        >
          <div
            className="surface-card relative max-w-3xl w-full my-8 overflow-hidden p-6 shadow-2xl animate-scale-up max-h-[90vh] flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div className="flex items-start justify-between border-b border-slate-100 pb-4 dark:border-zinc-800 shrink-0">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <h4 className="text-base font-bold text-slate-900 dark:text-white">
                    {diffModalItem.is_new_item ? "Rincian Item Baru" : "Perbandingan Sebelum dan Sesudah"}
                  </h4>
                  {diffModalItem.is_new_item ? (
                    <span className="rounded bg-teal-100 px-2 py-0.5 text-[10px] font-bold text-teal-800 dark:bg-teal-950/60 dark:text-teal-300">
                      Item Baru
                    </span>
                  ) : diffModalItem.is_deleted_item ? (
                    <span className="rounded bg-rose-100 px-2 py-0.5 text-[10px] font-bold text-rose-800 dark:bg-rose-950/60 dark:text-rose-300">
                      Hapus Item
                    </span>
                  ) : (
                    <span className="rounded bg-amber-100 px-2 py-0.5 text-[10px] font-bold text-amber-800 dark:bg-amber-950/60 dark:text-amber-300">
                      Item Diperbarui
                    </span>
                  )}
                </div>
                <p className="text-xs text-slate-500 dark:text-zinc-400">
                  {diffModalItem.outlet_name} · Store ID: <span className="font-mono">{diffModalItem.sid}</span> · Item ID: <span className="font-mono">{diffModalItem.item_id || "-"}</span>
                </p>
              </div>

              <button
                type="button"
                onClick={() => setDiffModalItem(null)}
                className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-zinc-800 dark:hover:text-white"
              >
                <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Scrollable Content Body */}
            <div className="overflow-y-auto pr-1 mt-4 space-y-4">
              {/* Side-by-Side 2 Column Comparison Grid */}
              <div className={`grid grid-cols-1 gap-4 ${diffModalItem.is_new_item ? "" : "md:grid-cols-2"}`}>
                {/* Kolom Kiri: SEBELUM */}
                {!diffModalItem.is_new_item && (
                  <div className="rounded-xl border border-slate-200 bg-slate-50/60 p-4 dark:border-zinc-800 dark:bg-zinc-900/40">
                  <div className="flex items-center justify-between border-b border-slate-200 pb-2 dark:border-zinc-800 mb-3">
                    <div>
                      <span className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-zinc-400">
                        Sebelum (Baseline Portal)
                      </span>
                      {diffModalItem.baseline_pulled_at && (
                        <p className="text-[10px] text-slate-400 dark:text-zinc-500 mt-0.5" title="Waktu menu aktif ditarik dari aplikator">
                          Ditarik: {diffModalItem.baseline_pulled_at}
                        </p>
                      )}
                    </div>
                    <div className="text-right">
                      <span className="text-[10px] rounded bg-slate-200/80 px-1.5 py-0.5 font-medium text-slate-600 dark:bg-zinc-800 dark:text-zinc-400">
                        Kondisi Aktif
                      </span>
                      {diffModalItem.baseline_file && (
                        <p className="text-[9.5px] font-mono text-slate-400 dark:text-zinc-500 mt-0.5 truncate max-w-[150px]" title={diffModalItem.baseline_file}>
                          {diffModalItem.baseline_file}
                        </p>
                      )}
                    </div>
                  </div>

                  <div className="space-y-3 text-xs">
                    <div>
                      <span className="text-[11px] font-semibold text-slate-400 dark:text-zinc-500 block">Nama Hidangan</span>
                      <p className="font-medium text-slate-800 dark:text-zinc-200 mt-0.5">
                        {diffModalItem.baseline_name || <em className="text-slate-400 font-normal">(Tidak ada di baseline / Item Baru)</em>}
                      </p>
                    </div>

                    <div>
                      <span className="text-[11px] font-semibold text-slate-400 dark:text-zinc-500 block">Kategori</span>
                      <p className="font-medium text-slate-800 dark:text-zinc-200 mt-0.5">
                        {diffModalItem.baseline_category || "-"}
                      </p>
                    </div>

                    <div>
                      <span className="text-[11px] font-semibold text-slate-400 dark:text-zinc-500 block">Harga</span>
                      <p className="font-bold text-slate-800 dark:text-zinc-200 mt-0.5 text-sm">
                        {diffModalItem.baseline_found && !diffModalItem.is_new_item
                          ? fmtCurrency(diffModalItem.baseline_price)
                          : "-"}
                      </p>
                    </div>

                    <div>
                      <span className="text-[11px] font-semibold text-slate-400 dark:text-zinc-500 block">Foto Menu</span>
                      {diffModalItem.baseline_photo && typeof diffModalItem.baseline_photo === "string" && diffModalItem.baseline_photo.startsWith("http") ? (
                        <div className="mt-1 flex items-center gap-2">
                          <img
                            src={diffModalItem.baseline_photo}
                            alt="Foto Baseline"
                            className="h-12 w-12 rounded-lg object-cover border border-slate-200 dark:border-zinc-700"
                          />
                          <a
                            href={diffModalItem.baseline_photo}
                            target="_blank"
                            rel="noreferrer"
                            className="text-[11px] text-slate-500 hover:underline truncate max-w-[180px]"
                          >
                            Lihat Foto Asli
                          </a>
                        </div>
                      ) : (
                        <p className="text-slate-400 mt-0.5 font-normal">
                          {diffModalItem.baseline_photo || "-"}
                        </p>
                      )}
                    </div>

                    <div>
                      <span className="text-[11px] font-semibold text-slate-400 dark:text-zinc-500 block">Deskripsi</span>
                      <p className="text-slate-600 dark:text-zinc-400 mt-0.5 text-[11px] line-clamp-3">
                        {diffModalItem.baseline_description || "-"}
                      </p>
                    </div>
                  </div>
                  </div>
                )}

                {/* Kolom Kanan: SESUDAH */}
                <div className={`rounded-xl border p-4 ${
                  diffModalItem.is_valid === false
                    ? "border-red-300 bg-red-50/30 dark:border-red-900 dark:bg-red-950/20"
                    : "border-slate-300 bg-white dark:border-zinc-700 dark:bg-zinc-900/90"
                }`}>
                  <div className="flex items-center justify-between border-b border-slate-200 pb-2 dark:border-zinc-800 mb-3">
                    <div>
                      <span className="text-xs font-bold uppercase tracking-wider text-slate-900 dark:text-white">
                        {diffModalItem.is_new_item ? "Rincian Item Baru" : "Sesudah (File C5 Baru)"}
                      </span>
                      {parseResult?.filename && (
                        <p className="text-[10px] font-mono text-slate-400 dark:text-zinc-500 mt-0.5 truncate max-w-[170px]" title={parseResult.filename}>
                          {parseResult.filename}
                        </p>
                      )}
                    </div>
                    <span className="text-[10px] rounded bg-emerald-100 px-1.5 py-0.5 font-bold text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300">
                      Akan Di-Push
                    </span>
                  </div>

                  <div className="space-y-3 text-xs">
                    <div>
                      <span className="text-[11px] font-semibold text-slate-400 dark:text-zinc-500 block">Nama Hidangan</span>
                      <p className={`font-bold mt-0.5 ${
                        diffModalItem.changes?.name_changed
                          ? "text-blue-700 dark:text-blue-300"
                          : "text-slate-900 dark:text-white"
                      }`}>
                        {diffModalItem.item_name_new || diffModalItem.item_name}
                        {diffModalItem.changes?.name_changed && (
                          <span className="ml-1.5 text-[10px] rounded bg-blue-100 px-1 py-0.2 font-semibold text-blue-700 dark:bg-blue-950/60 dark:text-blue-300">
                            Nama Baru
                          </span>
                        )}
                      </p>
                    </div>

                    <div>
                      <span className="text-[11px] font-semibold text-slate-400 dark:text-zinc-500 block">Kategori</span>
                      <p className={`font-bold mt-0.5 ${
                        diffModalItem.is_new_category || diffModalItem.changes?.category_changed
                          ? "text-indigo-700 dark:text-indigo-300"
                          : "text-slate-900 dark:text-white"
                      }`}>
                        {diffModalItem.category || "-"}
                        {diffModalItem.is_new_category && (
                          <span className="ml-1.5 text-[10px] rounded bg-indigo-100 px-1 py-0.2 font-semibold text-indigo-700 dark:bg-indigo-950/60 dark:text-indigo-300">
                            Kategori Baru
                          </span>
                        )}
                      </p>
                    </div>

                    <div>
                      <span className="text-[11px] font-semibold text-slate-400 dark:text-zinc-500 block">Harga</span>
                      <div className="flex items-center gap-2 mt-0.5">
                        <p className="font-extrabold text-slate-900 dark:text-white text-sm">
                          {fmtCurrency(diffModalItem.new_fake_price)}
                        </p>
                        {diffModalItem.price_diff_percent !== undefined && diffModalItem.price_diff_percent !== null && (
                          <span
                            className={`rounded px-1.5 py-0.2 text-[10px] font-bold ${
                              diffModalItem.price_warning
                                ? "bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300"
                                : "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300"
                            }`}
                          >
                            {diffModalItem.price_diff_percent > 0 ? `+${diffModalItem.price_diff_percent}%` : `${diffModalItem.price_diff_percent}%`}
                            {diffModalItem.price_warning ? " (Step Push)" : ""}
                          </span>
                        )}
                      </div>
                    </div>

                    <div>
                      <span className="text-[11px] font-semibold text-slate-400 dark:text-zinc-500 block">Foto Menu</span>
                      {diffModalItem.photo_link && typeof diffModalItem.photo_link === "string" && diffModalItem.photo_link.startsWith("http") ? (
                        <div className="mt-1 flex items-center gap-2">
                          <img
                            src={diffModalItem.photo_link}
                            alt="Foto Baru"
                            className="h-12 w-12 rounded-lg object-cover border border-slate-200 dark:border-zinc-700 cursor-pointer"
                            onClick={() => setPreviewImage({ url: diffModalItem.photo_link, name: diffModalItem.item_name, sid: diffModalItem.sid })}
                            title="Klik untuk pratinjau penuh"
                          />
                          <div>
                            {diffModalItem.changes?.photo_changed && (
                              <span className="block text-[10px] font-bold text-purple-700 dark:text-purple-300 mb-0.5">
                                Foto Baru Terdeteksi
                              </span>
                            )}
                            <a
                              href={diffModalItem.photo_link}
                              target="_blank"
                              rel="noreferrer"
                              className="text-[11px] text-blue-600 dark:text-blue-400 hover:underline truncate max-w-[180px] block"
                            >
                              Buka Link Foto C5
                            </a>
                          </div>
                        </div>
                      ) : (
                        <p className="text-slate-400 mt-0.5 font-normal">
                          {diffModalItem.photo_link || "-"}
                        </p>
                      )}
                    </div>

                    <div>
                      <span className="text-[11px] font-semibold text-slate-400 dark:text-zinc-500 block">Deskripsi</span>
                      <p className="text-slate-700 dark:text-zinc-300 mt-0.5 text-[11px] line-clamp-3">
                        {diffModalItem.description || "-"}
                      </p>
                    </div>
                  </div>
                </div>
              </div>

              {/* List Detail Perubahan Spesifik (diff_details) */}
              {diffModalItem.diff_details && diffModalItem.diff_details.length > 0 && (
                <div className="rounded-xl border border-slate-200 bg-slate-50/50 p-4 dark:border-zinc-800 dark:bg-zinc-900/30">
                  <h5 className="text-xs font-bold uppercase tracking-wider text-slate-700 dark:text-zinc-300 mb-2">
                    Daftar Kolom Berubah ({diffModalItem.diff_details.length})
                  </h5>
                  <div className="divide-y divide-slate-200 dark:divide-zinc-800 text-xs">
                    {diffModalItem.diff_details.map((d, dIdx) => (
                      <div key={dIdx} className="py-2 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-1">
                        <span className="font-semibold text-slate-700 dark:text-zinc-300 sm:w-1/3">
                          {d.column}
                        </span>
                        <div className="flex items-center gap-2 sm:w-2/3">
                          <span className="text-slate-400 line-through truncate max-w-[180px]">
                            {d.old_val || "-"}
                          </span>
                          <span className="text-slate-400">→</span>
                          <span className="font-bold text-slate-900 dark:text-white truncate max-w-[220px]">
                            {d.new_val}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Catatan Khusus Peringatan Step Push */}
              {diffModalItem.price_warning && (
                <div className="rounded-xl border border-amber-300 bg-amber-50 p-3 text-xs text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/40 dark:text-amber-300">
                  Peringatan Step Push: Kenaikan harga hidangan ini sebesar {diffModalItem.price_diff_percent}% (&gt;15%). Sistem otomasi FoodMaster akan memecah kenaikan ini menjadi beberapa tahapan bertahap saat di-push ke merchant portal.
                </div>
              )}
            </div>

            {/* Modal Actions */}
            <div className="mt-5 flex justify-end shrink-0 pt-2 border-t border-slate-100 dark:border-zinc-800">
              <button
                type="button"
                onClick={() => setDiffModalItem(null)}
                className="secondary-action text-xs px-5 py-2"
              >
                Tutup
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
