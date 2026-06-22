export default function LoadingSkeleton() {
  return (
    <div>
      <div className="grid">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="card stat">
            <div className="skeleton" style={{ height: 14, width: "50%" }} />
            <div className="skeleton" style={{ height: 26, width: "72%", marginTop: 14 }} />
            <div className="skeleton" style={{ height: 36, marginTop: 14 }} />
          </div>
        ))}
      </div>
      <div className="card panel" style={{ marginTop: 16 }}>
        <div className="skeleton" style={{ height: 16, width: 130 }} />
        <div className="skeleton" style={{ height: 260, marginTop: 16 }} />
      </div>
    </div>
  );
}
