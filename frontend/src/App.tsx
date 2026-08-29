/**
 * ORCA marine decision-support dashboard.
 * Layout: conversation panel (left) | map (center) | recommendation/evidence (right).
 * Placeholder scaffold — layers and panels land in Phase 7.
 */
export default function App() {
  return (
    <div className="app-shell">
      <div className="banner">⚠ DEMO / CACHED DATA — not live observations (placeholder banner)</div>
      <aside className="panel left">
        <h2>ORCA</h2>
        <p>Conversation panel (Phase 7)</p>
      </aside>
      <main className="map-container">
        <p style={{ padding: 16 }}>Map (Phase 7)</p>
      </main>
      <aside className="panel right">
        <h3>Recommendation</h3>
        <p>Evidence panel (Phase 7)</p>
      </aside>
    </div>
  );
}
