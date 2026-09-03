export const fmt = (v) => (!v && v !== 0) ? "" : Number(v).toLocaleString("id-ID");
export const parse = (s) => parseInt(String(s).replace(/\D/g, ""), 10) || 0;

export function applyAdj(price, mode, type, val, rounding = "none") {
  const n = parseFloat(val) || 0;
  if (!n) return price;
  let target = price;
  if (type === "pct") {
    const d = Math.round(price * n / 100);
    target = mode === "add" ? price + d : Math.max(1, price - d);
  } else {
    target = mode === "add" ? price + n : Math.max(1, price - n);
  }

  if (rounding === "500") {
    target = Math.round(target / 500) * 500;
  } else if (rounding === "1000") {
    target = Math.round(target / 1000) * 1000;
  }
  return Math.max(1, target);
}

export function checkViolation(platform, oldPrice, newPrice) {
  const o = Number(oldPrice) || 0;
  const n = Number(newPrice) || 0;
  if (n === o || o <= 0 || n <= 0) return { isViolation: false, message: "" };
  const diff = n - o;
  const pct = (diff / o) * 100;
  // Pembulatan ke 2 desimal agar 15% pas tidak terkena artifak floating point (misal 15.000000000000002)
  const roundedPct = Math.round(pct * 100) / 100;
  const absPct = Math.abs(roundedPct);
  const direction = pct > 0 ? "kenaikan" : "penurunan";

  if (platform === "gofood") {
    if (absPct > 15) return { isViolation: true, message: `GoFood: Maksimal ${direction} 15%.` };
  } else if (platform === "grab") {
    if (absPct > 15) return { isViolation: true, message: `GrabFood: Maksimal ${direction} 15% dan maks. 15x per bulan.` };
  } else if (platform === "shopee") {
    if (absPct > 25) return { isViolation: true, message: `ShopeeFood: Maksimal ${direction} 25% dan maks. 1x per hari.` };
  }
  return { isViolation: false, message: "" };
}

export function checkShopeeViolation(oldPrice, newPrice) {
  return checkViolation("shopee", oldPrice, newPrice);
}

export function fmtPromoPct(val) {
  if (!val && val !== 0) return "";
  const str = String(val).trim();
  const num = parseFloat(str.replace("%", ""));
  if (isNaN(num)) return str;
  let normalized = num;
  if (normalized > 100) {
    normalized = normalized / 100;
  }
  const rounded = Math.round(normalized * 10) / 10;
  return `${rounded % 1 === 0 ? Math.round(rounded) : rounded}%`;
}
