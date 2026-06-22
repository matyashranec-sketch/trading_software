// Muted, flat brand tints — recognizable without shouting.
const COLORS: Record<string, string> = {
  BTC: "#d9912f",
  ETH: "#8a92c4",
  SOL: "#5fae8e",
  BNB: "#cda84a",
  XRP: "#aab0bb",
};

export default function AssetBadge({ symbol }: { symbol: string }) {
  const color = COLORS[symbol] ?? "#8fa97c";
  return (
    <span className="asset">
      <span className="glyph" style={{ background: color }}>
        {symbol.slice(0, 1)}
      </span>
      {symbol}
    </span>
  );
}
