import React from "react";

export default function StepLabel({ number, label, active, done, themeColor = "red", className = "mb-2.5" }) {
  const isOrange = themeColor === "orange";
  const doneBg = isOrange
    ? "bg-orange-600 text-white dark:bg-white dark:text-black"
    : "bg-red-700 text-white dark:bg-white dark:text-black";
  const activeBg = isOrange
    ? "bg-orange-100 text-orange-700 ring-4 ring-orange-50 dark:bg-zinc-800 dark:text-white dark:ring-zinc-700"
    : "bg-red-100 text-red-700 ring-4 ring-red-50 dark:bg-zinc-800 dark:text-white dark:ring-zinc-700";

  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <span className={`w-6 h-6 rounded-full text-[13px] font-bold flex items-center justify-center shrink-0 transition-colors ${
        done ? doneBg : active ? activeBg : "bg-slate-100 text-slate-400 dark:bg-zinc-900 dark:text-zinc-500"
      }`}>{done ? "✓" : number}</span>
      <span className={`text-[15px] font-bold uppercase tracking-wider transition-colors ${
        active || done ? "text-slate-700 dark:text-white" : "text-slate-400 dark:text-zinc-500"
      }`}>{label}</span>
    </div>
  );
}
