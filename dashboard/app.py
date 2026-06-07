"""
dashboard/app.py — NEXUS Flask Admin Dashboard

Routes:
  GET  /              - Dashboard home (stats overview)
  GET  /logs          - Chat logs viewer
  GET  /tools         - Tool usage statistics
  GET  /memory/search - Memory search interface
  GET  /status        - System status
  POST /api/search    - Memory search API
  GET  /api/stats     - Stats JSON API
"""
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, render_template_string, request, jsonify, abort

from config import config
from memory.database import DatabaseManager
from utils.logger import setup_logger

log = setup_logger("dashboard")

app = Flask(__name__)
app.secret_key = config.FLASK_SECRET_KEY

_db: DatabaseManager = None


def get_db() -> DatabaseManager:
    global _db
    if _db is None:
        _db = DatabaseManager(config.DATABASE_PATH)
    return _db


# ---------------------------------------------------------------------------
# HTML Templates
# ---------------------------------------------------------------------------
BASE_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NEXUS Admin — {{ page_title }}</title>
<style>
  :root {
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --text: #e6edf3; --muted: #8b949e; --accent: #58a6ff;
    --green: #3fb950; --red: #f85149; --yellow: #d29922;
    --purple: #bc8cff; --font: 'Courier New', monospace;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: var(--font); min-height: 100vh; }
  nav {
    background: var(--surface); border-bottom: 1px solid var(--border);
    padding: 1rem 2rem; display: flex; align-items: center; gap: 2rem;
    position: sticky; top: 0; z-index: 100;
  }
  nav .logo { color: var(--accent); font-size: 1.2rem; font-weight: bold; letter-spacing: 2px; }
  nav a { color: var(--muted); text-decoration: none; font-size: 0.9rem; transition: color 0.2s; }
  nav a:hover, nav a.active { color: var(--accent); }
  .container { max-width: 1400px; margin: 0 auto; padding: 2rem; }
  h1 { color: var(--accent); margin-bottom: 1.5rem; font-size: 1.5rem; letter-spacing: 1px; }
  h2 { color: var(--text); margin-bottom: 1rem; font-size: 1.1rem; }
  .grid { display: grid; gap: 1.5rem; }
  .grid-4 { grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); }
  .grid-2 { grid-template-columns: repeat(auto-fit, minmax(400px, 1fr)); }
  .card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 8px; padding: 1.5rem;
  }
  .stat-card { text-align: center; }
  .stat-value { font-size: 2.5rem; font-weight: bold; color: var(--accent); }
  .stat-label { color: var(--muted); font-size: 0.85rem; margin-top: 0.25rem; }
  .stat-sub { color: var(--green); font-size: 0.8rem; margin-top: 0.5rem; }
  table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
  th { color: var(--muted); text-align: left; padding: 0.75rem 0.5rem;
       border-bottom: 1px solid var(--border); font-weight: normal; text-transform: uppercase; font-size: 0.75rem; }
  td { padding: 0.6rem 0.5rem; border-bottom: 1px solid var(--border); vertical-align: top; }
  tr:hover td { background: rgba(88,166,255,0.05); }
  .badge {
    display: inline-block; padding: 0.15rem 0.5rem; border-radius: 4px;
    font-size: 0.75rem; font-weight: bold;
  }
  .badge-user { background: rgba(88,166,255,0.2); color: var(--accent); }
  .badge-assistant { background: rgba(63,185,80,0.2); color: var(--green); }
  .badge-success { background: rgba(63,185,80,0.2); color: var(--green); }
  .badge-fail { background: rgba(248,81,73,0.2); color: var(--red); }
  .badge-tool { background: rgba(188,140,255,0.2); color: var(--purple); }
  .truncate { max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .search-bar { display: flex; gap: 0.75rem; margin-bottom: 1.5rem; }
  .search-bar input {
    flex: 1; background: var(--surface); border: 1px solid var(--border);
    color: var(--text); padding: 0.6rem 1rem; border-radius: 6px; font-family: var(--font);
  }
  .search-bar input:focus { outline: none; border-color: var(--accent); }
  .search-bar button {
    background: var(--accent); color: var(--bg); border: none; padding: 0.6rem 1.5rem;
    border-radius: 6px; cursor: pointer; font-family: var(--font); font-weight: bold;
  }
  .search-bar button:hover { opacity: 0.85; }
  .result-item {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 6px; padding: 1rem; margin-bottom: 0.75rem;
  }
  .result-meta { color: var(--muted); font-size: 0.75rem; margin-top: 0.5rem; }
  pre { background: #0d1117; padding: 1rem; border-radius: 6px; overflow-x: auto;
        font-size: 0.8rem; border: 1px solid var(--border); white-space: pre-wrap; }
  .status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 0.5rem; }
  .dot-green { background: var(--green); box-shadow: 0 0 6px var(--green); }
  .dot-red { background: var(--red); }
  .pagination { display: flex; gap: 0.5rem; margin-top: 1rem; }
  .pagination a {
    padding: 0.25rem 0.75rem; border: 1px solid var(--border);
    color: var(--muted); text-decoration: none; border-radius: 4px;
  }
  .pagination a:hover { border-color: var(--accent); color: var(--accent); }
  .ts { color: var(--muted); font-size: 0.75rem; white-space: nowrap; }
</style>
</head>
<body>
<nav>
  <span class="logo">⚡ NEXUS</span>
  <a href="/" {% if active=='home' %}class="active"{% endif %}>Dashboard</a>
  <a href="/logs" {% if active=='logs' %}class="active"{% endif %}>Chat Logs</a>
  <a href="/tools" {% if active=='tools' %}class="active"{% endif %}>Tools</a>
  <a href="/memory" {% if active=='memory' %}class="active"{% endif %}>Memory</a>
  <a href="/status" {% if active=='status' %}class="active"{% endif %}>Status</a>
</nav>
<div class="container">
  {{ content }}
</div>
</body>
</html>
"""


def render_page(page_title: str, content: str, active: str = "home") -> str:
    return render_template_string(
        BASE_TEMPLATE,
        page_title=page_title,
        content=content,
        active=active,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def dashboard_home():
    db = get_db()
    stats = db.get_dashboard_stats()
    tool_stats = db.get_tool_stats()
    recent_logs = db.get_all_conversations(limit=5)

    top_tools = "".join(
        f"""<tr>
        <td><span class="badge badge-tool">{s['tool_name']}</span></td>
        <td>{s['total_calls']}</td>
        <td><span class="badge {'badge-success' if s['successful']==s['total_calls'] else 'badge-fail'}">{s['successful']}/{s['total_calls']}</span></td>
        <td>{int(s['avg_duration_ms'] or 0)}ms</td>
        <td class="ts">{s['last_used'][:16] if s['last_used'] else 'Never'}</td>
        </tr>"""
        for s in tool_stats[:5]
    )

    recent_msgs = "".join(
        f"""<tr>
        <td class="ts">{r['created_at'][:16]}</td>
        <td>{r.get('username') or r['user_id']}</td>
        <td><span class="badge {'badge-user' if r['role']=='user' else 'badge-assistant'}">{r['role']}</span></td>
        <td class="truncate">{r['content'][:120]}</td>
        </tr>"""
        for r in recent_logs
    )

    content = f"""
    <h1>⚡ NEXUS Dashboard</h1>

    <div class="grid grid-4" style="margin-bottom:2rem">
      <div class="card stat-card">
        <div class="stat-value">{stats['total_users']}</div>
        <div class="stat-label">Total Users</div>
      </div>
      <div class="card stat-card">
        <div class="stat-value">{stats['total_messages']}</div>
        <div class="stat-label">Messages</div>
        <div class="stat-sub">+{stats['messages_today']} today</div>
      </div>
      <div class="card stat-card">
        <div class="stat-value">{stats['total_tool_calls']}</div>
        <div class="stat-label">Tool Calls</div>
        <div class="stat-sub">+{stats['tool_calls_today']} today</div>
      </div>
      <div class="card stat-card">
        <div class="stat-value">{stats['total_decisions']}</div>
        <div class="stat-label">Agent Decisions</div>
      </div>
    </div>

    <div class="grid grid-2">
      <div class="card">
        <h2>🔧 Top Tools</h2>
        <table>
          <tr><th>Tool</th><th>Calls</th><th>Success</th><th>Avg Time</th><th>Last Used</th></tr>
          {top_tools or '<tr><td colspan="5" style="color:var(--muted)">No tool usage yet</td></tr>'}
        </table>
      </div>
      <div class="card">
        <h2>💬 Recent Messages</h2>
        <table>
          <tr><th>Time</th><th>User</th><th>Role</th><th>Content</th></tr>
          {recent_msgs or '<tr><td colspan="4" style="color:var(--muted)">No messages yet</td></tr>'}
        </table>
      </div>
    </div>
    """
    return render_page("Dashboard", content, active="home")


@app.route("/logs")
def chat_logs():
    db = get_db()
    page = request.args.get("page", 1, type=int)
    per_page = 50
    all_convs = db.get_all_conversations(limit=per_page * page)
    convs = all_convs[(page - 1) * per_page: page * per_page]

    rows = "".join(
        f"""<tr>
        <td class="ts">{r['created_at'][:19]}</td>
        <td>{r.get('first_name') or ''} {r.get('username') and '@'+r['username'] or r['user_id']}</td>
        <td><span class="badge {'badge-user' if r['role']=='user' else 'badge-assistant'}">{r['role']}</span></td>
        <td style="white-space:pre-wrap;max-width:600px;font-size:0.8rem">{r['content'][:400]}</td>
        </tr>"""
        for r in convs
    )

    content = f"""
    <h1>💬 Chat Logs</h1>
    <div class="card">
      <table>
        <tr><th>Time</th><th>User</th><th>Role</th><th>Message</th></tr>
        {rows or '<tr><td colspan="4" style="color:var(--muted)">No messages yet</td></tr>'}
      </table>
      <div class="pagination">
        {'<a href="/logs?page=' + str(page-1) + '">← Prev</a>' if page > 1 else ''}
        <span style="color:var(--muted);padding:0.25rem 0.75rem">Page {page}</span>
        {'<a href="/logs?page=' + str(page+1) + '">Next →</a>' if len(all_convs) >= per_page else ''}
      </div>
    </div>
    """
    return render_page("Chat Logs", content, active="logs")


@app.route("/tools")
def tool_stats():
    db = get_db()
    stats = db.get_tool_stats()
    recent_calls = db.get_recent_tool_logs(limit=30)

    rows = "".join(
        f"""<tr>
        <td><span class="badge badge-tool">{s['tool_name']}</span></td>
        <td style="color:var(--text);font-size:1.1rem">{s['total_calls']}</td>
        <td><span class="badge badge-success">{s['successful']}</span></td>
        <td><span class="badge badge-fail">{s['failed']}</span></td>
        <td>{int(s['avg_duration_ms'] or 0)}ms</td>
        <td class="ts">{(s['last_used'] or '')[:16]}</td>
        </tr>"""
        for s in stats
    )

    call_rows = "".join(
        f"""<tr>
        <td class="ts">{r['created_at'][:19]}</td>
        <td>{r.get('username') or r['user_id']}</td>
        <td><span class="badge badge-tool">{r['tool_name']}</span></td>
        <td class="truncate">{r.get('tool_input','')[:100]}</td>
        <td><span class="badge {'badge-success' if r['success'] else 'badge-fail'}">{'✓' if r['success'] else '✗'}</span></td>
        <td>{r.get('duration_ms') or 0}ms</td>
        </tr>"""
        for r in recent_calls
    )

    content = f"""
    <h1>🔧 Tool Statistics</h1>
    <div class="grid grid-2">
      <div class="card">
        <h2>Aggregate Stats</h2>
        <table>
          <tr><th>Tool</th><th>Total</th><th>Success</th><th>Failed</th><th>Avg Time</th><th>Last Used</th></tr>
          {rows or '<tr><td colspan="6" style="color:var(--muted)">No tool calls yet</td></tr>'}
        </table>
      </div>
      <div class="card">
        <h2>Recent Calls</h2>
        <table>
          <tr><th>Time</th><th>User</th><th>Tool</th><th>Input</th><th>OK</th><th>ms</th></tr>
          {call_rows or '<tr><td colspan="6" style="color:var(--muted)">No calls yet</td></tr>'}
        </table>
      </div>
    </div>
    """
    return render_page("Tool Statistics", content, active="tools")


@app.route("/memory")
def memory_search_page():
    keyword = request.args.get("q", "").strip()
    results = []
    if keyword:
        db = get_db()
        results = db.search_memory(keyword, limit=20)

    result_html = ""
    for r in results:
        result_html += f"""
        <div class="result-item">
          <div>{r.get('text','')[:500]}</div>
          <div class="result-meta">
            Source: <span class="badge badge-tool">{r.get('source','')}</span> |
            User ID: {r.get('user_id','')} |
            Time: {r.get('created_at','')[:16]}
          </div>
        </div>
        """

    content = f"""
    <h1>🧠 Memory Search</h1>
    <div class="card" style="margin-bottom:1.5rem">
      <form method="get" action="/memory">
        <div class="search-bar">
          <input type="text" name="q" value="{keyword}" placeholder="Search conversations, tool outputs..." autofocus>
          <button type="submit">Search</button>
        </div>
      </form>
      {'<p style="color:var(--muted)">Found ' + str(len(results)) + ' result(s) for: <strong style="color:var(--accent)">' + keyword + '</strong></p>' if keyword else '<p style="color:var(--muted)">Enter a keyword to search agent memory.</p>'}
    </div>
    {result_html if result_html else ('<p style="color:var(--muted)">No results found.</p>' if keyword else '')}
    """
    return render_page("Memory Search", content, active="memory")


@app.route("/status")
def system_status():
    import platform
    import psutil

    db = get_db()
    stats = db.get_dashboard_stats()

    # System info
    cpu = "N/A"
    mem_info = "N/A"
    disk_info = "N/A"
    try:
        import psutil
        cpu = f"{psutil.cpu_percent(interval=0.1):.1f}%"
        mem = psutil.virtual_memory()
        mem_info = f"{mem.percent:.1f}% ({mem.used // 1024 // 1024}MB / {mem.total // 1024 // 1024}MB)"
        disk = psutil.disk_usage("/")
        disk_info = f"{disk.percent:.1f}% ({disk.used // 1024 // 1024 // 1024}GB / {disk.total // 1024 // 1024 // 1024}GB)"
    except ImportError:
        pass

    db_size = "N/A"
    try:
        size_bytes = os.path.getsize(config.DATABASE_PATH)
        db_size = f"{size_bytes / 1024:.1f} KB"
    except Exception:
        pass

    content = f"""
    <h1>📊 System Status</h1>
    <div class="grid grid-2">
      <div class="card">
        <h2>🤖 Agent Status</h2>
        <table>
          <tr><td>Status</td><td><span class="status-dot dot-green"></span> Online</td></tr>
          <tr><td>Model</td><td><code>{config.GEMINI_MODEL}</code></td></tr>
          <tr><td>Max Iterations</td><td>{config.MAX_TOOL_ITERATIONS}</td></tr>
          <tr><td>Max History</td><td>{config.MAX_HISTORY_CONTEXT} messages</td></tr>
          <tr><td>Scrape Delay</td><td>{config.SCRAPE_DELAY_SECONDS}s</td></tr>
        </table>
      </div>
      <div class="card">
        <h2>💾 Database</h2>
        <table>
          <tr><td>Path</td><td><code>{config.DATABASE_PATH}</code></td></tr>
          <tr><td>Size</td><td>{db_size}</td></tr>
          <tr><td>Total Users</td><td>{stats['total_users']}</td></tr>
          <tr><td>Total Messages</td><td>{stats['total_messages']}</td></tr>
          <tr><td>Total Tool Calls</td><td>{stats['total_tool_calls']}</td></tr>
        </table>
      </div>
      <div class="card">
        <h2>🖥️ System Resources</h2>
        <table>
          <tr><td>Platform</td><td>{platform.system()} {platform.release()}</td></tr>
          <tr><td>Python</td><td>{platform.python_version()}</td></tr>
          <tr><td>CPU Usage</td><td>{cpu}</td></tr>
          <tr><td>Memory</td><td>{mem_info}</td></tr>
          <tr><td>Disk</td><td>{disk_info}</td></tr>
        </table>
      </div>
      <div class="card">
        <h2>🔧 Active Tools</h2>
        <table>
          {''.join('<tr><td><span class="badge badge-tool">' + t + '</span></td><td><span class="status-dot dot-green"></span>Active</td></tr>' for t in ['web_search','ip_lookup','domain_whois','code_executor','file_analyzer','github_repo_analyzer','url_scraper'])}
        </table>
      </div>
    </div>
    """
    return render_page("System Status", content, active="status")


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------
@app.route("/api/stats")
def api_stats():
    db = get_db()
    return jsonify({
        "stats": db.get_dashboard_stats(),
        "tool_stats": db.get_tool_stats(),
    })


@app.route("/api/search", methods=["POST"])
def api_search():
    db = get_db()
    data = request.get_json()
    keyword = data.get("keyword", "").strip()
    if not keyword:
        return jsonify({"error": "keyword required"}), 400
    results = db.search_memory(keyword)
    return jsonify({"results": results})


def create_app(db_path: str = None) -> Flask:
    """Factory function for creating the Flask app."""
    global _db
    if db_path:
        _db = DatabaseManager(db_path)
    return app


if __name__ == "__main__":
    log.info(f"Starting NEXUS Dashboard on {config.FLASK_HOST}:{config.FLASK_PORT}")
    app.run(
        host=config.FLASK_HOST,
        port=config.FLASK_PORT,
        debug=config.FLASK_DEBUG,
    )
