import React from "react";

export default function StickyBottomBar({
  totalChanges = 0,
  violationCount = 0,
  onOpenPush,
  onReset,
  pushing = false,
  theme = "red" // "red" | "orange"
}) {
  if (totalChanges === 0) return null;

  const isOrange = theme === "orange";
  const pushBtnBg = isOrange
    ? "bg-gradient-to-r from-orange-600 to-red-600 hover:from-orange-700 hover:to-red-700 shadow-orange-950/20"
    : "bg-red-700 hover:bg-red-800 shadow-red-950/20";

  return (
    <div className="fixed bottom-4 left-4 right-4 z-40 max-w-5xl mx-auto animate-fade-in">
      <div className="flex flex-col sm:flex-row items-center justify-between gap-3 p-3.5 sm:px-6 rounded-2xl bg-white/95 dark:bg-zinc-950/95 text-zinc-900 dark:text-white backdrop-blur-md shadow-2xl border border-zinc-200/90 dark:border-zinc-800">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-red-500/10 dark:bg-red-500/20 border border-red-500/20 dark:border-red-500/30 text-red-600 dark:text-red-400 font-bold shrink-0">
            {totalChanges}
          </div>
          <div>
            <div className="font-bold text-[14px] leading-tight flex items-center gap-2 text-zinc-900 dark:text-white">
              <span>{totalChanges} item harga disesuaikan</span>
              {violationCount > 0 && (
                <span className="px-2 py-0.5 rounded-md bg-red-600 text-white text-[11px] font-bold">
                  ⚠️ {violationCount} batas aturan terlampaui
                </span>
              )}
            </div>
            <p className="text-[12px] text-zinc-500 dark:text-zinc-400">
              {violationCount > 0
                ? "Periksa kembali perubahan harga yang melebihi batas aplikator sebelum mengirim."
                : "Perubahan siap dikirim dan diverifikasi ke portal merchant."}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 w-full sm:w-auto justify-end">
          {onReset && (
            <button
              type="button"
              onClick={onReset}
              disabled={pushing}
              className="px-3.5 py-2 text-[13px] font-semibold text-zinc-700 dark:text-zinc-300 hover:text-zinc-900 dark:hover:text-white bg-zinc-100 dark:bg-zinc-800 hover:bg-zinc-200 dark:hover:bg-zinc-700 rounded-xl transition cursor-pointer"
            >
              Reset
            </button>
          )}
          <button
            type="button"
            onClick={onOpenPush}
            disabled={pushing}
            className={`px-5 py-2 text-[14px] font-bold text-white rounded-xl shadow-lg transition flex items-center gap-2 cursor-pointer disabled:opacity-50 ${pushBtnBg}`}
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
            </svg>
            <span>{pushing ? "Memproses..." : `Push ${totalChanges} Perubahan`}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
