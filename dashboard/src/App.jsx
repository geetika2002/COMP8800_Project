import { useEffect, useMemo, useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  Legend,
  PieChart,
  Pie,
  Cell,
} from "recharts";
import "./App.css";

function safeDateStr(ts) {
  if (!ts) return "—";
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return String(ts);
  }
}

function parseAnalysis(llmAnalysis) {
  if (!llmAnalysis) return null;

  if (typeof llmAnalysis === "object") return llmAnalysis;

  try {
    return JSON.parse(llmAnalysis);
  } catch {
    return { raw: llmAnalysis };
  }
}

// Row color coding for session triage (main table only)
function sessionRowStyle(session) {
  const intent = session.intent;
  const risk = session.risk;

  // High risk always red
  if (typeof risk === "number" && risk >= 7) {
    return { backgroundColor: "rgba(239, 68, 68, 0.18)" }; // red
  }

  switch (intent) {
    case "priv_esc":
    case "persistence":
    case "download":
    case "bruteforce":
      return { backgroundColor: "rgba(239, 68, 68, 0.18)" }; // red

    case "recon":
      return { backgroundColor: "rgba(234, 179, 8, 0.18)" }; // yellow

    case "other":
    default:
      return { backgroundColor: "rgba(34, 197, 94, 0.18)" }; // green
  }
}

export default function App() {
  const [events, setEvents] = useState([]);
  const [selectedSessionId, setSelectedSessionId] = useState(null);

  useEffect(() => {
    const fetchEvents = async () => {
      try {
        const res = await fetch("http://127.0.0.1:8000/api/events");
        const data = await res.json();
        setEvents(Array.isArray(data) ? data : []);
      } catch (err) {
        console.error("Error fetching events:", err);
      }
    };

    fetchEvents();
    const interval = setInterval(fetchEvents, 5000);
    return () => clearInterval(interval);
  }, []);

  // --- Derived Metrics (overall) ---
  const totalAttacks = events.length;
  const uniqueIPs = new Set(events.map((e) => e.src_ip)).size;
  const latestAttack =
    events.length > 0 && events[0]?.timestamp
      ? new Date(events[0].timestamp).toLocaleString()
      : "N/A";

  // Attacks by day
  const attacksByDay = Object.values(
    events.reduce((acc, e) => {
      const day = e.timestamp ? e.timestamp.split("T")[0] : "Unknown";
      acc[day] = acc[day] || { day, count: 0 };
      acc[day].count += 1;
      return acc;
    }, {})
  );

  // Top commands (sorted)
  const commandFrequency = Object.values(
    events.reduce((acc, e) => {
      const cmd = e.command || "Unknown";
      acc[cmd] = acc[cmd] || { command: cmd, count: 0 };
      acc[cmd].count += 1;
      return acc;
    }, {})
  )
    .sort((a, b) => b.count - a.count)
    .slice(0, 10);

  // IP distribution
  const ipCounts = Object.values(
    events.reduce((acc, e) => {
      const ip = e.src_ip || "Unknown";
      acc[ip] = acc[ip] || { name: ip, value: 0 };
      acc[ip].value += 1;
      return acc;
    }, {})
  );

  const COLORS = ["#60a5fa", "#34d399", "#fbbf24", "#f87171", "#a78bfa"];

  // --- Sessions grouping ---
  const sessions = useMemo(() => {
    const map = new Map();

    for (const e of events) {
      const sid = e.session_id || "unknown";
      if (!map.has(sid)) map.set(sid, []);
      map.get(sid).push(e);
    }

    // sort events inside each session by time asc
    for (const evs of map.values()) {
      evs.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
    }

    const out = Array.from(map.entries()).map(([sid, evs]) => {
      const start = evs[0]?.timestamp || null;
      const end = evs[evs.length - 1]?.timestamp || null;
      const src_ip = evs.find((x) => x.src_ip)?.src_ip || "Unknown";

      // use most recent event that has llm_analysis
      const analysisEvent = [...evs].reverse().find((x) => x.llm_analysis);
      const analysisObj = parseAnalysis(analysisEvent?.llm_analysis || null);

      // normalized fields (if JSON)
      const summary =
        analysisObj?.summary ||
        (analysisObj?.raw ? "Non-JSON analysis" : null) ||
        null;
      const intent = analysisObj?.intent || null;
      const risk =
        typeof analysisObj?.risk_score === "number" ? analysisObj.risk_score : null;

      return {
        session_id: sid,
        start,
        end,
        src_ip,
        count: evs.length,
        analysisObj,
        summary,
        intent,
        risk,
        events: evs,
      };
    });

    // newest sessions first by end time
    out.sort((a, b) => new Date(b.end) - new Date(a.end));
    return out;
  }, [events]);

  const selectedSession = useMemo(() => {
    if (!selectedSessionId) return null;
    return sessions.find((s) => s.session_id === selectedSessionId) || null;
  }, [selectedSessionId, sessions]);

  // ---------------------------
  // "Details page" view
  // ---------------------------
  if (selectedSession) {
    const { analysisObj } = selectedSession;

    return (
      <div className="dashboard-container">
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <button
            onClick={() => setSelectedSessionId(null)}
            style={{
              padding: "8px 12px",
              borderRadius: 10,
              border: "1px solid rgba(255,255,255,0.15)",
              background: "rgba(255,255,255,0.06)",
              color: "white",
              cursor: "pointer",
            }}
          >
            ← Back
          </button>
          <h1 className="dashboard-title" style={{ margin: 0 }}>
            Session {selectedSession.session_id}
          </h1>
        </div>

        <div className="stats-grid" style={{ marginTop: 16 }}>
          <div className="stat-card">
            <p className="label">Start</p>
            <p className="timestamp">{safeDateStr(selectedSession.start)}</p>
          </div>
          <div className="stat-card">
            <p className="label">End</p>
            <p className="timestamp">{safeDateStr(selectedSession.end)}</p>
          </div>
          <div className="stat-card">
            <p className="label">Source IP</p>
            <p className="value">{selectedSession.src_ip}</p>
          </div>
          <div className="stat-card">
            <p className="label"># Events</p>
            <p className="value">{selectedSession.count}</p>
          </div>
        </div>

        <div className="chart-card" style={{ marginTop: 16 }}>
          <h2>Session Analysis</h2>
          <div style={{ display: "grid", gap: 10 }}>
            {analysisObj ? (
              <>
                {"raw" in analysisObj ? (
                  <pre
                    style={{
                      whiteSpace: "pre-wrap",
                      margin: 0,
                      padding: "12px",
                      borderRadius: 12,
                      background: "rgba(0,0,0,0.25)",
                      overflow: "auto",
                    }}
                  >
                    {analysisObj.raw}
                  </pre>
                ) : (
                  <div style={{ display: "grid", gap: 8 }}>
                    <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
                      <span>
                        <b>Intent:</b> {analysisObj.intent ?? "—"}
                      </span>
                      <span>
                        <b>Risk:</b>{" "}
                        {typeof analysisObj.risk_score === "number"
                          ? analysisObj.risk_score
                          : "—"}
                      </span>
                    </div>
                    <div>
                      <b>Summary:</b> {analysisObj.summary ?? "—"}
                    </div>
                    <div>
                      <b>Explanation:</b> {analysisObj.explanation ?? "—"}
                    </div>
                  </div>
                )}
              </>
            ) : (
              <p style={{ margin: 0 }}>No analysis yet (run exit or analyze manually).</p>
            )}
          </div>
        </div>

        <div className="table-container" style={{ marginTop: 16 }}>
          <h2>Commands / Events</h2>
          <table className="event-table">
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>Command</th>
                <th>Meta</th>
              </tr>
            </thead>
            <tbody>
              {selectedSession.events.map((e) => (
                <tr key={e.id}>
                  <td>{safeDateStr(e.timestamp)}</td>
                  <td>{e.command || "—"}</td>
                  <td style={{ maxWidth: 800 }}>
                    {e.meta_data
                      ? e.meta_data.slice(0, 220) +
                        (e.meta_data.length > 220 ? "…" : "")
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  // ---------------------------
  // Sessions list view
  // ---------------------------
  return (
    <div className="dashboard-container">
      <h1 className="dashboard-title">Honeypot Event Dashboard</h1>

      {/* Summary Stats */}
      <div className="stats-grid">
        <div className="stat-card">
          <p className="label">Total Events</p>
          <p className="value">{totalAttacks}</p>
        </div>
        <div className="stat-card">
          <p className="label">Unique IPs</p>
          <p className="value">{uniqueIPs}</p>
        </div>
        <div className="stat-card">
          <p className="label">Latest Event</p>
          <p className="timestamp">{latestAttack}</p>
        </div>
      </div>

      {/* Charts */}
      <div className="charts-grid">
        <div className="chart-card">
          <h2>Events Over Time</h2>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={attacksByDay}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="day" />
              <YAxis />
              <Tooltip />
              <Line type="monotone" dataKey="count" stroke="#82ca9d" strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <div className="chart-card">
          <h2>Top Commands</h2>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={commandFrequency}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="command" />
              <YAxis />
              <Tooltip />
              <Legend />
              <Bar dataKey="count" fill="#8884d8" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="chart-card">
          <h2>Events by Source IP</h2>
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie data={ipCounts} cx="50%" cy="50%" outerRadius={100} dataKey="value" label>
                {ipCounts.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Sessions table */}
      <div className="table-container">
        <h2>Sessions (Latest 50)</h2>

        {/* Legend */}
        <div style={{ display: "flex", gap: 16, marginBottom: 8, fontSize: 14 }}>
          <span style={{ color: "#22c55e" }}>● Low risk</span>
          <span style={{ color: "#eab308" }}>● Recon / Suspicious</span>
          <span style={{ color: "#ef4444" }}>● Active attack</span>
        </div>

        <table className="event-table">
          <thead>
            <tr>
              <th>Session ID</th>
              <th>Intent</th>
              <th>Risk</th>
              <th>Summary</th>
              <th>Start</th>
              <th>End</th>
              <th>Source IP</th>
              <th># Events</th>
            </tr>
          </thead>

          <tbody>
            {sessions.slice(0, 50).map((s) => (
              <tr
                key={s.session_id}
                onClick={() => setSelectedSessionId(s.session_id)}
                title="Click to view details"
                style={{
                  cursor: "pointer",
                  ...sessionRowStyle(s),
                }}
              >
                <td>{s.session_id}</td>
                <td>{s.intent || "—"}</td>
                <td>{typeof s.risk === "number" ? s.risk : "—"}</td>
                <td style={{ maxWidth: 520 }}>
                  {s.summary
                    ? s.summary.length > 120
                      ? s.summary.slice(0, 120) + "…"
                      : s.summary
                    : "—"}
                </td>
                <td>{safeDateStr(s.start)}</td>
                <td>{safeDateStr(s.end)}</td>
                <td>{s.src_ip}</td>
                <td>{s.count}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <p style={{ opacity: 0.75, marginTop: 10 }}>
          Click a session row to view the full analysis and all commands for that session.
        </p>
      </div>
    </div>
  );
}