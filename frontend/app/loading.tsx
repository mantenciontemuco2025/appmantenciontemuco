export default function Loading() {
  return (
    <main
      aria-busy="true"
      aria-live="polite"
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: "1rem",
        background: "#f8fafc",
        color: "#475569",
        fontFamily: "system-ui, -apple-system, sans-serif",
      }}
    >
      <div style={{ textAlign: "center" }}>
        <div
          style={{
            width: 34,
            height: 34,
            margin: "0 auto 12px",
            border: "4px solid #dbeafe",
            borderTopColor: "#2563eb",
            borderRadius: "50%",
            animation: "mantencion-spin 0.8s linear infinite",
          }}
        />
        <p style={{ margin: 0, fontSize: 14 }}>Abriendo la plataforma...</p>
      </div>
      <style>{`
        @keyframes mantencion-spin {
          to { transform: rotate(360deg); }
        }
      `}</style>
    </main>
  );
}
