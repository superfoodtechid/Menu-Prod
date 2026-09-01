import React, { useState, useRef, useEffect, useId } from "react";
import { createPortal } from "react-dom";
import { fmtPromoPct } from "./priceUtils";

export default function PromoBadgeTooltip({ item, platform = "shopee", fmt }) {
  const [coords, setCoords] = useState(null);
  const [isVisible, setIsVisible] = useState(false);
  const triggerRef = useRef(null);
  const tooltipId = useId();

  const updateCoords = () => {
    if (!triggerRef.current) return;
    const r = triggerRef.current.getBoundingClientRect();
    const placeBelow = r.top < 220;
    const left = Math.max(8, Math.min(r.left, window.innerWidth - 296));
    const top = placeBelow ? r.bottom + 8 : r.top - 8;
    setCoords({ top, left, placeBelow });
  };

  const showTooltip = () => {
    updateCoords();
    setIsVisible(true);
  };

  const hideTooltip = () => {
    setIsVisible(false);
  };

  useEffect(() => {
    if (!isVisible) return;
    const handleDismiss = () => setIsVisible(false);
    window.addEventListener("scroll", handleDismiss, true);
    window.addEventListener("resize", handleDismiss);
    return () => {
      window.removeEventListener("scroll", handleDismiss, true);
      window.removeEventListener("resize", handleDismiss);
    };
  }, [isVisible]);

  if (!item || (!item.is_flash_sale && !item.is_in_promo)) return null;
  const isFs = Boolean(item.is_flash_sale);
  const displayPromoValue = fmtPromoPct(item.promo_value);

  return (
    <div
      ref={triggerRef}
      onMouseEnter={showTooltip}
      onMouseLeave={hideTooltip}
      onFocus={showTooltip}
      onBlur={hideTooltip}
      tabIndex={0}
      role="button"
      aria-describedby={isVisible ? tooltipId : undefined}
      className="inline-flex items-center outline-none focus:ring-2 focus:ring-offset-1 focus:ring-zinc-400 rounded cursor-help"
    >
      {isFs || item.is_price_locked ? (
        <span className="px-2 py-0.5 rounded bg-rose-50 dark:bg-rose-950/60 text-rose-700 dark:text-rose-300 font-semibold text-[11px] border border-rose-300 dark:border-rose-800 shrink-0 inline-flex items-center gap-1">
          <span>{isFs ? `Flash Sale ${displayPromoValue ? `(${displayPromoValue})` : ""}` : `Promo Dikunci ${displayPromoValue ? `(${displayPromoValue})` : ""}`}</span>
        </span>
      ) : (
        <span className="px-2 py-0.5 rounded bg-amber-50 dark:bg-amber-950/60 text-amber-800 dark:text-amber-300 font-semibold text-[11px] border border-amber-300 dark:border-amber-700 shrink-0 inline-flex items-center gap-1">
          <span>Promo {displayPromoValue ? `(${displayPromoValue})` : "Aktif"}</span>
        </span>
      )}

      {isVisible && coords &&
        createPortal(
          <div
            id={tooltipId}
            role="tooltip"
            style={{
              position: "fixed",
              top: `${coords.top}px`,
              left: `${coords.left}px`,
              transform: coords.placeBelow ? "none" : "translateY(-100%)",
              zIndex: 9999
            }}
            className="w-80 p-4 bg-white dark:bg-zinc-900 text-zinc-800 dark:text-zinc-100 rounded-xl shadow-lg text-xs space-y-3 border border-zinc-200 dark:border-zinc-800 pointer-events-none transition-opacity duration-150"
          >
            {/* Header */}
            <div className="font-semibold border-b border-zinc-100 dark:border-zinc-800 pb-2 flex items-center justify-between">
              <span className="text-zinc-900 dark:text-zinc-100 font-bold">
                {isFs ? "Flash Sale Shopee" : (platform === "shopee" ? "Rincian Promo Shopee" : "Rincian Promo Aktif")}
              </span>
              <span className={`text-[10px] px-2 py-0.5 rounded font-semibold uppercase tracking-wider ${
                isFs || item.is_price_locked
                  ? "bg-rose-100 dark:bg-rose-950/80 text-rose-700 dark:text-rose-300 border border-rose-200 dark:border-rose-800"
                  : "bg-amber-100 dark:bg-amber-950/80 text-amber-800 dark:text-amber-300 border border-amber-200 dark:border-amber-700"
              }`}>
                {isFs ? "Terkunci" : (item.promo_type || "Promo")}
              </span>
            </div>

            {/* Price breakdown */}
            <div className="space-y-1.5 pt-0.5">
              <div className="flex justify-between text-zinc-500 dark:text-zinc-400">
                <span>{isFs ? "Harga Normal:" : "Harga Normal / Coret:"}</span>
                <span className="font-mono line-through text-zinc-400 dark:text-zinc-500">
                  Rp {fmt(isFs ? (item.original_price || item.price) : item.price)}
                </span>
              </div>

              <div className="flex justify-between text-emerald-600 dark:text-emerald-400 font-semibold">
                <span>{isFs ? "Harga Flash Sale:" : "Harga Jual Promo:"}</span>
                <span className="font-mono">
                  Rp {fmt(isFs ? (item.promo_details?.discount_price || item.discounted_price || item.price) : (item.discounted_price || item.price))}
                </span>
              </div>

              {isFs && item.promo_details?.stock !== undefined && (
                <div className="flex justify-between text-zinc-600 dark:text-zinc-400">
                  <span>Kuota Flash Sale:</span>
                  <span className="font-mono text-zinc-800 dark:text-zinc-200">
                    {item.promo_details.stock} (Terjual: {item.promo_details.sold_num || 0})
                  </span>
                </div>
              )}

              {!isFs && displayPromoValue && (
                <div className="flex justify-between text-zinc-600 dark:text-zinc-300">
                  <span>Besaran Diskon:</span>
                  <span className="font-mono font-semibold text-amber-700 dark:text-amber-300">{displayPromoValue}</span>
                </div>
              )}
            </div>

            {/* If there's also a regular store discount alongside Flash Sale */}
            {isFs && item.promo_details?.regular_discount && (
              <div className="p-2.5 rounded-lg bg-zinc-50 dark:bg-zinc-800/60 border border-zinc-200/70 dark:border-zinc-700/60 space-y-1">
                <div className="text-[11px] font-semibold text-amber-700 dark:text-amber-300 flex items-center justify-between">
                  <span>Promo Diskon Toko</span>
                  <span className="font-mono font-bold">{fmtPromoPct(item.promo_details.regular_discount.discount_percentage) || "Aktif"}</span>
                </div>
                {item.promo_details.regular_discount.discount_price > 0 && (
                  <div className="flex justify-between text-[11px] text-zinc-600 dark:text-zinc-400">
                    <span>Harga Setelah Diskon Toko:</span>
                    <span className="font-mono font-semibold text-zinc-800 dark:text-zinc-200">
                      Rp {fmt(item.promo_details.regular_discount.discount_price)}
                    </span>
                  </div>
                )}
                {item.promo_details.regular_discount.start_time && (
                  <div className="text-[10px] text-zinc-500 dark:text-zinc-400 pt-0.5 border-t border-zinc-200/50 dark:border-zinc-700/50">
                    Periode: {item.promo_details.regular_discount.start_time} {item.promo_details.regular_discount.end_time ? `s/d ${item.promo_details.regular_discount.end_time}` : ""}
                  </div>
                )}
              </div>
            )}

            {/* Time period */}
            {item.promo_details?.start_time && (
              <div className="text-xs text-zinc-500 dark:text-zinc-400 border-t border-zinc-100 dark:border-zinc-800 pt-2 space-y-1">
                <div>Periode Flash Sale: {item.promo_details.start_time} {item.promo_details.end_time ? `s/d ${item.promo_details.end_time}` : ""}</div>
              </div>
            )}

            {/* Lock explanation */}
            <div className="pt-2 border-t border-zinc-100 dark:border-zinc-800 text-xs leading-relaxed text-zinc-500 dark:text-zinc-400">
              {isFs
                ? "Harga dikunci otomatis selama Flash Sale berlangsung."
                : (platform === "shopee"
                  ? "Promo aktif. Harga dasar dapat disesuaikan."
                  : "Harga dasar dikunci otomatis untuk validitas promo.")}
            </div>
          </div>,
          document.body
        )}
    </div>
  );
}
