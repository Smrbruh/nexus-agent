"""
main.py — NEXUS Agent Main Entrypoint

Runs both the Telegram bot and Flask dashboard concurrently using
asyncio + threading so they share the same process and database.

Usage:
    python main.py              # Run everything
    python main.py --bot-only   # Telegram bot only
    python main.py --dash-only  # Dashboard only
"""
import argparse
import asyncio
import os
import sys
import threading

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import config
from utils.logger import setup_logger

log = setup_logger("main", level=config.LOG_LEVEL, log_file=config.LOG_FILE)


def run_dashboard():
    """Run Flask dashboard in a separate thread."""
    from dashboard.app import create_app
    app = create_app(db_path=config.DATABASE_PATH)
    log.info(f"Dashboard starting on http://{config.FLASK_HOST}:{config.FLASK_PORT}")
    app.run(
        host=config.FLASK_HOST,
        port=config.FLASK_PORT,
        debug=False,
        use_reloader=False,  # Must be False in thread
    )


async def run_bot():
    """Run Telegram bot."""
    from bot.telegram_bot import run_bot as _run_bot
    await _run_bot()


def main():
    parser = argparse.ArgumentParser(description="NEXUS AI Agent")
    parser.add_argument("--bot-only", action="store_true", help="Run only the Telegram bot")
    parser.add_argument("--dash-only", action="store_true", help="Run only the Flask dashboard")
    parser.add_argument("--check", action="store_true", help="Check configuration and exit")
    args = parser.parse_args()

    # Print banner
    banner = r"""
  ███╗   ██╗███████╗██╗  ██╗██╗   ██╗███████╗
  ████╗  ██║██╔════╝╚██╗██╔╝██║   ██║██╔════╝
  ██╔██╗ ██║█████╗   ╚███╔╝ ██║   ██║███████╗
  ██║╚██╗██║██╔══╝   ██╔██╗ ██║   ██║╚════██║
  ██║ ╚████║███████╗██╔╝ ██╗╚██████╔╝███████║
  ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝
       AI AGENT — OSINT + DEV ENGINE v1.0
    """
    print(banner)

    # Validate config
    missing = config.validate()
    if missing:
        log.error(f"Missing required environment variables: {missing}")
        log.error("Copy .env.example to .env and fill in the values.")
        sys.exit(1)
    else:
        log.info("Configuration validated ✓")

    if args.check:
        log.info("Config check passed. Exiting.")
        sys.exit(0)

    # Create data directories
    os.makedirs("data", exist_ok=True)
    os.makedirs("logs", exist_ok=True)

    if args.dash_only:
        log.info("Starting in DASHBOARD-ONLY mode")
        run_dashboard()
        return

    if args.bot_only:
        log.info("Starting in BOT-ONLY mode")
        asyncio.run(run_bot())
        return

    # Full mode: bot + dashboard
    log.info("Starting NEXUS in FULL mode (Bot + Dashboard)")

    # Dashboard in background thread
    dash_thread = threading.Thread(target=run_dashboard, daemon=True, name="Dashboard")
    dash_thread.start()
    log.info("Dashboard thread started")

    # Bot in main asyncio loop
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        log.info("NEXUS shutting down gracefully...")


if __name__ == "__main__":
    main()
