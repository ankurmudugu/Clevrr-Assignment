import { useEffect, useState } from "react";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || (import.meta.env.DEV ? "http://localhost:8000" : "");

const samplePrompts = [
  "Which products were sold in the month of May 2025?",
  "Show a chart of the top 5 products sold in 2025.",
  "Show a table of revenue by city.",
  "Who are my repeat customers?",
];

function createSessionId() {
  return `session-${Math.random().toString(36).slice(2)}-${Date.now()}`;
}


function Chart({ chart }) {
  if (!chart?.data?.length) return null;

  const sampleDatum = chart.data.find((item) => item && typeof item === "object") || {};
  const candidateKeys = Object.keys(sampleDatum);
  const toSnakeCase = (value) =>
    String(value || "")
      .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
      .toLowerCase();
  const toCamelCase = (value) =>
    String(value || "").replace(/_([a-z])/g, (_, letter) => letter.toUpperCase());
  const resolveDataKey = (preferredKeys, fallbackKeys) => {
    const allCandidates = [...preferredKeys, ...fallbackKeys].filter(Boolean);
    for (const key of allCandidates) {
      if (candidateKeys.includes(key)) return key;
      const snakeKey = toSnakeCase(key);
      if (candidateKeys.includes(snakeKey)) return snakeKey;
      const camelKey = toCamelCase(key);
      if (candidateKeys.includes(camelKey)) return camelKey;
    }
    return fallbackKeys.find((key) => candidateKeys.includes(key)) || candidateKeys[0] || "label";
  };
  const coerceNumber = (value) => {
    if (typeof value === "number") return Number.isFinite(value) ? value : 0;
    if (typeof value === "string") {
      const normalized = value.replace(/[^0-9.-]+/g, "");
      const parsed = Number(normalized);
      return Number.isFinite(parsed) ? parsed : 0;
    }
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  };
  const xKey =
    resolveDataKey(
      [chart.xKey, chart.x_key],
      ["label", "date", "day", "month", "city", "product", "product_title", "title", "name"],
    );
  const yKey =
    resolveDataKey(
      [chart.yKey, chart.y_key],
      ["value", "aov", "revenue", "orders", "units_sold", "gross_sales", "grossSales", "count"],
    );
  const values = chart.data.map((item) => coerceNumber(item[yKey] ?? 0));
  const maxValue = Math.max(...values, 1);
  const yAxisTicks = [maxValue, maxValue * 0.75, maxValue * 0.5, maxValue * 0.25, 0];
  const chartLeft = 12;
  const chartRight = 98;
  const chartTop = 6;
  const chartBottom = 92;
  const chartWidth = chartRight - chartLeft;
  const chartHeight = chartBottom - chartTop;
  const barWidth = chartWidth / chart.data.length;
  const formatTickValue = (value) => {
    if (maxValue >= 1000) {
      return value.toLocaleString(undefined, { maximumFractionDigits: 0 });
    }
    if (maxValue >= 10) {
      return value.toLocaleString(undefined, { maximumFractionDigits: 1 });
    }
    return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  };
  const formatLabel = (value) => {
    const text = String(value ?? "");
    if (text.length <= 18) return text;
    return `${text.slice(0, 16)}...`;
  };

  if (chart.type === "line") {
    const points = chart.data
      .map((item, index) => {
        const x = chartLeft + (index / Math.max(chart.data.length - 1, 1)) * chartWidth;
        const y = chartBottom - (coerceNumber(item[yKey] ?? 0) / maxValue) * chartHeight;
        return `${x},${y}`;
      })
      .join(" ");

    return (
      <div className="chart-card">
        {chart.title ? <h4>{chart.title}</h4> : null}
        <svg viewBox="0 0 100 100" className="chart-svg" preserveAspectRatio="none">
          {yAxisTicks.map((tickValue) => {
            const y = chartBottom - (tickValue / maxValue) * chartHeight;
            return (
              <g key={tickValue}>
                <line x1={chartLeft} y1={y} x2={chartRight} y2={y} className="chart-grid-line" />
                <text x={chartLeft - 1.5} y={y} className="chart-y-tick" textAnchor="end" dominantBaseline="middle">
                  {formatTickValue(tickValue)}
                </text>
              </g>
            );
          })}
          <line x1={chartLeft} y1={chartTop} x2={chartLeft} y2={chartBottom} className="chart-axis-line" />
          <line x1={chartLeft} y1={chartBottom} x2={chartRight} y2={chartBottom} className="chart-axis-line" />
          <polyline fill="none" stroke="currentColor" strokeWidth="2" points={points} />
        </svg>
        <div className="chart-labels">
          {chart.data.map((item) => (
            <span key={String(item[xKey])} title={String(item[xKey])}>
              {formatLabel(item[xKey])}
            </span>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="chart-card">
      {chart.title ? <h4>{chart.title}</h4> : null}
      <svg viewBox="0 0 100 100" className="chart-svg" preserveAspectRatio="none">
        {yAxisTicks.map((tickValue) => {
          const y = chartBottom - (tickValue / maxValue) * chartHeight;
          return (
            <g key={tickValue}>
              <line x1={chartLeft} y1={y} x2={chartRight} y2={y} className="chart-grid-line" />
              <text x={chartLeft - 1.5} y={y} className="chart-y-tick" textAnchor="end" dominantBaseline="middle">
                {formatTickValue(tickValue)}
              </text>
            </g>
          );
        })}
        <line x1={chartLeft} y1={chartTop} x2={chartLeft} y2={chartBottom} className="chart-axis-line" />
        <line x1={chartLeft} y1={chartBottom} x2={chartRight} y2={chartBottom} className="chart-axis-line" />
        {chart.data.map((item, index) => {
          const value = coerceNumber(item[yKey] ?? 0);
          const height = (value / maxValue) * chartHeight;
          const x = chartLeft + index * barWidth + 1.5;
          const width = Math.max(barWidth - 4, 4);
          const y = chartBottom - height;
          return <rect key={String(item[xKey])} x={x} y={y} width={width} height={height} rx="2" className="chart-bar" />;
        })}
      </svg>
      <div className="chart-labels">
        {chart.data.map((item) => (
          <span key={String(item[xKey])} title={String(item[xKey])}>
            {formatLabel(item[xKey])}
          </span>
        ))}
      </div>
    </div>
  );
}

function DataTable({ table }) {
  if (!table?.columns?.length) return null;

  return (
    <div className="table-card">
      {table.title ? <h4>{table.title}</h4> : null}
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              {table.columns.map((column) => (
                <th key={column}>{column}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row, rowIndex) => (
              <tr key={`${rowIndex}-${row.join("|")}`}>
                {row.map((cell, cellIndex) => (
                  <td key={`${rowIndex}-${cellIndex}`}>{String(cell)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function AssistantMessage({ response }) {
  const displayAnswer =
    response?.answer?.trim() ||
    response?.insights?.[0] ||
    (response?.table?.rows?.length ? "Here is the requested table." : "") ||
    (response?.chart?.data?.length ? "Here is the requested chart." : "") ||
    "The agent returned a response, but no summary text was included.";

  return (
    <div className="message assistant">
      <p>{displayAnswer}</p>
      {response.insights?.length ? (
        <ul className="insights">
          {response.insights.map((insight) => (
            <li key={insight}>{insight}</li>
          ))}
        </ul>
      ) : null}
      <DataTable table={response.table} />
      <Chart chart={response.chart} />
    </div>
  );
}

export default function App() {
  const [storeUrl, setStoreUrl] = useState("clevrr-test.myshopify.com");
  const [sessionId, setSessionId] = useState("");
  const [message, setMessage] = useState("");
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setSessionId(createSessionId());
  }, []);

  const canSubmit = Boolean(message.trim() && storeUrl.trim() && !loading);

  async function sendMessage(nextMessage) {
    const trimmed = nextMessage.trim();
    if (!trimmed) return;
    const activeSessionId = sessionId || createSessionId();
    if (!sessionId) {
      setSessionId(activeSessionId);
    }

    const userEntry = { id: crypto.randomUUID(), role: "user", content: trimmed };
    setMessages((current) => [...current, userEntry]);
    setMessage("");
    setError("");
    setLoading(true);

    try {
      const response = await fetch(`${API_BASE_URL}/api/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          message: trimmed,
          session_id: activeSessionId,
          store_url: storeUrl,
        }),
      });

      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || "Failed to get agent response.");
      }

      setMessages((current) => [
        ...current,
        { id: crypto.randomUUID(), role: "assistant", response: payload.response },
      ]);
    } catch (err) {
      setError(err.message || "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-top">
          <p className="eyebrow">Shopify Agent Assignment</p>
          <h1>Store analysis that feels like a conversation.</h1>
          <p className="lede">
            Connect a Shopify Admin REST store, ask natural-language questions, and get answers with tables and chart-ready data.
          </p>
        </div>

        <label className="field">
          <span>Shopify store URL</span>
          <input value={storeUrl} onChange={(event) => setStoreUrl(event.target.value)} placeholder="your-store.myshopify.com" />
        </label>

        <div className="sidebar-section">
          <div className="section-heading">
            <h2>Starter prompts</h2>
            <span>Jump into common store questions</span>
          </div>
          {samplePrompts.map((prompt) => (
            <button key={prompt} type="button" className="prompt-chip" onClick={() => sendMessage(prompt)} disabled={loading}>
              {prompt}
            </button>
          ))}
        </div>

        <div className="sidebar-footer">
          <div className="status-card">
            <span className="status-dot" aria-hidden="true" />
            <div>
              <strong>Session ready</strong>
              <p>Responses stay grounded in the same conversation context.</p>
            </div>
          </div>
        </div>
      </aside>

      <main className="chat-panel">
        <header className="chat-header">
          <div>
            <p className="chat-kicker">Chat workspace</p>
            <h2>Ask about orders, customers, products, revenue, or trends.</h2>
          </div>
          <div className="chat-badge">Live store analysis</div>
        </header>

        <div className="messages">
          {!messages.length ? (
            <div className="empty-state">
              <div className="empty-state-icon" aria-hidden="true">
                SA
              </div>
              <h3>Start with a question or try one of the prompts on the left.</h3>
              <p>The backend uses a tool-enabled agent that can fetch Shopify data and shape analysis results for this chat UI.</p>
            </div>
          ) : null}

          {messages.map((entry) =>
            entry.role === "user" ? (
              <div key={entry.id} className="message user">
                <p>{entry.content}</p>
              </div>
            ) : (
              <AssistantMessage key={entry.id} response={entry.response} />
            ),
          )}
          {loading ? <div className="message assistant pending">Thinking through the store data...</div> : null}
        </div>

        <form
          className="composer"
          onSubmit={(event) => {
            event.preventDefault();
            sendMessage(message);
          }}
        >
          <div className="composer-header">
            <span>Message</span>
            <span>{loading ? "Analyzing store data" : "Ask a follow-up anytime"}</span>
          </div>
          <textarea
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                if (canSubmit) {
                  sendMessage(message);
                }
              }
            }}
            rows={3}
            placeholder="Ask about revenue by city, repeat customers, AOV trends, top sellers..."
          />
          <div className="composer-row">
            {error ? <p className="error-text">{error}</p> : <span className="helper-text">The agent keeps session context across turns.</span>}
            <button type="submit" disabled={!canSubmit}>
              {loading ? "Analyzing..." : "Send"}
            </button>
          </div>
        </form>
      </main>
    </div>
  );
}
