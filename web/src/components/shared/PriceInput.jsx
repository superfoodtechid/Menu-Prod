import React, { useState, useEffect, useRef } from "react";
import { fmt, parse } from "./priceUtils";

export default function PriceInput({
  value = 0,
  disabled = false,
  isLocked = false,
  isViolation = false,
  isEdited = false,
  title = "",
  onChange,
  theme = "red"
}) {
  const [localVal, setLocalVal] = useState(() => fmt(value));
  const debounceTimerRef = useRef(null);

  useEffect(() => {
    setLocalVal(fmt(value));
  }, [value]);

  useEffect(() => {
    return () => {
      if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
    };
  }, []);

  const handleChange = (e) => {
    const raw = e.target.value;
    setLocalVal(raw);
    if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
    debounceTimerRef.current = setTimeout(() => {
      const parsed = parse(raw);
      if (onChange) onChange(parsed);
    }, 150);
  };

  const handleBlur = () => {
    if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
    const parsed = parse(localVal);
    setLocalVal(fmt(parsed));
    if (onChange) onChange(parsed);
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter") {
      e.currentTarget.blur();
    }
  };

  const activeFocusBorder = theme === "orange" ? "focus:border-orange-500" : "focus:border-red-500";
  const editedStyle = theme === "orange"
    ? "border-orange-500 bg-orange-50 dark:bg-orange-950/40 text-orange-900 dark:text-orange-200 focus:ring-2 focus:ring-orange-500/20"
    : "border-red-500 bg-red-50 dark:bg-red-950/40 text-red-900 dark:text-red-200 focus:ring-2 focus:ring-red-500/20";

  return (
    <input
      type="text"
      disabled={disabled || isLocked}
      title={title}
      value={localVal}
      onChange={handleChange}
      onBlur={handleBlur}
      onKeyDown={handleKeyDown}
      className={`w-32 text-right p-2 rounded-xl border font-mono font-bold text-sm transition-colors ${
        disabled || isLocked
          ? "border-purple-200 dark:border-purple-900/60 bg-purple-50/50 dark:bg-purple-950/30 text-purple-900 dark:text-purple-300 cursor-not-allowed opacity-80"
          : isViolation
          ? "border-red-400 dark:border-red-700 bg-white dark:bg-zinc-900 text-red-700 dark:text-red-300 focus:border-red-500 focus:ring-red-200"
          : isEdited
          ? editedStyle
          : `border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 text-zinc-900 dark:text-white ${activeFocusBorder}`
      }`}
    />
  );
}

