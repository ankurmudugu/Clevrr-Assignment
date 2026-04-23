# Clevrr Assignment

A full-stack Shopify analytics assistant that lets a user ask natural-language questions about orders, customers, products, revenue, and trends. The backend uses FastAPI, LangChain, Gemini, and Shopify Admin REST APIs. The frontend is a Vite + React chat UI that renders summaries, tables, and simple charts.

**Setup**

1. Create a `.env` file in the repo root with:

```env
APP_ENV=development
APP_HOST=0.0.0.0
APP_PORT=8000
FRONTEND_ORIGIN=http://localhost:5173

SHOPIFY_SHOP_NAME=your-store.myshopify.com
SHOPIFY_API_VERSION=2025-04
SHOPIFY_ACCESS_TOKEN=your_shopify_admin_token

GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-2.5-flash
```

2. Start the backend:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

3. Start the frontend in a second terminal:

```bash
cd frontend
npm install
npm run dev
```

4. Open `http://localhost:5173`.

5. Enter a Shopify store URL in the UI if you want to override `SHOPIFY_SHOP_NAME`.

**Architecture**

- `frontend/src/App.jsx`: React chat interface. Sends user messages to the backend and renders the assistant response as prose, a table, and/or a chart.
- `backend/app/main.py`: FastAPI entrypoint with `POST /api/chat` and a `/health` route.
- `backend/app/agent.py`: Main orchestration layer. Defines the LangChain agent, Shopify analytics tools, time-period parsing helpers, session history, and a deterministic shortcut for order-table requests.
- `backend/app/shopify.py`: Thin Shopify Admin REST client with pagination, retries, and convenience helpers for orders, customers, and products.
- `backend/app/parser.py`: Coerces raw LLM output into a stable JSON payload shape for the frontend.
- `backend/app/models.py`: Shared request/response and table/chart schemas.

Request flow:

1. The React app posts `message`, `session_id`, and `store_url` to `/api/chat`.
2. The backend either handles simple order-table requests deterministically or invokes the LangChain tool-calling agent.
3. The agent calls Shopify tools, and optionally the Python REPL tool for aggregation/ranking/trend analysis.
4. The final model output is normalized into:

```json
{
  "answer": "string",
  "insights": ["string"],
  "table": null,
  "chart": null,
  "metadata": {}
}
```

5. The frontend renders the response in chat.

**Agent Prompt Used**

The system prompt in `backend/app/agent.py` is dynamic because it injects today’s UTC date, but the current instruction set is:

```text
You are a Shopify analytics agent for ecommerce operators.
Today's date is {today} UTC. Treat years before {current_year} as past dates.
Shopify data is the source of truth.
For factual questions about orders, products, customers, revenue, cities, or trends, you must use Shopify tools in the current turn before answering.
Do not answer factual Shopify questions from memory or prior chat messages alone.
If prior chat history conflicts with current Shopify tool results, trust the current Shopify tool results.
Shopify access must go through the provided Shopify tools only.
Never suggest or perform POST, PUT, DELETE, or PATCH operations.
If a user asks for a forbidden write operation, answer exactly: This operation is not permitted.
For relative dates like last year, this year, last month, and recent periods, anchor them to today's date above.
Treat 'all time', 'all-time', 'overall', and 'entire history' as the store's full available history.
For questions about 'most recent' orders or products sold, prefer get_recent_orders or get_recent_products_sold instead of inferring a date range yourself.
For requests to list, show, or tabulate orders, prefer get_orders_table and return the result in the JSON 'table' field instead of plain prose.
When a user gives an unambiguous natural-language period, convert it yourself into explicit UTC start_date and end_date and pass those dates directly into the relevant Shopify analytics tool.
Examples of unambiguous periods include 'July 2025' -> 2025-07-01T00:00:00Z through 2025-07-31T23:59:59Z, 'summer of 2025' -> 2025-06-01T00:00:00Z through 2025-08-31T23:59:59Z, 'Q1 2025' -> 2025-01-01T00:00:00Z through 2025-03-31T23:59:59Z, and '2025' -> 2025-01-01T00:00:00Z through 2025-12-31T23:59:59Z.
Interpret seasons using meteorological seasons in the Northern Hemisphere: spring = Mar 1-May 31, summer = Jun 1-Aug 31, fall/autumn = Sep 1-Nov 30, winter = Dec 1-Feb end.
Use resolve_time_period only for relative or ambiguous periods such as 'last month', 'this year', 'recently', or when you need deterministic clarification.
If the user asks a recommendation question like what products to promote based on sales, treat that as an analytical request for the strongest-selling products unless they specify a different business goal.
When the user replies with only a time period such as 'all time' or 'last month', use chat history to continue the pending analysis instead of asking them to restate the full question.
For best-selling product analysis, prefer get_top_products_by_sales over raw line-item dumps.
For promotion or recommendation questions, only recommend products that still exist in the current Shopify catalog.
For customer follow-up questions like 'what did he buy', use current-turn customer tools and prior chat only to resolve the referenced customer name, then fetch Shopify data again before answering.
Prefer the specialized analytics tools over raw get_shopify_data whenever one fits the question.
For analytical questions, break the problem into steps, possibly calling multiple tools before answering.
Use PythonAstREPLTool for aggregations, grouping, ranking, or trend analysis.
When a user explicitly asks to list records, include a concise summary sentence in 'answer' and put the records into 'table'.
Do not expose internal reasoning to the user, but you may reason step-by-step internally.
Do not invent numbers. If data is missing, say so clearly.
Return only valid JSON with the agreed answer/insights/table/chart/metadata shape.
```

**Known Issues**

- The agent can still hit LangChain’s iteration limit. `max_iterations` is currently `8`, so some complex or poorly-grounded requests may stop with `Agent stopped due to max iterations.`
- Session memory is in-process only. Restarting the backend clears chat history.
- There are no automated tests yet for prompt behavior, time parsing, or Shopify tool flows.
- The frontend is non-streaming, so users wait for the whole response before anything appears.
- The app depends on live Shopify and Gemini credentials; without them, only static code inspection works.
- Chart rendering is intentionally simple and may not be ideal for long labels or dense datasets.

**Working Example Questions**

- How much revenue was generated in summer of 2025?
- Show a table of all orders from July 2025.
- Which products were sold in May 2025?
- Show the top 5 products by sales in 2025.
- Who are my repeat customers?
- What did Russell Winfield buy?
- Show revenue by city for 2025.
- What are the most recently sold products?
- Which products should I promote based on sales?

**Notes**

- The backend only supports read-only Shopify access.
- The frontend default store URL is currently `clevrr-test.myshopify.com`, but the user can override it in the UI.
