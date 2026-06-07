"""
agent/brain.py — NEXUS Agent Core Reasoning Engine

Architecture:
    User Input
        ↓
    Context Builder (history + RAG memory)
        ↓
    Gemini Planner (decide tools + steps)
        ↓
    Tool Router (execute tools in sequence)
        ↓
    Synthesizer (merge results → final answer)
        ↓
    Memory Writer (store decision + result)
        ↓
    Response

The agent uses a ReAct-like loop:
    Thought → Action → Observation → Thought → ... → Final Answer
"""
import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Optional

import google.generativeai as genai

from config import config
from memory.database import DatabaseManager
from tools.tool_registry import ToolRegistry, registry as default_registry
from utils.logger import setup_logger
from utils.helpers import truncate, sha256

log = setup_logger("agent.brain")


# ---------------------------------------------------------------------------
# Configure Gemini
# ---------------------------------------------------------------------------
genai.configure(api_key=config.GEMINI_API_KEY)


# ---------------------------------------------------------------------------
# Agent Response dataclass
# ---------------------------------------------------------------------------
@dataclass
class AgentResponse:
    text: str
    tools_used: list[str] = field(default_factory=list)
    iterations: int = 0
    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    plan: str = ""
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None


# ---------------------------------------------------------------------------
# System Prompt Builder
# ---------------------------------------------------------------------------
SYSTEM_PROMPT_TEMPLATE = """\
{base_prompt}

## YOUR CAPABILITIES
You are NEXUS — a multi-purpose AI agent with access to:

### Tools Available:
{tool_descriptions}

## REASONING PROTOCOL
You MUST follow this exact format in your responses when you need to use tools:

<thought>
Analyze the user's request. What do they need? What tools are relevant?
</thought>

<action>
tool_name: exact input for the tool
</action>

<observation>
[Tool result will be inserted here by the system]
</observation>

Then continue with more thought/action/observation cycles as needed.

When you have enough information, finish with:
<final_answer>
Your complete, well-formatted response to the user.
</final_answer>

## RULES
1. ALWAYS use <thought> tags to reason before acting
2. Use tools when you need real-time data, code execution, or external lookups
3. You can chain multiple tools in sequence
4. If a tool fails, reason about alternatives
5. For development tasks: generate complete, production-ready code
6. For OSINT tasks: be thorough and structured
7. Keep final answers concise but complete
8. Format responses with Markdown for Telegram
9. NEVER hallucinate tool results — always actually use the tools
10. Maximum {max_iterations} tool iterations per request

## MEMORY CONTEXT
{memory_context}

## CONVERSATION HISTORY
{history_summary}
"""

PLANNER_EXTRACT_PATTERN = re.compile(
    r"<thought>(.*?)</thought>|<action>(.*?)</action>|<final_answer>(.*?)</final_answer>",
    re.DOTALL | re.IGNORECASE,
)

ACTION_PATTERN = re.compile(r"^(\w+):\s*(.+)$", re.DOTALL)


# ---------------------------------------------------------------------------
# Agent Brain
# ---------------------------------------------------------------------------
class AgentBrain:
    """
    Core reasoning engine for NEXUS.
    Manages the Gemini model, tool calling loop, and memory integration.
    """

    def __init__(
        self,
        db: DatabaseManager,
        tool_registry: ToolRegistry = None,
    ):
        self.db = db
        self.registry = tool_registry or default_registry
        self.model = genai.GenerativeModel(
            model_name=config.GEMINI_MODEL,
            generation_config=genai.types.GenerationConfig(
                temperature=0.7,
                top_p=0.95,
                max_output_tokens=8192,
            ),
        )
        log.info(f"AgentBrain initialized with model: {config.GEMINI_MODEL}")

    def _build_system_prompt(self, user_id: int, query: str) -> str:
        """Build the full system prompt with context injection."""
        # Get conversation history
        history = self.db.get_history(user_id, limit=config.MAX_HISTORY_CONTEXT)
        if history:
            history_lines = []
            for msg in history[-6:]:  # Last 6 messages for context
                role_icon = "👤" if msg["role"] == "user" else "🤖"
                history_lines.append(f"{role_icon} {msg['role'].upper()}: {msg['content'][:200]}")
            history_summary = "\n".join(history_lines)
        else:
            history_summary = "No previous conversation."

        # RAG memory retrieval
        keywords = query.split()[:5]
        relevant_memories = []
        for kw in keywords:
            if len(kw) > 4:
                mems = self.db.search_memory(kw, limit=2)
                relevant_memories.extend(mems)

        if relevant_memories:
            mem_lines = []
            seen = set()
            for mem in relevant_memories[:3]:
                text = truncate(mem.get("text", ""), 200)
                h = sha256(text)
                if h not in seen:
                    seen.add(h)
                    mem_lines.append(f"• [{mem.get('source')}] {text}")
            memory_context = "Relevant past context:\n" + "\n".join(mem_lines)
        else:
            memory_context = "No relevant past context found."

        return SYSTEM_PROMPT_TEMPLATE.format(
            base_prompt=config.AGENT_SYSTEM_PROMPT,
            tool_descriptions=self.registry.get_descriptions_for_prompt(),
            max_iterations=config.MAX_TOOL_ITERATIONS,
            memory_context=memory_context,
            history_summary=history_summary,
        )

    def _parse_agent_output(self, text: str) -> dict:
        """Parse the agent's structured output into components."""
        result = {
            "thoughts": [],
            "actions": [],
            "final_answer": None,
        }

        # Extract structured blocks
        for match in PLANNER_EXTRACT_PATTERN.finditer(text):
            thought, action, answer = match.groups()
            if thought:
                result["thoughts"].append(thought.strip())
            if action:
                result["actions"].append(action.strip())
            if answer:
                result["final_answer"] = answer.strip()

        # Fallback: if no structured output, treat whole response as final answer
        if not result["final_answer"] and not result["actions"]:
            result["final_answer"] = text.strip()

        return result

    def _extract_action(self, action_text: str) -> Optional[tuple[str, str]]:
        """Parse 'tool_name: input' from action block."""
        action_text = action_text.strip()
        match = ACTION_PATTERN.match(action_text)
        if match:
            tool_name = match.group(1).strip()
            tool_input = match.group(2).strip()
            if tool_name in self.registry.tool_names:
                return tool_name, tool_input
        return None

    async def think(self, user_id: int, query: str, session_id: str = None) -> AgentResponse:
        """
        Main agent reasoning loop.
        Returns an AgentResponse with the final answer and metadata.
        """
        session_id = session_id or str(uuid.uuid4())[:8]
        response = AgentResponse(session_id=session_id)
        tools_used = []
        plan_steps = []

        try:
            system_prompt = self._build_system_prompt(user_id, query)

            # Build initial conversation for Gemini
            chat_messages = [
                {"role": "user", "parts": [system_prompt + f"\n\n---\nUSER QUERY: {query}"]},
            ]

            log.info(f"[Session {session_id}] Processing query for user {user_id}: {query[:80]!r}")

            iteration = 0
            full_reasoning = []
            current_messages = chat_messages.copy()

            while iteration < config.MAX_TOOL_ITERATIONS:
                iteration += 1
                log.debug(f"[Session {session_id}] Iteration {iteration}")

                # Call Gemini
                try:
                    gemini_response = self.model.generate_content(current_messages)
                    agent_text = gemini_response.text
                except Exception as exc:
                    log.error(f"Gemini API error: {exc}")
                    response.error = f"AI model error: {exc}"
                    response.text = f"❌ I encountered an error with the AI model: {exc}"
                    return response

                full_reasoning.append(agent_text)
                parsed = self._parse_agent_output(agent_text)

                # Log thought process
                for thought in parsed["thoughts"]:
                    plan_steps.append(f"💭 {thought[:100]}")

                # Execute actions
                if parsed["actions"]:
                    observations = []
                    for action_text in parsed["actions"]:
                        action = self._extract_action(action_text)
                        if not action:
                            log.warning(f"Could not parse action: {action_text!r}")
                            observations.append(f"[System: Could not execute action: {action_text}]")
                            continue

                        tool_name, tool_input = action
                        log.info(f"[Session {session_id}] Executing tool: {tool_name}({tool_input[:50]!r})")
                        tools_used.append(tool_name)
                        plan_steps.append(f"🔧 {tool_name}: {tool_input[:80]}")

                        tool_output, success, duration_ms = self.registry.execute(tool_name, tool_input)

                        # Store tool call in database
                        self.db.log_tool_call(
                            user_id=user_id,
                            tool_name=tool_name,
                            tool_input=tool_input,
                            tool_output=truncate(tool_output, 2000),
                            success=success,
                            duration_ms=duration_ms,
                            session_id=session_id,
                        )

                        observations.append(
                            f"[Tool: {tool_name}]\n{truncate(tool_output, 1500)}"
                        )

                    # Append agent output + observations as next turn
                    current_messages.append({"role": "model", "parts": [agent_text]})
                    observation_text = "\n\n".join(
                        [f"<observation>\n{obs}\n</observation>" for obs in observations]
                    )
                    current_messages.append({
                        "role": "user",
                        "parts": [f"{observation_text}\n\nNow provide your <final_answer> based on these observations."],
                    })

                    # If final answer already included
                    if parsed["final_answer"]:
                        break
                else:
                    # No actions — agent gave direct answer
                    break

            # Extract final answer
            if parsed["final_answer"]:
                response.text = parsed["final_answer"]
            else:
                # No structured final answer — use last Gemini response
                last_text = full_reasoning[-1] if full_reasoning else "I was unable to generate a response."
                # Clean up any remaining tags
                last_text = re.sub(r"<thought>.*?</thought>", "", last_text, flags=re.DOTALL)
                last_text = re.sub(r"<action>.*?</action>", "", last_text, flags=re.DOTALL)
                last_text = re.sub(r"<observation>.*?</observation>", "", last_text, flags=re.DOTALL)
                response.text = last_text.strip() or "✅ Task completed."

            response.tools_used = list(dict.fromkeys(tools_used))  # deduplicate, preserve order
            response.iterations = iteration
            response.plan = "\n".join(plan_steps)

            # Store agent decision
            self.db.log_decision(
                user_id=user_id,
                query=query,
                plan=response.plan,
                tools_used=response.tools_used,
                final_response=truncate(response.text, 1000),
                iterations=iteration,
                session_id=session_id,
            )

            log.info(
                f"[Session {session_id}] Completed in {iteration} iterations. "
                f"Tools: {response.tools_used}"
            )

        except Exception as exc:
            log.exception(f"AgentBrain.think() crashed: {exc}")
            response.error = str(exc)
            response.text = f"❌ Agent encountered an unexpected error: {exc}"

        return response
