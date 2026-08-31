import { useState, useEffect, useRef, useCallback, useMemo, Fragment } from "react";
import PlatformBadge from "./PlatformBadge";
import { fmt, parse, applyAdj, checkViolation } from "./shared/priceUtils";
import StepLabel from "./shared/StepLabel";
import AdjustBar from "./shared/AdjustBar";
import PushConfirmModal from "./shared/PushConfirmModal";
import StickyBottomBar from "./shared/StickyBottomBar";
import SearchFilterInput from "./shared/SearchFilterInput";
import PriceInput from "./shared/PriceInput";
import PromoBadgeTooltip from "./shared/PromoBadgeTooltip";

const group = (items) => {
  if (!items || !Array.isArray(items)) return {};
  return items.reduce((a, i) => {
    if (!i) return a;
    const cat = i.category || "General";
    (a[cat] ??= []).push(i);
    return a;
  }, {});
};

// ─── Main Component ───────────────────────────────────────────────────────────
export default function EditHargaTab({ API_BASE_URL, API_SECRET_KEY }) {
  const [platform, setPlatform] = useState("");
  const [allOutlets, setAllOutlets] = useState([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [uniqueParents, setUniqueParents] = useState([]);
  const [selectedParent, setSelectedParent] = useState("");
  const [branches, setBranches] = useState([]);
  const [selectedBrandId, setSelectedBrandId] = useState("");
  const [checkedIds, setCheckedIds] = useState([]);
  const [branchMenus, setBranchMenus] = useState({});
  const [edits, setEdits] = useState({});
  const [saveState, setSaveState] = useState({});
  const [verificationMap, setVerificationMap] = useState({}); // { [bid]: { [itemId]: { targetPrice, actualPrice, status } } }

  // GSheet auto-sync state
  const [gsheetSyncing, setGsheetSyncing] = useState(false);
  const [gsheetSyncedAt, setGsheetSyncedAt] = useState(null);

  // Auto-pull sync state
  const [syncPhase, setSyncPhase] = useState("idle"); // "idle" | "syncing" | "done"
  const [syncJobs, setSyncJobs] = useState([]);
  const syncPollingRef = useRef({});

  const [openPlatformDropdown, setOpenPlatformDropdown] = useState(false);
  const [openOutletDropdown, setOpenOutletDropdown] = useState(false);
  const [openBranchDropdown, setOpenBranchDropdown] = useState(false);

  const [pushing, setPushing] = useState(false);
  const [showSuccessModal, setShowSuccessModal] = useState(false);
  const [showPushConfirmModal, setShowPushConfirmModal] = useState(false);
  const [pushSummaryList, setPushSummaryList] = useState([]); // [{ branchId, branchName, updates: [{ id, name, category, oldPrice, newPrice, pct, isViolation, violationMsg }] }]
  const [intendedPushPrices, setIntendedPushPrices] = useState({}); // { [bid]: { [itemId]: targetPrice } }

  const [activeJobs, setActiveJobs] = useState([]);
  const [showPostPushMenu, setShowPostPushMenu] = useState(false);
  const pushPollingIntervalsRef = useRef({});

  // Item Selection Edit Controls state in Step 4
  const [itemEditMode, setItemEditMode] = useState("single"); // "single" | "multi" | "all"
  const [selectedItemIds, setSelectedItemIds] = useState([]);

  const toggleSelectItem = (itemId) => {
    setSelectedItemIds(prev =>
      prev.includes(itemId) ? prev.filter(id => id !== itemId) : [...prev, itemId]
    );
  };

  const [menuSearch, setMenuSearch] = useState("");

  const selectAllVisibleItems = (items) => {
    const validIds = (items || []).filter(i => !i.is_price_locked).map(i => i.id);
    setSelectedItemIds(validIds);
  };

  const deselectAllItems = () => {
    setSelectedItemIds([]);
  };

  // Trigger GSheet sync from backend POST /api/sync-sheets
  const triggerGSheetSync = useCallback(async () => {
    setGsheetSyncing(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/sync-sheets`, {
        method: "POST",
        headers: { "X-API-Key": API_SECRET_KEY || "" }
      });
      if (res.ok) {
        setGsheetSyncedAt(new Date().toLocaleTimeString("id-ID", { hour: '2-digit', minute: '2-digit', second: '2-digit' }));
      }
    } catch (err) {
      console.error("GSheet sync error:", err);
    } finally {
      setGsheetSyncing(false);
    }
  }, [API_BASE_URL, API_SECRET_KEY]);

  // Clear auto-pull polling intervals
  const clearSyncPolling = useCallback(() => {
    Object.values(syncPollingRef.current).forEach(clearInterval);
    syncPollingRef.current = {};
  }, []);

  // fetch outlets when platform changes
  useEffect(() => {
    clearSyncPolling();
    if (!platform) {
      setAllOutlets([]); setUniqueParents([]); setSelectedParent("");
      setBranches([]); setSelectedBrandId(""); setCheckedIds([]); setSearch(""); setEdits({}); setBranchMenus({});
      setSyncPhase("idle"); setSyncJobs([]); setVerificationMap({});
      setOpenOutletDropdown(false); setOpenBranchDropdown(false);
      return;
    }
    setLoading(true);
    setAllOutlets([]); setUniqueParents([]); setSelectedParent("");
    setBranches([]); setSelectedBrandId(""); setCheckedIds([]); setSearch(""); setEdits({}); setBranchMenus({});
    setSyncPhase("idle"); setSyncJobs([]); setVerificationMap({});

    // Sync GSheet first when platform is selected
    triggerGSheetSync().then(() => {
      const url = `${API_BASE_URL}/api/outlets?platform=${platform}`;
      return fetch(url, { headers: { "X-API-Key": API_SECRET_KEY || "" } })
        .then(r => r.ok ? r.json() : [])
        .then(data => {
          const list = Array.isArray(data) ? data : [];
          setAllOutlets(list);
          setUniqueParents(Array.from(new Set(list.map(o => o.nama_outlet || o.nama_resto_final || o.merchant_name).filter(Boolean))).sort());
        });
    }).catch((err) => {
      console.error("Error fetching outlets:", err);
      setAllOutlets([]);
      setUniqueParents([]);
    })
      .finally(() => setLoading(false));
  }, [platform, API_BASE_URL, API_SECRET_KEY, clearSyncPolling, triggerGSheetSync]);

  // Fetch menu items and run verification check against intended push prices
  const fetchMenusAndVerify = useCallback(async (targetBranches, targetIntendedPrices = intendedPushPrices) => {
    setLoading(true);
    const menusMap = {};
    const editsMap = {};
    const newVerifications = { ...verificationMap };

    await Promise.all(targetBranches.map(async (b) => {
      try {
        const res = await fetch(`${API_BASE_URL}/api/outlets/${b.id}/menu-items`, {
          headers: { "X-API-Key": API_SECRET_KEY || "" }
        });
        if (res.ok) {
          const items = await res.json();
          menusMap[b.id] = items;
          editsMap[b.id] = {};
          
          const branchIntended = targetIntendedPrices[b.id] || {};
          const branchVer = {};

          items.forEach(i => {
            editsMap[b.id][i.id] = i.price;
            if (branchIntended[i.id] !== undefined) {
              const targetP = branchIntended[i.id];
              const isMatch = i.price === targetP;
              branchVer[i.id] = {
                targetPrice: targetP,
                actualPrice: i.price,
                status: isMatch ? "VERIFIED" : "PENDING_SYNC"
              };
            }
          });

          if (Object.keys(branchVer).length > 0) {
            newVerifications[b.id] = branchVer;
          }
        } else {
          menusMap[b.id] = [];
        }
      } catch {
        menusMap[b.id] = [];
      }
    }));

    setBranchMenus(prev => ({ ...prev, ...menusMap }));
    setEdits(prev => ({ ...prev, ...editsMap }));
    setVerificationMap(newVerifications);
    setLoading(false);
  }, [API_BASE_URL, intendedPushPrices, verificationMap]);

  // Clean up polling intervals on unmount
  useEffect(() => {
    const pushIntervals = pushPollingIntervalsRef.current;
    const syncIntervals = syncPollingRef.current;
    return () => {
      Object.values(pushIntervals).forEach(clearInterval);
      Object.values(syncIntervals).forEach(clearInterval);
    };
  }, []);

  // Trigger real-time Auto-Pull for chosen brand
  const triggerAutoPull = useCallback(async (targetBranches, customIntendedPrices = intendedPushPrices) => {
    if (!targetBranches || targetBranches.length === 0) return;
    clearSyncPolling();
    setSyncPhase("syncing");

    const initialJobs = targetBranches.map(b => ({
      id: null,
      branchId: b.id,
      name: b.brand || b.nama_resto_final || b.merchant_name,
      storeId: b.store_id,
      platform: b.platform,
      status: "PENDING",
      progress_pct: 0,
      current_step: "Mengantrekan tugas penarikan real-time...",
      name: b.brand || b.nama_outlet || b.merchant_name,
      platform: b.platform || "shopee",
    }));
    setSyncJobs(initialJobs);

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
            platform: b.platform,
            status: job.status,
            progress_pct: job.progress_pct,
            current_step: job.current_step,
            error_message: null
          });
        } else {
          createdJobs.push({
            id: `err-${b.id}`,
            branchId: b.id,
            name: label,
            storeId: b.store_id,
            platform: b.platform,
            status: "FAILED",
            progress_pct: 0,
            current_step: "Gagal memicu tugas di backend.",
            error_message: "Response status error"
          });
        }
      } catch (err) {
        createdJobs.push({
          id: `err-${b.id}`,
          branchId: b.id,
          name: label,
          storeId: b.store_id,
          platform: b.platform,
          status: "FAILED",
          progress_pct: 0,
          current_step: "Gagal menghubungkan ke server.",
          error_message: err.message
        });
      }
    }

    setSyncJobs(createdJobs);

    const activeJobIds = createdJobs.filter(j => j.id && !j.id.startsWith("err-")).map(j => j.id);
    if (activeJobIds.length === 0) {
      fetchMenusAndVerify(targetBranches, customIntendedPrices);
      setSyncPhase("done");
      return;
    }

    activeJobIds.forEach(jobId => {
      syncPollingRef.current[jobId] = setInterval(() => {
        fetch(`${API_BASE_URL}/api/jobs/${jobId}`, {
          headers: { "X-API-Key": API_SECRET_KEY || "" }
        })
          .then(r => r.ok ? r.json() : null)
          .then(job => {
            if (!job) return;
            setSyncJobs(prev => prev.map(j => j.id === jobId ? {
              ...j,
              status: job.status,
              progress_pct: job.progress_pct,
              current_step: job.current_step,
              error_message: job.error_message
            } : j));

            if (job.status === "SUCCESS" || job.status === "FAILED") {
              clearInterval(syncPollingRef.current[jobId]);
              delete syncPollingRef.current[jobId];

              if (Object.keys(syncPollingRef.current).length === 0) {
                fetchMenusAndVerify(targetBranches, customIntendedPrices);
                setSyncPhase("done");
                if (targetBranches[0]?.id) {
                  fetchCacheStatus(targetBranches[0].id);
                }
              }
            }
          })
          .catch(err => console.error("Error polling sync job:", err));
      }, 2000);
    });

  }, [API_BASE_URL, API_SECRET_KEY, clearSyncPolling, fetchMenusAndVerify, intendedPushPrices]);

  const [cacheInfo, setCacheInfo] = useState(null);

  const fetchCacheStatus = (branchId) => {
    if (!branchId) return;
    fetch(`${API_BASE_URL}/api/outlets/${branchId}/menu-cache-status`, {
      headers: { "X-API-Key": API_SECRET_KEY || "" }
    })
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (data) setCacheInfo(data);
      })
      .catch(err => console.error("Error fetching cache status:", err));
  };

  // When selected parent (Outlet) changes
  const handleSelectOutlet = (name) => {
    setSelectedParent(name);
    setOpenOutletDropdown(false);
    const targetBranches = allOutlets.filter(o => (o.nama_outlet || o.nama_resto_final || o.merchant_name) === name);
    setBranches(targetBranches);
    setSelectedBrandId("");
    setCheckedIds([]);
    setSyncPhase("idle");
    setCacheInfo(null);
    triggerGSheetSync();
  };

  // When selected brand changes (Single Select)
  const handleSelectBrand = (branchId) => {
    setSelectedBrandId(branchId);
    setCheckedIds([branchId]);
    setOpenBranchDropdown(false);
    setSyncPhase("idle");
    setCacheInfo(null);
    fetchCacheStatus(branchId);
    triggerGSheetSync();
  };

  // Start Pull & Edit
  const handleStartPullAndEdit = () => {
    setActiveJobs([]);
    setShowPostPushMenu(false);
    const targetBranches = branches.filter(b => b.id === selectedBrandId);
    if (targetBranches.length > 0) {
      triggerAutoPull(targetBranches);
    }
  };

  // Skip pull and jump straight to editing
  const handleSkipSync = () => {
    setActiveJobs([]);
    setShowPostPushMenu(false);
    clearSyncPolling();
    const targetBranches = branches.filter(b => b.id === selectedBrandId);
    fetchMenusAndVerify(targetBranches);
    setSyncPhase("done");
  };

  const isPushInProgress = activeJobs.length > 0 && activeJobs.some(j => j.status === "PENDING" || j.status === "RUNNING");
  const isPushCompleted = activeJobs.length > 0 && activeJobs.every(j => j.status === "SUCCESS" || j.status === "FAILED" || j.status === "PARTIAL_SUCCESS");

  const filtered = uniqueParents.filter(n => n.toLowerCase().includes(search.toLowerCase()));
  const selectedBrandObj = branches.find(b => b.id === selectedBrandId);
  const preview = branches.filter(b => checkedIds.includes(b.id));

  const totalChanges = preview.reduce((total, branch) => {
    const items = branchMenus[branch.id] || [];
    return total + items.filter(item => !item.is_price_locked && (edits[branch.id]?.[item.id] ?? item.price) !== item.price).length;
  }, 0);

  const violationCount = preview.reduce((total, branch) => {
    const items = branchMenus[branch.id] || [];
    return total + items.filter(item => {
      if (item.is_price_locked) return false;
      const curPrice = edits[branch.id]?.[item.id] ?? item.price;
      const { isViolation } = checkViolation(platform, item.price, curPrice);
      return isViolation;
    }).length;
  }, 0);

  const currentItems = selectedBrandId ? (branchMenus[selectedBrandId] || []) : [];
  const filteredItems = useMemo(() => {
    if (!menuSearch.trim()) return currentItems;
    const q = menuSearch.toLowerCase();
    return currentItems.filter(i => (i.name && i.name.toLowerCase().includes(q)) || (i.category && i.category.toLowerCase().includes(q)));
  }, [currentItems, menuSearch]);

  const groups = group(filteredItems);

  const changePrice = (bid, iid, newPriceVal) => {
    const items = branchMenus[bid] || [];
    const targetItem = items.find(i => i.id === iid);
    if (targetItem?.is_price_locked) return;

    const val = typeof newPriceVal === "number" ? newPriceVal : parse(newPriceVal);
    setEdits(p => ({ ...p, [bid]: { ...p[bid], [iid]: val } }));
    setSaveState(p => ({ ...p, [bid]: null }));
  };

  const bulkAdj = (bids, mode, type, val, targetItemIds = null) => {
    const targets = bids.length ? bids : checkedIds;
    setEdits(p => {
      const n = { ...p };
      targets.forEach(bid => {
        const items = branchMenus[bid] || [];
        const be = { ...(p[bid] || {}) };
        items.forEach(i => {
          if (i.is_price_locked) return;
          if (!targetItemIds || targetItemIds.includes(i.id)) {
            be[i.id] = applyAdj(be[i.id] ?? i.price, mode, type, val);
          }
        });
        n[bid] = be;
      });
      return n;
    });
    setSaveState(p => { const n = { ...p }; targets.forEach(id => { n[id] = null; }); return n; });
  };

  const startPollingPushJob = (jobId, branchId) => {
    if (pushPollingIntervalsRef.current[jobId]) {
      clearInterval(pushPollingIntervalsRef.current[jobId]);
    }

    pushPollingIntervalsRef.current[jobId] = setInterval(() => {
      fetch(`${API_BASE_URL}/api/jobs/${jobId}`, {
        headers: { "X-API-Key": API_SECRET_KEY || "" }
      })
        .then((res) => {
          if (!res.ok) throw new Error("Failed to fetch job");
          return res.json();
        })
        .then((job) => {
          setActiveJobs((prevJobs) =>
            prevJobs.map((j) =>
              j.id === jobId
                ? {
                    ...j,
                    status: job.status,
                    progress_pct: job.progress_pct,
                    current_step: job.current_step,
                    error_message: job.error_message,
                    result_metadata: job.result_metadata
                  }
                : j
            )
          );

          if (job.status === "SUCCESS" || job.status === "FAILED" || job.status === "PARTIAL_SUCCESS") {
            clearInterval(pushPollingIntervalsRef.current[jobId]);
            delete pushPollingIntervalsRef.current[jobId];

            // Refresh local menu data for target branch quietly without secondary loading card
            const targetBranch = branches.filter(b => b.id === branchId);
            if (targetBranch.length > 0) {
              fetchMenusAndVerify(targetBranch, intendedPushPrices);
            }
          }
        })
        .catch((err) => {
          console.error(err);
          clearInterval(pushPollingIntervalsRef.current[jobId]);
          delete pushPollingIntervalsRef.current[jobId];
        });
    }, 2000);
  };

  const triggerPriceUpdate = async (bidsToUpdate) => {
    setPushing(true);
    setShowPostPushMenu(false);
    const targets = Array.isArray(bidsToUpdate) ? bidsToUpdate : [bidsToUpdate];
    const newJobsList = [];
    const newIntended = { ...intendedPushPrices };

    for (const bid of targets) {
      const branch = branches.find(x => x.id === bid);
      if (!branch) continue;
      const label = branch.brand || branch.nama_outlet || branch.merchant_name;

      const branchEdits = edits[bid] || {};
      const branchItems = branchMenus[bid] || [];
      const updates = [];
      const branchIntendedMap = {};

      branchItems.forEach(i => {
        if (i.is_price_locked) return;
        const curPrice = branchEdits[i.id];
        if (curPrice !== undefined && curPrice !== i.price) {
          updates.push({
            item_id: i.id,
            category_id: i.category_id || "",
            item_name: i.name || "",
            new_price: curPrice
          });
          branchIntendedMap[i.id] = curPrice;
        }
      });

      if (updates.length === 0) continue;

      newIntended[bid] = { ...(newIntended[bid] || {}), ...branchIntendedMap };

      try {
        setSaveState(p => ({ ...p, [bid]: "saving" }));
        const res = await fetch(`${API_BASE_URL}/api/jobs/push-price`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-API-Key": API_SECRET_KEY || ""
          },
          body: JSON.stringify({
            outlet_id: bid,
            updates: updates
          })
        });

        if (res.ok) {
          const job = await res.json();
          newJobsList.push({
            id: job.id,
            name: label,
            platform: branch.platform,
            status: job.status,
            progress_pct: job.progress_pct,
            current_step: job.current_step,
            error_message: null
          });
          // Update local item baseline & reset pending edits
          setBranchMenus(prev => {
            const prevList = prev[bid] || [];
            return {
              ...prev,
              [bid]: prevList.map(item => {
                const newP = branchEdits[item.id];
                return newP !== undefined ? { ...item, price: newP } : item;
              })
            };
          });
          setEdits(prev => ({ ...prev, [bid]: {} }));
          startPollingPushJob(job.id, bid);
          setSaveState(p => ({ ...p, [bid]: "saved" }));
        } else {
          setSaveState(p => ({ ...p, [bid]: null }));
          alert(`Gagal memicu update harga untuk ${label}`);
        }
      } catch (err) {
        setSaveState(p => ({ ...p, [bid]: null }));
        console.error(err);
      }
    }

    setIntendedPushPrices(newIntended);
    if (newJobsList.length > 0) {
      setActiveJobs(p => [...newJobsList, ...p]);
    }
    setPushing(false);
    return newJobsList.length;
  };

  // Open rich push summary modal before sending update
  const openPushConfirmationModal = (bidsToUpdate = checkedIds) => {
    const targets = Array.isArray(bidsToUpdate) ? bidsToUpdate : [bidsToUpdate];
    const summary = [];

    targets.forEach(bid => {
      const branch = branches.find(x => x.id === bid);
      if (!branch) return;
      const bLabel = branch.brand || branch.nama_outlet || branch.merchant_name;
      const branchItems = branchMenus[bid] || [];
      const itemUpdates = [];

      branchItems.forEach(item => {
        const curPrice = edits[bid]?.[item.id] ?? item.price;
        if (curPrice !== item.price) {
          const diff = curPrice - item.price;
          const pct = item.price > 0 ? (diff / item.price) * 100 : 0;
          const { isViolation, message: violationMsg } = checkViolation(branch.platform, item.price, curPrice);
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

      if (itemUpdates.length > 0) {
        summary.push({
          branchId: bid,
          branchName: bLabel,
          platform: branch.platform,
          storeId: branch.store_id,
          updates: itemUpdates
        });
      }
    });

    if (summary.length === 0) {
      alert("Tidak ada perubahan harga yang terdeteksi.");
      return;
    }

    setPushSummaryList(summary);
    setShowPushConfirmModal(true);
  };

  const executePushFromModal = async () => {
    setShowPushConfirmModal(false);
    const targetBids = pushSummaryList.map(s => s.branchId);
    const queuedJobs = await triggerPriceUpdate(targetBids);
    if (queuedJobs > 0) {
      setShowSuccessModal(true);
    }
  };

  const resetOne = (bid, items) => {
    const r = {}; items.forEach(i => { r[i.id] = i.price; });
    setEdits(p => ({ ...p, [bid]: r }));
    setSaveState(p => ({ ...p, [bid]: null }));
  };

  const resetAll = () => {
    setEdits(p => {
      const n = { ...p };
      preview.forEach(b => {
        const items = branchMenus[b.id] || [];
        const r = {}; items.forEach(i => { r[i.id] = i.price; }); n[b.id] = r;
      });
      return n;
    });
    setSaveState({});
  };

  const applyBranchToAll = (sourceBranchId) => {
    const sourceEdits = edits[sourceBranchId];
    if (!sourceEdits) return;
    setEdits(p => {
      const n = { ...p };
      preview.forEach(b => {
        n[b.id] = { ...(n[b.id] || {}), ...sourceEdits };
      });
      return n;
    });
    setSaveState({});
  };

  const completedSyncCount = syncJobs.filter(j => j.status === "SUCCESS" || j.status === "FAILED").length;
  const totalSummaryItems = pushSummaryList.reduce((acc, s) => acc + s.updates.length, 0);

  return (
    <main className="flex flex-col gap-6 pb-28">
      {/* ── Top: Controls ── */}
      <section className="surface-card p-5 sm:p-6 space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between border-b border-red-100 dark:border-zinc-800 pb-4 gap-2">
          <div>
            <p className="text-[13px] font-bold uppercase tracking-[0.18em] text-red-600 dark:text-zinc-400">Pengaturan harga</p>
            <h2 className="mt-1 text-xl font-bold text-slate-900 dark:text-white">Tentukan target perubahan</h2>
            <p className="mt-1 text-[15px] text-slate-500 dark:text-zinc-400">Pilih aplikator, outlet, dan brand (single-select), lalu lakukan tarik menu real-time sebelum melakukan perubahan harga.</p>
          </div>
          <div className="flex items-center gap-2 text-[13px] font-medium shrink-0">
            {gsheetSyncing ? (
              <span className="inline-flex items-center gap-1.5 text-amber-700 dark:text-amber-400 font-semibold">
                <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                Syncing GSheet...
              </span>
            ) : gsheetSyncedAt ? (
              <span className="inline-flex items-center gap-1.5 text-emerald-700 dark:text-emerald-400 font-bold uppercase tracking-wider">
                <span>Gsheet Synced</span>
                <span className="text-[11px] font-medium tracking-normal text-emerald-600/90 dark:text-emerald-400/90 lowercase">
                  ({gsheetSyncedAt})
                </span>
              </span>
            ) : null}
          </div>
        </div>

        <div className="grid grid-cols-1 items-start gap-5 md:grid-cols-3">

          {/* 1: Aplikator */}
          <div className="relative">
            <StepLabel number={1} label="Aplikator" active={!platform} done={!!platform} />
            <button type="button"
              disabled={syncPhase === "syncing"}
              onClick={() => {
                setOpenPlatformDropdown(!openPlatformDropdown);
                setOpenOutletDropdown(false);
                setOpenBranchDropdown(false);
              }}
              className="field-control flex items-center justify-between text-left font-medium"
            >
              <span className="truncate flex items-center gap-1.5">
                {platform ? (
                  <PlatformBadge platform={platform} />
                ) : (
                  <span className="text-zinc-400 dark:text-slate-500">Pilih Aplikator...</span>
                )}
              </span>
              <svg className={`w-3.5 h-3.5 text-zinc-400 shrink-0 transition-transform ${openPlatformDropdown ? "rotate-180" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>

            {openPlatformDropdown && (
              <>
                <div className="fixed inset-0 z-20" onClick={() => setOpenPlatformDropdown(false)} />
                <div className="absolute left-0 right-0 top-full mt-1 z-30 bg-white dark:bg-black rounded-xl shadow-xl border border-red-100 dark:border-zinc-800 p-1.5 space-y-0.5 animate-scale-up">
                  {[
                    ["gofood", "GoFood"],
                    ["grab", "GrabFood"]
                  ].map(([val]) => (
                    <button key={val} type="button"
                      onClick={() => {
                        setPlatform(val);
                        setOpenPlatformDropdown(false);
                      }}
                      className={`w-full text-left px-3 py-2 rounded-md text-[15px] flex items-center justify-between transition-all ${
                        platform === val ? "bg-red-50 text-red-700 font-bold dark:bg-zinc-900 dark:text-white" : "text-slate-700 hover:bg-slate-50 dark:text-white dark:hover:bg-zinc-900"
                      }`}
                    >
                      <PlatformBadge platform={val} />
                      {platform === val && <span className="text-red-700 dark:text-white font-bold">✓</span>}
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>

          {/* 2: Outlet (Single Select) */}
          <div className="relative">
            <StepLabel number={2} label={selectedParent ? `Outlet (1)` : "Outlet"} active={!!platform && !selectedParent} done={!!selectedParent} />
            <button type="button"
              disabled={!platform || loading || syncPhase === "syncing"}
              onClick={() => {
                setOpenOutletDropdown(!openOutletDropdown);
                setOpenPlatformDropdown(false);
                setOpenBranchDropdown(false);
              }}
              className="field-control flex items-center justify-between text-left font-medium"
            >
              <span className={`truncate ${selectedParent ? "text-zinc-800 dark:text-white font-semibold" : "text-zinc-400 dark:text-zinc-500"}`}>
                {loading
                  ? "Memuat..."
                  : !platform
                  ? "Pilih Aplikator dulu"
                  : selectedParent || "Pilih Outlet..."}
              </span>
              <svg className={`w-3.5 h-3.5 text-zinc-400 shrink-0 transition-transform ${openOutletDropdown ? "rotate-180" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>

            {openOutletDropdown && (
              <>
                <div className="fixed inset-0 z-20" onClick={() => setOpenOutletDropdown(false)} />
                <div className="absolute left-0 right-0 top-full mt-1 z-30 bg-white dark:bg-black rounded-xl shadow-xl border border-red-100 dark:border-zinc-800 p-2.5 space-y-2 animate-scale-up min-w-[240px]">
                  <input type="text" placeholder="Cari outlet..." value={search} onChange={e => setSearch(e.target.value)}
                    className="field-control py-2" autoFocus
                  />

                  <div className="max-h-48 overflow-y-auto space-y-0.5 pr-1">
                    {filtered.length === 0 ? (
                      <p className="text-center text-[15px] text-zinc-400 dark:text-zinc-500 py-3">Tidak ada outlet cocok</p>
                    ) : (
                      filtered.map(name => {
                        const isSelected = selectedParent === name;
                        return (
                          <button key={name} type="button"
                            onClick={() => handleSelectOutlet(name)}
                            className={`w-full text-left px-2.5 py-2 rounded-md text-[15px] flex items-center justify-between transition-colors ${
                              isSelected ? "bg-red-50 text-red-700 font-bold dark:bg-zinc-900 dark:text-white" : "text-slate-700 hover:bg-slate-50 dark:text-white dark:hover:bg-zinc-900"
                            }`}
                          >
                            <span className="truncate">{name}</span>
                            {isSelected && <span className="text-red-700 dark:text-white font-bold">✓</span>}
                          </button>
                        );
                      })
                    )}
                  </div>
                </div>
              </>
            )}
          </div>

          {/* 3: Brand (Single Select) */}
          <div className="relative">
            <StepLabel number={3} label={selectedBrandId ? "Brand (1)" : "Brand"} active={!!selectedParent && !selectedBrandId} done={!!selectedBrandId} />
            <button type="button"
              disabled={!selectedParent || syncPhase === "syncing"}
              onClick={() => {
                setOpenBranchDropdown(!openBranchDropdown);
                setOpenPlatformDropdown(false);
                setOpenOutletDropdown(false);
              }}
              className="field-control flex items-center justify-between text-left font-medium"
            >
              <span className={`truncate font-semibold ${!selectedBrandObj ? "text-slate-400 dark:text-zinc-500" : "text-slate-800 dark:text-white"}`}>
                {!selectedParent
                  ? "Pilih Outlet dulu"
                  : selectedBrandObj
                  ? (selectedBrandObj.brand || selectedBrandObj.nama_outlet || selectedBrandObj.merchant_name)
                  : "Pilih Brand..."}
              </span>
              <svg className={`w-3.5 h-3.5 text-zinc-400 shrink-0 transition-transform ${openBranchDropdown ? "rotate-180" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>

            {openBranchDropdown && (
              <>
                <div className="fixed inset-0 z-20" onClick={() => setOpenBranchDropdown(false)} />
                <div className="absolute left-0 right-0 top-full mt-1 z-30 bg-white dark:bg-black rounded-xl shadow-xl border border-red-100 dark:border-zinc-800 p-2.5 space-y-2 animate-scale-up min-w-[280px]">
                  <div className="max-h-48 overflow-y-auto space-y-0.5 pr-1">
                    {branches.map(b => {
                      const isSelected = selectedBrandId === b.id;
                      const l = b.brand || b.nama_outlet || b.merchant_name;
                      return (
                        <button key={b.id} type="button"
                          onClick={() => handleSelectBrand(b.id)}
                          className={`w-full text-left px-2.5 py-2 rounded-md text-[15px] flex items-center justify-between transition-colors ${
                            isSelected ? "bg-red-50 text-red-700 font-bold dark:bg-zinc-900 dark:text-white" : "text-slate-700 hover:bg-slate-50 dark:text-white dark:hover:bg-zinc-900"
                          }`}
                        >
                          <div className="min-w-0 flex-1">
                            <span className="block truncate">{l}</span>
                            <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[12px] font-normal">
                              <PlatformBadge platform={b.platform} storeId={b.store_id || "No Store ID"} />
                              {b.cabang && <span className="text-slate-400 dark:text-zinc-400">· Cabang: {b.cabang}</span>}
                            </div>
                          </div>
                          {isSelected && <span className="text-red-700 dark:text-white font-bold ml-2">✓</span>}
                        </button>
                      );
                    })}
                  </div>
                </div>
              </>
            )}
          </div>

        </div>

        {/* Pull Actions & 24h Cache Section */}
        {selectedBrandId && (
          <div className="pt-3 border-t border-red-100 dark:border-zinc-800 flex flex-col sm:flex-row items-center justify-between gap-3">
            <div className="text-[13px] text-zinc-600 dark:text-zinc-400 font-medium flex items-center gap-2">
              {cacheInfo?.has_cache ? (
                <span className={`text-[13px] font-medium ${
                  cacheInfo.is_valid_24h
                    ? "text-zinc-500 dark:text-zinc-400"
                    : "text-amber-600 dark:text-amber-400"
                }`}>
                  Terakhir ditarik: <strong>{cacheInfo.human_age}</strong>
                  {!cacheInfo.is_valid_24h && " (>24 jam)"}
                </span>
              ) : (
                <span className="text-zinc-400 dark:text-zinc-500 font-normal">Belum ada cache menu lokal.</span>
              )}
            </div>

            <div className="flex items-center gap-2 w-full sm:w-auto">
              {/* Existing Pull / Fast Load Cached Button */}
              {cacheInfo?.has_cache && (
                <button
                  type="button"
                  disabled={syncPhase === "syncing"}
                  onClick={handleSkipSync}
                  className={`px-4 py-2.5 rounded-xl font-bold text-[14px] bg-[#403D88] hover:bg-[#34316e] text-white shadow-sm flex items-center gap-2 transition-all ${
                    syncPhase === "syncing" ? "opacity-50 cursor-not-allowed pointer-events-none" : "cursor-pointer"
                  }`}
                  title="Tampilkan data menu lokal terakhir tanpa membuka browser"
                >
                  <span>Buka Data Terakhir ({cacheInfo.human_age})</span>
                </button>
              )}

              {/* Fresh Pull Button (Always Live Syncs) */}
              <button
                type="button"
                disabled={syncPhase === "syncing"}
                onClick={handleStartPullAndEdit}
                className={`inline-flex items-center justify-center rounded-xl font-bold text-white dark:text-black shadow-md transition gap-2 px-5 py-2.5 text-[14px] ${
                  syncPhase === "syncing" ? "opacity-50 cursor-not-allowed pointer-events-none" : ""
                } ${
                  cacheInfo?.has_cache ? "bg-black hover:bg-zinc-800 dark:bg-white dark:hover:bg-zinc-200" : "bg-red-700 hover:bg-red-800 dark:bg-white dark:hover:bg-zinc-200"
                }`}
                title="Meluncurkan browser untuk tarik menu live terbaru dari portal merchant"
              >
                <svg className={`w-4 h-4 ${syncPhase === "syncing" ? "animate-spin" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
                {syncPhase === "syncing"
                  ? "Sedang Menarik Menu Real-Time..."
                  : cacheInfo?.has_cache
                  ? "Update Menu Live"
                  : "Tarik Real-Time Menu & Edit Harga"}
              </button>
            </div>
          </div>
        )}
      </section>

      {/* ── Auto-Pull Syncing Loading Section ── */}
      {syncPhase === "syncing" && (
        <section className="surface-card p-6 space-y-5 border-2 border-red-200 dark:border-zinc-800 bg-red-50/20 dark:bg-zinc-900/40">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-red-100 dark:border-zinc-800 pb-4">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-red-700 text-white shadow-md">
                <svg className="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                </svg>
              </div>
              <div>
                <h3 className="text-base font-bold text-slate-900 dark:text-white">Menarik data menu real-time...</h3>
                <p className="text-[13px] text-slate-500 dark:text-zinc-400">
                  Brand: <strong>{selectedBrandObj ? (selectedBrandObj.brand || selectedBrandObj.nama_outlet || selectedBrandObj.merchant_name) : selectedParent}</strong> ({completedSyncCount}/{syncJobs.length} selesai)
                </p>
              </div>
            </div>
          </div>

          <div className="space-y-3 max-h-80 overflow-y-auto pr-1">
            {syncJobs.map(job => (
              <div key={job.branchId || job.id} className="rounded-xl border border-red-100 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 space-y-2.5 shadow-sm">
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <p className="text-[15px] font-semibold text-slate-800 dark:text-white truncate">{job.name}</p>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[12px]">
                      <PlatformBadge platform={job.platform} storeId={job.storeId} />
                    </div>
                  </div>
                  <span className={`px-2.5 py-1 rounded-full text-[13px] font-bold uppercase tracking-wider ${
                    job.status === "SUCCESS" ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-400" :
                    job.status === "FAILED" ? "bg-red-100 text-red-700 dark:bg-red-950/60 dark:text-red-400" :
                    "bg-amber-100 text-amber-700 dark:bg-amber-950/60 dark:text-amber-400"
                  }`}>
                    {job.status === "SUCCESS" ? "SELESAI ✓" : job.status === "FAILED" ? "GAGAL ✗" : `${job.progress_pct}%`}
                  </span>
                </div>

                <div className="w-full bg-slate-100 dark:bg-zinc-800 rounded-full h-1.5 overflow-hidden">
                  <div className={`h-1.5 transition-all duration-300 ${
                    job.status === "SUCCESS" ? "bg-emerald-500" :
                    job.status === "FAILED" ? "bg-red-500" :
                    "bg-red-600"
                  }`} style={{ width: `${job.progress_pct}%` }} />
                </div>

                <div className="flex items-center justify-between text-[13px]">
                  <span className="text-slate-500 dark:text-zinc-400 truncate">{job.current_step || "Mengantrekan..."}</span>
                  {job.error_message && (
                    <span className="text-red-600 dark:text-red-400 font-medium truncate ml-2">{job.error_message}</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* ── Middle: Global Bulk Adjust & Mode Switcher (Step 4: Sesuaikan Harga) ── */}
      {syncPhase === "done" && preview.length > 0 && (
        <section className="surface-card p-5 lg:p-6 space-y-4">
          <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 border-b border-red-100 dark:border-zinc-800 pb-4">
            <div>
              <StepLabel number={4} label="Sesuaikan Harga" active={true} done={false} className="mb-1" />
              <p className="text-[13px] text-zinc-500 dark:text-zinc-400 ml-8">
                Terapkan ke <strong>{preview.length} brand</strong> terpilih. Saat ini ada <strong className="text-red-700 dark:text-red-400">{totalChanges} item disesuaikan</strong>.
              </p>
            </div>
            <div className="flex items-center gap-1 bg-zinc-150 dark:bg-zinc-900 p-1 rounded-xl shrink-0 self-start lg:self-auto border border-zinc-200 dark:border-zinc-700">
              <button
                type="button"
                onClick={() => {
                  setItemEditMode("single");
                  deselectAllItems();
                }}
                className={`px-3 py-1.5 text-[12px] font-bold rounded-lg transition-all cursor-pointer ${
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
                className={`px-3 py-1.5 text-[12px] font-bold rounded-lg transition-all cursor-pointer ${
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
              onApply={(m, t, v) => {
                if (itemEditMode === "multi") {
                  if (selectedItemIds.length === 0) {
                    alert("Silakan pilih/centang item yang ingin diubah terlebih dahulu.");
                    return;
                  }
                  bulkAdj([], m, t, v, selectedItemIds);
                } else {
                  bulkAdj([], m, t, v);
                }
              }}
              buttonText={
                itemEditMode === "multi"
                  ? `Terapkan ke ${selectedItemIds.length} Pilihan`
                  : "Terapkan ke Semua"
              }
              extraActions={
                <>
                  <button type="button" onClick={resetAll}
                    className="px-3.5 py-1.5 text-[13px] font-semibold text-zinc-700 bg-zinc-100 hover:bg-zinc-200 rounded-xl transition-colors shrink-0 cursor-pointer"
                  >
                    Reset Harga
                  </button>
                  <button type="button" onClick={() => openPushConfirmationModal(checkedIds)} disabled={pushing || totalChanges === 0}
                    className="primary-action gap-2 px-4 py-1.5 text-[13px] font-bold shrink-0"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                        d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
                    </svg>
                    {pushing ? "Mengirim job..." : `Push ${totalChanges} Perubahan`}
                  </button>
                </>
              }
            />
          </div>
        </section>
      )}

      {/* ── Active Push Price Jobs & Real-Time Verification Section (Single Unified Loading Process) ── */}
      {activeJobs.length > 0 && (
        <section className="surface-card space-y-4 p-5 shadow-sm border border-zinc-200/80 rounded-2xl">
          <div className="flex items-center justify-between">
            <h3 className="text-[14px] font-bold text-zinc-800 uppercase tracking-wider">
              Proses Pembaruan Harga & Verifikasi Real-Time
            </h3>
          </div>
          <div className="space-y-3.5 max-h-[400px] overflow-y-auto pr-1">
            {activeJobs.map(job => {
              const isRunning = job.status === "PENDING" || job.status === "RUNNING";
              const isSuccess = job.status === "SUCCESS";
              const isFailed = job.status === "FAILED";
              const isPartial = job.status === "PARTIAL_SUCCESS";

              return (
                <div 
                  key={job.id} 
                  className={`p-4 rounded-xl border transition-all flex flex-col gap-3 ${
                    isSuccess ? "bg-emerald-50/40 dark:bg-emerald-950/20 border-emerald-200 dark:border-emerald-900/50" :
                    isFailed ? "bg-red-50/50 dark:bg-red-950/20 border-red-200 dark:border-red-900/50" :
                    isPartial ? "bg-amber-50/40 dark:bg-amber-950/20 border-amber-200 dark:border-amber-900/50" :
                    "bg-zinc-50 dark:bg-zinc-900 border-zinc-200 dark:border-zinc-800 shadow-sm"
                  }`}
                >
                  <div className="flex justify-between items-start">
                    <div>
                      <div className="text-[15px] font-bold text-zinc-800 dark:text-zinc-100 flex items-center gap-2">
                        {job.name}
                      </div>
                      <div className="text-[12px] text-zinc-400 dark:text-zinc-500 font-mono mt-0.5">
                        JOB ID: {job.id} · PLATFORM: {job.platform?.toUpperCase()}
                      </div>
                    </div>
                    {isRunning ? (
                      <span className="text-[12px] font-bold uppercase px-3 py-1 rounded-full bg-blue-50 text-blue-800 border border-blue-200 inline-flex items-center gap-1.5 shadow-sm">
                        <svg className="animate-spin h-3.5 w-3.5 text-blue-700" fill="none" viewBox="0 0 24 24">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                        </svg>
                        Memproses
                      </span>
                    ) : (
                      <span className={`text-[12px] font-bold uppercase px-3 py-1 rounded-full ${
                        isSuccess ? "bg-emerald-100 text-emerald-800 border border-emerald-200" :
                        isFailed ? "bg-red-100 text-red-800 border border-red-200" :
                        isPartial ? "bg-amber-100 text-amber-800 border border-amber-200" :
                        "bg-blue-100 text-blue-800 border border-blue-200"
                      }`}>
                        {job.status}
                      </span>
                    )}
                  </div>
                  
                  {/* Progress Bar & Percentage */}
                  <div className="space-y-1">
                    <div className="flex justify-between text-[12px] font-semibold text-zinc-600 dark:text-zinc-400">
                      <span>Proses Push & Verifikasi</span>
                      <span>{job.progress_pct || 0}%</span>
                    </div>
                    <div className="w-full bg-zinc-100 dark:bg-zinc-800 rounded-full h-2 overflow-hidden border border-zinc-200/60 dark:border-zinc-700/60">
                      <div 
                        className={`h-full transition-all duration-500 rounded-full ${
                          isSuccess ? "bg-emerald-500" :
                          isFailed ? "bg-red-500" :
                          isPartial ? "bg-amber-500" :
                          "bg-gradient-to-r from-red-500 to-amber-500"
                        }`} 
                        style={{ width: `${job.progress_pct || 0}%` }} 
                      />
                    </div>
                  </div>
                  
                  {/* Live Step Description */}
                  <div className="text-[13px] text-zinc-700 dark:text-zinc-300 font-medium flex items-center gap-2 bg-zinc-50 dark:bg-zinc-800/60 p-2.5 rounded-lg border border-zinc-100 dark:border-zinc-700/60">
                    <span>{job.current_step || "Mengantrekan tugas..."}</span>
                  </div>

                  {/* Explicit Error Banner when Failed or Partial */}
                  {(job.error_message || isFailed) && (
                    <div className="rounded-xl border border-red-200 bg-red-50/90 p-3 flex items-start gap-2 text-[13px] text-red-800 font-medium shadow-sm">
                      <div className="flex-1">
                        <div className="font-bold text-red-900 mb-0.5">Detail Kesalahan Pembaruan:</div>
                        <div>{job.error_message || "Pembaruan harga tidak dapat diselesaikan atau 0 item terverifikasi."}</div>
                      </div>
                    </div>
                  )}

                  {/* Rincian Verifikasi Hasil Per Item */}
                  {job.result_metadata?.items_breakdown && job.result_metadata.items_breakdown.length > 0 && (
                    <div className="mt-1 space-y-2">
                      <div className="text-[12px] font-bold text-zinc-700 uppercase tracking-wider flex items-center justify-between">
                        <span>Rincian Hasil Verifikasi Per Item ({job.result_metadata.items_breakdown.length} Menu)</span>
                      </div>
                      <div className="overflow-x-auto border border-zinc-200/80 dark:border-zinc-700/80 rounded-xl bg-white dark:bg-zinc-900 shadow-xs">
                        <table className="w-full text-left text-[12px]">
                          <thead className="bg-zinc-50 dark:bg-zinc-800 border-b border-zinc-200/80 dark:border-zinc-700/80 font-semibold text-zinc-600 dark:text-zinc-300">
                            <tr>
                              <th className="py-2 px-3">Nama Menu</th>
                              <th className="py-2 px-3">Harga Asli</th>
                              <th className="py-2 px-3">Harga Diminta</th>
                              <th className="py-2 px-3">Verified Live</th>
                              <th className="py-2 px-3">Status</th>
                              <th className="py-2 px-3">Keterangan / Error</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
                            {job.result_metadata.items_breakdown.map((item, idx) => (
                              <tr key={idx} className={item.status === 'SUCCESS' ? 'bg-emerald-50/20 dark:bg-emerald-950/10' : 'bg-red-50/20 dark:bg-red-950/10'}>
                                <td className="py-2 px-3 font-semibold text-zinc-800 dark:text-zinc-100">{item.item_name}</td>
                                <td className="py-2 px-3 text-zinc-500 dark:text-zinc-400">{item.old_price ? `Rp ${Number(item.old_price).toLocaleString('id-ID')}` : '-'}</td>
                                <td className="py-2 px-3 font-medium text-zinc-800 dark:text-zinc-200">{item.requested_price ? `Rp ${Number(item.requested_price).toLocaleString('id-ID')}` : '-'}</td>
                                <td className="py-2 px-3 font-medium text-emerald-700 dark:text-emerald-400">{item.verified_price ? `Rp ${Number(item.verified_price).toLocaleString('id-ID')}` : '-'}</td>
                                <td className="py-2 px-3">
                                  <span className={`inline-flex px-2 py-0.5 font-bold rounded-md text-[11px] ${
                                    item.status === 'SUCCESS' ? 'bg-emerald-100 text-emerald-800' : 'bg-red-100 text-red-800'
                                  }`}>
                                    {item.status === 'SUCCESS' ? 'SUKSES' : 'GAGAL'}
                                  </span>
                                </td>
                                <td className="py-2 px-3 text-[11px] text-zinc-500">
                                  {item.error_message ? (
                                    <span className="text-red-700 font-medium">{item.error_message}</span>
                                  ) : (
                                    <span className="text-emerald-700 font-medium">Terverifikasi di portal</span>
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
        </section>
      )}

      {/* ── Bottom: Cards (only when syncPhase === "done") ── */}
      {syncPhase === "done" && (
        <section>
          {preview.length === 0 ? (
            <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-red-200 dark:border-zinc-800 bg-white/60 dark:bg-zinc-950/60 py-16 text-center">
              <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-red-50">
                <svg className="h-6 w-6 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                    d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
              <p className="text-base font-semibold text-slate-700">Belum ada brand dipilih</p>
              <p className="mt-1 text-[15px] text-slate-500">Selesaikan langkah 1–3 lalu klik tombol tarik real-time untuk mulai mengedit harga.</p>
            </div>
          ) : isPushInProgress ? (
            null
          ) : isPushCompleted && !showPostPushMenu ? (
            <div className="flex flex-col items-center justify-center py-6 text-center">
              <button
                type="button"
                onClick={() => setShowPostPushMenu(true)}
                className="px-5 py-2.5 bg-red-800 hover:bg-red-900 text-white font-bold text-[14px] rounded-xl shadow-md transition-all flex items-center gap-2 cursor-pointer"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                </svg>
                <span>Buka Menu Hasil Verifikasi Terbaru</span>
              </button>
            </div>
          ) : (
            <div className="surface-card p-5 lg:p-6 space-y-4 pb-24">
              {/* Header Info */}
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-red-100 dark:border-zinc-800 pb-3">
                <div className="min-w-0">
                  <h3 className="text-base font-bold text-zinc-800 dark:text-zinc-100 flex items-center gap-2">
                    <span>{selectedBrandObj ? (selectedBrandObj.brand || selectedBrandObj.nama_outlet || selectedBrandObj.merchant_name) : ""}</span>
                    <PlatformBadge platform={platform} storeId={selectedBrandObj?.store_id || "No Store ID"} />
                  </h3>
                  <p className="text-[13px] text-zinc-500 dark:text-zinc-400 mt-0.5">
                    Daftar menu lengkap. Total {currentItems.length} menu ({totalChanges} item diubah).
                  </p>
                </div>
              </div>

              {/* Multi-mode Select info bar */}
              {itemEditMode === "multi" && (
                <div className="flex items-center gap-2 text-[13px] text-zinc-650 bg-amber-50/70 border border-amber-200/80 px-4 py-2.5 rounded-xl">
                  <span>Centang item pada tabel di bawah yang ingin disesuaikan harganya:</span>
                  <div className="flex items-center gap-2 ml-auto">
                    <button
                      type="button"
                      onClick={() => selectAllVisibleItems(currentItems)}
                      className="text-amber-800 font-bold hover:underline cursor-pointer"
                    >
                      Pilih Semua
                    </button>
                    <span className="text-zinc-300">|</span>
                    <button
                      type="button"
                      onClick={deselectAllItems}
                      className="text-zinc-600 font-bold hover:underline cursor-pointer"
                    >
                      Batal Pilih
                    </button>
                  </div>
                </div>
              )}
              {/* Search Filter Input */}
              <div>
                <SearchFilterInput
                  value={menuSearch}
                  onChange={setMenuSearch}
                  placeholder="Cari nama menu atau kategori di brand ini..."
                  resultCount={filteredItems.length}
                />
              </div>

              {/* Menu Table Full Width */}
              <div className="overflow-x-auto rounded-2xl border border-zinc-200 dark:border-zinc-800">
                <table className="w-full text-left text-xs min-w-[700px]">
                  <thead className="bg-zinc-100 dark:bg-zinc-950 font-bold uppercase tracking-wider text-zinc-600 dark:text-zinc-400 border-b border-zinc-200 dark:border-zinc-800">
                    <tr>
                      {itemEditMode === "multi" && <th className="p-3.5 w-12 text-center">Pilih</th>}
                      <th className="p-3.5 min-w-[220px]">Nama Menu</th>
                      <th className="p-3.5 w-36">Kategori</th>
                      <th className="p-3.5 text-right w-44">Harga Saat Ini</th>
                      <th className="p-3.5 text-right w-48">Harga Fake Price Baru ({platform?.toUpperCase()})</th>
                      <th className="p-3.5 text-center w-44">Status Aturan / Promo</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800 font-semibold">
                    {Object.entries(groups).length === 0 ? (
                      <tr>
                        <td colSpan={itemEditMode === "multi" ? 6 : 5} className="text-center text-sm text-zinc-400 py-8">
                          {menuSearch ? `Tidak ada menu yang cocok dengan "${menuSearch}"` : "Tidak ada item menu ditemukan."}
                        </td>
                      </tr>
                    ) : (
                      Object.entries(groups).map(([cat, catItems]) => (
                        <Fragment key={cat}>
                          <tr className="bg-red-50/60 dark:bg-red-950/30 border-y border-red-200/50 dark:border-red-900/40">
                            <td colSpan={itemEditMode === "multi" ? 6 : 5} className="p-3 font-bold text-xs text-red-900 dark:text-red-300 uppercase tracking-wider">
                              {cat} ({catItems.length} items)
                            </td>
                          </tr>
                          {catItems.map(item => {
                            const curPrice = edits[selectedBrandId]?.[item.id] ?? item.price;
                            const isEdited = curPrice !== item.price;
                            const diff = curPrice - item.price;
                            const pct = item.price > 0 ? (diff / item.price) * 100 : 0;
                            const pctFmt = (pct > 0 ? "+" : "") + (Number.isInteger(pct) ? pct.toFixed(0) : pct.toFixed(1)) + "%";
                            const { isViolation, message: violationMsg } = checkViolation(platform, item.price, curPrice);
                            const ver = verificationMap[selectedBrandId]?.[item.id];
                            const isChecked = selectedItemIds.includes(item.id);

                            return (
                              <tr key={item.id} className={`transition ${
                                item.is_price_locked
                                  ? "bg-purple-50/40 dark:bg-purple-950/20 opacity-85 cursor-not-allowed"
                                  : isChecked
                                  ? "bg-amber-50/80 dark:bg-amber-950/30"
                                  : isEdited
                                  ? "bg-amber-50/40 dark:bg-amber-950/20"
                                  : "hover:bg-zinc-50 dark:hover:bg-zinc-950/50"
                              }`}>
                                {itemEditMode === "multi" && (
                                  <td className="p-3.5 text-center align-middle">
                                    <input
                                      type="checkbox"
                                      disabled={item.is_price_locked}
                                      checked={!item.is_price_locked && isChecked}
                                      title={item.is_price_locked ? "Item sedang dalam promo nominal aktif (tidak dapat diubah)" : ""}
                                      onChange={() => !item.is_price_locked && toggleSelectItem(item.id)}
                                      className={`h-4 w-4 rounded border-zinc-300 ${
                                        item.is_price_locked ? "opacity-40 cursor-not-allowed" : "text-red-600 focus:ring-red-500 cursor-pointer"
                                      }`}
                                    />
                                  </td>
                                )}
                                <td className="p-3.5 text-zinc-900 dark:text-white font-bold align-middle">
                                  <div className="flex items-center gap-2 flex-wrap">
                                    <span>{item.name}</span>
                                    <PromoBadgeTooltip item={item} platform={platform} fmt={fmt} />
                                  </div>
                                </td>
                                <td className="p-3.5 text-zinc-500 font-medium align-middle">{item.category}</td>
                                <td className="p-3.5 text-right text-zinc-600 dark:text-zinc-300 font-mono font-bold align-middle whitespace-nowrap">
                                  {item.discounted_price && item.discounted_price < item.price ? (
                                    <div className="flex items-center justify-end gap-1.5 flex-wrap">
                                      <span className="line-through text-zinc-400 dark:text-zinc-500 font-normal">
                                        Rp {fmt(item.price)}
                                      </span>
                                      <span className="text-zinc-400">→</span>
                                      <span className="text-emerald-600 dark:text-emerald-400 font-bold">
                                        Rp {fmt(item.discounted_price)}
                                      </span>
                                    </div>
                                  ) : (
                                    <span>Rp {fmt(item.price)}</span>
                                  )}
                                </td>
                                <td className="p-3.5 text-right align-middle">
                                  <div className="flex items-center justify-end gap-1.5">
                                    <input
                                      type="text"
                                      disabled={item.is_price_locked}
                                      title={item.is_price_locked ? "Harga dikunci karena menu sedang dalam promo nominal aktif" : ""}
                                      value={fmt(curPrice)}
                                      onChange={(e) => changePrice(selectedBrandId, item.id, e.target.value)}
                                      className={`w-32 text-right p-2 rounded-xl border font-mono font-bold text-sm ${
                                        item.is_price_locked
                                          ? "border-rose-300 dark:border-rose-900/60 bg-rose-50/50 dark:bg-rose-950/30 text-rose-900 dark:text-rose-300 cursor-not-allowed opacity-80"
                                          : isViolation
                                          ? "border-red-400 dark:border-red-700 bg-white dark:bg-zinc-900 text-red-700 dark:text-red-300 focus:border-red-500 focus:ring-red-200"
                                          : isEdited
                                          ? "border-red-500 bg-red-50 dark:bg-red-950/40 text-red-900 dark:text-red-200 focus:ring-2 focus:ring-red-500/20"
                                          : "border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 text-zinc-900 dark:text-white focus:border-red-500"
                                      }`}
                                    />
                                  </div>
                                </td>
                                <td className="p-3.5 text-center align-middle">
                                  {item.is_price_locked ? (
                                    <span title="Harga menu dikunci karena sedang dalam promo nominal aktif" className="px-2.5 py-1 rounded bg-rose-100 dark:bg-rose-950/60 text-rose-800 dark:text-rose-300 text-[11px] font-semibold border border-rose-300 dark:border-rose-800 inline-block">
                                      Promo Nominal (Dikunci)
                                    </span>
                                  ) : isViolation ? (
                                    <span title={violationMsg} className="px-2.5 py-1 rounded bg-red-100 dark:bg-red-950/60 text-red-700 dark:text-red-300 text-[11px] font-semibold border border-red-200 dark:border-red-900/60 inline-block">
                                      {pctFmt} (Melebihi Batas)
                                    </span>
                                  ) : isEdited ? (
                                    <span className="px-2.5 py-1 rounded bg-emerald-100 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300 text-[11px] font-semibold border border-emerald-200 dark:border-emerald-900/60 inline-block">
                                      {pctFmt} (Valid)
                                    </span>
                                  ) : ver ? (
                                    ver.status === "VERIFIED" ? (
                                      <span className="px-2 py-0.5 rounded bg-emerald-100 text-emerald-800 text-[11px] font-semibold">
                                        Terverifikasi Portal
                                      </span>
                                    ) : (
                                      <span className="px-2 py-0.5 rounded bg-amber-100 text-amber-800 text-[11px] font-semibold">
                                        Menunggu Sinkron
                                      </span>
                                    )
                                  ) : item.is_in_promo ? (
                                    <span className="px-2.5 py-1 rounded bg-amber-100 dark:bg-amber-950/60 text-amber-800 dark:text-amber-300 text-[11px] font-semibold border border-amber-300 dark:border-amber-700 inline-block">
                                      Promo ({item.promo_value || "Aktif"})
                                    </span>
                                  ) : (
                                    <span className="text-zinc-400 text-xs">-</span>
                                  )}
                                </td>
                              </tr>
                            );
                          })}
                        </Fragment>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </section>
      )}

      {/* ── Pop-up Push Rich Confirmation Summary Modal ── */}
      {showPushConfirmModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 animate-fade-in"
          onClick={() => setShowPushConfirmModal(false)}
        >
          <div className="bg-white dark:bg-zinc-950 rounded-2xl p-6 max-w-xl w-full shadow-2xl border border-red-100 dark:border-zinc-800 space-y-4 animate-scale-up max-h-[85vh] flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-start justify-between border-b border-zinc-100 dark:border-zinc-800 pb-3">
              <div>
                <h3 className="text-lg font-bold text-slate-900 dark:text-white">Ringkasan Update Harga Sebelum Push</h3>
                <p className="text-[13px] text-zinc-500 dark:text-zinc-400 mt-0.5">
                  Tinjau daftar rincian <strong>{totalSummaryItems} item</strong> yang akan dikirim ke Merchant Portal.
                </p>
              </div>
              <button type="button" onClick={() => setShowPushConfirmModal(false)}
                className="text-zinc-400 hover:text-zinc-600 dark:text-zinc-500 dark:hover:text-zinc-300 text-lg font-bold"
              >×</button>
            </div>

            {/* Content List */}
            <div className="flex-1 overflow-y-auto space-y-4 pr-1">
              {pushSummaryList.map(summary => (
                <div key={summary.branchId} className="rounded-xl border border-red-100 dark:border-zinc-800 bg-red-50/20 dark:bg-zinc-900/40 p-4 space-y-3">
                  <div className="flex items-center justify-between border-b border-red-100 dark:border-zinc-800 pb-2">
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
                            <span title={u.violationMsg} className="rounded bg-red-600 text-white text-[12px] font-bold px-1.5 py-0.5">! Batas</span>
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
                className="px-5 py-2 bg-red-700 hover:bg-red-800 text-white font-bold text-[14px] rounded-xl transition-colors shadow-md flex items-center gap-1.5"
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

      {/* ── Sticky Bottom Floating Action Bar ── */}
      {syncPhase === "done" && (
        <StickyBottomBar
          totalChanges={totalChanges}
          violationCount={violationCount}
          onOpenPush={() => openPushConfirmationModal(checkedIds)}
          onReset={resetAll}
          pushing={pushing}
          theme="red"
        />
      )}

      {/* ── Pop-up Success Modal ── */}
      {showSuccessModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4 animate-fade-in"
          onClick={() => setShowSuccessModal(false)}
        >
          <div className="bg-white dark:bg-zinc-950 rounded-2xl p-6 max-w-sm w-full shadow-2xl border border-red-100 dark:border-zinc-800 text-center space-y-4 animate-scale-up"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-400 ring-8 ring-emerald-50/60 dark:ring-emerald-950/30">
              <svg className="w-7 h-7" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <div>
              <h3 className="text-lg font-bold text-slate-900 dark:text-white">Update mulai diproses</h3>
              <p className="text-[15px] text-zinc-500 dark:text-zinc-400 mt-1">
                Job untuk <strong>{preview.length} brand</strong> sudah dikirim. Pantau status job di bagian bawah. Setelah job selesai, sistem akan otomatis melakukan tarik ulang menu untuk membandingkan kesesuaian harga.
              </p>
            </div>
            <button type="button" onClick={() => setShowSuccessModal(false)}
              className="w-full bg-red-700 hover:bg-red-800 text-white font-semibold text-[15px] py-2.5 rounded-xl transition-colors shadow-md"
            >
              Lihat status
            </button>
          </div>
        </div>
      )}
    </main>
  );
}
