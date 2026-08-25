import React, { useState, useRef, useEffect } from "react";
import { createPortal } from "react-dom";

export default function PromoBadgeTooltip({ item, platform = "shopee", fmt }) {
  const [coords, setCoords] = useState(null);
  const triggerRef = useRef(null);

  const handleMouseEnter = () => {
    if (!triggerRef.current) return;
    const r = triggerRef.current.getBoundingClientRect();
    const placeBelow = r.top < 220;
    const left = Math.max(10, Math.min(r.left, window.innerWidth - 300));
    const top = placeBelow ? r.bottom + 6 : r.top - 6;
    setCoords({ top, left, placeBelow });
  };

  const handleMouseLeave = () => setCoords(null);

  useEffect(() => {
    if (!coords) return;
    const close = () => setCoords(null);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [coords]);

  if (!item || (!item.is_flash_sale && !item.is_in_promo)) return null;
  const isFs = Boolean(item.is_flash_sale);

  return (
    <div
      ref={triggerRef}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      className="inline-block"
    >
      {isFs ? (
        <span className="px-2 py-0.5 rounded-lg bg-amber-500/15 dark:bg-amber-500/25 text-amber-600 dark:text-amber-300 font-extrabold text-[10px] border border-amber-400 dark:border-amber-600 shrink-0 cursor-help inline-flex items-center gap-1 shadow-xs">
          <span>⚡ FLASH SALE {item.promo_value ? `(${item.promo_value})` : ""}</span>
          <span className="text-[9px]">ℹ️</span>
        </span>
      ) : (
        <span className="px-1.5 py-0.5 rounded bg-purple-100 dark:bg-purple-950/60 text-purple-800 dark:text-purple-300 font-bold text-[10px] border border-purple-200 dark:border-purple-800 shrink-0 cursor-help inline-flex items-center gap-1">
          <span>PROMO {item.promo_value ? `(${item.promo_value})` : "AKTIF"}</span>
          <span className="text-[9px] opacity-70">ℹ️</span>
        </span>
      )}

      {coords &&
        createPortal(
          <div
            style={{
              position: "fixed",
              top: `${coords.top}px`,
              left: `${coords.left}px`,
              transform: coords.placeBelow ? "none" : "translateY(-100%)",
              zIndex: 9999
            }}
            className={`p-3 bg-zinc-900 text-white rounded-xl shadow-2xl text-xs space-y-1.5 border pointer-events-none animate-scale-up ${
              isFs ? "w-72 border-amber-500/40" : "w-64 border-zinc-700"
            }`}
          >
            <div className={`font-bold border-b border-zinc-700 pb-1 flex items-center justify-between ${isFs ? "text-amber-300" : "text-purple-300"}`}>
              <span>{isFs ? "⚡ Flash Sale Shopee" : (platform === "shopee" ? "Rincian Promo Shopee" : "Rincian Promo Aktif")}</span>
              <span className={`text-[10px] px-1.5 py-0.5 rounded font-mono ${isFs ? "bg-amber-500/30 text-amber-200 font-bold" : "bg-purple-900/80 text-purple-200"}`}>
                {isFs ? "TERKUNCI" : (item.promo_type || "PROMO")}
              </span>
            </div>
            <div className="flex justify-between text-zinc-300">
              <span>{isFs ? "Harga Normal:" : "Harga Normal / Coret:"}</span>
              <span className="font-mono font-bold line-through text-zinc-400">
                Rp {fmt(isFs ? (item.original_price || item.price) : item.price)}
              </span>
            </div>
            <div className={`flex justify-between ${isFs ? "text-amber-300" : "text-emerald-400"}`}>
              <span>{isFs ? "Harga Promo:" : "Harga Jual Promo:"}</span>
              <span className="font-mono font-bold">
                Rp {fmt(isFs ? item.price : (item.discounted_price || item.price))}
              </span>
            </div>
            {isFs && item.promo_details?.stock !== undefined && (
              <div className="flex justify-between text-zinc-300">
                <span>Kuota:</span>
                <span className="font-mono">{item.promo_details.stock} (Terjual: {item.promo_details.sold_num || 0})</span>
              </div>
            )}
            {!isFs && item.promo_value && (
              <div className="flex justify-between text-purple-300">
                <span>Besaran Diskon:</span>
                <span className="font-mono font-bold">{item.promo_value}</span>
              </div>
            )}
            {item.promo_details?.start_time && (
              <div className="text-[10px] text-zinc-400 border-t border-zinc-800 pt-1">
                <div>Mulai: {item.promo_details.start_time}</div>
                {item.promo_details.end_time && <div>Selesai: {item.promo_details.end_time}</div>}
              </div>
            )}
            <div className={`pt-1 border-t border-zinc-800 text-[10px] leading-tight ${isFs ? "text-amber-400 font-medium" : (platform === "shopee" ? "text-emerald-400 font-normal" : "text-amber-300 font-normal")}`}>
              {isFs
                ? "🔒 Harga dikunci selama Flash Sale aktif."
                : (platform === "shopee"
                  ? "✨ Promo aktif. Harga dasar dapat diedit & di-push."
                  : "🔒 Harga dasar menu dikunci otomatis untuk menjaga validitas campaign aktif.")}
            </div>
          </div>,
          document.body
        )}
    </div>
  );
}
