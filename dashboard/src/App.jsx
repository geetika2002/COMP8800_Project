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

function osmEmbedUrl(lat, lon) {
  // Simple bbox around the point (bigger box = more zoomed out)
  const delta = 0.5;
  const left = lon - delta;
  const right = lon + delta;
  const top = lat + delta;
  const bottom = lat - delta;

  const bbox = `${left}%2C${bottom}%2C${right}%2C${top}`;
  const marker = `${lat}%2C${lon}`;

  return `https://www.openstreetmap.org/export/embed.html?bbox=${bbox}&layer=mapnik&marker=${marker}`;
}

// Helper: format timestamps safely for display (handles null/invalid values)
function safeDateStr(ts) {
  if (!ts) return "—";
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return String(ts);
  }
}

function safeTimeMs(ts) {
  const t = new Date(ts).getTime();
  return Number.isFinite(t) ? t : null;
}

function formatDuration(ms) {
  if (!Number.isFinite(ms) || ms < 0) return "—";
  const sec = Math.floor(ms / 1000);
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  const rem = sec % 60;
  if (min < 60) return `${min}m ${rem}s`;
  const hr = Math.floor(min / 60);
  const remMin = min % 60;
  return `${hr}h ${remMin}m`;
}

// Helper: normalize llm_analysis into an object (supports JSON string or raw text)
function parseAnalysis(llmAnalysis) {
  if (!llmAnalysis) return null;
  if (typeof llmAnalysis === "object") return llmAnalysis;

  try {
    return JSON.parse(llmAnalysis);
  } catch {
    return { raw: llmAnalysis };
  }
}

// Session triage coloring for the main sessions table (green/yellow/red)
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

function riskBucket(risk) {
  if (typeof risk !== "number") return "unknown";
  if (risk >= 7) return "high";
  if (risk >= 4) return "med";
  return "low";
}

function classifyCommand(cmdRaw) {
  const cmd = (cmdRaw || "").trim().toLowerCase();
  if (!cmd) return { cat: "OTHER", level: "low" };

  const recon = /^(id|whoami|pwd|uname|hostname|w|last|cat\s+\/etc\/(passwd|shadow)|ifconfig|ip\s+a|netstat|ss\s)/i;
  const download = /(wget|curl|scp|ftp|tftp)/i;
  const priv = /(sudo|su\b|passwd|useradd|usermod|chown|chmod\s+\+x)/i;
  const persistence = /(crontab|systemctl|service|rc\.local|authorized_keys)/i;
  const destructive = /(rm\s+-rf|mkfs|dd\s+if=|:>\s)/i;
  const exit = /^(exit|logout|quit)$/i;

  if (exit.test(cmd)) return { cat: "EXIT", level: "low" };
  if (destructive.test(cmd)) return { cat: "DESTRUCT", level: "high" };
  if (priv.test(cmd)) return { cat: "PRIV_ESC", level: "high" };
  if (persistence.test(cmd)) return { cat: "PERSIST", level: "high" };
  if (download.test(cmd)) return { cat: "DOWNLOAD", level: "med" };
  if (recon.test(cmd)) return { cat: "RECON", level: "low" };

  return { cat: "OTHER", level: "low" };
}

function phaseForCategory(cat) {
  if (cat === "RECON") return "RECON PHASE";
  if (["PRIV_ESC", "PERSIST", "DOWNLOAD", "DESTRUCT"].includes(cat)) return "ACTION PHASE";
  if (cat === "EXIT") return "EXIT";
  return "GENERAL";
}

function topCommandsForSession(events, limit = 3) {
  const freq = new Map();
  for (const e of events) {
    const cmd = (e.command || "").trim();
    if (!cmd) continue;
    freq.set(cmd, (freq.get(cmd) || 0) + 1);
  }
  return [...freq.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit)
    .map(([cmd]) => cmd);
}

export default function App() {
  const [events, setEvents] = useState([]);
  const [selectedSessionId, setSelectedSessionId] = useState(null);
  const [showRawEvents, setShowRawEvents] = useState(false);
  const [view, setView] = useState("dashboard");

  // Filters (Milestone 4 UX)
  const [intentFilter, setIntentFilter] = useState("all");
  const [riskFilter, setRiskFilter] = useState("all");
  const [searchText, setSearchText] = useState("");
  const [eventSearch, setEventSearch] = useState("");
  const [ipSearch, setIpSearch] = useState("");

  const [geoOpen, setGeoOpen] = useState(false);
  const [geoLoading, setGeoLoading] = useState(false);
  const [geoError, setGeoError] = useState("");
  const [geoData, setGeoData] = useState(null);

  async function openGeo(ip) {
  setGeoOpen(true);
  setGeoLoading(true);
  setGeoError("");
  setGeoData(null);

  try {
    const res = await fetch(`http://127.0.0.1:8000/api/geo?ip=${encodeURIComponent(ip)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail || "Geo lookup failed");
    setGeoData(data);
  } catch (e) {
    setGeoError(String(e.message || e));
  } finally {
    setGeoLoading(false);
  }
}

  // Poll backend for latest events (live dashboard refresh)
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

  // Events by day (for timeline chart)
  const attacksByDay = Object.values(
    events.reduce((acc, e) => {
      const day = e.timestamp ? e.timestamp.split("T")[0] : "Unknown";
      acc[day] = acc[day] || { day, count: 0 };
      acc[day].count += 1;
      return acc;
    }, {})
  );

  // Event distribution by IP (for pie chart)
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

      const analysisEvent = [...evs].reverse().find((x) => x.llm_analysis);
      const analysisObj = parseAnalysis(analysisEvent?.llm_analysis || null);

      const summary =
        analysisObj?.summary ||
        (analysisObj?.raw ? "Non-JSON analysis" : null) ||
        null;

      const intent = analysisObj?.intent || null;
      const risk =
        typeof analysisObj?.risk_score === "number" ? analysisObj.risk_score : null;

      const startMs = start ? safeTimeMs(start) : null;
      const endMs = end ? safeTimeMs(end) : null;
      const durationMs =
        Number.isFinite(startMs) && Number.isFinite(endMs) ? endMs - startMs : null;

      const top3 = topCommandsForSession(evs, 3);

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
        durationMs,
        top3,
        events: evs,
      };
    });

    // newest sessions first by end time
    out.sort((a, b) => new Date(b.end) - new Date(a.end));
    return out;
  }, [events]);

    // Top command families across latest 50 sessions
  const commandFrequency = useMemo(() => {
    const latestSessionIds = sessions.slice(0, 50).map((s) => s.session_id);
    const sessionSet = new Set(latestSessionIds);

    const freq = {};

    for (const e of events) {
      if (!sessionSet.has(e.session_id)) continue;

      const raw = (e.command || "").trim().toLowerCase();
      if (!raw) continue;

      // Remove noisy commands
      if (["exit", "logout", "quit", "login_success", "login_attempt"].includes(raw)) continue;

      // Normalize to base command
      const base = raw.split(/\s+/)[0];
      if (!base) continue;

      freq[base] = freq[base] || { command: base, count: 0 };
      freq[base].count += 1;
    }

    return Object.values(freq)
      .sort((a, b) => b.count - a.count)
      .slice(0, 10);
  }, [events, sessions]);

  const totalSessions = sessions.length;

  const ipRows = useMemo(() => {
    const map = new Map();
    for (const e of events) {
      const ip = e.src_ip || "Unknown";
      if (!map.has(ip)) {
        map.set(ip, {
          ip,
          events: 0,
          sessions: new Set(),
          firstSeen: e.timestamp || null,
          lastSeen: e.timestamp || null,
        });
      }
      const row = map.get(ip);
      row.events += 1;
      if (e.session_id) row.sessions.add(e.session_id);
      if (e.timestamp) {
        if (!row.firstSeen || new Date(e.timestamp) < new Date(row.firstSeen)) row.firstSeen = e.timestamp;
        if (!row.lastSeen || new Date(e.timestamp) > new Date(row.lastSeen)) row.lastSeen = e.timestamp;
      }
    }
    return Array.from(map.values())
      .map((r) => ({ ...r, sessionCount: r.sessions.size }))
      .sort((a, b) => b.events - a.events);
  }, [events]);


  // Build intent dropdown options from seen intents (+ defaults)
  const intentOptions = useMemo(() => {
    const base = ["recon", "bruteforce", "download", "priv_esc", "persistence", "other"];
    const seen = new Set();
    for (const s of sessions) if (s.intent) seen.add(s.intent);
    const merged = [...new Set([...base, ...seen])].filter(Boolean);
    return merged;
  }, [sessions]);

  // Apply filters/search
  const filteredSessions = useMemo(() => {
    const q = searchText.trim().toLowerCase();

    return sessions.filter((s) => {
      // Intent filter
      if (intentFilter !== "all") {
        if ((s.intent || "other") !== intentFilter) return false;
      }

      // Risk filter
      if (riskFilter !== "all") {
        const b = riskBucket(s.risk);
        if (riskFilter === "high" && b !== "high") return false;
        if (riskFilter === "med" && b !== "med") return false;
        if (riskFilter === "low" && b !== "low") return false;
        if (riskFilter === "unknown" && b !== "unknown") return false;
      }

      // Search
      if (q) {
        const haystack = [
          s.session_id,
          s.src_ip,
          s.intent || "",
          s.summary || "",
          ...(s.top3 || []),
          // Light scan of commands (don’t join all events; just take first ~25 to keep it snappy)
          ...s.events.slice(0, 25).map((e) => e.command || ""),
        ]
          .join(" ")
          .toLowerCase();

        if (!haystack.includes(q)) return false;
      }

      return true;
    });
  }, [sessions, intentFilter, riskFilter, searchText]);

  // Selected session drives a simple "details page" view
  const selectedSession = useMemo(() => {
    if (!selectedSessionId) return null;
    return sessions.find((s) => s.session_id === selectedSessionId) || null;
  }, [selectedSessionId, sessions]);

  // ---------------------------
  // Session details view
  // ---------------------------
  if (selectedSession) {
    const { analysisObj } = selectedSession;

// Enhanced Activity Timeline (Option B + intelligence)
    const GAP_SECONDS = 10;

    const rawActivity = (selectedSession.events || [])
      .filter((e) => e && e.timestamp)
      .map((e, idx) => {
        const ms = safeTimeMs(e.timestamp);
        const timeStr = Number.isFinite(ms) ? new Date(ms).toLocaleTimeString() : "—";
        const cmd = e.command || e.message || "—";
        const { cat, level } = classifyCommand(cmd);

        return {
          kind: "event",
          idx,
          ms,
          time: timeStr,
          cmd,
          cat,
          level,
          phase: phaseForCategory(cat),
        };
      })
      .sort((a, b) => (a.ms ?? 0) - (b.ms ?? 0));

    // Add phase headers + idle gaps to make the timeline meaningfully different from the table
    const activity = [];
    let lastMs = null;
    let lastPhase = null;

    for (let i = 0; i < rawActivity.length; i++) {
      const ev = rawActivity[i];

      if (ev.phase !== lastPhase) {
        activity.push({
          kind: "phase",
          key: `phase-${i}-${ev.phase}`,
          label: ev.phase,
        });
        lastPhase = ev.phase;
      }

      if (Number.isFinite(lastMs) && Number.isFinite(ev.ms)) {
        const gapSec = Math.round((ev.ms - lastMs) / 1000);
        if (gapSec >= GAP_SECONDS) {
          activity.push({
            kind: "gap",
            key: `gap-${i}-${gapSec}`,
            seconds: gapSec,
          });
        }
      }

      activity.push({ ...ev, key: `ev-${ev.idx}-${ev.ms ?? i}` });
      lastMs = ev.ms;
    }

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
            <p className="label">Duration</p>
            <p className="value">{formatDuration(selectedSession.durationMs)}</p>
          </div>
          <div className="stat-card">
            <p className="label">Source IP</p>
            <button
              onClick={() => openGeo(selectedSession.src_ip)}
              style={{
                background: "transparent",
                border: "none",
                padding: 0,
                color: "white",
                textDecoration: "underline",
                cursor: "pointer",
                textAlign: "left",
              }}
              title="Click to view geolocation"
            >
              {selectedSession.src_ip}
            </button>
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

<div className="chart-card" style={{ marginTop: 16, textAlign: "left" }}>
          <h2>Activity Timeline</h2>
          <p style={{ marginTop: 0, opacity: 0.8 }}>
            Commands/events in order (timeline UI with phases + idle gaps).
          </p>

          {activity.length === 0 ? (
            <div style={{ opacity: 0.8 }}>No events found for this session.</div>
          ) : (
            <div>
              {activity.map((a, i) => {
                if (a.kind === "phase") {
                  return (
                    <div
                      key={a.key}
                      style={{
                        margin: "10px 0 6px",
                        padding: "6px 10px",
                        borderRadius: 999,
                        display: "inline-block",
                        fontSize: 12,
                        letterSpacing: 0.6,
                        opacity: 0.9,
                        border: "1px solid rgba(255,255,255,0.18)",
                        background: "rgba(255,255,255,0.05)",
                      }}
                    >
                      {a.label}
                    </div>
                  );
                }

                if (a.kind === "gap") {
                  return (
                    <div
                      key={a.key}
                      style={{
                        marginLeft: 28,
                        marginBottom: 6,
                        opacity: 0.75,
                        fontSize: 12,
                      }}
                    >
                      — {a.seconds}s idle —
                    </div>
                  );
                }

                const badgeBg =
                  a.level === "high"
                    ? "rgba(255,99,132,0.18)"
                    : a.level === "med"
                    ? "rgba(255,217,102,0.18)"
                    : "rgba(130,202,157,0.18)";

                const dotColor =
                  a.level === "high" ? "#ff6384" : a.level === "med" ? "#ffd966" : "#82ca9d";

                // Draw a connector line if there's another event later in the list
                const hasNextEvent = activity.slice(i + 1).some((x) => x.kind === "event");

                return (
                  <div
                    key={a.key}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "18px 90px 1fr auto",
                      gap: 10,
                      alignItems: "start",
                      padding: "10px 8px",
                      borderRadius: 12,
                    }}
                  >
                    <div
                      style={{
                        position: "relative",
                        display: "flex",
                        justifyContent: "center",
                      }}
                    >
                      <div
                        style={{
                          width: 10,
                          height: 10,
                          borderRadius: 999,
                          marginTop: 4,
                          background: dotColor,
                        }}
                      />
                      {hasNextEvent && (
                        <div
                          style={{
                            position: "absolute",
                            top: 18,
                            bottom: -10,
                            width: 2,
                            background: "rgba(255,255,255,0.15)",
                          }}
                        />
                      )}
                    </div>

                    <div
                      style={{
                        opacity: 0.85,
                        whiteSpace: "nowrap",
                        fontVariantNumeric: "tabular-nums",
                      }}
                    >
                      {a.time}
                    </div>

                    <div style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>{a.cmd}</div>

                    <div
                      style={{
                        fontSize: 12,
                        padding: "3px 8px",
                        borderRadius: 999,
                        border: "1px solid rgba(255,255,255,0.18)",
                        whiteSpace: "nowrap",
                        background: badgeBg,
                      }}
                      title={a.cat}
                    >
                      {a.cat}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>


        

                {geoOpen && (
  <div
    onClick={() => setGeoOpen(false)}
    style={{
      position: "fixed",
      inset: 0,
      background: "rgba(0,0,0,0.65)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      padding: 16,
      zIndex: 9999,
    }}
  >
    <div
      onClick={(e) => e.stopPropagation()}
      style={{
        width: "min(820px, 95vw)",
        borderRadius: 16,
        padding: 16,
        background: "rgba(20,20,20,0.98)",
        border: "1px solid rgba(255,255,255,0.12)",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
        <h2 style={{ margin: 0 }}>IP Geolocation</h2>
        <button
          onClick={() => setGeoOpen(false)}
          style={{
            padding: "6px 10px",
            borderRadius: 10,
            border: "1px solid rgba(255,255,255,0.15)",
            background: "rgba(255,255,255,0.06)",
            color: "white",
            cursor: "pointer",
          }}
        >
          Close
        </button>
      </div>

      <div style={{ marginTop: 12 }}>
        {geoLoading && <p style={{ margin: 0 }}>Looking up IP…</p>}
        {geoError && <p style={{ margin: 0, color: "#f87171" }}>{geoError}</p>}

        {geoData && (
          <>
            {!geoData.ok ? (
              <p style={{ margin: 0 }}>
                {geoData.ip}: {geoData.reason}
              </p>
            ) : (
              <>
                <p style={{ marginTop: 0 }}>
                  <b>{geoData.ip}</b> — {geoData.city || "—"}, {geoData.region || "—"},{" "}
                  {geoData.country || "—"}
                  <br />
                  <span style={{ opacity: 0.85 }}>
                    {geoData.org || geoData.isp || "—"} {geoData.asn ? `(${geoData.asn})` : ""}
                  </span>
                </p>

                {Number.isFinite(geoData.lat) && Number.isFinite(geoData.lon) && (
                  <div style={{ marginTop: 10, borderRadius: 12, overflow: "hidden" }}>
                    <iframe
                      title="ip-map"
                      src={osmEmbedUrl(geoData.lat, geoData.lon)}
                      style={{ width: "100%", height: 360, border: 0 }}
                      loading="lazy"
                    />
                  </div>
                )}

                <p style={{ marginTop: 10, opacity: 0.75, fontSize: 13 }}>
                  Note: IP geolocation is approximate and can be inaccurate for VPNs/proxies.
                </p>
              </>
            )}
          </>
        )}
      </div>
    </div>
  </div>
)}

<div className="table-container" style={{ marginTop: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <h2 style={{ margin: 0 }}>Commands / Events</h2>
            <button
              onClick={() => setShowRawEvents((s) => !s)}
              style={{
                padding: "8px 12px",
                borderRadius: 10,
                border: "1px solid rgba(255,255,255,0.15)",
                background: "rgba(255,255,255,0.06)",
                color: "white",
                cursor: "pointer",
              }}
            >
              {showRawEvents ? "Hide Raw Events ▲" : "Show Raw Events ▼"}
            </button>
          </div>

          {showRawEvents && (
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
          )}

        </div>
      </div>
    );
  }


  // ---------------------------
  // All Events view (click from stats)
  // ---------------------------
  if (!selectedSessionId && view === "events") {
    const filtered = [...events]
      .filter((e) => {
        const q = (eventSearch || "").trim().toLowerCase();
        if (!q) return true;
        return (
          String(e.command || "").toLowerCase().includes(q) ||
          String(e.src_ip || "").toLowerCase().includes(q) ||
          String(e.session_id || "").toLowerCase().includes(q) ||
          String(e.event_type || "").toLowerCase().includes(q)
        );
      })
      .sort((a, b) => new Date(b.timestamp || 0) - new Date(a.timestamp || 0));

    return (
      <div className="dashboard-container">
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <button
            onClick={() => setView("dashboard")}
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
            All Events
          </h1>
        </div>

        <p style={{ marginTop: 10, opacity: 0.8 }}>
          Showing {filtered.length} events (search filters client-side).
        </p>

        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 10 }}>
          <input
            value={eventSearch}
            onChange={(e) => setEventSearch(e.target.value)}
            placeholder="Search events (cmd, ip, session, type)..."
            style={{
              padding: "10px 12px",
              borderRadius: 10,
              border: "1px solid rgba(255,255,255,0.15)",
              background: "rgba(255,255,255,0.06)",
              color: "white",
              minWidth: 320,
              outline: "none",
            }}
          />
        </div>

        <div className="table-container" style={{ marginTop: 16 }}>
          <table className="event-table">
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>Session</th>
                <th>Source IP</th>
                <th>Type</th>
                <th>Command</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((e) => (
                <tr key={e.id || `${e.session_id}-${e.timestamp}-${e.command}`}>
                  <td>{safeDateStr(e.timestamp)}</td>
                  <td style={{ whiteSpace: "nowrap" }}>{e.session_id || "—"}</td>
                  <td style={{ whiteSpace: "nowrap" }}>{e.src_ip || "—"}</td>
                  <td style={{ whiteSpace: "nowrap" }}>{e.event_type || "—"}</td>
                  <td style={{ maxWidth: 720 }}>{e.command || e.message || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  // ---------------------------
  // IPs view (click from stats)
  // ---------------------------
  if (!selectedSessionId && view === "ips") {
    const filteredIps = ipRows.filter((r) => {
      const q = (ipSearch || "").trim().toLowerCase();
      if (!q) return true;
      return r.ip.toLowerCase().includes(q);
    });

    return (
      <div className="dashboard-container">
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <button
            onClick={() => setView("dashboard")}
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
            Unique IPs
          </h1>
        </div>

        <p style={{ marginTop: 10, opacity: 0.8 }}>
          {filteredIps.length} IPs found.
        </p>

        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 10 }}>
          <input
            value={ipSearch}
            onChange={(e) => setIpSearch(e.target.value)}
            placeholder="Search IP..."
            style={{
              padding: "10px 12px",
              borderRadius: 10,
              border: "1px solid rgba(255,255,255,0.15)",
              background: "rgba(255,255,255,0.06)",
              color: "white",
              minWidth: 240,
              outline: "none",
            }}
          />
        </div>

        <div className="table-container" style={{ marginTop: 16 }}>
          <table className="event-table">
            <thead>
              <tr>
                <th>IP</th>
                <th># Events</th>
                <th># Sessions</th>
                <th>First Seen</th>
                <th>Last Seen</th>
              </tr>
            </thead>
            <tbody>
              {filteredIps.map((r) => (
                <tr key={r.ip}>
                  <td style={{ whiteSpace: "nowrap" }}>{r.ip}</td>
                  <td>{r.events}</td>
                  <td>{r.sessionCount}</td>
                  <td style={{ whiteSpace: "nowrap" }}>{safeDateStr(r.firstSeen)}</td>
                  <td style={{ whiteSpace: "nowrap" }}>{safeDateStr(r.lastSeen)}</td>
                  
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  // ---------------------------
  // Main dashboard view
  // ---------------------------
  return (
    <div className="dashboard-container">
      <h1 className="dashboard-title">Honeypot Event Dashboard</h1>

      <div className="stats-grid">
        <div
          className="stat-card"
          role="button"
          tabIndex={0}
          onClick={() => setView("events")}
          onKeyDown={(e) => e.key === "Enter" && setView("events")}
          style={{ cursor: "pointer" }}
          title="Click to view all events"
        >
          <p className="label">Total Sessions</p>
          <p className="value">{totalSessions}</p>
        </div>
        <div
          className="stat-card"
          role="button"
          tabIndex={0}
          onClick={() => setView("ips")}
          onKeyDown={(e) => e.key === "Enter" && setView("ips")}
          style={{ cursor: "pointer" }}
          title="Click to view all unique IPs"
        >
          <p className="label">Unique IPs</p>
          <p className="value">{uniqueIPs}</p>
        </div>
        <div className="stat-card">
          <p className="label">Latest Event</p>
          <p className="timestamp">{latestAttack}</p>
        </div>
      </div>

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
              <XAxis
                dataKey="command"
                interval={0}
                angle={-25}
                textAnchor="end"
                height={70}
              />
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

      <div className="table-container">
        <h2>Sessions (Latest 50)</h2>

        {/* Filters */}
        <div
          style={{
            display: "flex",
            gap: 12,
            flexWrap: "wrap",
            alignItems: "center",
            marginBottom: 12,
          }}
        >
          <div style={{ display: "grid", gap: 6 }}>
            <span style={{ fontSize: 12, opacity: 0.8 }}>Intent</span>
            <select
              value={intentFilter}
              onChange={(e) => setIntentFilter(e.target.value)}
              style={{
                padding: "8px 10px",
                borderRadius: 10,
                border: "1px solid rgba(255,255,255,0.15)",
                background: "rgba(255,255,255,0.06)",
                color: "white",
                outline: "none",
              }}
            >
              <option value="all">All</option>
              {intentOptions.map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
          </div>

          <div style={{ display: "grid", gap: 6 }}>
            <span style={{ fontSize: 12, opacity: 0.8 }}>Risk</span>
            <select
              value={riskFilter}
              onChange={(e) => setRiskFilter(e.target.value)}
              style={{
                padding: "8px 10px",
                borderRadius: 10,
                border: "1px solid rgba(255,255,255,0.15)",
                background: "rgba(255,255,255,0.06)",
                color: "white",
                outline: "none",
              }}
            >
              <option value="all">All</option>
              <option value="high">High (7+)</option>
              <option value="med">Medium (4–6)</option>
              <option value="low">Low (0–3)</option>
              <option value="unknown">Unknown</option>
            </select>
          </div>

          <div style={{ display: "grid", gap: 6, minWidth: 260 }}>
            <span style={{ fontSize: 12, opacity: 0.8 }}>Search</span>
            <input
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              placeholder="session id / ip / command / summary…"
              style={{
                padding: "8px 10px",
                borderRadius: 10,
                border: "1px solid rgba(255,255,255,0.15)",
                background: "rgba(255,255,255,0.06)",
                color: "white",
                outline: "none",
              }}
            />
          </div>

          <div style={{ marginLeft: "auto", opacity: 0.85 }}>
            Showing <b>{Math.min(50, filteredSessions.length)}</b> /{" "}
            <b>{sessions.length}</b>
          </div>
        </div>

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
              <th>Top Commands</th>
              <th>Summary</th>
              <th>Start</th>
              <th>End</th>
              <th>Duration</th>
              <th>Source IP</th>
              <th># Events</th>
            </tr>
          </thead>

          <tbody>
            {filteredSessions.slice(0, 50).map((s) => (
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

                <td style={{ maxWidth: 420 }}>
                  {s.top3?.length ? (
                    <span>
                      {s.top3.map((c, idx) => (
                        <span key={`${s.session_id}-cmd-${idx}`}>
                          {c}
                          {idx < s.top3.length - 1 ? " • " : ""}
                        </span>
                      ))}
                    </span>
                  ) : (
                    "—"
                  )}
                </td>

                <td style={{ maxWidth: 520 }}>
                  {s.summary
                    ? s.summary.length > 120
                      ? s.summary.slice(0, 120) + "…"
                      : s.summary
                    : "—"}
                </td>
                <td>{safeDateStr(s.start)}</td>
                <td>{safeDateStr(s.end)}</td>
                <td>{formatDuration(s.durationMs)}</td>
                <td>{s.src_ip}</td>
                <td>{s.count}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <p style={{ opacity: 0.75, marginTop: 10 }}>
          Click a session row to view the full analysis, timeline, and all commands for that
          session.
        </p>
      </div>
    </div>
  );
}