import React, { useState, useEffect, useRef, useCallback, useMemo } from "react";
import PlatformBadge from "./PlatformBadge";

const fmt = (v) => (!v && v !== 0) ? "" : Number(v).toLocaleString("id-ID");
const parse = (s) => parseInt(String(s).replace(/\D/g, ""), 10) || 0;
const group = (items) => {
  if (!items || !Array.isArray(items)) return {};
  return items.reduce((a, i) => {
    if (!i) return a;
    const cat = i.category || "General";
    (a[cat] ??= []).push(i);
    return a;
  }, {});
};

function applyAdj(price, mode, type, val) {
  const n = parseFloat(val) || 0;
  if (!n) return price;
  if (type === "pct") {
    const d = Math.round(price * n / 100);
    return mode === "add" ? price + d : Math.max(1, price - d);
  }
  return mode === "add" ? price + n : Math.max(1, price - n);
}

function checkShopeeViolation(oldPrice, newPrice) {
  const o = Number(oldPrice) || 0;
  const n = Number(newPrice) || 0;
  if (n <= o || o <= 0) return { isViolation: false, message: "" };
  const diff = n - o;
  const pct = (diff / o) * 100;
  if (pct > 25) return { isViolation: true, message: "ShopeeFood: Maksimal kenaikan 25% per update." };
  return { isViolation: false, message: "" };
}

function StepLabel({ number, label, active, done, className = "mb-2.5" }) {
  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <span className={`w-6 h-6 rounded-full text-[13px] font-bold flex items-center justify-center shrink-0 transition-colors ${
        done ? "bg-orange-600 text-white dark:bg-white dark:text-black"
        : active ? "bg-orange-100 text-orange-700 ring-4 ring-orange-50 dark:bg-zinc-800 dark:text-white dark:ring-zinc-700"
        : "bg-zinc-100 text-zinc-400 dark:bg-zinc-900 dark:text-zinc-500"
      }`}>{done ? "✓" : number}</span>
      <span className={`text-[15px] font-bold uppercase tracking-wider transition-colors ${
        active || done ? "text-zinc-800 dark:text-white" : "text-zinc-400 dark:text-zinc-500"
      }`}>{label}</span>
    </div>
  );
}

// ─── Inline Adjust Bar ───────────────────────────────────────────────────────
const CHIPS_NOM = [1000, 2000, -1000, -2000];
const CHIPS_PCT = [5, 10, -5, -10];

function AdjustBar({ onApply, buttonText = "OK", extraActions = null }) {
  const [type, setType] = useState("nominal");
  const [val, setVal] = useState("");

  const parsedNum = parseFloat(val);
  const isNegative = !isNaN(parsedNum) && (parsedNum < 0 || String(val).trim().startsWith("-"));
  const isValid = !isNaN(parsedNum) && parsedNum !== 0;

  const fire = () => {
    if (!isValid) return;
    const mode = isNegative ? "sub" : "add";
    onApply(mode, type, Math.abs(parsedNum));
  };

  return (
    <div className="flex flex-wrap items-end gap-3 bg-orange-50/60 dark:bg-orange-950/20 p-3.5 rounded-2xl border border-orange-200/60 dark:border-orange-900/40">
      <div>
        <p className="mb-1 text-[12px] font-bold uppercase tracking-wider text-orange-800 dark:text-orange-300">Metode</p>
        <div className="inline-flex overflow-hidden rounded-xl border border-orange-200 dark:border-orange-800 bg-white dark:bg-zinc-900 p-0.5 shadow-xs">
          {[["nominal", "Rp"], ["pct", "%"]].map(([t, label]) => (
            <button key={t} type="button" onClick={() => setType(t)} aria-pressed={type === t}
              className={`px-3 py-1.5 text-[13px] font-bold rounded-lg transition-colors cursor-pointer ${
                type === t ? "bg-orange-600 text-white shadow-xs" : "text-zinc-600 dark:text-zinc-400 hover:text-orange-600"
              }`}
            >{label}</button>
          ))}
        </div>
      </div>

      <div className="flex-1 min-w-[200px]">
        <div className="flex items-center justify-between mb-1">
          <span className="text-[12px] font-bold uppercase tracking-wider text-zinc-600 dark:text-zinc-400">Nilai Perubahan (Positif / Negatif)</span>
          {val && isValid && (
            <span className={`text-[11px] font-bold uppercase px-2 py-0.5 rounded-md ${
              isNegative ? "bg-red-100 text-red-700 border border-red-200" : "bg-emerald-100 text-emerald-700 border border-emerald-200"
            }`}>
              {isNegative ? "↓ Potongan / Diskon" : "↑ Kenaikan Harga"}
            </span>
          )}
        </div>
        <div className="relative flex items-center">
          <input
            type="text"
            inputMode="numeric"
            placeholder={type === "nominal" ? "Contoh: 2000 atau -2000" : "Contoh: 10 atau -10"}
            value={val}
            onChange={(e) => setVal(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && fire()}
            className={`w-full rounded-xl border bg-white dark:bg-zinc-900 px-3.5 py-2 text-[14px] font-semibold text-zinc-800 dark:text-zinc-100 placeholder:text-zinc-400 focus:outline-none transition-all ${
              !val ? "border-orange-200 dark:border-orange-900/50 focus:border-orange-500" :
              isNegative ? "border-red-300 dark:border-red-800 text-red-700" : "border-emerald-300 dark:border-emerald-800 text-emerald-700"
            }`}
          />
        </div>
        <div className="flex flex-wrap items-center gap-1.5 mt-1.5">
          <span className="text-[11px] font-semibold text-zinc-400">Pintas:</span>
          {(type === "nominal" ? CHIPS_NOM : CHIPS_PCT).map((num) => {
            const isNeg = num < 0;
            const labelStr = type === "nominal"
              ? (isNeg ? `-${Math.abs(num).toLocaleString('id-ID')}` : `+${num.toLocaleString('id-ID')}`)
              : (isNeg ? `-${Math.abs(num)}%` : `+${num}%`);
            const isSelected = val === String(num);

            return (
              <button
                key={num}
                type="button"
                onClick={() => setVal(String(num))}
                className={`px-2 py-0.5 text-[11px] font-bold rounded-md transition-all cursor-pointer ${
                  isSelected
                    ? isNeg ? "text-red-600 dark:text-red-400 underline underline-offset-2" : "text-emerald-600 dark:text-emerald-400 underline underline-offset-2"
                    : isNeg ? "text-red-500 dark:text-red-500 hover:text-red-700 dark:hover:text-red-300" : "text-emerald-600 dark:text-emerald-500 hover:text-emerald-800 dark:hover:text-emerald-300"
                }`}
              >
                {labelStr}
              </button>
            );
          })}
        </div>
      </div>

      <button
        type="button"
        onClick={fire}
        disabled={!isValid}
        className={`px-4 py-2 text-[13px] font-bold rounded-xl transition-all shadow-xs shrink-0 cursor-pointer disabled:bg-zinc-200 disabled:text-zinc-400 ${
          !isValid ? "" : isNegative ? "bg-red-600 hover:bg-red-700 text-white" : "bg-orange-600 hover:bg-orange-700 text-white"
        }`}
      >
        {buttonText}
      </button>

      {extraActions && (
        <div className="flex items-center gap-2 shrink-0 ml-auto pt-2 sm:pt-0">
          {extraActions}
        </div>
      )}
    </div>
  );
}

// ─── Shopee Interactive OTP Modal ────────────────────────────────────────────
function ShopeeOTPModal({ isOpen, username, phone, onSubmitOTP, onCancel, submitting, statusMsg }) {
  const [otpCode, setOtpCode] = useState("");
  const [otpChannel, setOtpChannel] = useState("sms"); // "sms" | "whatsapp"

  if (!isOpen) return null;

  const handleSubmit = (e) => {
    e.preventDefault();
    if (otpCode.trim().length >= 4) {
      onSubmitOTP(otpCode.trim(), otpChannel);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-md p-4 animate-in fade-in duration-200">
      <div className="w-full max-w-md rounded-3xl bg-white dark:bg-zinc-900 border border-orange-200 dark:border-orange-900/50 shadow-2xl p-6 relative overflow-hidden">
        <div className="absolute top-0 right-0 left-0 h-2 bg-gradient-to-r from-orange-500 via-amber-500 to-red-500" />
        
        <div className="flex items-center gap-3 mb-4">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-orange-100 dark:bg-orange-950/60 border border-orange-200 dark:border-orange-800 text-orange-600 dark:text-orange-400">
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 002-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
            </svg>
          </div>
          <div>
            <h3 className="text-lg font-bold text-zinc-900 dark:text-white">Verifikasi OTP Shopee</h3>
            <p className="text-xs text-orange-600 dark:text-orange-400 font-medium">Diperlukan untuk login portal partner</p>
          </div>
        </div>

        <div className="mb-5 p-3.5 rounded-2xl bg-orange-50/80 dark:bg-orange-950/40 border border-orange-200/70 dark:border-orange-900/50 text-xs text-zinc-700 dark:text-zinc-300">
          <p className="font-semibold text-orange-900 dark:text-orange-300 mb-1">📌 Detail Akun Login Shopee:</p>
          <div className="flex flex-col gap-1 font-mono text-[13px]">
            <div><span className="text-zinc-500">Nama Pengguna (Kolom Q):</span> <strong className="text-zinc-900 dark:text-white">{username || "-"}</strong></div>
            {phone && <div><span className="text-zinc-500">No. HP / Kontak:</span> <strong className="text-zinc-900 dark:text-white">{phone}</strong></div>}
          </div>
          <p className="mt-2 text-[11px] text-zinc-500">Silakan pilih kanal pengiriman OTP dan masukkan Kode OTP 6-Digit.</p>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-bold uppercase tracking-wider text-zinc-500 dark:text-zinc-400 mb-1.5">
              Metode Pengiriman OTP
            </label>
            <div className="grid grid-cols-2 gap-2 mb-3">
              <button
                type="button"
                onClick={() => setOtpChannel("sms")}
                className={`flex items-center justify-center gap-2 py-2 px-3 rounded-xl border text-xs font-bold transition cursor-pointer ${
                  otpChannel === "sms"
                    ? "border-orange-500 bg-orange-50 dark:bg-orange-950/60 text-orange-700 dark:text-orange-300 ring-2 ring-orange-500/20"
                    : "border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50 dark:hover:bg-zinc-800"
                }`}
              >
                <span>📱 SMS</span>
              </button>
              <button
                type="button"
                onClick={() => setOtpChannel("whatsapp")}
                className={`flex items-center justify-center gap-2 py-2 px-3 rounded-xl border text-xs font-bold transition cursor-pointer ${
                  otpChannel === "whatsapp"
                    ? "border-emerald-500 bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300 ring-2 ring-emerald-500/20"
                    : "border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50 dark:hover:bg-zinc-800"
                }`}
              >
                <span>💬 WhatsApp</span>
              </button>
            </div>

            <label className="block text-xs font-bold uppercase tracking-wider text-zinc-500 dark:text-zinc-400 mb-1.5">
              Kode OTP (6 Digit)
            </label>
            <input
              type="text"
              maxLength={6}
              autoFocus
              value={otpCode}
              onChange={(e) => setOtpCode(e.target.value.replace(/\D/g, ""))}
              placeholder="Contoh: 123456"
              className="w-full text-center text-2xl font-mono tracking-widest py-3 px-4 rounded-2xl border-2 border-orange-300 dark:border-orange-700 bg-white dark:bg-zinc-800 text-zinc-900 dark:text-white focus:outline-none focus:border-orange-500 focus:ring-4 focus:ring-orange-100 dark:focus:ring-orange-950/50 font-bold"
            />
          </div>

          {statusMsg && (
            <p className="text-xs text-center font-medium text-orange-600 dark:text-orange-400">
              {statusMsg}
            </p>
          )}

          <div className="flex items-center gap-3 pt-2">
            <button
              type="button"
              onClick={onCancel}
              className="flex-1 py-2.5 px-4 text-xs font-bold text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800 rounded-xl transition cursor-pointer"
            >
              Batal
            </button>
            <button
              type="submit"
              disabled={submitting || otpCode.trim().length < 4}
              className="flex-1 py-2.5 px-4 text-xs font-bold text-white bg-gradient-to-r from-orange-600 to-red-600 hover:from-orange-700 hover:to-red-700 disabled:opacity-50 rounded-xl shadow-md shadow-orange-900/20 transition flex items-center justify-center gap-2 cursor-pointer"
            >
              {submitting ? (
                <>
                  <svg className="animate-spin h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                  </svg>
                  <span>Mengirim...</span>
                </>
              ) : (
                <span>Kirim OTP ({otpChannel.toUpperCase()})</span>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ─── Main Component: ShopeeEditHargaTab ───────────────────────────────────────
export default function ShopeeEditHargaTab({ API_BASE_URL, API_SECRET_KEY }) {
  const [allOutlets, setAllOutlets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [selectedParent, setSelectedParent] = useState("");
  const [branches, setBranches] = useState([]);
  const [selectedBrandId, setSelectedBrandId] = useState("");
  const [branchMenus, setBranchMenus] = useState({});
  const [edits, setEdits] = useState({});
  const [pushing, setPushing] = useState(false);
  const [activeJobs, setActiveJobs] = useState([]);
  const [syncPhase, setSyncPhase] = useState("idle");
  const [itemEditMode, setItemEditMode] = useState("single"); // "single" | "multi"
  const [selectedItemIds, setSelectedItemIds] = useState([]);

  // Custom Searchable Dropdown States
  const [openOutletDropdown, setOpenOutletDropdown] = useState(false);
  const [openBranchDropdown, setOpenBranchDropdown] = useState(false);

  // OTP Modal State
  const [otpModal, setOtpModal] = useState({
    isOpen: false,
    username: "",
    phone: "",
    submitting: false,
    statusMsg: ""
  });

  const [showPushConfirmModal, setShowPushConfirmModal] = useState(false);
  const [pushSummaryList, setPushSummaryList] = useState([]);
  const [showSuccessModal, setShowSuccessModal] = useState(false);

  const [showPasswordMap, setShowPasswordMap] = useState({});
  const [cacheInfo, setCacheInfo] = useState(null);

  const pushPollingIntervalsRef = useRef({});

  // Fetch cache status for selected outlet
  useEffect(() => {
    if (!selectedBrandId) {
      setCacheInfo(null);
      return;
    }
    fetch(`${API_BASE_URL}/api/outlets/${selectedBrandId}/menu-cache-status`, {
      headers: { "X-API-Key": API_SECRET_KEY || "" }
    })
      .then(r => r.ok ? r.json() : null)
      .then(data => setCacheInfo(data))
      .catch(err => console.error("Error fetching cache status:", err));
  }, [API_BASE_URL, API_SECRET_KEY, selectedBrandId]);

  // Sync Google Sheets on Mount & Fetch Shopee Outlets
  const triggerGSheetSync = useCallback(async () => {
    try {
      await fetch(`${API_BASE_URL}/api/sync-sheets`, {
        method: "POST",
        headers: { "X-API-Key": API_SECRET_KEY || "" }
      });
    } catch (err) {
      console.error("GSheet sync error:", err);
    }
  }, [API_BASE_URL, API_SECRET_KEY]);

  useEffect(() => {
    setLoading(true);
    triggerGSheetSync().then(() => {
      return fetch(`${API_BASE_URL}/api/outlets?platform=shopee`, {
        headers: { "X-API-Key": API_SECRET_KEY || "" }
      }).then(r => r.ok ? r.json() : []);
    })
      .then(data => {
        setAllOutlets(data || []);
        setLoading(false);
      })
      .catch(err => {
        console.error("Error fetching Shopee outlets:", err);
        setLoading(false);
      });
  }, [API_BASE_URL, API_SECRET_KEY, triggerGSheetSync]);

  // Unique Parents list
  const uniqueParents = useMemo(() => {
    const setNames = new Set();
    allOutlets.forEach(o => {
      const name = o.nama_outlet || o.nama_resto_final || o.merchant_name;
      if (name) setNames.add(name);
    });
    return Array.from(setNames).sort();
  }, [allOutlets]);

  // Filtered Parents by Search Query
  const filteredParents = useMemo(() => {
    return uniqueParents.filter(n => n.toLowerCase().includes(search.toLowerCase()));
  }, [uniqueParents, search]);

  // Periodic OTP status check during PUSH — poll seluruh akun tanpa filter username
  const otpPollIntervalRef = useRef(null);

  const startOtpPolling = useCallback(() => {
    if (otpPollIntervalRef.current) return; // sudah berjalan
    otpPollIntervalRef.current = setInterval(() => {
      fetch(`${API_BASE_URL}/api/shopee/otp-status`, {
        headers: { "X-API-Key": API_SECRET_KEY || "" }
      })
        .then(r => r.ok ? r.json() : null)
        .then(data => {
          if (data && data.waiting) {
            setOtpModal(prev => {
              if (prev.isOpen && prev.username === data.username) return prev; // sudah terbuka
              return {
                ...prev,
                isOpen: true,
                username: data.username || "",
                phone: data.phone || "",
                submitting: false,
                statusMsg: ""
              };
            });
          }
        })
        .catch(() => {});
    }, 1500);
  }, [API_BASE_URL, API_SECRET_KEY]);

  const stopOtpPolling = useCallback(() => {
    if (otpPollIntervalRef.current) {
      clearInterval(otpPollIntervalRef.current);
      otpPollIntervalRef.current = null;
    }
  }, []);

  useEffect(() => {
    const hasActivePush = activeJobs.some(j => j.status === "PENDING" || j.status === "RUNNING");
    if (hasActivePush) {
      startOtpPolling();
    } else {
      stopOtpPolling();
    }
    return () => stopOtpPolling();
  }, [activeJobs, startOtpPolling, stopOtpPolling]);

  const triggerAutoPull = useCallback(async (targetBranches) => {
    if (!targetBranches || targetBranches.length === 0) return;
    setSyncPhase("syncing");

    const createdJobs = [];
    for (const b of targetBranches) {
      const label = b.brand || b.nama_outlet || b.merchant_name;
      try {
        const res = await fetch(`${API_BASE_URL}/api/jobs/pull?outlet_id=${b.id}`, {
          method: "POST",
          headers: { "X-API-Key": API_SECRET_KEY || "" }
        });
        if (res.ok) {
          const job = await res.json();
          createdJobs.push({
            id: job.id,
            branchId: b.id,
            name: label,
            storeId: b.store_id,
            platform: b.platform || "shopee",
            status: job.status,
            progress_pct: job.progress_pct,
            current_step: job.current_step,
            error_message: null
          });
        }
      } catch (err) {
        console.error("Error triggering pull job:", err);
      }
    }

    if (createdJobs.length === 0) {
      setSyncPhase("done");
      return;
    }

    setActiveJobs(createdJobs);

    createdJobs.forEach(job => {
      const interval = setInterval(() => {
        fetch(`${API_BASE_URL}/api/jobs/${job.id}`, {
          headers: { "X-API-Key": API_SECRET_KEY || "" }
        })
          .then(r => r.ok ? r.json() : null)
          .then(async updatedJob => {
            if (!updatedJob) return;
            setActiveJobs(prev => prev.map(j => j.id === job.id ? {
              ...j,
              status: updatedJob.status,
              progress_pct: updatedJob.progress_pct,
              current_step: updatedJob.current_step,
              error_message: updatedJob.error_message
            } : j));

            if (updatedJob.status === "SUCCESS" || updatedJob.status === "FAILED") {
              clearInterval(interval);
              const res = await fetch(`${API_BASE_URL}/api/outlets/${job.branchId}/menu-items`, {
                headers: { "X-API-Key": API_SECRET_KEY || "" }
              });
              if (res.ok) {
                const rawItems = await res.json();
                const items = rawItems.map(i => ({
                  id: String(i.id || i.item_id),
                  name: i.name,
                  category: i.category || "General",
                  price: Number(i.price || 0),
                  is_in_promo: Boolean(i.is_in_promo || i.is_promo_col)
                }));
                setBranchMenus(prev => ({ ...prev, [job.branchId]: items }));
                const bEdits = {};
                items.forEach(item => { bEdits[item.id] = item.price; });
                setEdits(prev => ({ ...prev, [job.branchId]: bEdits }));
              }
              setSyncPhase("done");
            }
          })
          .catch(err => console.error("Error polling pull job:", err));
      }, 2000);
    });
  }, [API_BASE_URL, API_SECRET_KEY]);

  const fetchMenus = useCallback(async (targetBranches, autoPullIfEmpty = false) => {
    const newMenus = {};
    const editsMap = {};
    let emptyCount = 0;

    setLoading(true);
    for (const b of targetBranches) {
      try {
        const res = await fetch(`${API_BASE_URL}/api/outlets/${b.id}/menu-items`, {
          headers: { "X-API-Key": API_SECRET_KEY || "" }
        });
        if (res.ok) {
          const rawItems = await res.json();
          const items = rawItems.map(i => ({
            id: String(i.id || i.item_id),
            name: i.name,
            category: i.category || "General",
            price: Number(i.price || 0),
            is_in_promo: Boolean(i.is_in_promo || i.is_promo_col)
          }));
          newMenus[b.id] = items;

          const bEdits = {};
          items.forEach(item => {
            bEdits[item.id] = item.price;
          });
          editsMap[b.id] = bEdits;

          if (items.length === 0) {
            emptyCount++;
          }
        } else {
          emptyCount++;
        }
      } catch (err) {
        console.error(`Error fetching menu for ${b.id}:`, err);
        emptyCount++;
      }
    }

    setBranchMenus(prev => ({ ...prev, ...newMenus }));
    setEdits(prev => ({ ...prev, ...editsMap }));
    setLoading(false);

    if (autoPullIfEmpty && emptyCount === targetBranches.length) {
      triggerAutoPull(targetBranches);
    } else {
      setSyncPhase("done");
    }
  }, [API_BASE_URL, API_SECRET_KEY, triggerAutoPull]);

  const handleSelectOutlet = (name) => {
    setSelectedParent(name);
    setOpenOutletDropdown(false);
    const targetBranches = allOutlets.filter(o => (o.nama_outlet || o.nama_resto_final || o.merchant_name) === name);
    setBranches(targetBranches);
    setSelectedBrandId("");
    setSyncPhase("idle");
  };

  const handleSelectBrand = (branchId) => {
    setSelectedBrandId(branchId);
    setOpenBranchDropdown(false);
    setSyncPhase("idle");
  };

  const startPollingPushJob = (jobId, branchId) => {
    pushPollingIntervalsRef.current[jobId] = setInterval(() => {
      fetch(`${API_BASE_URL}/api/jobs/${jobId}`, {
        headers: { "X-API-Key": API_SECRET_KEY || "" }
      })
        .then(r => r.ok ? r.json() : null)
        .then(job => {
          if (!job) return;
          setActiveJobs(prev => prev.map(j => j.id === jobId ? {
            ...j,
            status: job.status,
            progress_pct: job.progress_pct,
            current_step: job.current_step,
            error_message: job.error_message,
            result_metadata: job.result_metadata
          } : j));

          if (job.current_step && job.current_step.includes("[WAIT_OTP]")) {
            const match = job.current_step.match(/username:\s*([^\s]+)/i);
            const userStr = match ? match[1] : "";
            setOtpModal(prev => ({
              ...prev,
              isOpen: true,
              username: userStr || branches.find(b => b.id === branchId)?.account?.username || ""
            }));
          }

          if (job.status === "SUCCESS" || job.status === "FAILED" || job.status === "PARTIAL_SUCCESS") {
            clearInterval(pushPollingIntervalsRef.current[jobId]);
            delete pushPollingIntervalsRef.current[jobId];
          }
        })
        .catch(err => console.error("Error polling push job:", err));
    }, 2000);
  };

  const triggerPriceUpdate = async () => {
    if (!selectedBrandId) return;
    const branch = branches.find(x => x.id === selectedBrandId);
    if (!branch) return;

    setPushing(true);
    const branchEdits = edits[selectedBrandId] || {};
    const branchItems = branchMenus[selectedBrandId] || [];
    const updates = [];

    branchItems.forEach(i => {
      if (i.is_in_promo) return;
      const curPrice = branchEdits[i.id];
      if (curPrice !== undefined && curPrice !== i.price) {
        updates.push({
          item_id: i.id,
          category_id: i.category_id || "",
          item_name: i.name || "",
          new_price: curPrice
        });
      }
    });

    if (updates.length === 0) {
      alert("Tidak ada perubahan harga untuk di-push.");
      setPushing(false);
      return;
    }

    try {
      const res = await fetch(`${API_BASE_URL}/api/jobs/push-price`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-API-Key": API_SECRET_KEY || ""
        },
        body: JSON.stringify({
          outlet_id: selectedBrandId,
          updates: updates
        })
      });

      if (res.ok) {
        const job = await res.json();
        setActiveJobs([{
          id: job.id,
          name: branch.brand || branch.nama_outlet || branch.merchant_name,
          platform: "shopee",
          status: job.status,
          progress_pct: job.progress_pct,
          current_step: job.current_step,
          error_message: null
        }]);
        startPollingPushJob(job.id, selectedBrandId);
        startOtpPolling(); // mulai polling OTP segera
      } else {
        alert("Gagal memicu update harga Shopee");
      }
    } catch (err) {
      console.error(err);
    }
    setPushing(false);
  };

  // Open rich push summary modal before sending update
  const openPushConfirmationModal = () => {
    if (!selectedBrandId) return;
    const branch = branches.find(x => x.id === selectedBrandId);
    if (!branch) return;
    const bLabel = branch.brand || branch.nama_outlet || branch.merchant_name;
    const branchItems = branchMenus[selectedBrandId] || [];
    const branchEdits = edits[selectedBrandId] || {};
    const itemUpdates = [];

    branchItems.forEach(item => {
      if (item.is_in_promo) return;
      const curPrice = branchEdits[item.id];
      if (curPrice !== undefined && curPrice !== item.price) {
        const diff = curPrice - item.price;
        const pct = item.price > 0 ? (diff / item.price) * 100 : 0;
        const { isViolation, message: violationMsg } = checkShopeeViolation(item.price, curPrice);
        itemUpdates.push({
          id: item.id,
          name: item.name,
          category: item.category,
          oldPrice: item.price,
          newPrice: curPrice,
          diff: diff,
          pct: pct,
          isViolation: isViolation,
          violationMsg: violationMsg
        });
      }
    });

    if (itemUpdates.length === 0) {
      alert("Tidak ada perubahan harga yang terdeteksi.");
      return;
    }

    setPushSummaryList([{
      branchId: selectedBrandId,
      branchName: bLabel,
      platform: "shopee",
      storeId: branch.store_id || selectedBrandId,
      updates: itemUpdates
    }]);
    setShowPushConfirmModal(true);
  };

  const executePushFromModal = async () => {
    setShowPushConfirmModal(false);
    setShowSuccessModal(true);
    await triggerPriceUpdate();
  };

  const handleSubmittedOTP = async (code, channel = "sms") => {
    setOtpModal(p => ({ ...p, submitting: true, statusMsg: `Mengirim OTP (${channel.toUpperCase()}) ke backend...` }));
    try {
      const res = await fetch(`${API_BASE_URL}/api/shopee/submit-otp`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-API-Key": API_SECRET_KEY || ""
        },
        body: JSON.stringify({
          username: otpModal.username,
          code: code,
          channel: channel
        })
      });
      if (res.ok) {
        setOtpModal(p => ({
          ...p,
          submitting: false,
          statusMsg: `✅ OTP (${channel.toUpperCase()}) Terverifikasi! Shopee melanjutkan PUSH...`
        }));
        setTimeout(() => {
          setOtpModal(p => ({ ...p, isOpen: false, statusMsg: "" }));
        }, 1500);
      } else {
        setOtpModal(p => ({ ...p, submitting: false, statusMsg: "❌ Gagal mengirim OTP ke server" }));
      }
    } catch (err) {
      setOtpModal(p => ({ ...p, submitting: false, statusMsg: `❌ Error: ${err.message}` }));
    }
  };

  const handleLoadCache = async () => {
    const targetBranches = branches.filter(b => b.id === selectedBrandId);
    if (targetBranches.length > 0) {
      await fetchMenus(targetBranches, false);
      setSyncPhase("done");
    }
  };

  const handleLiveSync = () => {
    const targetBranches = branches.filter(b => b.id === selectedBrandId);
    if (targetBranches.length > 0) {
      triggerAutoPull(targetBranches);
    }
  };

  const selectedBrandObj = useMemo(() => branches.find(b => b.id === selectedBrandId) || null, [branches, selectedBrandId]);
  const items = useMemo(() => (selectedBrandId && Array.isArray(branchMenus[selectedBrandId])) ? branchMenus[selectedBrandId] : [], [branchMenus, selectedBrandId]);
  const groups = useMemo(() => group(items), [items]);
  const changedCount = useMemo(() => {
    if (!selectedBrandId || !items || items.length === 0) return 0;
    const bEdits = edits[selectedBrandId] || {};
    return items.filter(i => !i.is_in_promo && (bEdits[i.id] !== undefined && bEdits[i.id] !== i.price)).length;
  }, [items, edits, selectedBrandId]);
  const promoCount = useMemo(() => items.filter(i => i.is_in_promo).length, [items]);

  const bulkAdj = (mode, type, val, itemIds = null) => {
    setEdits(prev => {
      const bEdits = { ...(prev[selectedBrandId] || {}) };
      items.forEach(i => {
        if (!i.is_in_promo) {
          if (!itemIds || itemIds.includes(i.id)) {
            bEdits[i.id] = applyAdj(bEdits[i.id] ?? i.price, mode, type, val);
          }
        }
      });
      return { ...prev, [selectedBrandId]: bEdits };
    });
  };

  const resetAll = () => {
    setEdits(prev => ({ ...prev, [selectedBrandId]: {} }));
  };

  const selectAllVisibleItems = () => {
    setSelectedItemIds(items.filter(i => !i.is_in_promo).map(i => i.id));
  };
  const deselectAllItems = () => {
    setSelectedItemIds([]);
  };
  const toggleSelectItem = (id) => {
    setSelectedItemIds(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
    );
  };

  return (
    <div className="space-y-6">
      {/* Header Banner */}
      <div className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-orange-600 via-orange-500 to-amber-600 p-6 text-white shadow-xl shadow-orange-950/20">
        <div className="relative z-10 flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full bg-white/20 px-3 py-1 text-xs font-bold backdrop-blur-md mb-2">
              <PlatformBadge platform="shopee" />
              <span>Shopee Partner Portal Sync</span>
            </div>
            <h2 className="text-2xl font-extrabold tracking-tight sm:text-3xl">Edit Harga Shopee Food</h2>
            <p className="mt-1 max-w-xl text-xs sm:text-sm text-orange-100">
              Update harga menu Shopee Partner secara aman menggunakan kredensial Kolom Q (Username) & Kolom S (Password) dengan verifikasi OTP otomatis.
            </p>
          </div>
        </div>
      </div>

      {/* Outlet Selection Card */}
      <div className="rounded-3xl border border-orange-200/80 dark:border-orange-900/40 bg-white dark:bg-zinc-900 p-6 shadow-sm">
        <h3 className="text-sm font-bold text-zinc-900 dark:text-white uppercase tracking-wider mb-4 flex items-center gap-2">
          <span>1. Pilih Outlet Shopee</span>
        </h3>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {/* Custom Searchable Outlet Dropdown */}
          <div className="relative">
            <label className="block text-xs font-bold uppercase tracking-wider text-zinc-500 mb-1">Parent Resto / Outlet</label>
            <button
              type="button"
              disabled={loading}
              onClick={() => {
                setOpenOutletDropdown(!openOutletDropdown);
                setOpenBranchDropdown(false);
              }}
              className="w-full flex items-center justify-between text-left rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 p-3.5 text-sm font-semibold text-zinc-900 dark:text-white focus:outline-none focus:border-orange-500 cursor-pointer"
            >
              <span className={`truncate ${selectedParent ? "text-zinc-900 dark:text-white font-semibold" : "text-zinc-400 dark:text-zinc-500"}`}>
                {loading ? "Memuat outlet..." : selectedParent || "-- Pilih Outlet Shopee --"}
              </span>
              <svg className={`w-4 h-4 text-zinc-400 shrink-0 transition-transform ${openOutletDropdown ? "rotate-180" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>

            {openOutletDropdown && (
              <>
                <div className="fixed inset-0 z-20" onClick={() => setOpenOutletDropdown(false)} />
                <div className="absolute left-0 right-0 top-full mt-1 z-30 bg-white dark:bg-zinc-900 rounded-2xl shadow-xl border border-orange-200 dark:border-orange-900/50 p-2.5 space-y-2 animate-scale-up min-w-[240px]">
                  <input
                    type="text"
                    placeholder="Cari outlet..."
                    value={search}
                    onChange={e => setSearch(e.target.value)}
                    className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-medium text-zinc-900 dark:text-white focus:outline-none focus:border-orange-500"
                    autoFocus
                  />

                  <div className="max-h-56 overflow-y-auto space-y-0.5 pr-1">
                    {filteredParents.length === 0 ? (
                      <p className="text-center text-xs text-zinc-400 dark:text-zinc-500 py-3">Tidak ada outlet cocok</p>
                    ) : (
                      filteredParents.map(name => {
                        const isSelected = selectedParent === name;
                        return (
                          <button
                            key={name}
                            type="button"
                            onClick={() => handleSelectOutlet(name)}
                            className={`w-full text-left px-3 py-2 rounded-xl text-xs flex items-center justify-between transition-colors cursor-pointer ${
                              isSelected ? "bg-orange-50 text-orange-700 font-bold dark:bg-orange-950/60 dark:text-orange-300" : "text-zinc-700 hover:bg-zinc-50 dark:text-zinc-200 dark:hover:bg-zinc-800"
                            }`}
                          >
                            <span className="truncate">{name}</span>
                            {isSelected && <span className="text-orange-600 dark:text-orange-400 font-bold">✓</span>}
                          </button>
                        );
                      })
                    )}
                  </div>
                </div>
              </>
            )}
          </div>

          {/* Custom Searchable Brand Dropdown */}
          <div className="relative">
            <label className="block text-xs font-bold uppercase tracking-wider text-zinc-500 mb-1">Brand / Branch Shopee</label>
            <button
              type="button"
              disabled={!selectedParent}
              onClick={() => {
                setOpenBranchDropdown(!openBranchDropdown);
                setOpenOutletDropdown(false);
              }}
              className="w-full flex items-center justify-between text-left rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 p-3.5 text-sm font-semibold text-zinc-900 dark:text-white focus:outline-none focus:border-orange-500 cursor-pointer disabled:opacity-50"
            >
              <span className={`truncate ${selectedBrandObj ? "text-zinc-900 dark:text-white font-semibold" : "text-zinc-400 dark:text-zinc-500"}`}>
                {!selectedParent
                  ? "-- Pilih Outlet dulu --"
                  : selectedBrandObj
                  ? `${selectedBrandObj.brand || selectedBrandObj.nama_outlet || selectedBrandObj.merchant_name} (Store: ${selectedBrandObj.store_id})`
                  : "-- Pilih Brand / Branch --"}
              </span>
              <svg className={`w-4 h-4 text-zinc-400 shrink-0 transition-transform ${openBranchDropdown ? "rotate-180" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>

            {openBranchDropdown && (
              <>
                <div className="fixed inset-0 z-20" onClick={() => setOpenBranchDropdown(false)} />
                <div className="absolute left-0 right-0 top-full mt-1 z-30 bg-white dark:bg-zinc-900 rounded-2xl shadow-xl border border-orange-200 dark:border-orange-900/50 p-2.5 space-y-2 animate-scale-up min-w-[280px]">
                  <div className="max-h-56 overflow-y-auto space-y-0.5 pr-1">
                    {branches.map(b => {
                      const isSelected = selectedBrandId === b.id;
                      const bName = b.brand || b.nama_outlet || b.merchant_name;
                      return (
                        <button
                          key={b.id}
                          type="button"
                          onClick={() => handleSelectBrand(b.id)}
                          className={`w-full text-left px-3 py-2 rounded-xl text-xs flex items-center justify-between transition-colors cursor-pointer ${
                            isSelected ? "bg-orange-50 text-orange-700 font-bold dark:bg-orange-950/60 dark:text-orange-300" : "text-zinc-700 hover:bg-zinc-50 dark:text-zinc-200 dark:hover:bg-zinc-800"
                          }`}
                        >
                          <div className="truncate">
                            <div className="font-bold">{bName}</div>
                            <div className="text-[10px] text-zinc-400">Store ID: {b.store_id} | User: {b.account?.username || "-"}</div>
                          </div>
                          {isSelected && <span className="text-orange-600 dark:text-orange-400 font-bold">✓</span>}
                        </button>
                      );
                    })}
                  </div>
                </div>
              </>
            )}
          </div>
        </div>

        {/* Selected Outlet Credentials Display */}
        {selectedBrandObj && (
          <div className="mt-4 p-4 rounded-2xl bg-orange-50/70 dark:bg-orange-950/30 border border-orange-200/80 dark:border-orange-900/40">
            <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
              <div className="space-y-1.5 min-w-0 flex-1">
                <span className="text-[11px] font-bold uppercase tracking-wider text-orange-800 dark:text-orange-300">
                  Kredensial Shopee Partner Portal
                </span>
                <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-xs font-mono">
                  <div className="flex items-center gap-1.5">
                    <span className="text-zinc-500 font-sans">Nama Pengguna (Kolom Q):</span>
                    <strong className="text-zinc-900 dark:text-white font-bold">{selectedBrandObj.account?.username || "-"}</strong>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <span className="text-zinc-500 font-sans">Kata Sandi (Kolom S):</span>
                    {selectedBrandObj.account?.password && selectedBrandObj.account.password !== "-" ? (
                      <div className="inline-flex items-center">
                        <strong className="text-zinc-900 dark:text-white font-bold">
                          {showPasswordMap[selectedBrandObj.id] ? selectedBrandObj.account.password : "••••••••"}
                        </strong>
                        <button
                          type="button"
                          onClick={() => setShowPasswordMap(p => ({ ...p, [selectedBrandObj.id]: !p[selectedBrandObj.id] }))}
                          className="ml-2 text-[11px] font-sans font-bold text-orange-600 dark:text-orange-400 underline cursor-pointer"
                        >
                          {showPasswordMap[selectedBrandObj.id] ? "Sembunyikan" : "Tampilkan"}
                        </button>
                      </div>
                    ) : (
                      <span className="font-sans font-bold text-amber-700 dark:text-amber-300 bg-amber-100 dark:bg-amber-950/60 px-2 py-0.5 rounded-md border border-amber-200 dark:border-amber-800/60 text-[11px]">
                        Tanpa Password (Langsung OTP)
                      </span>
                    )}
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-2.5 shrink-0 pt-2 lg:pt-0">
                {/* Button 1: Buka Data Terakhir */}
                {cacheInfo?.has_cache && (
                  <button
                    type="button"
                    disabled={syncPhase === "syncing"}
                    onClick={handleLoadCache}
                    className="px-5 py-2.5 rounded-2xl font-bold text-xs bg-[#403D88] hover:bg-[#34316e] text-white shadow-sm transition flex items-center gap-2 cursor-pointer disabled:opacity-50"
                    title="Tampilkan data menu lokal terakhir tanpa membuka browser"
                  >
                    <span>Buka Data Terakhir ({cacheInfo.human_age})</span>
                  </button>
                )}

                {/* Button 2: Update Menu Live */}
                <button
                  type="button"
                  disabled={syncPhase === "syncing"}
                  onClick={handleLiveSync}
                  className="px-5 py-2.5 rounded-2xl font-bold text-xs bg-white hover:bg-zinc-100 text-zinc-900 border border-zinc-200 dark:border-zinc-700 shadow-sm transition flex items-center gap-2 cursor-pointer disabled:opacity-50"
                  title="Meluncurkan browser untuk tarik menu live terbaru dari Shopee Partner (allvbadmin)"
                >
                  <svg className={`w-4 h-4 text-zinc-700 ${syncPhase === "syncing" ? "animate-spin" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                  </svg>
                  <span>{syncPhase === "syncing" ? "Sedang Menarik Menu Real-Time..." : "Update Menu Live"}</span>
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Active Jobs Progress Card */}
      {activeJobs.length > 0 && (
        <div className="rounded-3xl border border-orange-200 dark:border-orange-900/40 bg-white dark:bg-zinc-900 p-6 shadow-sm space-y-4">
          <h4 className="text-xs font-bold uppercase tracking-wider text-zinc-500 mb-1">Status PUSH Harga Shopee</h4>
          {activeJobs.map(j => {
            const isRunning = j.status === "PENDING" || j.status === "RUNNING";
            const isSuccess = j.status === "SUCCESS";
            const isFailed = j.status === "FAILED";
            const isPartial = j.status === "PARTIAL_SUCCESS";

            return (
              <div
                key={j.id}
                className={`p-4 rounded-2xl border transition-all flex flex-col gap-3 ${
                  isSuccess ? "bg-emerald-50/40 dark:bg-emerald-950/20 border-emerald-200 dark:border-emerald-900/50" :
                  isFailed ? "bg-red-50/50 dark:bg-red-950/20 border-red-200 dark:border-red-900/50" :
                  isPartial ? "bg-amber-50/40 dark:bg-amber-950/20 border-amber-200 dark:border-amber-900/50" :
                  "bg-zinc-50 dark:bg-zinc-950 border-zinc-200 dark:border-zinc-800 shadow-sm"
                }`}
              >
                <div className="flex justify-between items-start">
                  <div>
                    <div className="text-sm font-bold text-zinc-900 dark:text-white flex items-center gap-2">
                      {j.name}
                    </div>
                    <div className="text-[11px] text-zinc-400 font-mono mt-0.5">
                      JOB ID: {j.id} · PLATFORM: SHOPEE
                    </div>
                  </div>
                  {isRunning ? (
                    <span className="text-[11px] font-bold uppercase px-3 py-1 rounded-full bg-orange-100 text-orange-800 border border-orange-200 inline-flex items-center gap-1.5 shadow-sm">
                      <svg className="animate-spin h-3.5 w-3.5 text-orange-600" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                      </svg>
                      Memproses ({j.progress_pct}%)
                    </span>
                  ) : (
                    <span className={`text-[11px] font-bold uppercase px-3 py-1 rounded-full ${
                      isSuccess ? "bg-emerald-100 text-emerald-800 border border-emerald-200" :
                      isFailed ? "bg-red-100 text-red-800 border border-red-200" :
                      isPartial ? "bg-amber-100 text-amber-800 border border-amber-200" :
                      "bg-orange-100 text-orange-800 border border-orange-200"
                    }`}>
                      {j.status} ({j.progress_pct}%)
                    </span>
                  )}
                </div>

                {/* Progress Bar */}
                <div className="w-full bg-zinc-200 dark:bg-zinc-800 rounded-full h-2 overflow-hidden">
                  <div
                    className={`h-full transition-all duration-300 rounded-full ${
                      isSuccess ? "bg-emerald-500" :
                      isFailed ? "bg-red-500" :
                      isPartial ? "bg-amber-500" :
                      "bg-orange-600"
                    }`}
                    style={{ width: `${j.progress_pct}%` }}
                  />
                </div>

                {/* Step Description */}
                <p className="text-xs text-zinc-600 dark:text-zinc-400 font-medium bg-white dark:bg-zinc-900 p-2.5 rounded-xl border border-zinc-100 dark:border-zinc-800">
                  {j.current_step}
                </p>

                {/* Explicit Error Banner when Failed or Partial */}
                {(j.error_message || isFailed || isPartial) && (
                  <div className="rounded-xl border border-red-200 bg-red-50/90 dark:bg-red-950/40 p-3 flex items-start gap-2 text-xs text-red-800 dark:text-red-300 font-medium shadow-sm">
                    <div className="flex-1">
                      <div className="font-bold text-red-900 dark:text-red-200 mb-0.5">Detail Ringkasan Perubahan:</div>
                      <div>{j.error_message || j.current_step || "Beberapa item gagal diperbarui atau dibatalkan oleh Shopee Portal."}</div>
                    </div>
                  </div>
                )}

                {/* Detailed Breakdown per Item Table */}
                {j.result_metadata?.items_breakdown && j.result_metadata.items_breakdown.length > 0 && (
                  <div className="mt-2 space-y-2">
                    <div className="text-[11px] font-bold text-zinc-700 dark:text-zinc-300 uppercase tracking-wider flex items-center justify-between">
                      <span>Rincian Hasil Pembaruan Per Item ({j.result_metadata.items_breakdown.length} Menu)</span>
                      {isPartial && (
                        <span className="text-amber-700 dark:text-amber-400 font-bold lowercase text-xs">
                          ({j.result_metadata.success_count ?? 0} sukses, {j.result_metadata.fail_count ?? 0} gagal)
                        </span>
                      )}
                    </div>
                    <div className="overflow-x-auto border border-zinc-200 dark:border-zinc-800 rounded-2xl bg-white dark:bg-zinc-900 shadow-xs">
                      <table className="w-full text-left text-xs">
                        <thead className="bg-zinc-100 dark:bg-zinc-950 font-bold uppercase tracking-wider text-zinc-600 dark:text-zinc-400 border-b border-zinc-200 dark:border-zinc-800">
                          <tr>
                            <th className="py-2.5 px-3">Nama Menu</th>
                            <th className="py-2.5 px-3 text-right">Harga Asli</th>
                            <th className="py-2.5 px-3 text-right">Harga Diminta</th>
                            <th className="py-2.5 px-3 text-right">Harga Baru Live</th>
                            <th className="py-2.5 px-3 text-center">Status</th>
                            <th className="py-2.5 px-3">Keterangan / Detail Error</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800 font-semibold">
                          {j.result_metadata.items_breakdown.map((item, idx) => (
                            <tr key={idx} className={item.status === 'SUCCESS' ? 'bg-emerald-50/20 dark:bg-emerald-950/10' : 'bg-red-50/30 dark:bg-red-950/20'}>
                              <td className="py-2.5 px-3 text-zinc-900 dark:text-zinc-100 font-bold">{item.item_name}</td>
                              <td className="py-2.5 px-3 text-right font-mono text-zinc-500 dark:text-zinc-400">{item.old_price ? `Rp ${Number(item.old_price).toLocaleString('id-ID')}` : '-'}</td>
                              <td className="py-2.5 px-3 text-right font-mono text-zinc-900 dark:text-zinc-200">{item.requested_price ? `Rp ${Number(item.requested_price).toLocaleString('id-ID')}` : '-'}</td>
                              <td className="py-2.5 px-3 text-right font-mono text-emerald-700 dark:text-emerald-400">{item.verified_price ? `Rp ${Number(item.verified_price).toLocaleString('id-ID')}` : '-'}</td>
                              <td className="py-2.5 px-3 text-center">
                                <span className={`inline-flex px-2 py-0.5 font-bold rounded-md text-[10px] ${
                                  item.status === 'SUCCESS' ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300' : 'bg-red-100 text-red-800 dark:bg-red-950/60 dark:text-red-300'
                                }`}>
                                  {item.status === 'SUCCESS' ? 'SUKSES' : 'GAGAL'}
                                </span>
                              </td>
                              <td className="py-2.5 px-3 text-xs">
                                {item.error_message ? (
                                  <span className="text-red-700 dark:text-red-400 font-bold flex items-center gap-1">
                                    <span>⚠️</span> {item.error_message}
                                  </span>
                                ) : (
                                  <span className="text-emerald-700 dark:text-emerald-400 font-medium">Terverifikasi di Shopee Portal</span>
                                )}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Menu & Price Edit Table (Step 4: Sesuaikan Harga) */}
      {syncPhase === "done" && selectedBrandObj && (
        <div className="rounded-3xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 shadow-sm space-y-4">
          {/* Step 4 Header & Mode Switcher */}
          <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 border-b border-zinc-200 dark:border-zinc-800 pb-4">
            <div>
              <StepLabel number={4} label="Sesuaikan Harga" active={true} done={false} className="mb-1" />
              <p className="text-[13px] text-zinc-500 dark:text-zinc-400 ml-8">
                Terapkan ke <strong>1 brand</strong> terpilih. Saat ini ada <strong className="text-orange-600 dark:text-orange-400">{changedCount} perubahan</strong>.
                {promoCount > 0 && (
                  <span className="ml-2 text-purple-700 dark:text-purple-400 font-bold">
                    ({promoCount} menu promo aktif dikunci)
                  </span>
                )}
              </p>
            </div>
            <div className="flex items-center gap-1 bg-zinc-100 dark:bg-zinc-950 p-1 rounded-xl shrink-0 self-start lg:self-auto border border-zinc-200 dark:border-zinc-800">
              <button
                type="button"
                onClick={() => {
                  setItemEditMode("single");
                  setSelectedItemIds([]);
                }}
                className={`px-3.5 py-1.5 text-[12px] font-bold rounded-lg transition-all cursor-pointer ${
                  itemEditMode === "single"
                    ? "bg-white dark:bg-zinc-800 text-zinc-800 dark:text-zinc-100 shadow-sm"
                    : "text-zinc-500 dark:text-zinc-400 hover:text-zinc-800 dark:hover:text-zinc-200"
                }`}
              >
                Semua Menu
              </button>
              <button
                type="button"
                onClick={() => {
                  setItemEditMode("multi");
                }}
                className={`px-3.5 py-1.5 text-[12px] font-bold rounded-lg transition-all cursor-pointer ${
                  itemEditMode === "multi"
                    ? "bg-white dark:bg-zinc-800 text-zinc-800 dark:text-zinc-100 shadow-sm"
                    : "text-zinc-500 dark:text-zinc-400 hover:text-zinc-800 dark:hover:text-zinc-200"
                }`}
              >
                Centang Manual
              </button>
            </div>
          </div>

          {/* Adjust Bar & Actions */}
          <div className="pt-1">
            <AdjustBar
              onApply={(mode, type, val) => {
                if (itemEditMode === "multi") {
                  if (selectedItemIds.length === 0) {
                    alert("Silakan pilih/centang item yang ingin diubah terlebih dahulu.");
                    return;
                  }
                  bulkAdj(mode, type, val, selectedItemIds);
                } else {
                  bulkAdj(mode, type, val);
                }
              }}
              buttonText={
                itemEditMode === "multi"
                  ? `Terapkan ke ${selectedItemIds.length} Pilihan`
                  : "Terapkan ke Semua"
              }
              extraActions={
                <>
                  <button
                    type="button"
                    onClick={resetAll}
                    className="px-3.5 py-1.5 text-[13px] font-semibold text-zinc-700 dark:text-zinc-300 bg-zinc-100 dark:bg-zinc-800 hover:bg-zinc-200 dark:hover:bg-zinc-700 rounded-xl transition-colors shrink-0 cursor-pointer"
                  >
                    Reset Harga
                  </button>
                  <button
                    type="button"
                    onClick={openPushConfirmationModal}
                    disabled={pushing || changedCount === 0}
                    className="px-4 py-2 text-[13px] font-bold text-white bg-gradient-to-r from-orange-600 to-red-600 hover:from-orange-700 hover:to-red-700 disabled:opacity-50 rounded-xl shadow-md transition-all shrink-0 flex items-center gap-2 cursor-pointer"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                    </svg>
                    {pushing ? "Memproses..." : `Push ${changedCount} Perubahan`}
                  </button>
                </>
              }
            />
          </div>

          {itemEditMode === "multi" && (
            <div className="flex items-center gap-2 text-[13px] text-zinc-700 dark:text-zinc-300 bg-amber-50/70 dark:bg-amber-950/30 border border-amber-200/80 dark:border-amber-900/40 px-4 py-2.5 rounded-xl">
              <span>Centang item pada menu di bawah yang ingin disesuaikan harganya:</span>
              <div className="flex items-center gap-2 ml-auto">
                <button
                  type="button"
                  onClick={selectAllVisibleItems}
                  className="text-amber-800 dark:text-amber-300 font-bold hover:underline cursor-pointer"
                >
                  Pilih Semua
                </button>
                <span className="text-zinc-300">|</span>
                <button
                  type="button"
                  onClick={deselectAllItems}
                  className="text-zinc-600 dark:text-zinc-400 font-bold hover:underline cursor-pointer"
                >
                  Batal Pilih
                </button>
              </div>
            </div>
          )}

          {/* Menu Table */}
          <div className="overflow-x-auto rounded-2xl border border-zinc-200 dark:border-zinc-800">
            <table className="w-full text-left text-xs min-w-[700px]">
              <thead className="bg-zinc-100 dark:bg-zinc-950 font-bold uppercase tracking-wider text-zinc-600 dark:text-zinc-400 border-b border-zinc-200 dark:border-zinc-800">
                <tr>
                  {itemEditMode === "multi" && <th className="p-3.5 w-12 text-center">Pilih</th>}
                  <th className="p-3.5 min-w-[200px]">Nama Menu</th>
                  <th className="p-3.5 w-36">Kategori</th>
                  <th className="p-3.5 text-right w-36">Harga Saat Ini</th>
                  <th className="p-3.5 text-right w-44">Harga Baru Shopee</th>
                  <th className="p-3.5 text-center w-40">Status Aturan</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800 font-semibold">
                {Object.entries(groups).map(([cat, catItems]) => (
                  <React.Fragment key={cat}>
                    <tr className="bg-orange-50/60 dark:bg-orange-950/30 border-y border-orange-200/50 dark:border-orange-900/40">
                      <td colSpan={itemEditMode === "multi" ? 6 : 5} className="p-3 font-bold text-xs text-orange-900 dark:text-orange-300 uppercase tracking-wider">
                        {cat} ({catItems.length} items)
                      </td>
                    </tr>
                    {catItems.map(item => {
                      const curPrice = edits[selectedBrandId]?.[item.id] ?? item.price;
                      const isEdited = curPrice !== item.price;
                      const { isViolation, message: violationMsg } = checkShopeeViolation(item.price, curPrice);
                      const isChecked = selectedItemIds.includes(item.id);

                      return (
                        <tr key={item.id} className={`transition ${
                          item.is_in_promo
                            ? "bg-purple-50/40 dark:bg-purple-950/20 opacity-85 cursor-not-allowed"
                            : isChecked
                            ? "bg-amber-50/80 dark:bg-amber-950/30"
                            : "hover:bg-zinc-50 dark:hover:bg-zinc-950/50"
                        }`}>
                          {itemEditMode === "multi" && (
                            <td className="p-3.5 text-center align-middle">
                              <input
                                type="checkbox"
                                disabled={item.is_in_promo}
                                checked={!item.is_in_promo && isChecked}
                                title={item.is_in_promo ? "Item sedang dalam promo aktif (tidak dapat diubah)" : ""}
                                onChange={() => !item.is_in_promo && toggleSelectItem(item.id)}
                                className={`h-4 w-4 rounded border-zinc-300 ${
                                  item.is_in_promo ? "opacity-40 cursor-not-allowed" : "text-orange-600 focus:ring-orange-500 cursor-pointer"
                                }`}
                              />
                            </td>
                          )}
                          <td className="p-3.5 text-zinc-900 dark:text-white font-bold align-middle">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span>{item.name}</span>
                              {item.is_in_promo && (
                                <span title="Item sedang dalam promo aktif di ShopeeFood. Harga dasar dikunci oleh portal merchant." className="px-1.5 py-0.5 rounded bg-purple-100 dark:bg-purple-950/60 text-purple-800 dark:text-purple-300 font-bold text-[10px] border border-purple-200 dark:border-purple-800 shrink-0">
                                  PROMO AKTIF
                                </span>
                              )}
                            </div>
                          </td>
                          <td className="p-3.5 text-zinc-500 font-medium align-middle">{item.category}</td>
                          <td className="p-3.5 text-right text-zinc-600 dark:text-zinc-300 font-mono font-bold align-middle">Rp {fmt(item.price)}</td>
                          <td className="p-3.5 text-right align-middle">
                            <input
                              type="text"
                              disabled={item.is_in_promo}
                              title={item.is_in_promo ? "Harga dikunci oleh ShopeeFood karena menu sedang dalam promo aktif" : ""}
                              value={fmt(curPrice)}
                              onChange={(e) => {
                                if (item.is_in_promo) return;
                                const val = parse(e.target.value);
                                setEdits(p => ({
                                  ...p,
                                  [selectedBrandId]: {
                                    ...(p[selectedBrandId] || {}),
                                    [item.id]: val
                                  }
                                }));
                              }}
                              className={`w-32 text-right p-2 rounded-xl border font-mono font-bold text-sm ${
                                item.is_in_promo
                                  ? "border-purple-200 dark:border-purple-900/60 bg-purple-50/50 dark:bg-purple-950/30 text-purple-900 dark:text-purple-300 cursor-not-allowed opacity-80"
                                  : isEdited
                                  ? "border-orange-500 bg-orange-50 dark:bg-orange-950/40 text-orange-900 dark:text-orange-200 focus:ring-2 focus:ring-orange-500/20"
                                  : "border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 text-zinc-900 dark:text-white focus:border-orange-500"
                              }`}
                            />
                          </td>
                          <td className="p-3.5 text-center align-middle">
                            {item.is_in_promo ? (
                              <span title="Harga menu dikunci karena sedang dalam promo aktif di Shopee Partner Portal" className="px-2.5 py-1 rounded-lg bg-purple-100 dark:bg-purple-950/60 text-purple-800 dark:text-purple-300 text-[11px] font-bold border border-purple-200 dark:border-purple-900/60 inline-block">
                                🔒 Promo Aktif (Dikunci)
                              </span>
                            ) : isViolation ? (
                              <span className="px-2.5 py-1 rounded-lg bg-red-100 dark:bg-red-950/60 text-red-700 dark:text-red-300 text-[11px] font-bold border border-red-200 dark:border-red-900/60 inline-block">
                                ⚠️ {violationMsg}
                              </span>
                            ) : isEdited ? (
                              <span className="px-2.5 py-1 rounded-lg bg-emerald-100 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300 text-[11px] font-bold border border-emerald-200 dark:border-emerald-900/60 inline-block">
                                ✓ Valid (Shopee OK)
                              </span>
                            ) : (
                              <span className="text-zinc-400 text-xs">-</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Shopee OTP Interactive Modal */}
      <ShopeeOTPModal
        isOpen={otpModal.isOpen}
        username={otpModal.username}
        phone={otpModal.phone}
        submitting={otpModal.submitting}
        statusMsg={otpModal.statusMsg}
        onSubmitOTP={handleSubmittedOTP}
        onCancel={() => setOtpModal(p => ({ ...p, isOpen: false }))}
      />

      {/* ── Pop-up Push Rich Confirmation Summary Modal ── */}
      {showPushConfirmModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 animate-fade-in"
          onClick={() => setShowPushConfirmModal(false)}
        >
          <div className="bg-white dark:bg-zinc-950 rounded-2xl p-6 max-w-xl w-full shadow-2xl border border-orange-100 dark:border-zinc-800 space-y-4 animate-scale-up max-h-[85vh] flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-start justify-between border-b border-zinc-100 dark:border-zinc-800 pb-3">
              <div>
                <h3 className="text-lg font-bold text-slate-900 dark:text-white">Ringkasan Update Harga Shopee Sebelum Push</h3>
                <p className="text-[13px] text-zinc-500 dark:text-zinc-400 mt-0.5">
                  Tinjau daftar rincian <strong>{pushSummaryList.reduce((acc, s) => acc + s.updates.length, 0)} item</strong> yang akan dikirim ke Merchant Portal.
                </p>
              </div>
              <button type="button" onClick={() => setShowPushConfirmModal(false)}
                className="text-zinc-400 hover:text-zinc-600 dark:text-zinc-500 dark:hover:text-zinc-300 text-lg font-bold"
              >×</button>
            </div>

            {/* Content List */}
            <div className="flex-1 overflow-y-auto space-y-4 pr-1">
              {pushSummaryList.map(summary => (
                <div key={summary.branchId} className="rounded-xl border border-orange-100 dark:border-zinc-800 bg-orange-50/20 dark:bg-zinc-900/40 p-4 space-y-3">
                  <div className="flex items-center justify-between border-b border-orange-100 dark:border-zinc-800 pb-2">
                    <span className="font-bold text-slate-800 dark:text-white text-[15px]">{summary.branchName}</span>
                    <PlatformBadge platform={summary.platform} storeId={summary.storeId} />
                  </div>

                  <div className="space-y-2">
                    {summary.updates.map(u => (
                      <div key={u.id} className="flex flex-col sm:flex-row sm:items-center justify-between rounded-lg bg-zinc-50 dark:bg-zinc-900 p-2.5 border border-zinc-100 dark:border-zinc-800 gap-1 text-[13px]">
                        <div className="min-w-0 flex-1">
                          <p className="font-medium text-slate-800 dark:text-zinc-100 leading-snug text-wrap break-words">{u.name}</p>
                          <span className="text-[12px] text-slate-400 dark:text-zinc-400 uppercase tracking-wider">{u.category}</span>
                        </div>
                        <div className="flex items-center gap-2 shrink-0">
                          <span className="line-through text-slate-400 dark:text-zinc-500">Rp {fmt(u.oldPrice)}</span>
                          <span className="text-slate-400 dark:text-zinc-500">→</span>
                          <span className="font-bold text-slate-900 dark:text-white">Rp {fmt(u.newPrice)}</span>
                          <span className={`rounded px-1.5 py-0.5 text-[12px] font-bold ${
                            u.diff > 0
                              ? "bg-amber-100 text-amber-700 dark:bg-amber-950/60 dark:text-amber-400"
                              : "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-400"
                          }`}>
                            ({u.diff > 0 ? "+" : ""}{u.pct.toFixed(1)}%)
                          </span>
                          {u.isViolation && (
                            <span title={u.violationMsg} className="rounded bg-red-600 text-white text-[12px] font-bold px-1.5 py-0.5">! Batas Shopee</span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>

            {/* Footer Actions */}
            <div className="flex items-center justify-end gap-2 pt-3 border-t border-zinc-100 dark:border-zinc-800">
              <button type="button" onClick={() => setShowPushConfirmModal(false)}
                className="px-4 py-2 bg-zinc-100 hover:bg-zinc-200 text-zinc-700 dark:bg-zinc-800 dark:hover:bg-zinc-700 dark:text-zinc-200 font-semibold text-[14px] rounded-xl transition-colors"
              >
                Batal
              </button>
              <button type="button" onClick={executePushFromModal}
                className="px-5 py-2 bg-gradient-to-r from-orange-600 to-red-600 hover:from-orange-700 hover:to-red-700 text-white font-bold text-[14px] rounded-xl transition-colors shadow-md flex items-center gap-1.5"
              >
                <span>Konfirmasi & Push Update</span>
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
                </svg>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Pop-up Success Modal ── */}
      {showSuccessModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4 animate-fade-in"
          onClick={() => setShowSuccessModal(false)}
        >
          <div className="bg-white dark:bg-zinc-950 rounded-2xl p-6 max-w-sm w-full shadow-2xl border border-orange-100 dark:border-zinc-800 text-center space-y-4 animate-scale-up"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-400 ring-8 ring-emerald-50/60 dark:ring-emerald-950/30">
              <svg className="w-7 h-7" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <div>
              <h3 className="text-lg font-bold text-slate-900 dark:text-white">Update Shopee mulai diproses</h3>
              <p className="text-[15px] text-zinc-500 dark:text-zinc-400 mt-1">
                Job update harga Shopee sudah dikirim. Pantau status job di bagian bawah.
              </p>
            </div>
            <button type="button" onClick={() => setShowSuccessModal(false)}
              className="w-full bg-gradient-to-r from-orange-600 to-red-600 hover:from-orange-700 hover:to-red-700 text-white font-semibold text-[15px] py-2.5 rounded-xl transition-colors shadow-md"
            >
              Lihat status
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
