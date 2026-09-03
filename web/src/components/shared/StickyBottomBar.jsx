import React from "react";

export default function StickyBottomBar({
  totalChanges = 0,
  violationCount = 0,
  onOpenPush,
  onReset,
  pushing = false,
  theme = "red", // "red" | "orange"
  allowViolationPush = false
}) {
  if (totalChanges === 0) return null;

  const isOrange = theme === "orange";
  const pushBtnBg = isOrange
    ? "bg-gradient-to-r from-orange-600 to-red-600 hover:from-orange-700 hover:to-red-700 shadow-orange-950/20"
    : "bg-red-700 hover:bg-red-800 shadow-red-950/20";

  const isBlocked = !allowViolationPush && violationCount > 0;

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
                <span className={`px-2 py-0.5 rounded-md text-white text-[11px] font-bold ${
                  isBlocked ? "bg-rose-600" : "bg-amber-500"
                }`}>
                  ⚠️ {violationCount} melebihi batas aturan
                </span>
              )}
            </div>
            <p className="text-[12px] text-zinc-500 dark:text-zinc-400">
              {violationCount > 0
                ? isBlocked
                  ? "Dilarang Push: Mohon perbaiki harga yang melanggar batas aturan sebelum mengirim."
                  : "Peringatan: Terdapat harga yang melebihi batas aturan aplikator, namun tetap dapat di-push."
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
            disabled={pushing || isBlocked}
            title={
              isBlocked
                ? "Dilarang push: Perbaiki harga yang melebihi batas aturan aplikator terlebih dahulu"
                : violationCount > 0
                ? "Peringatan: Terdapat harga yang melebihi batas aturan aplikator"
                : ""
            }
            className={`px-5 py-2 text-[14px] font-bold rounded-xl transition flex items-center gap-2 ${
              isBlocked
                ? "bg-zinc-200 dark:bg-zinc-800 text-zinc-400 dark:text-zinc-500 cursor-not-allowed shadow-none border border-zinc-300 dark:border-zinc-700"
                : `text-white shadow-lg cursor-pointer disabled:opacity-50 ${pushBtnBg}`
            }`}
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
            </svg>
            <span>{pushing ? "Memproses..." : isBlocked ? "Push Dinonaktifkan" : `Push ${totalChanges} Perubahan`}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
