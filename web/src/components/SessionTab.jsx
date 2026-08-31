import { useState, useEffect, useRef } from "react";

export default function SessionTab({ API_BASE_URL, API_SECRET_KEY }) {
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState("");
  const [filterType, setFilterType] = useState("all");

  // Assign session modal
  const [assignTarget, setAssignTarget] = useState(null);
  const [assignJobId, setAssignJobId] = useState(null);
  const [assignStatus, setAssignStatus] = useState(null); // null|"RUNNING"|"OTP"|"DONE"|"FAILED"
  const [assignError, setAssignError] = useState(null);
  const [otpCode, setOtpCode] = useState("");
  const [otpSubmitting, setOtpSubmitting] = useState(false);
  const [otpChannel, setOtpChannel] = useState("sms"); // "sms" | "whatsapp"
  const [waCooldown, setWaCooldown] = useState(60); // 1 minute cooldown before showing WA option
  const [otpTotalTime, setOtpTotalTime] = useState(900); // 15 minutes overall timeout
  const [waRequesting, setWaRequesting] = useState(false);
  const [waRequested, setWaRequested] = useState(false);
  const pollRef = useRef(null);
  const otpTimerRef = useRef(null);

  const headers = { "X-API-Key": API_SECRET_KEY || "" };

  useEffect(() => { fetchSessions(); }, [API_BASE_URL]);

  const fetchSessions = () => {
    setLoading(true);
    setError(null);
    fetch(`${API_BASE_URL}/api/sessions`, { headers })
      .then(r => { if (!r.ok) throw new Error(); return r.json(); })
      .then(setSessions)
      .catch(() => setError("Gagal memuat status sesi dari server."))
      .finally(() => setLoading(false));
  };

  const fmt = ts => {
    if (!ts) return "-";
    try {
      const d = typeof ts === "number" ? new Date(ts * 1000) : new Date(ts);
      return isNaN(d) ? String(ts) : d.toLocaleString("id-ID", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
    } catch { return String(ts); }
  };

  const formatTimer = sec => {
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${m}:${s < 10 ? "0" : ""}${s}`;
  };

  // ── Assign Session ──────────────────────────────────────────────────────────

  const openAssign = outlet => {
    setAssignTarget(outlet);
    setAssignJobId(null);
    setAssignStatus(null);
    setAssignError(null);
    setOtpCode("");
    setOtpChannel("sms");
    setWaCooldown(60);
    setOtpTotalTime(900);
    setWaRequesting(false);
    setWaRequested(false);
    clearInterval(otpTimerRef.current);
  };

  const closeAssign = () => {
    clearInterval(pollRef.current);
    clearInterval(otpTimerRef.current);
    if (assignStatus === "OTP" && assignTarget) {
      fetch(`${API_BASE_URL}/api/shopee/cancel-otp`, {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ username: assignTarget.phone || assignTarget.store_id, channel: "sms" })
      }).catch(() => {});
    }
    setAssignTarget(null);
    setAssignStatus(null);
  };

  const startAssign = async () => {
    setAssignStatus("RUNNING");
    setAssignError(null);
    setOtpCode("");
    setOtpChannel("sms");
    setWaCooldown(60);
    setOtpTotalTime(900);
    setWaRequesting(false);
    setWaRequested(false);
    clearInterval(otpTimerRef.current);

    try {
      const res = await fetch(`${API_BASE_URL}/api/shopee/assign-session`, {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ outlet_id: assignTarget.id })
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Gagal memulai assign session");
      }
      const { job_id } = await res.json();
      setAssignJobId(job_id);
      pollRef.current = setInterval(() => pollJob(job_id), 3000);
    } catch (e) {
      setAssignStatus("FAILED");
      setAssignError(e.message);
    }
  };

  // Start countdown timer when entering OTP mode
  useEffect(() => {
    if (assignStatus === "OTP") {
      setWaCooldown(60);
      setOtpTotalTime(900);
      clearInterval(otpTimerRef.current);
      otpTimerRef.current = setInterval(() => {
        setWaCooldown(prev => (prev > 0 ? prev - 1 : 0));
        setOtpTotalTime(prev => {
          if (prev <= 1) {
            clearInterval(otpTimerRef.current);
            clearInterval(pollRef.current);
            setAssignStatus("FAILED");
            setAssignError("Waktu verifikasi OTP habis (Timeout 15 menit).");
            if (assignTarget) {
              fetch(`${API_BASE_URL}/api/shopee/cancel-otp`, {
                method: "POST",
                headers: { ...headers, "Content-Type": "application/json" },
                body: JSON.stringify({ username: assignTarget.phone || assignTarget.store_id, channel: "sms" })
              }).catch(() => {});
            }
            return 0;
          }
          return prev - 1;
        });
      }, 1000);
    } else {
      clearInterval(otpTimerRef.current);
    }
    return () => clearInterval(otpTimerRef.current);
  }, [assignStatus, assignTarget]);

  const pollJob = async job_id => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/shopee/assign-job-status/${job_id}`, { headers });
      if (!res.ok) return;
      const data = await res.json();
      if (data.otp_waiting) {
        setAssignStatus(prev => (prev !== "OTP" ? "OTP" : prev));
        return;
      }
      if (data.status === "DONE") {
        clearInterval(pollRef.current);
        clearInterval(otpTimerRef.current);
        setAssignStatus("DONE");
        fetchSessions();
      } else if (data.status === "FAILED") {
        clearInterval(pollRef.current);
        clearInterval(otpTimerRef.current);
        setAssignStatus("FAILED");
        setAssignError(data.error || "Proses login gagal");
      }
    } catch { /* keep polling */ }
  };

  const requestWhatsappOtp = async () => {
    if (waRequesting || waCooldown > 0 || !assignTarget) return;
    setWaRequesting(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/shopee/select-otp-channel`, {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ username: assignTarget.phone || assignTarget.store_id, channel: "whatsapp" })
      });
      if (!res.ok) throw new Error("Gagal beralih ke saluran WhatsApp");
      setOtpChannel("whatsapp");
      setWaRequested(true);
    } catch (e) {
      setAssignError(e.message);
    } finally {
      setWaRequesting(false);
    }
  };

  const submitOtp = async () => {
    if (!otpCode.trim() || !assignTarget) return;
    setOtpSubmitting(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/shopee/submit-otp`, {
        method: "POST",
        headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify({ username: assignTarget.phone, code: otpCode.trim(), channel: otpChannel })
      });
      if (!res.ok) throw new Error("Gagal mengirim OTP");
      setAssignStatus("RUNNING");
      setOtpCode("");
    } catch (e) {
      setAssignError(e.message);
    } finally {
      setOtpSubmitting(false);
    }
  };

  useEffect(() => () => {
    clearInterval(pollRef.current);
    clearInterval(otpTimerRef.current);
  }, []);

  // ── Filter ──────────────────────────────────────────────────────────────────

  const filtered = sessions.filter(s => {
    const q = search.toLowerCase();
    const matchSearch = [s.merchant_name, s.nama_resto_final, s.nama_outlet, s.store_id, s.phone]
      .some(v => (v || "").toLowerCase().includes(q));
    const matchType = filterType === "all"
      || (filterType === "active" && s.has_session)
      || (filterType === "missing" && !s.has_session);
    return matchSearch && matchType;
  });

  const activeCount = sessions.filter(s => s.has_session).length;
  const missingCount = sessions.filter(s => !s.has_session).length;

  // ── UI ──────────────────────────────────────────────────────────────────────

  return (
    <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 shadow-sm">

      {/* Header */}
      <div className="mb-6 flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="text-base font-bold text-zinc-900 dark:text-zinc-100">Manajemen Sesi Shopee</h2>
            <span className="rounded-md bg-orange-100 dark:bg-orange-950/60 px-2 py-0.5 text-xs font-bold text-orange-700 dark:text-orange-400 border border-orange-200 dark:border-orange-900/50">Shopee</span>
          </div>
          <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
            Status sesi login akun owner Shopee per outlet untuk bypass OTP saat push harga
          </p>
        </div>
        <button onClick={fetchSessions} disabled={loading}
          className="inline-flex items-center gap-2 rounded-xl border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800 px-4 py-2 text-sm font-medium text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-700 transition-colors disabled:opacity-50 cursor-pointer">
          <svg className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 1121.21 8H17" />
          </svg>
          Refresh
        </button>
      </div>

      {/* Stats */}
      <div className="mb-6 grid grid-cols-3 gap-4">
        <div className="rounded-xl border border-zinc-100 dark:border-zinc-800 bg-zinc-50/50 dark:bg-zinc-800/50 p-4">
          <span className="text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">Total Outlet</span>
          <p className="mt-2 text-2xl font-bold text-zinc-900 dark:text-zinc-100">{sessions.length}</p>
        </div>
        <div className="rounded-xl border border-emerald-100 dark:border-emerald-900/40 bg-emerald-50/30 dark:bg-emerald-950/20 p-4">
          <span className="text-xs font-semibold uppercase tracking-wider text-emerald-700 dark:text-emerald-400">Sesi Aktif</span>
          <p className="mt-2 text-2xl font-bold text-emerald-800 dark:text-emerald-400">{activeCount}</p>
        </div>
        <div className="rounded-xl border border-rose-100 dark:border-rose-900/40 bg-rose-50/30 dark:bg-rose-950/20 p-4">
          <span className="text-xs font-semibold uppercase tracking-wider text-rose-700 dark:text-rose-400">Perlu Login</span>
          <p className="mt-2 text-2xl font-bold text-rose-800 dark:text-rose-400">{missingCount}</p>
        </div>
      </div>

      {/* Filters */}
      <div className="mb-6 flex flex-col gap-3 md:flex-row md:items-center">
        <div className="relative flex-1">
          <svg className="absolute inset-y-0 left-3 my-auto h-4 w-4 text-zinc-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input type="text" placeholder="Cari merchant, store ID, atau nomor/username..."
            value={search} onChange={e => setSearch(e.target.value)}
            className="w-full rounded-xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 py-2 pl-9 pr-4 text-sm text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 outline-none focus:border-orange-500 focus:ring-1 focus:ring-orange-500" />
        </div>
        <div className="flex flex-wrap gap-2">
          {[["all", "Semua"], ["active", "Aktif"], ["missing", "Perlu Login"]].map(([v, l]) => (
            <button key={v} onClick={() => setFilterType(v)}
              className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors cursor-pointer ${filterType === v ? "bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900" : "bg-zinc-100 dark:bg-zinc-800 text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100"}`}>
              {l}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      {error ? (
        <div className="rounded-xl border border-rose-100 dark:border-rose-900/40 bg-rose-50 dark:bg-rose-950/20 p-4 text-sm text-rose-700 dark:text-rose-400">{error}</div>
      ) : loading ? (
        <div className="py-16 text-center text-zinc-500 dark:text-zinc-400">
          <svg className="mx-auto h-8 w-8 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 1121.21 8H17" />
          </svg>
          <p className="mt-3 text-sm">Memuat data sesi Shopee...</p>
        </div>
      ) : filtered.length === 0 ? (
        <div className="rounded-xl border border-dashed border-zinc-200 dark:border-zinc-700 py-16 text-center text-sm text-zinc-400 dark:text-zinc-500">
          Tidak ada outlet Shopee yang cocok.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-zinc-100 dark:divide-zinc-800 text-left text-sm">
            <thead className="text-xs font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
              <tr>
                <th className="px-4 py-3">Merchant &amp; Outlet</th>
                <th className="px-4 py-3">Store ID</th>
                <th className="px-4 py-3">Akun Owner</th>
                <th className="px-4 py-3">Status Sesi</th>
                <th className="px-4 py-3">Terakhir Aktif</th>
                <th className="px-4 py-3">Aksi</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
              {filtered.map(s => (
                <tr key={s.id} className="hover:bg-zinc-50/50 dark:hover:bg-zinc-800/40 transition-colors">
                  <td className="px-4 py-3">
                    <div className="font-medium text-zinc-900 dark:text-zinc-100">{s.nama_resto_final || s.nama_outlet || s.merchant_name}</div>
                    {s.brand && <div className="text-xs text-zinc-400 dark:text-zinc-500">{s.brand}</div>}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-zinc-500 dark:text-zinc-400">
                    {s.store_id || "-"}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-zinc-600 dark:text-zinc-300">
                    <div>{s.phone || "-"}</div>
                    {s.session_file && <div className="mt-0.5 text-zinc-400 dark:text-zinc-500 break-all max-w-xs font-sans text-[11px]">{s.session_file}</div>}
                  </td>
                  <td className="px-4 py-3">
                    {s.has_session ? (
                      <span className="inline-flex items-center gap-1 rounded-full border border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-950/30 px-2 py-0.5 text-xs font-semibold text-emerald-700 dark:text-emerald-400">
                        <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />Aktif
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 rounded-full border border-rose-200 dark:border-rose-800 bg-rose-50 dark:bg-rose-950/30 px-2 py-0.5 text-xs font-semibold text-rose-700 dark:text-rose-400">
                        <span className="h-1.5 w-1.5 rounded-full bg-rose-500" />Kosong
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs text-zinc-500 dark:text-zinc-400">{fmt(s.last_active)}</td>
                  <td className="px-4 py-3">
                    <button onClick={() => openAssign(s)}
                      className="rounded-lg border border-zinc-200 dark:border-zinc-700 px-3 py-1.5 text-xs font-medium text-zinc-700 dark:text-zinc-300 hover:border-orange-300 hover:bg-orange-50 hover:text-orange-700 dark:hover:border-orange-700 dark:hover:bg-orange-950/30 dark:hover:text-orange-400 transition-colors cursor-pointer">
                      {s.has_session ? "Perbarui Sesi" : "Assign Sesi"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* ── Assign Session Modal ── */}
      {assignTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-zinc-950/60 backdrop-blur-xs p-4" onClick={closeAssign}>
          <div className="bg-white dark:bg-zinc-900 rounded-2xl p-6 max-w-md w-full shadow-xl border border-zinc-200 dark:border-zinc-800 space-y-4" onClick={e => e.stopPropagation()}>

            <div>
              <div className="text-xs font-semibold uppercase tracking-wider text-zinc-400 dark:text-zinc-500 mb-1">Shopee — Assign Sesi</div>
              <h3 className="text-base font-bold text-zinc-900 dark:text-zinc-100">
                {assignTarget.nama_resto_final || assignTarget.merchant_name}
              </h3>
              <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
                Akun: <span className="font-mono">{assignTarget.phone || assignTarget.store_id}</span>
              </p>
            </div>

            {!assignStatus && (
              <div className="rounded-xl bg-zinc-50 dark:bg-zinc-800 p-4 border border-zinc-200/80 dark:border-zinc-700 text-xs text-zinc-600 dark:text-zinc-400 leading-relaxed">
                Sistem akan login ke Shopee Partner menggunakan akun owner outlet ini dan menyimpan sesinya. Push harga berikutnya tidak memerlukan OTP ulang selama sesi masih aktif.
              </div>
            )}

            {assignStatus === "RUNNING" && (
              <div className="flex items-center gap-3 rounded-xl bg-zinc-50 dark:bg-zinc-800 p-4 border border-zinc-200/80 dark:border-zinc-700">
                <svg className="h-5 w-5 animate-spin text-zinc-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 1121.21 8H17" />
                </svg>
                <p className="text-sm text-zinc-600 dark:text-zinc-400">Sedang login ke Shopee Partner...</p>
              </div>
            )}

            {assignStatus === "OTP" && (
              <div className="space-y-3.5 rounded-xl bg-amber-50/90 dark:bg-amber-950/20 p-4 border border-amber-200 dark:border-amber-800">
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-1.5">
                    <span className="relative flex h-2 w-2">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75"></span>
                      <span className="relative inline-flex rounded-full h-2 w-2 bg-amber-500"></span>
                    </span>
                    <p className="text-sm font-semibold text-amber-900 dark:text-amber-200">Verifikasi OTP diperlukan</p>
                  </div>
                  <div className="flex items-center gap-1 font-mono text-xs font-semibold text-amber-800 dark:text-amber-300 bg-amber-100 dark:bg-amber-900/40 px-2 py-0.5 rounded-md border border-amber-200 dark:border-amber-800/80">
                    <svg className="h-3.5 w-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    <span>{formatTimer(otpTotalTime)}</span>
                  </div>
                </div>

                <p className="text-xs text-amber-700 dark:text-amber-400 leading-relaxed">
                  {waRequested ? (
                    <span className="text-emerald-700 dark:text-emerald-400 font-medium">
                      ✓ Shopee mengirimkan kode OTP via <strong>WhatsApp</strong>. Silakan periksa chat WA pada nomor terdaftar.
                    </span>
                  ) : (
                    <>Shopee mengirimkan kode OTP ke nomor terdaftar. Masukkan kode di bawah ini.</>
                  )}
                </p>

                <div className="flex gap-2">
                  <input
                    type="text"
                    inputMode="numeric"
                    maxLength={8}
                    value={otpCode}
                    onChange={e => setOtpCode(e.target.value.replace(/\D/g, ""))}
                    onKeyDown={e => e.key === "Enter" && submitOtp()}
                    placeholder="Kode OTP"
                    autoFocus
                    className="flex-1 rounded-lg border border-amber-300 dark:border-amber-700 bg-white dark:bg-zinc-900 px-3.5 py-2 text-sm font-mono tracking-widest text-zinc-900 dark:text-zinc-100 outline-none focus:border-amber-500 focus:ring-1 focus:ring-amber-500 shadow-xs"
                  />
                  <button
                    onClick={submitOtp}
                    disabled={otpSubmitting || !otpCode.trim()}
                    className="rounded-lg bg-amber-600 hover:bg-amber-700 text-white text-sm font-medium px-5 py-2 transition-colors disabled:opacity-50 cursor-pointer shadow-xs"
                  >
                    {otpSubmitting ? "..." : "Kirim"}
                  </button>
                </div>

                {/* WhatsApp Channel Switcher (appears after 1 minute cooldown) */}
                <div className="pt-1.5 border-t border-amber-200/60 dark:border-amber-800/40">
                  {waCooldown > 0 ? (
                    <div className="flex items-center justify-between text-[11px] text-zinc-500 dark:text-zinc-400">
                      <span>Tidak menerima SMS? Opsi WhatsApp:</span>
                      <span className="font-mono font-medium text-amber-700 dark:text-amber-400">Tersedia dalam {waCooldown}s</span>
                    </div>
                  ) : (
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-zinc-600 dark:text-zinc-400">Tidak menerima SMS?</span>
                      <button
                        type="button"
                        onClick={requestWhatsappOtp}
                        disabled={waRequesting || waRequested}
                        className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors cursor-pointer border ${
                          waRequested
                            ? "border-emerald-300 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300"
                            : "border-emerald-300 dark:border-emerald-700 bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-400 hover:bg-emerald-100 dark:hover:bg-emerald-900/50"
                        } disabled:opacity-75`}
                      >
                        <svg className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" viewBox="0 0 24 24" fill="currentColor">
                          <path d="M.057 24l1.687-6.163c-1.041-1.804-1.588-3.849-1.587-5.946.003-6.556 5.338-11.891 11.893-11.891 3.181.001 6.167 1.24 8.413 3.488 2.245 2.248 3.481 5.236 3.48 8.414-.003 6.557-5.338 11.892-11.893 11.892-1.99-.001-3.951-.5-5.688-1.448l-5.805 1.654zm6.597-3.807c1.676.995 3.276 1.591 5.392 1.592 5.448 0 9.886-4.434 9.889-9.885.002-5.462-4.415-9.89-9.881-9.892-5.452 0-9.887 4.434-9.889 9.884-.001 2.225.651 3.891 1.746 5.634l-.999 3.648 3.742-.981zm11.387-5.464c-.074-.124-.272-.198-.57-.347-.297-.149-1.758-.868-2.031-.967-.272-.099-.47-.149-.669.149-.198.297-.768.967-.941 1.165-.173.198-.347.223-.644.074-.297-.149-1.255-.462-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.297-.347.446-.521.151-.172.2-.296.3-.495.099-.198.05-.372-.025-.521-.075-.148-.669-1.611-.916-2.206-.242-.579-.487-.501-.669-.51l-.57-.01c-.198 0-.52.074-.792.372s-1.04 1.016-1.04 2.479 1.065 2.876 1.213 3.074c.149.198 2.095 3.2 5.076 4.487.709.306 1.263.489 1.694.626.712.226 1.36.194 1.872.118.571-.085 1.758-.719 2.006-1.413.248-.695.248-1.29.173-1.414z"/>
                        </svg>
                        {waRequested ? "Terkirim ke WhatsApp ✓" : waRequesting ? "Memproses..." : "Kirim via WhatsApp"}
                      </button>
                    </div>
                  )}
                </div>
              </div>
            )}

            {assignStatus === "DONE" && (
              <div className="flex items-center gap-3 rounded-xl bg-emerald-50 dark:bg-emerald-950/20 p-4 border border-emerald-200 dark:border-emerald-800">
                <svg className="h-5 w-5 text-emerald-600 dark:text-emerald-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
                <p className="text-sm font-semibold text-emerald-800 dark:text-emerald-300">Sesi berhasil disimpan.</p>
              </div>
            )}

            {assignStatus === "FAILED" && (
              <div className="rounded-xl bg-rose-50 dark:bg-rose-950/20 p-4 border border-rose-200 dark:border-rose-800 space-y-1">
                <p className="text-sm font-semibold text-rose-800 dark:text-rose-300">Assign sesi gagal</p>
                {assignError && <p className="text-xs text-rose-600 dark:text-rose-400 font-mono break-all">{assignError}</p>}
              </div>
            )}

            <div className="flex items-center justify-end gap-3 pt-2">
              <button type="button" onClick={closeAssign}
                className="px-4 py-2 bg-zinc-100 hover:bg-zinc-200 dark:bg-zinc-800 dark:hover:bg-zinc-700 text-zinc-700 dark:text-zinc-300 font-medium text-sm rounded-xl transition cursor-pointer">
                {assignStatus === "DONE" ? "Tutup" : "Batal"}
              </button>
              {(!assignStatus || assignStatus === "FAILED") && (
                <button type="button" onClick={startAssign}
                  className="px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white font-medium text-sm rounded-xl transition cursor-pointer">
                  {assignStatus === "FAILED" ? "Coba Lagi" : "Mulai Login"}
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
