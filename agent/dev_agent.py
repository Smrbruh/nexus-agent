"""
agent/dev_agent.py — DEV AGENT mode for NEXUS

Specialized prompts and handlers for software development tasks:
  - Code generation
  - Debugging
  - Architecture design
  - Code review & refactoring
  - GitHub repo analysis
  - Project scaffolding
"""
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from utils.logger import setup_logger

log = setup_logger("agent.dev")


class DevTaskType(Enum):
    CODE_GENERATION = "code_generation"
    DEBUGGING = "debugging"
    CODE_REVIEW = "code_review"
    ARCHITECTURE = "architecture"
    REFACTORING = "refactoring"
    GITHUB_ANALYSIS = "github_analysis"
    EXPLAIN_CODE = "explain_code"
    PROJECT_SCAFFOLD = "project_scaffold"
    GENERAL_DEV = "general_dev"


DEV_TASK_PATTERNS = {
    DevTaskType.CODE_GENERATION: [
        r"(write|create|generate|build|implement|make)\s+(a|an|the)?\s*(code|function|class|script|app|api|backend|server|bot|tool)",
        r"(code|write|implement)\s+(for|to)\s+",
    ],
    DevTaskType.DEBUGGING: [
        r"(debug|fix|solve|resolve)\s+(this|my|the)?\s*(error|bug|issue|problem|exception|crash)",
        r"(why|what).*(not working|failing|broken|error|wrong)",
        r"getting\s+(an?\s+)?(error|exception|traceback)",
    ],
    DevTaskType.CODE_REVIEW: [
        r"(review|check|analyze|audit|improve)\s+(my|this|the)?\s*(code|script|function|class|implementation)",
        r"(what.*(wrong|bad|improve)|how.*(better|optimize))\s*(with|this)\s*(code|script)",
    ],
    DevTaskType.ARCHITECTURE: [
        r"(design|architect|plan|structure)\s+(a|an|the)?\s*(system|architecture|database|schema|api|project)",
        r"(how to|best way to)\s+(structure|organize|design|build)\s+",
    ],
    DevTaskType.REFACTORING: [
        r"(refactor|rewrite|clean up|restructure|optimize)\s+(this|my|the)?\s*(code|function|class|module)",
        r"(make|help).*(code|this).*(cleaner|better|efficient|pythonic|idiomatic)",
    ],
    DevTaskType.GITHUB_ANALYSIS: [
        r"(analyze|look at|check|review|examine)\s+(this|the)?\s*(repo|repository|github)",
        r"github\.com/",
    ],
    DevTaskType.EXPLAIN_CODE: [
        r"(explain|describe|walk me through|what does)\s+(this|the)?\s*(code|function|class|script)",
        r"(how|what)\s+(does|is)\s+(this|the)\s+(code|function|algorithm|script)\s+(do|work)",
    ],
    DevTaskType.PROJECT_SCAFFOLD: [
        r"(scaffold|bootstrap|set up|initialize|create)\s+(a|an|the|new)?\s*(project|app|application|service|microservice)",
        r"(full|complete)\s+(project|app|application|template|boilerplate)",
    ],
}


DEV_SYSTEM_PROMPTS = {
    DevTaskType.CODE_GENERATION: """\
You are an expert software engineer. Generate complete, production-ready code:
- Include all imports and dependencies
- Add comprehensive error handling
- Write clean, readable code with comments
- Follow language best practices and idioms
- If a framework is involved, use proper patterns
- Output complete working files, not snippets
- Add a brief explanation of how to run/use it
""",
    DevTaskType.DEBUGGING: """\
You are an expert debugger. Analyze the issue systematically:
1. Identify the root cause precisely
2. Explain WHY it fails (not just that it fails)
3. Provide the exact fix with corrected code
4. Suggest preventive measures for similar bugs
5. If multiple issues exist, address all of them
""",
    DevTaskType.CODE_REVIEW: """\
You are a senior code reviewer. Provide structured feedback:
## Issues (Critical / Major / Minor)
- List specific problems with line references
## Security Concerns
- Identify any vulnerabilities
## Performance
- Identify bottlenecks and optimization opportunities
## Code Quality
- Readability, maintainability, naming conventions
## Refactored Version
- Provide improved code where appropriate
""",
    DevTaskType.ARCHITECTURE: """\
You are a system architect. Design with production in mind:
- Provide clear component diagrams (ASCII or description)
- Justify technology choices
- Address scalability, reliability, and security
- Include data flow descriptions
- Consider failure modes
- Provide implementation roadmap
""",
    DevTaskType.REFACTORING: """\
You are a refactoring expert. Improve the code while preserving behavior:
- Apply SOLID principles where appropriate
- Reduce code duplication (DRY)
- Improve naming clarity
- Optimize for readability over cleverness
- Show BEFORE and AFTER with explanation of each change
""",
    DevTaskType.EXPLAIN_CODE: """\
You are an expert technical explainer. Break down the code clearly:
- Start with a high-level overview (what does it do?)
- Walk through the logic step by step
- Explain any complex patterns or algorithms
- Identify design patterns used
- Note any potential issues or edge cases
- Use analogies for complex concepts
""",
    DevTaskType.PROJECT_SCAFFOLD: """\
You are a full-stack architect generating complete project scaffolding:
- Output the full directory structure
- Generate ALL necessary files (main, config, requirements, README)
- Include environment setup instructions
- Add proper error handling from the start
- Include basic tests
- Make it immediately runnable
""",
}


@dataclass
class DevContext:
    task_type: DevTaskType
    language: Optional[str] = None
    framework: Optional[str] = None
    system_prompt_addon: str = ""

    @property
    def emoji(self) -> str:
        emoji_map = {
            DevTaskType.CODE_GENERATION: "⚡",
            DevTaskType.DEBUGGING: "🐛",
            DevTaskType.CODE_REVIEW: "👀",
            DevTaskType.ARCHITECTURE: "🏗️",
            DevTaskType.REFACTORING: "🔧",
            DevTaskType.GITHUB_ANALYSIS: "🐙",
            DevTaskType.EXPLAIN_CODE: "📖",
            DevTaskType.PROJECT_SCAFFOLD: "🚀",
            DevTaskType.GENERAL_DEV: "💻",
        }
        return emoji_map.get(self.task_type, "💻")

    @property
    def label(self) -> str:
        return self.task_type.value.replace("_", " ").title()


LANGUAGE_PATTERNS = {
    "python": r"\bpython\b|\bpython3\b|\bpip\b|\bdjango\b|\bflask\b|\bfastapi\b",
    "javascript": r"\bjavascript\b|\bjs\b|\bnode\.?js\b|\bexpress\b|\breact\b|\bnext\.?js\b",
    "typescript": r"\btypescript\b|\bts\b",
    "go": r"\bgolang\b|\bgo lang\b|\bgo\b",
    "rust": r"\brust\b|\bcargo\b",
    "java": r"\bjava\b|\bspring\b|\bmaven\b|\bgradle\b",
    "kotlin": r"\bkotlin\b",
    "swift": r"\bswift\b|\bxcode\b",
    "cpp": r"\bc\+\+\b|\bcpp\b",
    "csharp": r"\bc#\b|\b\.net\b|\baspnet\b",
    "php": r"\bphp\b|\blaravel\b|\bsymfony\b",
    "ruby": r"\bruby\b|\brails\b",
    "sql": r"\bsql\b|\bmysql\b|\bpostgres\b|\bsqlite\b",
    "bash": r"\bbash\b|\bshell\b|\bsh script\b",
}


def classify_dev_task(query: str) -> DevContext:
    """
    Classify a query into a DevTaskType and extract language/framework hints.
    """
    query_lower = query.lower()

    # Detect task type
    detected_type = DevTaskType.GENERAL_DEV
    for task_type, patterns in DEV_TASK_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, query_lower):
                detected_type = task_type
                break
        if detected_type != DevTaskType.GENERAL_DEV:
            break

    # Detect language
    detected_language = None
    for lang, pat in LANGUAGE_PATTERNS.items():
        if re.search(pat, query_lower):
            detected_language = lang
            break

    system_addon = DEV_SYSTEM_PROMPTS.get(detected_type, "")

    return DevContext(
        task_type=detected_type,
        language=detected_language,
        system_prompt_addon=system_addon,
    )


def is_dev_query(query: str) -> bool:
    """Quick check if query looks like a development task."""
    dev_keywords = [
        "code", "function", "class", "debug", "error", "bug", "implement",
        "api", "backend", "frontend", "database", "algorithm", "refactor",
        "architecture", "github", "repo", "script", "program", "develop",
        "python", "javascript", "typescript", "java", "rust", "go ", "c++",
        "flask", "django", "fastapi", "express", "react", "vue", "angular",
        "sql", "docker", "kubernetes", "deploy", "test", "unittest",
    ]
    query_lower = query.lower()
    return any(kw in query_lower for kw in dev_keywords)


def format_dev_response_header(ctx: DevContext) -> str:
    """Generate a header for dev agent responses."""
    parts = [f"{ctx.emoji} **NEXUS DEV AGENT — {ctx.label}**"]
    if ctx.language:
        parts.append(f"Language: `{ctx.language}`")
    if ctx.framework:
        parts.append(f"Framework: `{ctx.framework}`")
    return " | ".join(parts)
