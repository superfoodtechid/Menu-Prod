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
                        <span title={u.violationMsg} className="rounded bg-red-600 text-white text-[12px] font-bold px-1.5 py-0.5">! Batas</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>

        <div className="flex items-center justify-end gap-2 pt-3 border-t border-zinc-100 dark:border-zinc-800">
          <button type="button" onClick={onClose} disabled={submitting}
            className="px-4 py-2 bg-zinc-100 hover:bg-zinc-200 text-zinc-700 font-semibold text-[14px] rounded-xl cursor-pointer"
          >Batal</button>
          <button type="button" onClick={onConfirm} disabled={submitting}
            className={`px-5 py-2 text-white font-bold text-[14px] rounded-xl shadow-md flex items-center gap-1.5 cursor-pointer ${
              isShopee ? "bg-gradient-to-r from-orange-600 to-red-600" : "bg-red-700 hover:bg-red-800"
            }`}
          >
            <span>{submitting ? "Memproses..." : "Konfirmasi & Push"}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
