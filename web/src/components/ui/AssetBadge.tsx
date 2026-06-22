const COLORS: Record<string, string> = {
  BTC: "#f7931a",
  ETH: "#8a92ff",
  SOL: "#14f195",
  BNB: "#f3ba2f",
  XRP: "#cfd3dc",
};

export default function AssetBadge({ symbol }: { symbol: string }) {
  const color = COLORS[symbol] ?? "#7c5cff";
  return (
    <span className="asset">
      <span
        className="glyph"
        style={{ background: `linear-gradient(135deg, ${color}, ${color}aa)` }}
      >
        {symbol.slice(0, 1)}
      </span>
      {symbol}
    </span>
  );
}
