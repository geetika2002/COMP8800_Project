import { useEffect, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  BarChart, Bar, Legend, PieChart, Pie, Cell
} from "recharts";
import "./App.css"; // add custom styles here

export default function App() {
  // State to hold all fetched event data
  const [events, setEvents] = useState([]);

  // Fetch data from API when component mounts and every 5 seconds after
  useEffect(() => {
    const fetchEvents = async () => {
      try {
        const res = await fetch("http://127.0.0.1:8000/api/events");
        const data = await res.json();
        setEvents(data); // update state with new event data
      } catch (err) {
        console.error("Error fetching events:", err);
      }
    };

    fetchEvents(); // initial fetch
    const interval = setInterval(fetchEvents, 5000); // periodic refresh
    return () => clearInterval(interval); // cleanup interval on unmount
  }, []);

  // --- Derived Metrics ---
  const totalAttacks = events.length; 
  const uniqueIPs = new Set(events.map((e) => e.src_ip)).size;
  const latestAttack =
    events.length > 0 ? new Date(events[0].timestamp).toLocaleString() : "N/A";

  // Group attacks by day
  const attacksByDay = Object.values(
    events.reduce((acc, e) => {
      const day = e.timestamp ? e.timestamp.split("T")[0] : "Unknown";
      acc[day] = acc[day] || { day, count: 0 };
      acc[day].count += 1;
      return acc;
    }, {})
  );

  // Top commands
  const commandFrequency = Object.values(
    events.reduce((acc, e) => {
      const cmd = e.command || "Unknown";
      acc[cmd] = acc[cmd] || { command: cmd, count: 0 };
      acc[cmd].count += 1;
      return acc;
    }, {})
  ).slice(0, 10);

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

  return (
    <div className="dashboard-container">
      <h1 className="dashboard-title">Honeypot Event Dashboard</h1>

      {/* Summary Stats */}
      <div className="stats-grid">
        <div className="stat-card">
          <p className="label">Total Attacks</p>
          <p className="value">{totalAttacks}</p>
        </div>
        <div className="stat-card">
          <p className="label">Unique IPs</p>
          <p className="value">{uniqueIPs}</p>
        </div>
        <div className="stat-card">
          <p className="label">Latest Attack</p>
          <p className="timestamp">{latestAttack}</p>
        </div>
      </div>

      {/* Charts */}
      <div className="charts-grid">
        <div className="chart-card">
          <h2>Attacks Over Time</h2>
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
          <h2>Attacks by Source IP</h2>
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

      {/* --- Recent Events Table --- */}
      <div className="table-container">
        <h2>Recent Events (Latest 50)</h2>
        <table className="event-table">
          <thead>
            <tr>
              <th>Timestamp</th>
              <th>Source IP</th>
              <th>Command</th>
              <th>LLM Analysis</th>
            </tr>
          </thead>


          {/* ⬇⬇⬇ ONLY CHANGE IS HERE — limit table to 50 rows */}
          <tbody>
            {events.slice(0, 50).map((e) => (
              <tr key={e.id}>
                <td>{e.timestamp}</td>
                <td>{e.src_ip}</td>
                <td>{e.command}</td>
                <td>{e.llm_analysis || "—"}</td>
              </tr>
            ))}
          </tbody>

        </table>
      </div>
    </div>
  );
}
