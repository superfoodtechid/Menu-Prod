import React from "react";
import PlatformBadge from "../PlatformBadge";
import { fmt } from "./priceUtils";

export default function PushConfirmModal({
  isOpen,
  onClose,
  onConfirm,
  pushSummaryList = [],
  platform = "general",
  submitting = false
}) {
  if (!isOpen) return null;
  const totalSummaryItems = pushSummaryList.reduce((acc, s) => acc + (s.updates?.length || 0), 0);
  const totalViolations = pushSummaryList.reduce(
    (acc, s) => acc + (s.updates?.filter(u => u.isViolation).length || 0),
    0
  );
  const hasViolation = totalViolations > 0;
  const isShopee = platform === "shopee";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 animate-fade-in" onClick={onClose}>
      <div
        className={`bg-white dark:bg-zinc-950 rounded-2xl p-6 max-w-xl w-full shadow-2xl border space-y-4 animate-scale-up max-h-[85vh] flex flex-col ${
          isShopee ? "border-orange-100 dark:border-zinc-800" : "border-red-100 dark:border-zinc-800"
        }`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between border-b border-zinc-100 dark:border-zinc-800 pb-3">
          <div>
            <h3 className="text-lg font-bold text-slate-900 dark:text-white">
              {isShopee ? "Ringkasan Update Shopee Sebelum Push" : "Ringkasan Update Harga Sebelum Push"}
            </h3>
            <p className="text-[13px] text-zinc-500 dark:text-zinc-400 mt-0.5">
              Tinjau daftar <strong>{totalSummaryItems} item</strong> yang akan dikirim.
            </p>
          </div>
          <button type="button" onClick={onClose} className="text-zinc-400 hover:text-zinc-600 text-lg font-bold">×</button>
        </div>

        <div className="flex-1 overflow-y-auto space-y-4 pr-1">
          {pushSummaryList.map((summary) => (
            <div key={summary.branchId} className={`rounded-xl border p-4 space-y-3 ${
              isShopee ? "border-orange-100 bg-orange-50/20 dark:bg-zinc-900/40" : "border-red-100 bg-red-50/20 dark:bg-zinc-900/40"
            }`}>
              <div className="flex items-center justify-between border-b pb-2">
                <span className="font-bold text-slate-800 dark:text-white text-[15px]">{summary.branchName}</span>
                <PlatformBadge platform={summary.platform} storeId={summary.storeId} />
              </div>
              <div className="space-y-2">
                {summary.updates.map((u) => (
                  <div key={u.id} className="flex flex-col sm:flex-row sm:items-center justify-between rounded-lg bg-zinc-50 dark:bg-zinc-900 p-2.5 border border-zinc-100 dark:border-zinc-800 gap-1 text-[13px]">
                    <div className="min-w-0 flex-1">
                      <p className="font-medium text-slate-800 dark:text-zinc-100 leading-snug">{u.name}</p>
                      <span className="text-[12px] text-slate-400 uppercase tracking-wider">{u.category}</span>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <span className="line-through text-slate-400">Rp {fmt(u.oldPrice)}</span>
                      <span>→</span>
                      <span className="font-bold">Rp {fmt(u.newPrice)}</span>
                      <span className={`rounded px-1.5 py-0.5 text-[12px] font-bold ${
                        u.diff > 0 ? "bg-amber-100 text-amber-700" : "bg-emerald-100 text-emerald-700"
                      }`}>
                        ({u.diff > 0 ? "+" : ""}{u.pct ? u.pct.toFixed(1) : 0}%)
                      </span>
                      {u.isViolation && (
                        <span title={u.violationMsg} className="rounded bg-rose-600 text-white text-[12px] font-bold px-2 py-0.5">
                          ⚠️ Melebihi Batas
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>

        {hasViolation && (
          <div className="p-3 rounded-xl bg-rose-50 dark:bg-rose-950/60 border border-rose-200 dark:border-rose-900 text-rose-700 dark:text-rose-300 text-xs font-semibold flex items-center gap-2">
            <span className="text-base">⛔</span>
            <span>
              <strong>Dilarang Push:</strong> Terdapat {totalViolations} perubahan harga yang melebihi batas aturan aplikator (maksimal {isShopee ? "±25% untuk ShopeeFood" : "kenaikan/penurunan harga"}). Mohon tutup modal ini dan perbaiki harga sebelum melanjutkan.
            </span>
          </div>
        )}

        <div className="flex items-center justify-end gap-2 pt-3 border-t border-zinc-100 dark:border-zinc-800">
          <button type="button" onClick={onClose} disabled={submitting}
            className="px-4 py-2 bg-zinc-100 hover:bg-zinc-200 dark:bg-zinc-800 dark:hover:bg-zinc-700 text-zinc-700 dark:text-zinc-300 font-semibold text-[14px] rounded-xl cursor-pointer"
          >Batal</button>
          <button type="button" onClick={onConfirm} disabled={submitting || hasViolation}
            className={`px-5 py-2 text-white font-bold text-[14px] rounded-xl shadow-md flex items-center gap-1.5 ${
              hasViolation
                ? "bg-zinc-300 dark:bg-zinc-800 text-zinc-400 dark:text-zinc-500 cursor-not-allowed shadow-none"
                : isShopee
                ? "bg-gradient-to-r from-orange-600 to-red-600 hover:from-orange-700 hover:to-red-700 cursor-pointer"
                : "bg-red-700 hover:bg-red-800 cursor-pointer"
            }`}
          >
            <span>{submitting ? "Memproses..." : hasViolation ? "Dilarang Push (Melebihi Batas)" : "Konfirmasi & Push"}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
