"""
Core Agent Logic Module.

This module defines the `ReviewAgent` which is the central intelligence of the system.
It integrates various analyzers (Semantic, SAST, Quality) and manages the interaction
with the LLM using a structured prompt and memory strategies.
"""

import json
import os
import textwrap
from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.messages import SystemMessage
from langchain_core.prompts import ChatPromptTemplate

from code_reviewer.application.ports import LLMProvider, MemoryStrategy
from code_reviewer.infrastructure.llm.narration_loop import (
    NarrationLoop,
    max_iterations_from_env,
    max_seconds_from_env,
)
from code_reviewer.infrastructure.llm.token_counter import ModelTokenCounter
from code_reviewer.infrastructure.observability.logging import get_logger
from code_reviewer.infrastructure.security.redaction import SecretRedactor
from code_reviewer.infrastructure.tools.definitions import get_tools

logger = get_logger(__name__)

#: How tools may be offered to the model.
#:
#: The two ends of the range exist because the agent runs in two very different
#: deployments. A hosted endpoint (OpenAI, Groq) can only call a tool if the
#: schema was bound through the tool API; an on-prem vLLM started without
#: ``--enable-auto-tool-choice`` rejects the request if it was. `auto` tries the
#: first and falls back to the second, which is only safe because
#: :class:`ToolCallParser` reads whichever dialect comes back (finding G-02).
TOOL_PROTOCOLS = frozenset({"auto", "native", "hermes", "none"})


TOOL_CALL_FORMAT = (
    "<tool_call>\n"
    "<function=TOOL_NAME>\n"
    "<parameter=ARGUMENT_NAME>\n"
    "ARGUMENT_VALUE\n"
    "</parameter>\n"
    "</function>\n"
    "</tool_call>"
)


def render_tool_catalogue(tools: Sequence[Any]) -> str:
    """Describes the available tools in the dialect the parser reads.

    The model is served through vLLM in a Hermes dialect, which is why
    ``HermesToolOutputParser`` exists. Binding tools through the OpenAI
    function-calling API would produce payloads that parser cannot read, so the
    catalogue is rendered into the prompt instead and both ends of the loop
    speak one convention (finding F-03).
    """
    if not tools:
        return (
            "You have no tools available in this run. Base your review only on "
            "the diff and the file content you were given."
        )

    entries = []
    for tool in tools:
        try:
            parameters = tool.args
        except Exception:  # a tool without an args schema is still worth listing
            parameters = {}
        entries.append(
            json.dumps(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": {"type": "object", "properties": parameters},
                },
                ensure_ascii=False,
            )
        )

    return (
        "You can call the following tools.\n\n"
        "<tools>\n" + "\n".join(entries) + "\n</tools>\n\n"
        "To call one, emit exactly this and nothing else:\n"
        f"{TOOL_CALL_FORMAT}\n\n"
        "Call one tool at a time and wait for its <tool_response> before the "
        "next call. When you have gathered enough evidence, stop calling tools "
        "and reply with the review report."
    )


class ReviewAgent:
    """
    Advanced Architectural Code Review Agent.

    Capabilities:
    - Semantic Change Analysis (beyond syntax)
    - Dependency Tracking (including code not in git diff)
    - SAST Security Scanning
    - SOLID Principles & Code Quality
    - Performance Analysis (O(n²), memory leaks)
    - Smart Token Management
    """

    SYSTEM_TEMPLATE = textwrap.dedent("""
        You are an Advanced Architectural Code Review Agent (SENIOR SOFTWARE ARCHITECT).
        Your analysis goes BEYOND syntax to understand SEMANTIC IMPACT of changes.

        ═══════════════════════════════════════════════════════════════════════════════
        🧠 OPERATIONAL STRATEGY (Follow in Order)
        ═══════════════════════════════════════════════════════════════════════════════

        1. **SEMANTIC CHANGE ANALYSIS** (First Step):
           - Use `run_semantic_analysis` with format 'diff ||| full_content ||| file_path'
           - Identify WHAT type of change this is: REFACTOR, FEATURE, BUGFIX, BREAKING_CHANGE
           - Check completeness: Are there missing pieces to this change?
           - Evaluate code integrity: Does this change maintain system cohesion?

        2. **DEPENDENCY IMPACT ANALYSIS** (CRITICAL):
           - When data structures change (especially for IPC/messaging):
             * Use `find_affected_by_change` to find ALL dependent functions
             * Use `find_ripple_effects` to trace indirect impacts up to 2 levels deep
             * Even if not in git diff, these MUST be analyzed
             * Add them to memory: `ADD_MEMORY: [AFFECTED_CODE] file:symbol - reason`
           - Use `get_file_imports` for direct dependencies
           - Use `find_references` for reverse dependencies
           - **Rule**: If you cannot prove a refactor is safe, do not suggest it.

        3. **SECURITY ANALYSIS (SAST)**:
           - Use `run_sast_scan` on modified files
           - Check for: SQL Injection, XSS, Command Injection, Hardcoded Secrets
           - Log findings: `ADD_MEMORY: [SECURITY] <severity> <finding>`
           - Risk score: CRITICAL/HIGH/MEDIUM/LOW

        4. **CODE QUALITY ASSESSMENT**:
           - Use `check_code_quality` for SOLID principles
           - Check for:
             * SRP: Classes/functions with too many responsibilities
             * DIP: Concrete dependencies that should be injected
             * DRY: Duplicate code blocks
             * Error Handling: Empty catches, generic exceptions
             * Testability: Global state, too many parameters

        5. **PERFORMANCE ANALYSIS**:
           - Use `analyze_performance` to detect:
             * O(n²) or worse nested loops
             * Memory leak patterns (unclosed resources)
             * N+1 query patterns (DB calls in loops)
             * Blocking operations

        6. **MEMORY & TRACEABILITY**:
           - Log important findings: `ADD_MEMORY: [TAG] <file_or_concept>: <insight>`
           - Tags:
             * `[SECURITY]` - Security vulnerabilities (CRITICAL priority)
             * `[BREAKING]` - Breaking changes (CRITICAL priority)
             * `[AFFECTED_CODE]` - Code not in diff but affected (HIGH priority)
             * `[DEPENDENCY]` - Dependency relationships (HIGH priority)
             * `[RISK]` - Architectural risks (HIGH priority)
             * `[PERFORMANCE]` - Performance issues (NORMAL priority)
             * `[PATTERN]` - Design patterns (NORMAL priority)
             * `[QUALITY]` - Code quality issues (NORMAL priority)

        7. **TOKEN MANAGEMENT**:
           - Context limit: ~131k tokens
           - Memory auto-summarizes when reaching 80% capacity
           - CRITICAL and SECURITY insights are NEVER summarized
           - If you see "MEMORY IS FULL", summarize your findings

        ═══════════════════════════════════════════════════════════════════════════════
        🛠️ DIFF GENERATION RULES
        ═══════════════════════════════════════════════════════════════════════════════
        To ensure the diff can be applied automatically:
        1. Always include 3 lines of unchanged context BEFORE and AFTER the changes.
        2. Use standard format:
           --- path/to/file
           +++ path/to/file
           @@ -line,count +line,count @@

        ═══════════════════════════════════════════════════════════════════════════════
        📋 OUTPUT FORMAT
        ═══════════════════════════════════════════════════════════════════════════════

        # 🏛️ Architectural Review Summary
        > [High-level summary of system health, technical debt, and risks.]

        ## 🔒 Security Analysis
        - **SAST Scan Result**: [Specify: PASS/FAIL - Risk Level]
        - **Vulnerabilities Found**: [List specific findings or 'None']

        ## 🔍 Semantic Change Analysis
        - **Change Type**: [Specify one: REFACTOR/FEATURE/BUGFIX/BREAKING_CHANGE]
        - **Completeness**: [Assess: Complete/Incomplete - Provide Details]
        - **Breaking Changes**: [Yes/No - Detail the Impact]

        ## 🔗 Impact Analysis
        - **Dependencies Checked**: [List of files analyzed]
        - **Affected Code (Not in Diff)**: [List files/symbols or 'None']
        - **Risk Assessment**: [Specify: Low/Medium/High/Critical] - [Justification]

        ## 📊 Code Quality
        - **SOLID Compliance**: [Numeric Score/100]
        - **Issues Found**: [List key violations or 'None']

        ## ⚡ Performance Analysis
        - **Complexity Issues**: [Describe: e.g., O(n²) loops, or 'None']
        - **Resource Leaks**: [Report: Memory/File/Connection issues or 'None']

        ## 🛠️ Refactoring Roadmap
        ### [Specify Priority: High/Med/Low] - [Short Descriptive Title]
        **Why**: [Detailed explanation linking to SOLID/patterns/security/impact]
        **How**:
        - **Action**: [Specify one: Create / Modify / Delete / Move] `{{filename}}`
        - **Diff**:
        ```diff
        --- {{filename}}
        +++ {{filename}}
        @@ -line,count +line,count @@
        [Context]
        - [Old Code]
        + [New Code]
        [Context]
        ```
    """).strip()

    #: Context window of the served model, used for the buffer report shown to it.
    CONTEXT_WINDOW_TOKENS = 131072
    #: Point at which the model is told to summarise before reading anything else.
    MEMORY_PRESSURE_TOKENS = 90000

    def __init__(
        self,
        llm_provider: LLMProvider,
        memory_strategy: MemoryStrategy,
        token_counter: Callable[[str], int] | None = None,
        tool_protocol: str | None = None,
        redactor: SecretRedactor | None = None,
    ):
        self.llm = llm_provider.get_chat_model()
        self.memory_strategy = memory_strategy
        self.count_tokens = token_counter or ModelTokenCounter(self.llm)
        # Built from the environment so the secrets this process was actually
        # given are masked by value, not only by shape (finding G-04).
        self.redactor = redactor or SecretRedactor.from_environment()

        self.tool_protocol = self._resolve_protocol(tool_protocol)
        # Under `none` the model narrates from the diff alone. Registering the
        # tools and then not binding them would leave the catalogue advertising
        # calls the loop would refuse.
        self.tools = [] if self.tool_protocol == "none" else get_tools()
        self.model = self._bind_tools(self.llm)

        # The tool catalogue is a literal SystemMessage rather than a template
        # string: it contains JSON braces, which a template would try to
        # interpret as variables.
        self.prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.SYSTEM_TEMPLATE),
                SystemMessage(content=render_tool_catalogue(self.tools)),
                (
                    "system",
                    "REVIEW MEMORY (carried over from files already analysed):\n{memory_context}",
                ),
                ("user", "{input}"),
            ]
        )

        # The loop belongs to this project rather than to LangChain: 1.0
        # removed AgentExecutor, and its replacement offers no hook for
        # parsing a tool call out of message text, which is the only way the
        # Hermes path works at all (decision D-1, finding F-45).
        self.loop = NarrationLoop(
            model=self.model,
            tools=self.tools,
            max_iterations=max_iterations_from_env(),
            max_seconds=max_seconds_from_env(),
            log=logger.debug,
        )

    # -- tool protocol ------------------------------------------------------

    @staticmethod
    def _resolve_protocol(explicit: str | None) -> str:
        """Reads the tool protocol, rejecting a value it does not recognise.

        Falling back to a default on an unknown value would turn a typo into a
        silently tool-less review — the exact failure this level exists to
        remove, arriving through a different door.
        """
        protocol = (explicit or os.getenv("REVIEW_TOOL_PROTOCOL") or "auto").strip().lower()

        if protocol not in TOOL_PROTOCOLS:
            raise ValueError(
                f"Unknown REVIEW_TOOL_PROTOCOL {protocol!r}. "
                f"Expected one of: {', '.join(sorted(TOOL_PROTOCOLS))}."
            )
        return protocol

    def _bind_tools(self, llm: Any) -> Any:
        """Offers the tools to the model according to the declared protocol.

        ``auto`` binds and falls back to the prompt catalogue when the server
        refuses. The fallback is safe because the parser reads both dialects;
        without that, falling back would mean silently losing the tools.
        """
        if self.tool_protocol in ("hermes", "none"):
            logger.info(
                "Tools are not bound natively",
                extra={"fields": {"protocol": self.tool_protocol}},
            )
            return llm

        try:
            return llm.bind_tools(self.tools)
        except Exception as exc:
            if self.tool_protocol == "native":
                raise
            logger.warning(
                "Native tool binding unavailable; falling back to prompt-based Hermes calls",
                extra={"fields": {"error": str(exc)}},
            )
            return llm

    def review_diff(
        self,
        filename: str,
        diff_content: str,
        full_file_content: str | None = None,
        other_files: list | None = None,
    ) -> str:
        """
        Main entry point for reviewing a single file diff.

        Args:
            filename: Name of the file being reviewed.
            diff_content: Git diff content.
            full_file_content: Optional full content of the file for context.
            other_files: List of other files modified in the same Merge Request,
                         used to provide cross-file context to the agent.

        Returns:
            str: The review output generated by the agent.
        """
        # Formulate Input with Context Awareness
        user_input = f"Review the changes in `{filename}`.\n\n"

        if other_files:
            # Filter out self
            others = [f for f in other_files if f != filename]
            if others:
                user_input += (
                    "CONTEXT: The following files are ALSO modified in this MR:\n"
                    + "\n".join([f"- {f}" for f in others])
                    + "\n\n"
                )

        user_input += f"DIFF:\n{diff_content}\n"
        if full_file_content:
            user_input += f"\nFULL FILE CONTENT (Reference):\n{full_file_content}\n"

        # --- AUTO-DEPENDENCY ANALYSIS (Fail-Safe) ---
        # The user requires us to find "outside files" affected by this change.
        # We do this programmatically to ensure it's not skipped by the Agent.
        try:
            from code_reviewer.infrastructure.tools.definitions import DependencyAnalysisTools

            # 1. Start with imports of the modified file
            deps = DependencyAnalysisTools.get_file_imports(filename)
            if "Error" not in deps:
                # Log these imports as dependencies
                self.memory_strategy.log_insight(f"ADD_MEMORY: [DEPENDENCY] {filename} DEPENDS ON:\n{deps}")
                logger.debug("Analysed forward dependencies", extra={"fields": {"path": filename}})

            # 2. Find reverse dependencies (who uses this file?)
            # Use basename (e.g., fibonacci.h or fibonacci)
            base_name = os.path.basename(filename)
            # If C++, try stripping extension for header search or just search full name
            refs = DependencyAnalysisTools.find_references(base_name)
            if "Error" not in refs and "No references" not in refs:
                self.memory_strategy.log_insight(
                    f"ADD_MEMORY: [DEPENDENCY] ALIAS/FILES DEPENDING ON {base_name}:\n{refs}"
                )
                logger.debug("Analysed reverse dependencies", extra={"fields": {"path": filename}})

        except Exception as e:
            logger.warning(
                "Dependency analysis failed", extra={"fields": {"path": filename, "error": str(e)}}
            )
        # ----------------------------------------------

        # Load context once, after the automatic dependency analysis above has
        # had a chance to add its insights (finding F-19: this used to be
        # loaded a second time at the top of the method and thrown away).
        context_str = self.memory_strategy.load_context()

        # Token Management / "Impact Architect" Logic
        current_context_tokens = self.count_tokens(self.SYSTEM_TEMPLATE + context_str + user_input)

        remaining = self.CONTEXT_WINDOW_TOKENS - current_context_tokens
        avg_file_tokens = 500  # Estimated
        safe_files_buffer = int(remaining / avg_file_tokens)

        token_status_msg = (
            f"\n[SYSTEM METRICS]\n"
            f"- Current Token Usage: {current_context_tokens} / {self.CONTEXT_WINDOW_TOKENS}\n"
            f"- Remaining Buffer: ~{safe_files_buffer} files can be read safely.\n"
        )

        # LOGGING TO STDOUT FOR CI VISIBILITY
        logger.debug(
            "Token budget",
            extra={
                "fields": {
                    "used": current_context_tokens,
                    "window": self.CONTEXT_WINDOW_TOKENS,
                    "files_buffer": safe_files_buffer,
                }
            },
        )

        if current_context_tokens > self.MEMORY_PRESSURE_TOKENS:
            warn_msg = "⚠️ CRITICAL WARNING: MEMORY IS FULL (>90k). YOU MUST TRIGGER 'Summarize_Memory' NOW."
            token_status_msg += (
                f"\n{warn_msg}\n(Do not continue reading new files until you have "
                "summarized previous insights)."
            )
            logger.warning(
                "Memory pressure: instructing the model to summarise",
                extra={"fields": {"used": current_context_tokens}},
            )

        user_input += token_status_msg

        # Run Agent
        try:
            logger.info("Reviewing file", extra={"fields": {"path": filename}})
            messages = self.prompt.format_messages(input=user_input, memory_context=context_str)
            output = self.loop.run(messages)

            # Check for memory updates (ADD_MEMORY pattern) in the output
            if "ADD_MEMORY:" in output:
                lines = output.split("\n")
                for line in lines:
                    if "ADD_MEMORY:" in line:
                        insight = line.split("ADD_MEMORY:", 1)[1].strip()
                        self.memory_strategy.log_insight(insight)
                        logger.debug("Insight stored", extra={"fields": {"insight": insight}})

            # Memory stays in-process, so it keeps the unmasked text: masking
            # it would lose context the next file's review may need.
            self.memory_strategy.save_context(user_input, output)

            # This is the boundary. Everything past here is a CI log or a
            # merge-request comment, and neither can be taken back — a comment
            # survives its own deletion in notification mail and webhook
            # history (finding G-04).
            redaction = self.redactor.redact_with_report(output)
            if redaction.count:
                logger.warning(
                    "Redacted potential secrets from a review",
                    extra={"fields": {"path": filename, "count": redaction.count}},
                )

            return redaction.text

        except Exception as e:
            logger.error(
                "Review agent failed",
                extra={"fields": {"path": filename, "error": str(e)}},
                exc_info=True,
            )
            return f"Agent failed: {e}"
