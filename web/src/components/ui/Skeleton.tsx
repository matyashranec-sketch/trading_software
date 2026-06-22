export default function LoadingSkeleton() {
  return (
    <div>
      <div className="grid">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="glass stat">
            <div className="skeleton" style={{ height: 16, width: "55%" }} />
            <div className="skeleton" style={{ height: 28, width: "75%", marginTop: 12 }} />
            <div className="skeleton" style={{ height: 40, marginTop: 14 }} />
          </div>
        ))}
      </div>
      <div className="glass panel" style={{ marginTop: 18 }}>
        <div className="skeleton" style={{ height: 18, width: 140 }} />
        <div className="skeleton" style={{ height: 260, marginTop: 16 }} />
      </div>
    </div>
  );
}
