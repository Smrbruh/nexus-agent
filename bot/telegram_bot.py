"""
bot/telegram_bot.py — NEXUS Telegram Bot Interface

Commands:
  /start     - Welcome message
  /help      - Full command list
  /tools     - List available tools
  /memory    - Show conversation history
  /clear     - Clear conversation history
  /status    - System status
  /osint     - OSINT mode hint
  /dev       - DEV agent mode hint
  /search    - Quick web search
  /ip        - Quick IP lookup
  /whois     - Quick WHOIS lookup
  /github    - Analyze GitHub repo
  /run       - Execute Python snippet
  /admin     - Admin panel (admin only)

Chat: any text message → full agent reasoning loop
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    BotCommand,
    BotCommandScopeDefault,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.utils.markdown import hbold, hcode
from aiogram.enums import ParseMode

from config import config
from agent.brain import AgentBrain
from agent.dev_agent import classify_dev_task, is_dev_query, format_dev_response_header
from memory.database import DatabaseManager
from tools.tool_registry import registry
from utils.logger import setup_logger
from utils.helpers import truncate, chunk_text

log = setup_logger("bot")

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------
db: DatabaseManager = None
agent: AgentBrain = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def send_long_message(message: Message, text: str, parse_mode: str = ParseMode.HTML):
    """Send a message, splitting it if it exceeds Telegram's 4096 char limit."""
    chunks = chunk_text(text, size=4000)
    for i, chunk in enumerate(chunks):
        if i == 0:
            await message.answer(chunk, parse_mode=parse_mode)
        else:
            await message.answer(f"...(continued)\n{chunk}", parse_mode=parse_mode)


async def typing_action(message: Message):
    """Show typing indicator."""
    try:
        await message.bot.send_chat_action(message.chat.id, action="typing")
    except Exception:
        pass


def is_admin(user_id: int) -> bool:
    return user_id in config.TELEGRAM_ADMIN_IDS


# ---------------------------------------------------------------------------
# Router setup
# ---------------------------------------------------------------------------
router = Router()


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------
@router.message(CommandStart())
async def cmd_start(message: Message):
    user = message.from_user
    db.upsert_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        is_admin=is_admin(user.id),
    )

    welcome = (
        f"⚡ <b>NEXUS AGENT ONLINE</b>\n\n"
        f"Welcome, <b>{user.first_name}</b>.\n\n"
        f"I am <b>NEXUS</b> — your AI-powered agent for:\n"
        f"  🕵️ <b>OSINT</b> — IP lookup, WHOIS, web intelligence\n"
        f"  💻 <b>DEV</b> — code generation, debugging, architecture\n"
        f"  🔍 <b>Research</b> — web scraping, GitHub analysis\n"
        f"  🧠 <b>Reasoning</b> — multi-step problem solving\n\n"
        f"Just send me any message to begin.\n"
        f"Type /help for the full command list."
    )
    await message.answer(welcome, parse_mode=ParseMode.HTML)


# ---------------------------------------------------------------------------
# /help
# ---------------------------------------------------------------------------
@router.message(Command("help"))
async def cmd_help(message: Message):
    help_text = (
        "📚 <b>NEXUS Command Reference</b>\n\n"
        "<b>🔎 OSINT Commands:</b>\n"
        "  /ip <code>&lt;address&gt;</code> — IP geolocation lookup\n"
        "  /whois <code>&lt;domain&gt;</code> — Domain WHOIS lookup\n"
        "  /search <code>&lt;query&gt;</code> — Web search\n\n"
        "<b>💻 Dev Commands:</b>\n"
        "  /github <code>&lt;url or owner/repo&gt;</code> — Analyze GitHub repo\n"
        "  /run <code>&lt;python code&gt;</code> — Execute Python snippet\n\n"
        "<b>🤖 Agent Commands:</b>\n"
        "  /tools — List all available tools\n"
        "  /status — System status\n\n"
        "<b>💬 Memory Commands:</b>\n"
        "  /memory — Show conversation history\n"
        "  /clear — Clear your conversation history\n\n"
        "<b>💡 Mode Hints:</b>\n"
        "  /osint — OSINT usage examples\n"
        "  /dev — DEV agent usage examples\n\n"
        "<b>🗨️ Chat Mode:</b>\n"
        "Just send any message and NEXUS will reason, pick tools, and respond.\n\n"
        "Examples:\n"
        '  • "Analyze github.com/fastapi/fastapi"\n'
        '  • "Look up IP 1.1.1.1"\n'
        '  • "Write a FastAPI CRUD API for users"\n'
        '  • "Debug this Python code: [paste code]"\n'
    )
    await message.answer(help_text, parse_mode=ParseMode.HTML)


# ---------------------------------------------------------------------------
# /tools
# ---------------------------------------------------------------------------
@router.message(Command("tools"))
async def cmd_tools(message: Message):
    tools_text = "🔧 <b>NEXUS Tool Arsenal</b>\n\n"
    tool_info = [
        ("🔍", "web_search", "Search the web for current information"),
        ("🌐", "ip_lookup", "Geolocate any IP address"),
        ("📋", "domain_whois", "WHOIS lookup for any domain"),
        ("🐍", "code_executor", "Execute Python code safely"),
        ("📁", "file_analyzer", "Analyze files and directories"),
        ("🐙", "github_repo_analyzer", "Deep-dive GitHub repositories"),
        ("🕷️", "url_scraper", "Scrape content from any URL"),
    ]
    for emoji, name, desc in tool_info:
        tools_text += f"{emoji} <code>{name}</code>\n   {desc}\n\n"
    await message.answer(tools_text, parse_mode=ParseMode.HTML)


# ---------------------------------------------------------------------------
# /osint
# ---------------------------------------------------------------------------
@router.message(Command("osint"))
async def cmd_osint(message: Message):
    osint_text = (
        "🕵️ <b>OSINT Mode Examples</b>\n\n"
        "NEXUS automatically uses OSINT tools when you ask:\n\n"
        "<b>IP Intelligence:</b>\n"
        '  "Look up 8.8.8.8"\n'
        '  "/ip 185.199.108.153"\n\n'
        "<b>Domain Research:</b>\n"
        '  "WHOIS on github.com"\n'
        '  "/whois telegram.org"\n\n'
        "<b>Web Intelligence:</b>\n"
        '  "Search for recent data breaches 2024"\n'
        '  "Scrape and summarize https://example.com"\n\n'
        "<b>Multi-step OSINT:</b>\n"
        '  "Research the company behind IP 185.199.108.153"\n'
        '  "Find information about the domain tesla.com including WHOIS and web presence"\n'
    )
    await message.answer(osint_text, parse_mode=ParseMode.HTML)


# ---------------------------------------------------------------------------
# /dev
# ---------------------------------------------------------------------------
@router.message(Command("dev"))
async def cmd_dev(message: Message):
    dev_text = (
        "💻 <b>DEV Agent Mode Examples</b>\n\n"
        "NEXUS is also a full-stack dev agent. Try:\n\n"
        "<b>Code Generation:</b>\n"
        '  "Write a FastAPI REST API with SQLite"\n'
        '  "Create a Python websocket server"\n\n'
        "<b>Debugging:</b>\n"
        '  "Debug this: [paste your code + error]"\n'
        '  "Why is my async function not awaited?"\n\n'
        "<b>Architecture:</b>\n"
        '  "Design a microservices architecture for a food delivery app"\n'
        '  "Design a Redis caching layer for a Django app"\n\n'
        "<b>Code Review:</b>\n"
        '  "Review this code: [paste code]"\n'
        '  "How can I improve this function?"\n\n'
        "<b>GitHub Analysis:</b>\n"
        '  "/github tiangolo/fastapi"\n'
        '  "Analyze github.com/django/django"\n\n'
        "<b>Project Scaffold:</b>\n"
        '  "Scaffold a full Telegram bot project in Python"\n'
    )
    await message.answer(dev_text, parse_mode=ParseMode.HTML)


# ---------------------------------------------------------------------------
# /status
# ---------------------------------------------------------------------------
@router.message(Command("status"))
async def cmd_status(message: Message):
    stats = db.get_dashboard_stats()
    status_text = (
        "📊 <b>NEXUS System Status</b>\n\n"
        f"🟢 <b>Agent:</b> Online\n"
        f"🧠 <b>Model:</b> {config.GEMINI_MODEL}\n"
        f"🔧 <b>Tools:</b> {len(registry.tool_names)} active\n\n"
        f"<b>📈 Statistics:</b>\n"
        f"  👥 Users: {stats.get('total_users', 0)}\n"
        f"  💬 Messages: {stats.get('total_messages', 0)}\n"
        f"  🔧 Tool Calls: {stats.get('total_tool_calls', 0)}\n"
        f"  🧠 Decisions: {stats.get('total_decisions', 0)}\n"
        f"  📅 Today's Messages: {stats.get('messages_today', 0)}\n"
        f"  📅 Today's Tool Calls: {stats.get('tool_calls_today', 0)}\n"
    )
    if is_admin(message.from_user.id):
        status_text += f"\n🌐 Dashboard: http://localhost:{config.FLASK_PORT}"
    await message.answer(status_text, parse_mode=ParseMode.HTML)


# ---------------------------------------------------------------------------
# /memory
# ---------------------------------------------------------------------------
@router.message(Command("memory"))
async def cmd_memory(message: Message):
    history = db.get_history(message.from_user.id, limit=10)
    if not history:
        await message.answer("📭 No conversation history yet.")
        return

    lines = ["🧠 <b>Recent Conversation History</b>\n"]
    for msg in history[-8:]:
        icon = "👤" if msg["role"] == "user" else "🤖"
        content = truncate(msg["content"], 150)
        lines.append(f"{icon} <i>{msg['role'].upper()}</i>: {content}\n")

    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)


# ---------------------------------------------------------------------------
# /clear
# ---------------------------------------------------------------------------
@router.message(Command("clear"))
async def cmd_clear(message: Message):
    db.clear_history(message.from_user.id)
    await message.answer("🗑️ Conversation history cleared. Fresh start!")


# ---------------------------------------------------------------------------
# Quick command shortcuts
# ---------------------------------------------------------------------------
@router.message(Command("ip"))
async def cmd_ip(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Usage: <code>/ip 8.8.8.8</code>", parse_mode=ParseMode.HTML)
        return
    await typing_action(message)
    result, success, _ = registry.execute("ip_lookup", args[1].strip())
    await send_long_message(message, result, parse_mode=None)


@router.message(Command("whois"))
async def cmd_whois(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Usage: <code>/whois example.com</code>", parse_mode=ParseMode.HTML)
        return
    await typing_action(message)
    result, success, _ = registry.execute("domain_whois", args[1].strip())
    await send_long_message(message, result, parse_mode=None)


@router.message(Command("search"))
async def cmd_search(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Usage: <code>/search your query here</code>", parse_mode=ParseMode.HTML)
        return
    await typing_action(message)
    processing = await message.answer("🔍 Searching the web...")
    result, success, _ = registry.execute("web_search", args[1].strip())
    await processing.delete()
    await send_long_message(message, result, parse_mode=None)


@router.message(Command("github"))
async def cmd_github(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "Usage: <code>/github owner/repo</code> or <code>/github https://github.com/owner/repo</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    await typing_action(message)
    processing = await message.answer("🐙 Analyzing repository...")
    result, success, _ = registry.execute("github_repo_analyzer", args[1].strip())
    await processing.delete()
    await send_long_message(message, result, parse_mode=None)


@router.message(Command("run"))
async def cmd_run(message: Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "Usage: <code>/run print('Hello, NEXUS!')</code>",
            parse_mode=ParseMode.HTML,
        )
        return
    await typing_action(message)
    code = args[1].strip().strip("`")
    result, success, _ = registry.execute("code_executor", code)
    await message.answer(result, parse_mode=None)


# ---------------------------------------------------------------------------
# Main message handler — Full Agent Loop
# ---------------------------------------------------------------------------
@router.message(F.text & ~F.text.startswith("/"))
async def handle_message(message: Message):
    """Main handler — routes all non-command messages through the agent."""
    user = message.from_user
    query = message.text.strip()

    if not query:
        return

    # Register/update user
    db.upsert_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        is_admin=is_admin(user.id),
    )

    # Store user message
    db.add_message(user.id, "user", query)
    db.index_query(user.id, query)

    # Show typing indicator
    await typing_action(message)
    processing_msg = await message.answer("⚡ NEXUS thinking...")

    try:
        # Check for dev mode
        dev_ctx = None
        if is_dev_query(query):
            dev_ctx = classify_dev_task(query)
            log.info(f"DEV mode detected: {dev_ctx.task_type.value} | lang: {dev_ctx.language}")

        # Run agent
        agent_response = await agent.think(
            user_id=user.id,
            query=query,
        )

        # Delete processing message
        try:
            await processing_msg.delete()
        except Exception:
            pass

        # Compose response
        response_text = agent_response.text

        # Add dev header if in dev mode
        if dev_ctx and agent_response.success:
            header = format_dev_response_header(dev_ctx)
            response_text = f"{header}\n\n{response_text}"

        # Add tool usage footer if tools were used
        if agent_response.tools_used:
            tools_str = " → ".join(f"`{t}`" for t in agent_response.tools_used)
            response_text += f"\n\n─────────────────\n🔧 Tools used: {tools_str}"

        # Store assistant response
        db.add_message(user.id, "assistant", truncate(agent_response.text, 500))

        # Send response
        await send_long_message(message, response_text, parse_mode=None)

    except Exception as exc:
        log.exception(f"Message handler crashed: {exc}")
        try:
            await processing_msg.delete()
        except Exception:
            pass
        await message.answer(
            f"❌ An error occurred: {exc}\n\nPlease try again.",
            parse_mode=None,
        )


# ---------------------------------------------------------------------------
# Bot runner
# ---------------------------------------------------------------------------
async def run_bot():
    """Initialize and start the Telegram bot."""
    global db, agent

    log.info("Initializing NEXUS Bot...")

    # Validate config
    missing = config.validate()
    if missing:
        log.error(f"Missing required config: {missing}")
        raise RuntimeError(f"Missing env vars: {missing}")

    # Initialize database
    db = DatabaseManager(config.DATABASE_PATH)

    # Initialize agent brain
    agent = AgentBrain(db=db)

    # Initialize bot
    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    # Register commands
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Start NEXUS Agent"),
            BotCommand(command="help", description="Command reference"),
            BotCommand(command="tools", description="List available tools"),
            BotCommand(command="osint", description="OSINT usage examples"),
            BotCommand(command="dev", description="DEV agent examples"),
            BotCommand(command="status", description="System status"),
            BotCommand(command="ip", description="IP lookup: /ip 8.8.8.8"),
            BotCommand(command="whois", description="WHOIS: /whois domain.com"),
            BotCommand(command="search", description="Web search: /search query"),
            BotCommand(command="github", description="GitHub analysis: /github owner/repo"),
            BotCommand(command="run", description="Run Python: /run print('hi')"),
            BotCommand(command="memory", description="View conversation history"),
            BotCommand(command="clear", description="Clear conversation history"),
        ],
        scope=BotCommandScopeDefault(),
    )

    log.info("NEXUS Bot started. Polling for messages...")
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    asyncio.run(run_bot())
