"""
tools/tool_registry.py — All NEXUS Agent tools with unified interface

Each tool is a callable class implementing:
    name: str
    description: str
    execute(input: str) -> str

The ToolRegistry maps tool names → instances and handles dispatch.
"""
import json
import os
import re
import time
from abc import ABC, abstractmethod
from typing import Optional

import requests

from config import config
from tools.web_scraper import scraper, ScrapedPage
from utils.helpers import is_valid_ip, is_valid_domain, truncate
from utils.logger import setup_logger

log = setup_logger("tools")


# ---------------------------------------------------------------------------
# Base Tool Interface
# ---------------------------------------------------------------------------
class BaseTool(ABC):
    name: str = ""
    description: str = ""
    usage_example: str = ""

    @abstractmethod
    def execute(self, tool_input: str) -> str:
        ...

    def safe_execute(self, tool_input: str) -> tuple[str, bool, int]:
        """
        Wrapper that catches exceptions, measures time, returns (output, success, ms).
        """
        start = time.monotonic()
        try:
            result = self.execute(tool_input)
            ms = int((time.monotonic() - start) * 1000)
            log.info(f"[{self.name}] OK ({ms}ms) input={tool_input[:80]!r}")
            return result, True, ms
        except Exception as exc:
            ms = int((time.monotonic() - start) * 1000)
            msg = f"Tool error [{self.name}]: {exc}"
            log.error(msg)
            return msg, False, ms


# ---------------------------------------------------------------------------
# 1. Web Search Tool
# ---------------------------------------------------------------------------
class WebSearchTool(BaseTool):
    name = "web_search"
    description = (
        "Search the web for current information. "
        "Input: a search query string. "
        "Returns: summarized content from top results."
    )
    usage_example = "web_search: latest OpenAI GPT-5 release news"

    def execute(self, tool_input: str) -> str:
        query = tool_input.strip()
        if not query:
            return "❌ Empty search query."

        pages = scraper.search_scrape(query)
        if not pages:
            return f"❌ No results found for: {query}"

        results = []
        for i, page in enumerate(pages, 1):
            if page.success:
                results.append(
                    f"**Result {i}:** {page.title}\n"
                    f"URL: {page.url}\n"
                    f"{page.main_text[:800]}\n"
                )
            else:
                results.append(f"**Result {i}:** Failed — {page.error}")

        return f"🔍 Search results for **{query}**:\n\n" + "\n---\n".join(results)


# ---------------------------------------------------------------------------
# 2. IP Lookup Tool
# ---------------------------------------------------------------------------
class IPLookupTool(BaseTool):
    name = "ip_lookup"
    description = (
        "Look up geolocation and network information for an IP address. "
        "Input: an IPv4 or IPv6 address. "
        "Returns: country, region, city, ISP, org, ASN."
    )
    usage_example = "ip_lookup: 8.8.8.8"

    def execute(self, tool_input: str) -> str:
        ip = tool_input.strip()
        if not ip:
            return "❌ No IP address provided."

        # Use ip-api.com (free, no key needed, 45 req/min)
        try:
            resp = requests.get(
                f"http://ip-api.com/json/{ip}",
                params={"fields": "status,message,country,countryCode,region,regionName,city,zip,lat,lon,isp,org,as,query"},
                timeout=10,
            )
            data = resp.json()
        except Exception as exc:
            return f"❌ IP lookup failed: {exc}"

        if data.get("status") != "success":
            return f"❌ IP lookup failed: {data.get('message', 'Unknown error')}"

        return (
            f"🌐 **IP Intelligence Report: {data['query']}**\n\n"
            f"📍 **Location:** {data.get('city')}, {data.get('regionName')}, {data.get('country')} ({data.get('countryCode')})\n"
            f"🗺️ **Coordinates:** {data.get('lat')}, {data.get('lon')}\n"
            f"📮 **ZIP:** {data.get('zip', 'N/A')}\n"
            f"🏢 **ISP:** {data.get('isp')}\n"
            f"🏗️ **Organization:** {data.get('org')}\n"
            f"🔢 **ASN:** {data.get('as')}\n"
        )


# ---------------------------------------------------------------------------
# 3. Domain WHOIS Tool
# ---------------------------------------------------------------------------
class DomainWhoisTool(BaseTool):
    name = "domain_whois"
    description = (
        "Perform a WHOIS lookup on a domain name. "
        "Input: a domain (e.g. example.com). "
        "Returns: registrar, dates, nameservers, registrant info."
    )
    usage_example = "domain_whois: google.com"

    def execute(self, tool_input: str) -> str:
        domain = tool_input.strip().lower().replace("http://", "").replace("https://", "").split("/")[0]
        if not domain:
            return "❌ No domain provided."

        try:
            import whois as python_whois
            w = python_whois.whois(domain)
        except ImportError:
            return "❌ python-whois not installed. Run: pip install python-whois"
        except Exception as exc:
            return f"❌ WHOIS lookup failed: {exc}"

        def fmt(val):
            if val is None:
                return "N/A"
            if isinstance(val, list):
                return ", ".join(str(v) for v in val[:3])
            return str(val)

        lines = [
            f"🔍 **WHOIS Report: {domain}**\n",
            f"📋 **Registrar:** {fmt(w.get('registrar'))}",
            f"📅 **Created:** {fmt(w.get('creation_date'))}",
            f"📅 **Updated:** {fmt(w.get('updated_date'))}",
            f"📅 **Expires:** {fmt(w.get('expiration_date'))}",
            f"🌐 **Name Servers:** {fmt(w.get('name_servers'))}",
            f"📊 **Status:** {fmt(w.get('status'))}",
            f"🏳️ **Country:** {fmt(w.get('country'))}",
            f"📧 **Emails:** {fmt(w.get('emails'))}",
            f"🏢 **Org:** {fmt(w.get('org'))}",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 4. Code Executor Tool (Safe Sandbox — NO OS execution)
# ---------------------------------------------------------------------------
SAFE_BUILTINS = {
    "abs": abs, "all": all, "any": any, "bin": bin, "bool": bool,
    "chr": chr, "dict": dict, "dir": dir, "divmod": divmod,
    "enumerate": enumerate, "filter": filter, "float": float,
    "format": format, "frozenset": frozenset, "getattr": getattr,
    "hasattr": hasattr, "hash": hash, "hex": hex, "int": int,
    "isinstance": isinstance, "issubclass": issubclass, "iter": iter,
    "len": len, "list": list, "map": map, "max": max, "min": min,
    "next": next, "oct": oct, "ord": ord, "pow": pow, "print": print,
    "range": range, "repr": repr, "reversed": reversed, "round": round,
    "set": set, "slice": slice, "sorted": sorted, "str": str,
    "sum": sum, "tuple": tuple, "type": type, "vars": vars, "zip": zip,
    "__import__": None,  # Explicitly blocked
}


class CodeExecutorTool(BaseTool):
    name = "code_executor"
    description = (
        "Execute small Python code snippets in a safe sandbox. "
        "No file system, network, or OS access. "
        "Input: Python code as a string. "
        "Returns: stdout output or error message."
    )
    usage_example = "code_executor: print(sum(range(1, 101)))"

    BLOCKED_PATTERNS = [
        r"\bimport\s+os\b", r"\bimport\s+sys\b", r"\bimport\s+subprocess\b",
        r"\bimport\s+socket\b", r"\bimport\s+shutil\b", r"\bopen\s*\(",
        r"\beval\s*\(", r"\bexec\s*\(", r"__import__", r"\bos\.\w+",
        r"\bsys\.\w+", r"subprocess", r"pty", r"ctypes",
    ]

    def _is_safe(self, code: str) -> tuple[bool, str]:
        for pat in self.BLOCKED_PATTERNS:
            if re.search(pat, code):
                return False, f"Blocked pattern: `{pat}`"
        return True, ""

    def execute(self, tool_input: str) -> str:
        code = tool_input.strip()
        if not code:
            return "❌ No code provided."

        safe, reason = self._is_safe(code)
        if not safe:
            return f"❌ Unsafe code blocked — {reason}\nOnly pure computation is allowed."

        import io
        import contextlib

        stdout_capture = io.StringIO()
        local_ns: dict = {}
        global_ns = {"__builtins__": SAFE_BUILTINS}

        try:
            with contextlib.redirect_stdout(stdout_capture):
                exec(compile(code, "<nexus_sandbox>", "exec"), global_ns, local_ns)
            output = stdout_capture.getvalue()
            if not output.strip():
                # If nothing printed, show last expression value
                last_line = code.strip().split("\n")[-1]
                try:
                    result = eval(compile(last_line, "<nexus_expr>", "eval"), global_ns, local_ns)
                    output = repr(result)
                except Exception:
                    output = "(no output)"
            return f"✅ **Code Output:**\n```\n{output.strip()}\n```"
        except SyntaxError as exc:
            return f"❌ Syntax Error: {exc}"
        except Exception as exc:
            return f"❌ Runtime Error: {type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# 5. File Analyzer Tool
# ---------------------------------------------------------------------------
class FileAnalyzerTool(BaseTool):
    name = "file_analyzer"
    description = (
        "Analyze a text file — reads its content and provides a structured summary. "
        "Input: absolute file path. "
        "Returns: file stats, language detection, content summary."
    )
    usage_example = "file_analyzer: /path/to/main.py"

    MAX_FILE_SIZE = 1 * 1024 * 1024  # 1 MB

    def execute(self, tool_input: str) -> str:
        path = tool_input.strip().strip("'\"")
        if not path:
            return "❌ No file path provided."
        if not os.path.exists(path):
            return f"❌ File not found: {path}"
        if os.path.isdir(path):
            return self._analyze_dir(path)

        file_size = os.path.getsize(path)
        if file_size > self.MAX_FILE_SIZE:
            return f"❌ File too large ({file_size // 1024} KB). Max: 1 MB."

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception as exc:
            return f"❌ Cannot read file: {exc}"

        ext = os.path.splitext(path)[1].lower()
        lines = content.splitlines()
        non_empty = [l for l in lines if l.strip()]

        lang_map = {
            ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
            ".java": "Java", ".go": "Go", ".rs": "Rust", ".cpp": "C++",
            ".c": "C", ".cs": "C#", ".rb": "Ruby", ".php": "PHP",
            ".sh": "Shell", ".yaml": "YAML", ".yml": "YAML",
            ".json": "JSON", ".md": "Markdown", ".sql": "SQL",
            ".html": "HTML", ".css": "CSS", ".xml": "XML",
        }
        language = lang_map.get(ext, "Unknown/Text")

        # Basic code metrics
        imports = [l for l in lines if re.match(r"^\s*(import|from|require|#include)", l)]
        functions = [l for l in lines if re.match(r"^\s*(def |function |func |public |private |class )", l)]

        summary = (
            f"📁 **File Analysis: {os.path.basename(path)}**\n\n"
            f"📊 **Stats:**\n"
            f"  • Size: {file_size:,} bytes\n"
            f"  • Total lines: {len(lines)}\n"
            f"  • Non-empty lines: {len(non_empty)}\n"
            f"  • Language: {language}\n"
            f"  • Imports/includes: {len(imports)}\n"
            f"  • Functions/classes: {len(functions)}\n\n"
            f"📝 **First 50 lines:**\n```{ext.lstrip('.')}\n"
            f"{chr(10).join(lines[:50])}\n```"
        )
        return summary

    def _analyze_dir(self, path: str) -> str:
        items = []
        total_size = 0
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
            level = root.replace(path, "").count(os.sep)
            if level > 2:
                continue
            indent = "  " * level
            items.append(f"{indent}📁 {os.path.basename(root)}/")
            for f in sorted(files)[:20]:
                size = os.path.getsize(os.path.join(root, f))
                total_size += size
                items.append(f"{indent}  📄 {f} ({size:,}B)")

        return (
            f"📂 **Directory: {os.path.basename(path)}/**\n\n"
            f"```\n{chr(10).join(items[:100])}\n```\n"
            f"Total size: {total_size:,} bytes"
        )


# ---------------------------------------------------------------------------
# 6. GitHub Repository Analyzer
# ---------------------------------------------------------------------------
class GitHubRepoAnalyzerTool(BaseTool):
    name = "github_repo_analyzer"
    description = (
        "Analyze a GitHub repository — fetches metadata, README, file tree, recent commits. "
        "Input: GitHub repo URL or 'owner/repo' format. "
        "Returns: structured repo intelligence report."
    )
    usage_example = "github_repo_analyzer: https://github.com/tiangolo/fastapi"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        if config.GITHUB_TOKEN:
            self.session.headers["Authorization"] = f"Bearer {config.GITHUB_TOKEN}"

    def _parse_repo(self, tool_input: str) -> tuple[str, str]:
        """Extract owner/repo from URL or direct format."""
        inp = tool_input.strip()
        # Handle full URL
        match = re.search(r"github\.com/([^/]+)/([^/\s?#]+)", inp)
        if match:
            return match.group(1), match.group(2).rstrip(".git")
        # Handle owner/repo format
        parts = inp.split("/")
        if len(parts) == 2:
            return parts[0], parts[1]
        raise ValueError(f"Cannot parse repo from: {inp}")

    def execute(self, tool_input: str) -> str:
        try:
            owner, repo = self._parse_repo(tool_input)
        except ValueError as exc:
            return f"❌ {exc}"

        base = f"https://api.github.com/repos/{owner}/{repo}"

        try:
            # Repo metadata
            resp = self.session.get(base, timeout=15)
            if resp.status_code == 404:
                return f"❌ Repository not found: {owner}/{repo}"
            resp.raise_for_status()
            data = resp.json()

            # README
            readme_text = ""
            try:
                readme_resp = self.session.get(f"{base}/readme", timeout=10)
                if readme_resp.ok:
                    import base64
                    raw = readme_resp.json().get("content", "")
                    readme_text = base64.b64decode(raw).decode("utf-8", errors="replace")[:1500]
            except Exception:
                pass

            # Recent commits
            commits = []
            try:
                c_resp = self.session.get(f"{base}/commits", params={"per_page": 5}, timeout=10)
                if c_resp.ok:
                    for c in c_resp.json():
                        msg = c["commit"]["message"].split("\n")[0]
                        author = c["commit"]["author"]["name"]
                        date = c["commit"]["author"]["date"][:10]
                        commits.append(f"  • [{date}] {author}: {msg}")
            except Exception:
                pass

            # Languages
            langs = []
            try:
                l_resp = self.session.get(f"{base}/languages", timeout=10)
                if l_resp.ok:
                    lang_data = l_resp.json()
                    total = sum(lang_data.values()) or 1
                    langs = [
                        f"{lang} ({bytes_/total*100:.1f}%)"
                        for lang, bytes_ in sorted(lang_data.items(), key=lambda x: -x[1])[:6]
                    ]
            except Exception:
                pass

            # File tree (top level)
            files = []
            try:
                t_resp = self.session.get(
                    f"{base}/git/trees/{data.get('default_branch', 'main')}",
                    timeout=10,
                )
                if t_resp.ok:
                    tree = t_resp.json().get("tree", [])
                    files = [
                        f"  {'📁' if item['type']=='tree' else '📄'} {item['path']}"
                        for item in tree[:25]
                    ]
            except Exception:
                pass

            report = [
                f"🐙 **GitHub Repository: {owner}/{repo}**\n",
                f"📝 **Description:** {data.get('description') or 'No description'}",
                f"⭐ **Stars:** {data.get('stargazers_count', 0):,}",
                f"🍴 **Forks:** {data.get('forks_count', 0):,}",
                f"👀 **Watchers:** {data.get('subscribers_count', 0):,}",
                f"🐛 **Open Issues:** {data.get('open_issues_count', 0):,}",
                f"🌐 **Language:** {data.get('language') or 'N/A'}",
                f"📅 **Created:** {data.get('created_at', '')[:10]}",
                f"📅 **Last Push:** {data.get('pushed_at', '')[:10]}",
                f"🔗 **URL:** {data.get('html_url')}",
            ]

            if data.get("topics"):
                report.append(f"🏷️ **Topics:** {', '.join(data['topics'][:8])}")

            if langs:
                report.append(f"\n💻 **Languages:**\n" + "\n".join(f"  • {l}" for l in langs))

            if files:
                report.append(f"\n📂 **File Tree (top level):**\n" + "\n".join(files))

            if commits:
                report.append(f"\n📦 **Recent Commits:**\n" + "\n".join(commits))

            if readme_text:
                report.append(f"\n📖 **README (first 1500 chars):**\n```\n{readme_text}\n```")

            return "\n".join(report)

        except requests.HTTPError as exc:
            return f"❌ GitHub API error: {exc}"
        except Exception as exc:
            return f"❌ Unexpected error: {exc}"


# ---------------------------------------------------------------------------
# 7. URL Scraper Tool (direct URL)
# ---------------------------------------------------------------------------
class URLScraperTool(BaseTool):
    name = "url_scraper"
    description = (
        "Scrape and extract content from a specific URL. "
        "Input: a full URL (https://...). "
        "Returns: page title, meta, and main text content."
    )
    usage_example = "url_scraper: https://example.com/article"

    def execute(self, tool_input: str) -> str:
        url = tool_input.strip()
        if not url.startswith("http"):
            url = "https://" + url
        page = scraper.scrape(url)
        return page.to_summary()


# ---------------------------------------------------------------------------
# Tool Registry
# ---------------------------------------------------------------------------
class ToolRegistry:
    """
    Central registry for all NEXUS tools.
    Handles dispatch, logging, and provides tool descriptions for the AI planner.
    """

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}
        self._register_defaults()

    def _register_defaults(self):
        for tool_cls in [
            WebSearchTool,
            IPLookupTool,
            DomainWhoisTool,
            CodeExecutorTool,
            FileAnalyzerTool,
            GitHubRepoAnalyzerTool,
            URLScraperTool,
        ]:
            tool = tool_cls()
            self._tools[tool.name] = tool
            log.debug(f"Registered tool: {tool.name}")

    def register(self, tool: BaseTool):
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def execute(self, name: str, tool_input: str) -> tuple[str, bool, int]:
        tool = self.get(name)
        if not tool:
            return f"❌ Unknown tool: {name}", False, 0
        return tool.safe_execute(tool_input)

    def list_tools(self) -> str:
        lines = ["📦 **Available NEXUS Tools:**\n"]
        for tool in self._tools.values():
            lines.append(f"**`{tool.name}`**\n  {tool.description}\n  Example: `{tool.usage_example}`\n")
        return "\n".join(lines)

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())

    def get_descriptions_for_prompt(self) -> str:
        """Format tool descriptions for injection into the AI system prompt."""
        lines = []
        for tool in self._tools.values():
            lines.append(f"- {tool.name}: {tool.description}")
        return "\n".join(lines)


# Singleton registry
registry = ToolRegistry()
