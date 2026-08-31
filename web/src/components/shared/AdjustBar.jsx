import React, { useState } from "react";

export default function AdjustBar({
  onApply,
  buttonText = "OK",
  extraActions = null,
  theme = "red"
}) {
  const [type, setType] = useState("nominal");
  const [val, setVal] = useState("");

  const parsedNum = parseFloat(val);
  const isNegative = !isNaN(parsedNum) && (parsedNum < 0 || String(val).trim().startsWith("-"));
  const isValid = !isNaN(parsedNum) && parsedNum !== 0;

  const fire = () => {
    if (!isValid) return;
    const mode = isNegative ? "sub" : "add";
    onApply(mode, type, Math.abs(parsedNum), "none");
  };
  const isOrange = theme === "orange";
  const containerStyle = isOrange
    ? "bg-orange-50/60 dark:bg-orange-950/20 border-orange-200/60 dark:border-orange-900/40"
    : "bg-zinc-50/80 dark:bg-zinc-950/80 border-zinc-200/80 dark:border-zinc-800/80";

  const activeToggleStyle = isOrange
    ? "bg-orange-600 text-white shadow-xs"
    : "bg-zinc-800 dark:bg-zinc-100 text-white dark:text-zinc-900 shadow-xs";

  const btnApplyStyle = isOrange
    ? isNegative ? "bg-red-600 hover:bg-red-700 text-white" : "bg-orange-600 hover:bg-orange-700 text-white"
    : isNegative ? "bg-red-700 hover:bg-red-800 text-white" : "bg-emerald-700 hover:bg-emerald-800 text-white";

  return (
    <div className={`flex flex-wrap items-end gap-3 p-3.5 rounded-2xl border ${containerStyle}`}>
      {/* Type Toggle */}
      <div>
        <p className="mb-1 text-[12px] font-bold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">Metode</p>
        <div className="inline-flex overflow-hidden rounded-xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 p-0.5 shadow-xs">
          {[["nominal", "Rp"], ["pct", "%"]].map(([t, label]) => (
            <button key={t} type="button" onClick={() => setType(t)} aria-pressed={type === t}
              className={`px-3 py-1.5 text-[13px] font-bold rounded-lg transition-colors cursor-pointer ${
                type === t ? activeToggleStyle : "text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
              }`}
            >{label}</button>
          ))}
        </div>
      </div>

      {/* Value Input */}
      <div className="flex-1 min-w-[200px]">
        <div className="flex items-center justify-between mb-1">
          <span className="text-[12px] font-bold uppercase tracking-wider text-zinc-500">Nilai Perubahan</span>
          {val && isValid && (
            <span className={`text-[11px] font-bold uppercase px-2 py-0.5 rounded-md ${
              isNegative ? "bg-red-100 text-red-700" : "bg-emerald-100 text-emerald-700"
            }`}>
              {isNegative ? "↓ Potongan" : "↑ Kenaikan"}
            </span>
          )}
        </div>
        <input
          type="text"
          inputMode="numeric"
          placeholder={type === "nominal" ? "Contoh: 2000 / -2000" : "Contoh: 10 / -10"}
          value={val}
          onChange={(e) => setVal(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && fire()}
          className="w-full rounded-xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-3.5 py-2 text-[14px] font-semibold text-zinc-800 dark:text-zinc-100"
        />
        <div className="flex flex-wrap items-center gap-1.5 mt-1.5">
          <span className="text-[11px] font-semibold text-zinc-400">Pintas:</span>
          {(type === "nominal" ? [1000, 2000, -1000, -2000] : [5, 10, -5, -10]).map((num) => {
            const isNeg = num < 0;
            const labelStr = type === "nominal"
              ? (isNeg ? `-${Math.abs(num).toLocaleString('id-ID')}` : `+${num.toLocaleString('id-ID')}`)
              : (isNeg ? `-${Math.abs(num)}%` : `+${num}%`);
            return (
              <button
                key={num}
                type="button"
                onClick={() => setVal(String(num))}
                className={`px-2 py-0.5 text-[11px] font-bold rounded-md cursor-pointer ${
                  val === String(num)
                    ? isNeg ? "text-red-600 underline" : "text-emerald-600 underline"
                    : isNeg ? "text-red-500 hover:text-red-700" : "text-emerald-600 hover:text-emerald-800"
                }`}
              >
                {labelStr}
              </button>
            );
          })}
        </div>
      </div>

      {/* Apply Button */}
      <button
        type="button"
        onClick={fire}
        disabled={!isValid}
        className={`px-4 py-2 text-[13px] font-bold rounded-xl transition-all shadow-xs shrink-0 cursor-pointer disabled:cursor-not-allowed disabled:bg-zinc-200 disabled:text-zinc-400 ${
          !isValid ? "" : btnApplyStyle
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
