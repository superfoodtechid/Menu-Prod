import { useState, useEffect, useRef } from "react";
import PlatformBadge from "./PlatformBadge";

const PLATFORM_OPTIONS = ["shopee", "gofood", "grab"];

function StepLabel({ number, label, active, done }) {
  return (
    <div className="mb-2.5 flex items-center gap-2">
      <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[13px] font-bold transition-colors ${
        done ? "bg-red-700 text-white dark:bg-white dark:text-black"
          : active ? "bg-red-100 text-red-700 ring-4 ring-red-50 dark:bg-zinc-800 dark:text-white dark:ring-zinc-700"
            : "bg-slate-100 text-slate-400 dark:bg-zinc-900 dark:text-zinc-500"
      }`}>{done ? "✓" : number}</span>
      <span className={`text-[15px] font-bold uppercase tracking-wider ${active || done ? "text-slate-700 dark:text-white" : "text-slate-400 dark:text-zinc-500"}`}>
        {label}
      </span>
    </div>
  );
}

export default function MenuPullTab({ API_BASE_URL, API_SECRET_KEY }) {
  const [selectedPlatforms, setSelectedPlatforms] = useState([]);
  const [allOutlets, setAllOutlets] = useState([]);
  const [loadingOutlets, setLoadingOutlets] = useState(false);
  const [triggering, setTriggering] = useState(false);

  // Search query
  const [searchQuery, setSearchQuery] = useState("");

  // Owner selection state (Filter)
  const [selectedOwner, setSelectedOwner] = useState("");
  const [openOwnerDropdown, setOpenOwnerDropdown] = useState(false);
  const [ownerSearchQuery, setOwnerSearchQuery] = useState("");

  // Parent name selection (Multi-Select)
  const [uniqueParentNames, setUniqueParentNames] = useState([]);
  const [selectedParents, setSelectedParents] = useState([]);

  // Branch list and check state (Multi-Select)
  const [availableBranches, setAvailableBranches] = useState([]);
  const [checkedBranchIds, setCheckedBranchIds] = useState([]);
  const [openPlatformDropdown, setOpenPlatformDropdown] = useState(false);
  const [openOutletDropdown, setOpenOutletDropdown] = useState(false);
  const [openBranchDropdown, setOpenBranchDropdown] = useState(false);

  // Active jobs tracked list
  const [activeJobs, setActiveJobs] = useState([]);
  const [retryingJobIds, setRetryingJobIds] = useState({});
  const [combinedResult, setCombinedResult] = useState(null);
  const [combining, setCombining] = useState(false);
  
  const pollingIntervalsRef = useRef({});
  const activeJobsRef = useRef([]);
  const hasTriggeredCombineRef = useRef(false);

  useEffect(() => {
    activeJobsRef.current = activeJobs;
  }, [activeJobs]);

  const getOutletDisplayName = () => {
    if (selectedParents.length === 0) return "Combined Outlets";
    if (selectedParents.length === 1) return selectedParents[0];
    return `${selectedParents[0]} dan ${selectedParents.length - 1} lainnya`;
  };

  // Trigger C5 combination for current outlet
  const triggerCombineC5 = async (jobList = activeJobs, outletName = getOutletDisplayName()) => {
    const successJobs = jobList.filter((j) => j.status === "SUCCESS" && j.id && !String(j.id).startsWith("err-"));
    const successJobIds = successJobs.map((j) => j.id);
    if (successJobIds.length === 0) return;

    setCombining(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/jobs/combine-c5`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-API-Key": API_SECRET_KEY || ""
        },
        body: JSON.stringify({
          job_ids: successJobIds,
          outlet_name: outletName || "Combined Outlet"
        })
      });
      if (res.ok) {
        const data = await res.json();
        setCombinedResult(data);
      } else {
        const errData = await res.json();
        console.error("Gagal menggabungkan C5:", errData.detail);
      }
    } catch (err) {
      console.error("Error trigger combine-c5:", err);
    } finally {
      setCombining(false);
    }
  };


  // Fetch outlets based on selected platforms
  useEffect(() => {
    if (selectedPlatforms.length === 0) {
      setAllOutlets([]);
      setSelectedOwner("");
      setUniqueParentNames([]);
      setSelectedParents([]);
      setAvailableBranches([]);
      setCheckedBranchIds([]);
      setSearchQuery("");
      setOwnerSearchQuery("");
      setActiveJobs([]);
      setCombinedResult(null);
      return;
    }

    const controller = new AbortController();
    setLoadingOutlets(true);
    setAllOutlets([]);
    setSelectedOwner("");
    setUniqueParentNames([]);
    setSelectedParents([]);
    setAvailableBranches([]);
    setCheckedBranchIds([]);
    setSearchQuery("");
    setOwnerSearchQuery("");
    setActiveJobs([]);
    setCombinedResult(null);

    const params = new URLSearchParams();
    selectedPlatforms.forEach((platform) => params.append("platform", platform));
    const url = `${API_BASE_URL}/api/outlets?${params.toString()}`;

    fetch(url, {
      signal: controller.signal,
      headers: { "X-API-Key": API_SECRET_KEY || "" }
    })
      .then((res) => {
        if (!res.ok) throw new Error("Failed to fetch outlets");
        return res.json();
      })
      .then((data) => {
        setAllOutlets(data);
        setSelectedOwner("");
        setSelectedParents([]);
      })
      .catch((err) => {
        if (err.name === "AbortError") return;
        console.error(err);
        alert("Gagal memuat daftar outlet dari server.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingOutlets(false);
      });

    return () => controller.abort();
  }, [selectedPlatforms, API_BASE_URL, API_SECRET_KEY]);

  // Extract unique owners from allOutlets
  const uniqueOwners = Array.from(
    new Set(allOutlets.map((o) => o.owner).filter((owner) => owner && owner.trim() !== ""))
  ).sort();

  // Update unique parent names (nama_outlet) based on selectedOwner filter
  useEffect(() => {
    const filteredByOwner = selectedOwner
      ? allOutlets.filter((o) => o.owner === selectedOwner)
      : allOutlets;
    const parents = Array.from(
      new Set(filteredByOwner.map((o) => o.nama_outlet || o.nama_resto_final || o.merchant_name).filter(Boolean))
    ).sort();
    setUniqueParentNames(parents);
    setSelectedParents((current) => current.filter((p) => parents.includes(p)));
  }, [allOutlets, selectedOwner]);

  // Update available branches when selectedParents, selectedOwner, or allOutlets changes
  useEffect(() => {
    if (selectedPlatforms.length === 0 || selectedParents.length === 0) {
      setAvailableBranches([]);
      setCheckedBranchIds([]);
      return;
    }

    // Filter branches whose parent name is in selectedParents list and owner matches if selectedOwner exists
    const filtered = allOutlets.filter((o) => {
      const parentName = o.nama_outlet || o.nama_resto_final || o.merchant_name;
      const matchParent = selectedParents.includes(parentName);
      const matchOwner = selectedOwner ? o.owner === selectedOwner : true;
      return matchParent && matchOwner;
    });
    setAvailableBranches(filtered);
    
    // Automatically check all branches of the selected parent outlets
    setCheckedBranchIds(filtered.map((b) => b.id));
  }, [selectedParents, selectedOwner, allOutlets, selectedPlatforms]);

  // Clean up all polling intervals on unmount
  useEffect(() => {
    const pollingIntervals = pollingIntervalsRef.current;
    return () => {
      Object.values(pollingIntervals).forEach(clearInterval);
    };
  }, []);

  // Filtered owners based on owner search query
  const filteredOwners = uniqueOwners.filter((owner) =>
    owner.toLowerCase().includes(ownerSearchQuery.toLowerCase())
  );

  // Filtered parent names based on search query
  const filteredParents = uniqueParentNames.filter((name) =>
    name.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const handlePlatformCheck = (value) => {
    setSelectedPlatforms((current) => current.includes(value)
      ? current.filter((platform) => platform !== value)
      : [...current, value]);
  };

  const handleSelectAllPlatforms = () => {
    setSelectedPlatforms((current) => current.length === PLATFORM_OPTIONS.length ? [] : [...PLATFORM_OPTIONS]);
  };

  // Toggle multiple parents checkbox
  const handleParentCheck = (parentName) => {
    setSelectedParents((current) =>
      current.includes(parentName)
        ? current.filter((p) => p !== parentName)
        : [...current, parentName]
    );
    setActiveJobs([]);
    setCombinedResult(null);
  };

  // Toggle select all parent outlets
  const handleSelectAllParents = () => {
    setSelectedParents((current) =>
      current.length === uniqueParentNames.length ? [] : [...uniqueParentNames]
    );
    setActiveJobs([]);
    setCombinedResult(null);
  };

  // Toggle single branch checkbox
  const handleBranchCheck = (branchId) => {
    setCheckedBranchIds((prev) =>
      prev.includes(branchId)
        ? prev.filter((id) => id !== branchId)
        : [...prev, branchId]
    );
  };

  // Toggle select all branches
  const handleSelectAllBranches = () => {
    if (checkedBranchIds.length === availableBranches.length) {
      setCheckedBranchIds([]);
    } else {
      setCheckedBranchIds(availableBranches.map((b) => b.id));
    }
  };

  // Poll progress for a specific job
  const startPollingJob = (jobId) => {
    if (pollingIntervalsRef.current[jobId]) {
      clearInterval(pollingIntervalsRef.current[jobId]);
    }

    pollingIntervalsRef.current[jobId] = setInterval(() => {
      fetch(`${API_BASE_URL}/api/jobs/${jobId}`, {
        headers: { "X-API-Key": API_SECRET_KEY || "" }
      })
        .then((res) => {
          if (!res.ok) throw new Error("Failed to fetch job status");
          return res.json();
        })
        .then((job) => {
          setActiveJobs((prevJobs) => {
            const nextJobs = prevJobs.map((j) =>
              j.id === jobId
                ? {
                    ...j,
                    status: job.status,
                    progress_pct: job.progress_pct,
                    current_step: job.current_step,
                    error_message: job.error_message,
                    result_metadata: job.result_metadata,
                    outlet_id: job.outlet_id || j.outlet_id,
                  }
                : j
            );
            activeJobsRef.current = nextJobs;

            const allDone = nextJobs.length > 0 && nextJobs.every((j) => j.status === "SUCCESS" || j.status === "FAILED");
            if (allDone && !hasTriggeredCombineRef.current) {
              hasTriggeredCombineRef.current = true;
              setTriggering(false);
              triggerCombineC5(nextJobs);
            }

            return nextJobs;
          });

          if (job.status === "SUCCESS" || job.status === "FAILED") {
            clearInterval(pollingIntervalsRef.current[jobId]);
            delete pollingIntervalsRef.current[jobId];
          }
        })
        .catch((err) => {
          console.error(err);
          clearInterval(pollingIntervalsRef.current[jobId]);
          delete pollingIntervalsRef.current[jobId];
        });
    }, 2000);
  };

  // Trigger Pull Jobs for all checked branches
  const handleTriggerPull = async (e) => {
    e.preventDefault();
    if (checkedBranchIds.length === 0) return;

    setTriggering(true);
    setCombinedResult(null);
    hasTriggeredCombineRef.current = false;

    // Filter branches details that are checked
    const targets = availableBranches.filter((b) => checkedBranchIds.includes(b.id));
    
    // Prepare jobs container
    const newJobsList = [];
    const validJobIdsToPoll = [];

    for (const target of targets) {
      const branchLabel = target.brand || target.nama_outlet || target.merchant_name;
      try {
        const res = await fetch(`${API_BASE_URL}/api/jobs/pull?outlet_id=${target.id}`, {
          method: "POST",
          headers: { "X-API-Key": API_SECRET_KEY || "" }
        });
        if (!res.ok) throw new Error("Failed to trigger job");
        const job = await res.json();

        newJobsList.push({
          id: job.id,
          outlet_id: target.id,
          name: branchLabel,
          platform: target.platform,
          status: job.status,
          progress_pct: job.progress_pct,
          current_step: job.current_step,
          error_message: null,
        });
        validJobIdsToPoll.push(job.id);
      } catch (err) {
        console.error(err);
        newJobsList.push({
          id: `err-${Math.random()}`,
          outlet_id: target.id,
          name: branchLabel,
          platform: target.platform,
          status: "FAILED",
          progress_pct: 0,
          current_step: "Gagal memicu tugas di backend.",
          error_message: err.message,
        });
      }
    }

    setActiveJobs(newJobsList);
    validJobIdsToPoll.forEach(jid => startPollingJob(jid));

    if (validJobIdsToPoll.length === 0) {
      setTriggering(false);
    }
  };

  // Re-run single failed pull job
  const handleReRunPullJob = async (failedJob) => {
    const outletId = failedJob.outlet_id;
    if (!outletId) {
      alert("ID Outlet tidak ditemukan untuk menjalankan ulang tugas ini.");
      return;
    }

    setRetryingJobIds((prev) => ({ ...prev, [failedJob.id]: true }));
    setTriggering(true);
    hasTriggeredCombineRef.current = false;

    try {
      const res = await fetch(`${API_BASE_URL}/api/jobs/pull?outlet_id=${outletId}`, {
        method: "POST",
        headers: { "X-API-Key": API_SECRET_KEY || "" }
      });
      if (!res.ok) throw new Error("Gagal memulai kembali tugas penarikan");
      const newJob = await res.json();

      const updatedJobObj = {
        id: newJob.id,
        outlet_id: outletId,
        name: failedJob.name,
        platform: failedJob.platform,
        status: newJob.status,
        progress_pct: newJob.progress_pct,
        current_step: newJob.current_step,
        error_message: null,
      };

      setActiveJobs((prev) =>
        prev.map((j) => (j.id === failedJob.id ? updatedJobObj : j))
      );

      startPollingJob(newJob.id);
    } catch (err) {
      console.error(err);
      alert(`Gagal menjalankan ulang: ${err.message}`);
    } finally {
      setRetryingJobIds((prev) => {
        const next = { ...prev };
        delete next[failedJob.id];
        return next;
      });
    }
  };

  return (
    <main className="grid grid-cols-1 gap-6 xl:grid-cols-5">
      {/* Left Form: Selectors */}
      <section className="surface-card min-w-0 h-fit space-y-6 p-5 sm:p-6 xl:col-span-2">
        <div className="border-b border-red-100 dark:border-zinc-800 pb-4">
          <p className="text-[13px] font-bold uppercase tracking-[0.18em] text-red-600 dark:text-zinc-400">Langkah 1</p>
          <h2 className="mt-1 text-xl font-bold text-slate-900 dark:text-white">Pilih menu sumber</h2>
          <p className="mt-1 text-[15px] leading-6 text-slate-500 dark:text-zinc-400">Ambil data menu terbaru sebelum melakukan perubahan harga.</p>
        </div>
        
        <form onSubmit={handleTriggerPull} className="space-y-5">
          <div className="relative">
            <StepLabel number={1} label={`Aplikator ${selectedPlatforms.length ? `(${selectedPlatforms.length})` : ""}`} active={selectedPlatforms.length === 0} done={selectedPlatforms.length > 0} />
            <button
              type="button"
              disabled={triggering}
              onClick={() => {
                setOpenPlatformDropdown(!openPlatformDropdown);
                setOpenOutletDropdown(false);
                setOpenBranchDropdown(false);
              }}
              className="field-control flex items-center justify-between text-left font-medium"
              aria-expanded={openPlatformDropdown}
            >
              {selectedPlatforms.length > 0 ? (
                <span className="flex min-w-0 items-center gap-1 overflow-hidden">
                  {selectedPlatforms.map((platform) => <PlatformBadge key={platform} platform={platform} />)}
                </span>
              ) : (
                <span className="text-zinc-400 dark:text-zinc-500">Pilih Aplikator...</span>
              )}
              <svg className={`h-3.5 w-3.5 shrink-0 text-zinc-400 transition-transform ${openPlatformDropdown ? "rotate-180" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>

            {openPlatformDropdown && (
              <>
                <div className="fixed inset-0 z-20" onClick={() => setOpenPlatformDropdown(false)} />
                <div className="absolute left-0 right-0 top-full z-30 mt-1 space-y-1 rounded-xl border border-red-100 dark:border-zinc-800 bg-white dark:bg-black p-2.5 shadow-xl animate-scale-up">
                  <div className="flex items-center justify-between border-b border-slate-100 dark:border-zinc-800 px-1 pb-2">
                    <span className="text-[13px] font-semibold uppercase tracking-wider text-slate-400 dark:text-zinc-500">Terpilih ({selectedPlatforms.length}/{PLATFORM_OPTIONS.length})</span>
                    <button type="button" onClick={handleSelectAllPlatforms} className="text-[13px] font-bold text-red-700 dark:text-red-400 hover:underline">
                      {selectedPlatforms.length === PLATFORM_OPTIONS.length ? "Batal Semua" : "Pilih Semua"}
                    </button>
                  </div>
                  {PLATFORM_OPTIONS.map((value) => {
                    const checked = selectedPlatforms.includes(value);
                    return (
                      <label key={value} className={`flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 transition-colors ${
                        checked ? "bg-red-50/60 dark:bg-zinc-900 text-red-700 dark:text-white font-bold" : "text-slate-700 hover:bg-slate-50 dark:text-white dark:hover:bg-zinc-900"
                      }`}>
                        <input type="checkbox" checked={checked} onChange={() => handlePlatformCheck(value)} className="h-4 w-4 accent-red-700 cursor-pointer" />
                        <PlatformBadge platform={value} selected={checked} />
                      </label>
                    );
                  })}
                </div>
              </>
            )}
          </div>

          {/* 2: OWNER Filter Dropdown */}
          <div className="relative">
            <StepLabel number={2} label={selectedOwner ? "Owner (1)" : "Owner"} active={selectedPlatforms.length > 0 && !selectedOwner} done={!!selectedOwner} />
            <button
              type="button"
              disabled={selectedPlatforms.length === 0 || loadingOutlets || triggering}
              onClick={() => {
                setOpenOwnerDropdown(!openOwnerDropdown);
                setOpenPlatformDropdown(false);
                setOpenOutletDropdown(false);
                setOpenBranchDropdown(false);
              }}
              className="field-control flex items-center justify-between text-left font-medium"
              aria-expanded={openOwnerDropdown}
            >
              <span className={`truncate ${selectedOwner ? "font-semibold text-zinc-800 dark:text-white" : "text-zinc-400 dark:text-zinc-500"}`}>
                {loadingOutlets ? "Memuat..."
                  : selectedPlatforms.length === 0 ? "Pilih Aplikator dulu"
                    : selectedOwner || "Semua Owner"}
              </span>
              <svg className={`h-3.5 w-3.5 shrink-0 text-zinc-400 transition-transform ${openOwnerDropdown ? "rotate-180" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>

            {openOwnerDropdown && (
              <>
                <div className="fixed inset-0 z-20" onClick={() => setOpenOwnerDropdown(false)} />
                <div className="absolute left-0 right-0 top-full z-30 mt-1 min-w-[260px] space-y-2 rounded-xl border border-red-100 dark:border-zinc-800 bg-white dark:bg-black p-2.5 shadow-xl animate-scale-up">
                  <input type="text" placeholder="Cari owner..." value={ownerSearchQuery} onChange={(e) => setOwnerSearchQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && e.preventDefault()} className="field-control py-2" autoFocus />
                  <div className="max-h-52 space-y-0.5 overflow-y-auto pr-1">
                    <button
                      type="button"
                      onClick={() => {
                        setSelectedOwner("");
                        setOpenOwnerDropdown(false);
                      }}
                      className={`w-full text-left cursor-pointer flex items-center justify-between rounded-lg px-2.5 py-2 text-[15px] transition-colors ${
                        !selectedOwner ? "bg-red-50 text-red-700 font-bold dark:bg-zinc-900 dark:text-white" : "text-slate-700 hover:bg-slate-50 dark:text-white dark:hover:bg-zinc-900"
                      }`}
                    >
                      <span className="truncate">Semua Owner</span>
                      {!selectedOwner && <span className="text-red-700 dark:text-white font-bold">✓</span>}
                    </button>
                    {filteredOwners.length === 0 ? (
                      <p className="py-3 text-center text-[15px] text-zinc-400 dark:text-zinc-500">Tidak ada owner cocok</p>
                    ) : filteredOwners.map((name) => {
                      const isSelected = selectedOwner === name;
                      return (
                        <button
                          key={name}
                          type="button"
                          onClick={() => {
                            setSelectedOwner(name);
                            setOpenOwnerDropdown(false);
                          }}
                          className={`w-full text-left cursor-pointer flex items-center justify-between rounded-lg px-2.5 py-2 text-[15px] transition-colors ${
                            isSelected ? "bg-red-50 text-red-700 font-bold dark:bg-zinc-900 dark:text-white" : "text-slate-700 hover:bg-slate-50 dark:text-white dark:hover:bg-zinc-900"
                          }`}
                        >
                          <span className="truncate">{name}</span>
                          {isSelected && <span className="text-red-700 dark:text-white font-bold">✓</span>}
                        </button>
                      );
                    })}
                  </div>
                </div>
              </>
            )}
          </div>

          {/* 3: OUTLET */}
          <div className="relative">
            <StepLabel number={3} label={selectedParents.length ? `Outlet (${selectedParents.length})` : "Outlet"} active={selectedPlatforms.length > 0 && selectedParents.length === 0} done={selectedParents.length > 0} />
            <button
              type="button"
              disabled={selectedPlatforms.length === 0 || loadingOutlets || triggering}
              onClick={() => {
                setOpenOutletDropdown(!openOutletDropdown);
                setOpenPlatformDropdown(false);
                setOpenOwnerDropdown(false);
                setOpenBranchDropdown(false);
              }}
              className="field-control flex items-center justify-between text-left font-medium"
              aria-expanded={openOutletDropdown}
            >
              <span className={`truncate ${selectedParents.length ? "font-semibold text-zinc-800 dark:text-white" : "text-zinc-400 dark:text-zinc-500"}`}>
                {loadingOutlets ? "Memuat..."
                  : selectedPlatforms.length === 0 ? "Pilih Aplikator dulu"
                    : selectedParents.length > 0 ? selectedParents.join(", ") : "Pilih Outlet..."}
              </span>
              <svg className={`h-3.5 w-3.5 shrink-0 text-zinc-400 transition-transform ${openOutletDropdown ? "rotate-180" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>

            {openOutletDropdown && (
              <>
                <div className="fixed inset-0 z-20" onClick={() => setOpenOutletDropdown(false)} />
                <div className="absolute left-0 right-0 top-full z-30 mt-1 min-w-[260px] space-y-2 rounded-xl border border-red-100 dark:border-zinc-800 bg-white dark:bg-black p-2.5 shadow-xl animate-scale-up">
                  <div className="flex items-center justify-between border-b border-slate-100 dark:border-zinc-800 px-1 pb-2">
                    <span className="text-[13px] font-semibold uppercase tracking-wider text-slate-400 dark:text-zinc-500">Terpilih ({selectedParents.length}/{uniqueParentNames.length})</span>
                    <button type="button" onClick={handleSelectAllParents} className="text-[13px] font-bold text-red-700 dark:text-red-400 hover:underline">
                      {selectedParents.length === uniqueParentNames.length ? "Batal Semua" : "Pilih Semua"}
                    </button>
                  </div>
                  <input type="text" placeholder="Cari outlet..." value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)} onKeyDown={(e) => e.key === "Enter" && e.preventDefault()} className="field-control py-2" autoFocus />
                  <div className="max-h-52 space-y-0.5 overflow-y-auto pr-1">
                    {filteredParents.length > 0 && !searchQuery && (
                      <label className="flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 text-[15px] font-bold text-red-700 dark:text-red-400 hover:bg-red-50/40 dark:hover:bg-zinc-900 transition-colors border-b border-slate-100 dark:border-zinc-800 pb-2 mb-1 shrink-0">
                        <input
                          type="checkbox"
                          checked={selectedParents.length === uniqueParentNames.length && uniqueParentNames.length > 0}
                          onChange={handleSelectAllParents}
                          className="h-4 w-4 accent-red-700 cursor-pointer shrink-0"
                        />
                        <span>Pilih Semua Outlet</span>
                      </label>
                    )}
                    {filteredParents.length === 0 ? (
                      <p className="py-3 text-center text-[15px] text-zinc-400 dark:text-zinc-500">Tidak ada outlet cocok</p>
                    ) : filteredParents.map((name) => {
                      const isSelected = selectedParents.includes(name);
                      return (
                        <label
                          key={name}
                          className={`flex cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 text-[15px] transition-colors ${
                            isSelected ? "bg-red-50 text-red-700 font-bold dark:bg-zinc-900 dark:text-white" : "text-slate-700 hover:bg-slate-50 dark:text-white dark:hover:bg-zinc-900"
                          }`}
                        >
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => handleParentCheck(name)}
                            className="h-4 w-4 accent-red-700 cursor-pointer shrink-0"
                          />
                          <span className="truncate">{name}</span>
                        </label>
                      );
                    })}
                  </div>
                </div>
              </>
            )}
          </div>

          {/* 4: CABANG */}
          <div className="relative">
            <StepLabel number={4} label={`Cabang ${availableBranches.length ? `(${checkedBranchIds.length})` : ""}`} active={selectedParents.length > 0 && checkedBranchIds.length === 0} done={checkedBranchIds.length > 0} />
            <button
              type="button"
              disabled={availableBranches.length === 0 || triggering}
              onClick={() => {
                setOpenBranchDropdown(!openBranchDropdown);
                setOpenPlatformDropdown(false);
                setOpenOwnerDropdown(false);
                setOpenOutletDropdown(false);
              }}
              className="field-control flex items-center justify-between text-left font-medium"
              aria-expanded={openBranchDropdown}
            >
              <span className={`truncate ${checkedBranchIds.length ? "font-semibold text-zinc-800 dark:text-white" : "text-zinc-400 dark:text-zinc-500"}`}>
                {selectedParents.length === 0 ? "Pilih Outlet dulu"
                  : checkedBranchIds.length === availableBranches.length ? `Semua Cabang (${availableBranches.length})`
                    : `${checkedBranchIds.length} dari ${availableBranches.length} Cabang`}
              </span>
              <svg className={`h-3.5 w-3.5 shrink-0 text-zinc-400 transition-transform ${openBranchDropdown ? "rotate-180" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>

            {openBranchDropdown && (
              <>
                <div className="fixed inset-0 z-20" onClick={() => setOpenBranchDropdown(false)} />
                <div className="absolute left-0 right-0 top-full z-30 mt-1 min-w-[280px] space-y-2 rounded-xl border border-red-100 dark:border-zinc-800 bg-white dark:bg-black p-2.5 shadow-xl animate-scale-up">
                  <div className="flex items-center justify-between border-b border-slate-100 dark:border-zinc-800 pb-2">
                    <span className="text-[13px] font-semibold uppercase tracking-wider text-slate-400 dark:text-zinc-500">Terpilih ({checkedBranchIds.length}/{availableBranches.length})</span>
                    <button type="button" onClick={handleSelectAllBranches} className="text-[13px] font-bold text-red-700 dark:text-red-400 hover:underline">
                      {checkedBranchIds.length === availableBranches.length ? "Batal Semua" : "Pilih Semua"}
                    </button>
                  </div>
                  <div className="max-h-60 space-y-0.5 overflow-y-auto pr-1">
                    {availableBranches.map((branch) => {
                      const checked = checkedBranchIds.includes(branch.id);
                      const branchLabel = branch.brand || branch.nama_outlet || branch.merchant_name;
                      return (
                        <label key={branch.id} className={`flex cursor-pointer items-start gap-2.5 rounded-lg px-2.5 py-2 transition-colors ${
                          checked ? "bg-red-50/60 dark:bg-zinc-900 text-red-700 dark:text-white font-bold" : "text-slate-700 hover:bg-slate-50 dark:text-white dark:hover:bg-zinc-900"
                        }`}>
                          <input type="checkbox" checked={checked} onChange={() => handleBranchCheck(branch.id)} className="mt-1 h-4 w-4 accent-red-700 cursor-pointer" />
                          <span className="min-w-0 flex-1">
                            <span className={`block truncate text-[15px] ${checked ? "font-bold text-zinc-800 dark:text-white" : "text-slate-700 dark:text-zinc-300"}`}>{branchLabel}</span>
                            <PlatformBadge platform={branch.platform} storeId={branch.store_id || "No Store ID"} className="mt-1" />
                          </span>
                        </label>
                      );
                    })}
                  </div>
                </div>
              </>
            )}
          </div>

          <button
            type="submit"
            disabled={checkedBranchIds.length === 0 || triggering}
            className="primary-action w-full"
          >
            {triggering ? "Menjalankan..." : `Tarik ${checkedBranchIds.length} Menu`}
          </button>
        </form>
      </section>

      {/* Right Status Panel: Active/Completed Jobs List */}
      <section className="min-w-0 space-y-6 xl:col-span-3">
        <div className="surface-card flex min-h-[420px] flex-col p-5 sm:p-6">
          <div className="mb-4 border-b border-red-100 dark:border-zinc-800 pb-4 flex justify-between items-end">
            <div>
              <p className="text-[13px] font-bold uppercase tracking-[0.18em] text-red-600 dark:text-zinc-400">Aktivitas</p>
              <h2 className="mt-1 text-xl font-bold text-slate-900 dark:text-white">Status penarikan menu</h2>
            </div>
            {activeJobs.some(j => j.status === "SUCCESS") && (
              <button
                type="button"
                disabled={combining || triggering}
                onClick={() => triggerCombineC5(activeJobs)}
                className="secondary-action text-[13px] px-3 py-1.5 gap-1.5"
              >
                <svg className="w-3.5 h-3.5 fill-none stroke-current stroke-2" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
                {combining ? "Menggabungkan..." : "Gabung Ulang C5"}
              </button>
            )}
          </div>

          {combining && (
            <div className="mb-4 rounded-xl border border-amber-200 dark:border-amber-900/60 bg-amber-50/60 dark:bg-amber-950/30 p-3.5 flex items-center gap-2 text-[13px] font-semibold text-amber-800 dark:text-amber-300 animate-scale-up">
              <svg className="w-4 h-4 animate-spin text-amber-600 dark:text-amber-400 shrink-0" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              <span>Menggabungkan file C5 per outlet & mengunggah ke Google Sheets...</span>
            </div>
          )}

          {combinedResult && (
            <div className="mb-4 rounded-xl border border-red-200 dark:border-zinc-700 bg-gradient-to-r from-red-50/80 to-amber-50/40 dark:from-zinc-900 dark:to-zinc-900/80 p-4 shadow-sm animate-scale-up">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-base font-bold text-slate-900 dark:text-white truncate">
                      Combined C5 — {combinedResult.outlet_name}
                    </h3>
                    <span className="rounded-full bg-red-100 dark:bg-red-950 px-2.5 py-0.5 text-[12px] font-bold text-red-700 dark:text-red-300 border border-red-200 dark:border-red-800 shrink-0">
                      {combinedResult.combined_count} Cabang Tergabung
                    </span>
                  </div>
                  <p className="text-[13px] leading-relaxed text-slate-600 dark:text-zinc-400">
                    File C5 seluruh cabang outlet <strong>{combinedResult.outlet_name}</strong> telah digabungkan menjadi satu file.
                  </p>
                </div>
                <div className="flex flex-col gap-2 shrink-0 sm:w-auto w-full">
                  {combinedResult.gspread_url && (
                    <a
                      href={combinedResult.gspread_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="secondary-action justify-center gap-1.5 px-3.5 py-2 text-[13px] w-full"
                    >
                      <svg className="w-3.5 h-3.5 fill-current shrink-0" viewBox="0 0 24 24">
                        <path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2m-7 14H6v-2h6v2zm8-4H6v-2h14v2zm0-4H6V7h14v2z" />
                      </svg>
                      <span>Buka Combined Google Sheets</span>
                    </a>
                  )}
                  <a
                    href={`${API_BASE_URL}${combinedResult.download_url}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="rounded-lg bg-red-700 px-3.5 py-2 text-[13px] font-bold text-white shadow-sm transition hover:bg-red-800 flex items-center justify-center gap-1.5 w-full"
                  >
                    <svg className="w-3.5 h-3.5 fill-none stroke-current stroke-2 shrink-0" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                    </svg>
                    <span>Unduh Combined C5 Excel</span>
                  </a>
                </div>
              </div>
            </div>
          )}

          {activeJobs.length === 0 ? (
            <div className="my-auto rounded-2xl border border-dashed border-red-200 bg-red-50/40 dark:border-zinc-800 dark:bg-zinc-950/60 px-6 py-14 text-center">
              <div className="mx-auto mb-3 flex h-11 w-11 items-center justify-center rounded-full bg-white dark:bg-zinc-800 text-red-600 dark:text-white shadow-sm font-bold">↓</div>
              <p className="font-semibold text-slate-700 dark:text-white">Belum ada aktivitas</p>
              <p className="mt-1 text-[15px] text-slate-500 dark:text-zinc-400">Pilih platform dan outlet, lalu tarik menu untuk melihat progres.</p>
            </div>
          ) : (
            <div className="space-y-4 max-h-[600px] overflow-y-auto pr-2">
              {activeJobs.map((job) => (
                <div key={job.id} className="space-y-3 rounded-xl border border-red-100 dark:border-zinc-800 bg-red-50/25 dark:bg-zinc-900 p-4">
                  <div className="flex justify-between items-start">
                    <div>
                      <div className="text-[15px] font-semibold text-zinc-800 dark:text-white">{job.name}</div>
                      <div className="mt-1 flex flex-wrap items-center gap-2">
                        <PlatformBadge platform={job.platform} />
                        <span className="text-[13px] text-slate-400">ID: {job.id}</span>
                      </div>
                    </div>
                    <span className={`text-[13px] font-bold uppercase tracking-wider px-2.5 py-1 rounded-full ${
                      job.status === "SUCCESS" ? "bg-emerald-100 text-emerald-700" :
                      job.status === "FAILED" ? "bg-red-100 text-red-700" :
                      "bg-amber-100 text-amber-700"
                    }`}>
                      {job.status}
                    </span>
                  </div>

                  <div className="space-y-1">
                    <div className="flex justify-between items-center text-[13px] text-zinc-400">
                      <span>Langkah: {job.current_step}</span>
                      <span>{job.progress_pct}%</span>
                    </div>
                    <div className="w-full bg-zinc-100 rounded-full h-1.5 overflow-hidden">
                      <div
                        className={`h-1.5 transition-all duration-300 ${job.status === "FAILED" ? "bg-red-500" : job.status === "SUCCESS" ? "bg-emerald-500" : "bg-red-600"}`}
                        style={{ width: `${job.progress_pct}%` }}
                      ></div>
                    </div>
                  </div>

                  {job.error_message && (
                    <div className="rounded-lg border border-red-200 bg-red-50 p-2 text-[13px] text-red-700">
                      {job.error_message}
                    </div>
                  )}

                  {job.status === "FAILED" && (
                    <div className="pt-2 border-t border-red-100 flex justify-end">
                      <button
                        type="button"
                        onClick={() => handleReRunPullJob(job)}
                        disabled={retryingJobIds[job.id]}
                        className="inline-flex items-center gap-1.5 rounded-lg bg-red-700 px-3 py-1.5 text-[13px] font-semibold text-white shadow-sm transition hover:bg-red-800 disabled:opacity-50"
                      >
                        <svg className="w-3.5 h-3.5 fill-none stroke-current stroke-2" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                        </svg>
                        {retryingJobIds[job.id] ? "Memulai Ulang..." : "Coba Lagi (Re-run)"}
                      </button>
                    </div>
                  )}

                  {job.status === "SUCCESS" && (
                    <div className="pt-2 border-t border-zinc-100 flex justify-end gap-2">
                      {job.result_metadata?.gspread_url && (
                        <a
                          href={job.result_metadata.gspread_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="secondary-action gap-1.5 px-3 py-1.5 text-[13px]"
                        >
                          <svg className="w-3.5 h-3.5 fill-current" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                            <path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2m-7 14H6v-2h6v2zm8-4H6v-2h14v2zm0-4H6V7h14v2z" />
                          </svg>
                          Buka Google Sheets
                        </a>
                      )}
                      <a
                        href={`${API_BASE_URL}/api/jobs/download/${job.id}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="rounded-lg bg-red-700 px-3 py-1.5 text-[13px] font-semibold text-white shadow-sm transition hover:bg-red-800"
                      >
                        Unduh Excel C5
                      </a>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </section>
    </main>
  );
}
