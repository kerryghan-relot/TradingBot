// Number/price/duration formatting — ported from the prototype so the
// output matches the mock exactly (en-US amounts, signed prefixes,
// crypto 0-dec / stocks 2-dec, 1-dec percentages).

export function usd(n: number, dec = 0): string {
  return (
    "$" +
    Number(n).toLocaleString("en-US", {
      minimumFractionDigits: dec,
      maximumFractionDigits: dec,
    })
  );
}

export function signed(n: number): string {
  const prefix = n >= 0 ? "+$" : "−$";
  return prefix + Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 0 });
}

export function pct(n: number): string {
  return (n >= 0 ? "+" : "−") + Math.abs(n).toFixed(1) + "%";
}

// Price string: crypto rounds to whole dollars, stocks to cents.
export function priceStr(sym: string, v: number, isCrypto?: boolean): string {
  const crypto = isCrypto ?? (sym === "BTC" || sym === "ETH");
  return crypto
    ? "$" + Math.round(v).toLocaleString("en-US")
    : "$" + v.toFixed(2);
}

export function duration(ms: number): string {
  const h = Math.floor(ms / 3600000);
  const m = Math.floor((ms % 3600000) / 60000);
  if (h >= 24) return Math.floor(h / 24) + "j " + (h % 24) + "h";
  return h + "h " + m + "m";
}
