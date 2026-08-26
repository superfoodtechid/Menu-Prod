import React from "react";

export default function SearchFilterInput({
  value,
  onChange,
  placeholder = "Cari nama menu atau kategori...",
  resultCount = null
}) {
  return (
    <div className="relative flex items-center w-full">
      <svg
        className="w-4 h-4 text-zinc-400 absolute left-3.5 pointer-events-none"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
      >
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
      </svg>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full pl-10 pr-20 py-2.5 rounded-xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-[14px] font-medium text-zinc-800 dark:text-zinc-100 placeholder:text-zinc-400 focus:outline-none focus:border-red-400 focus:ring-2 focus:ring-red-100 dark:focus:ring-zinc-800 transition shadow-xs"
      />
      {value && (
        <button
          type="button"
          onClick={() => onChange("")}
          className="absolute right-3 px-2 py-0.5 text-xs text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 font-bold cursor-pointer"
        >
          ✕
        </button>
      )}
      {resultCount !== null && !value && (
        <span className="absolute right-3 text-[11px] font-semibold text-zinc-400 pointer-events-none">
          {resultCount} menu
        </span>
      )}
    </div>
  );
}
