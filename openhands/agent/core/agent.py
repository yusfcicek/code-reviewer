"""
Core Agent Logic Module.

This module defines the `ReviewAgent` which is the central intelligence of the system.
It integrates various analyzers (Semantic, SAST, Quality) and manages the interaction
with the LLM using a structured prompt and memory strategies.
"""

from langchain.agents import AgentExecutor, AgentOutputParser
from langchain.agents.output_parsers import OpenAIFunctionsAgentOutputParser


from langchain.agents.format_scratchpad import format_to_openai_function_messages
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.agents import AgentAction, AgentFinish
from langchain_core.runnables import RunnableSequence
from openhands.agent.core.interfaces import LLMProvider, MemoryStrategy
from openhands.agent.tools.definitions import get_tools
import re
import textwrap

class HermesToolOutputParser(AgentOutputParser):
    """Parses Hermes / vLLM XML-style tool calls from LLM output."""
    
    def parse(self, text: str):
        # Clean cleanup
        text = text.strip()
        
        # Regex for <tool_call><function=NAME><parameter=ARG>VALUE</parameter></function></tool_call>
        # Supporting single parameter for now as per observations
        # <tool_call>\n<function=list_files>\n<parameter=path>\nxxxxx.h\n</parameter>\n</function>\n</tool_call>
        
        tool_regex = r"<tool_call>\s*<function=(.*?)>\s*<parameter=(.*?)>\s*(.*?)\s*</parameter>\s*</function>\s*</tool_call>"
        match = re.search(tool_regex, text, re.DOTALL)
        
        if match:
            func_name = match.group(1).strip()
            param_name = match.group(2).strip()
            param_value = match.group(3).strip()
            
            # Construct dictionary input
            tool_input = {param_name: param_value}
            
            return AgentAction(tool=func_name, tool_input=tool_input, log=text)
            
        # If no tool call, assume final answer
        return AgentFinish(return_values={"output": text}, log=text)

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
    

    def __init__(self, llm_provider: LLMProvider, memory_strategy: MemoryStrategy):
        self.llm = llm_provider.get_chat_model()
        self.memory_strategy = memory_strategy
        self.tools = get_tools()
        
        # Create Chat Prompt
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", self.SYSTEM_TEMPLATE),
            ("user", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])
        
        llm_with_tools = self.llm 
        
        self.agent_runnable = (
            {
                "input": lambda x: x["input"],
                "agent_scratchpad": lambda x: format_to_openai_function_messages(x["intermediate_steps"]), 
                "memory_context": lambda x: x["memory_context"]
            }
            | self.prompt
            | llm_with_tools
            | HermesToolOutputParser()
        )
        
        # Executor
        self.agent_executor = AgentExecutor(
            agent=self.agent_runnable, 
            tools=self.tools, 
            verbose=True, 
            handle_parsing_errors=True,
            max_iterations=10
        )

    def review_diff(self, filename: str, diff_content: str, full_file_content: str = None, other_files: list = None) -> str:
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
        # Load Context
        context_str = self.memory_strategy.load_context()
        
        # Formulate Input with Context Awareness
        user_input = f"Review the changes in `{filename}`.\n\n"
        
        if other_files:
             # Filter out self
             others = [f for f in other_files if f != filename]
             if others:
                 user_input += f"CONTEXT: The following files are ALSO modified in this MR:\n" + "\n".join([f"- {f}" for f in others]) + "\n\n"
        
        user_input += f"DIFF:\n{diff_content}\n"
        if full_file_content:
            user_input += f"\nFULL FILE CONTENT (Reference):\n{full_file_content}\n"
            
        # --- AUTO-DEPENDENCY ANALYSIS (Fail-Safe) ---
        # The user requires us to find "outside files" affected by this change.
        # We do this programmatically to ensure it's not skipped by the Agent.
        try:
            from openhands.agent.tools.definitions import DependencyAnalysisTools
            import os  # Fix: Ensure os is imported locally if not global
            
            # 1. Start with imports of the modified file
            deps = DependencyAnalysisTools.get_file_imports(filename)
            if "Error" not in deps:
                # Log these imports as dependencies
                self.memory_strategy.log_insight(f"ADD_MEMORY: [DEPENDENCY] {filename} DEPENDS ON:\n{deps}")
                print(f"[INFO] Auto-Analyzed Forward Dependencies for {filename}")

            # 2. Find reverse dependencies (who uses this file?)
            # Use basename (e.g., fibonacci.h or fibonacci)
            base_name = os.path.basename(filename)
            # If C++, try stripping extension for header search or just search full name
            refs = DependencyAnalysisTools.find_references(base_name)
            if "Error" not in refs and "No references" not in refs:
                 self.memory_strategy.log_insight(f"ADD_MEMORY: [DEPENDENCY] ALIAS/FILES DEPENDING ON {base_name}:\n{refs}")
                 print(f"[INFO] Auto-Analyzed Reverse Dependencies for {filename}")
                 
        except Exception as e:
            print(f"[WARNING] Auto-Dependency Analysis failed: {e}")
        # ----------------------------------------------

        # Load Context (Now includes the fresh insights!)
        context_str = self.memory_strategy.load_context()
        
        # Token Management / "Impact Architect" Logic
        # Calculate approximate current usage (Context + Input)
        messages = [
            {"role": "system", "content": self.SYSTEM_TEMPLATE},
            {"role": "user", "content": context_str + user_input}
        ]
        
        # Robust Token Counting (Offline Fallback)
        try:
            current_context_tokens = self.llm.get_num_tokens_from_messages(messages)
        except Exception:
            # Fallback to Char/4 heuristic if model doesn't support token counting
            total_chars = sum(len(str(m.get('content', ''))) for m in messages)
            current_context_tokens = int(total_chars / 4)
        
        remaining = 131072 - current_context_tokens
        avg_file_tokens = 500 # Estimated
        safe_files_buffer = int(remaining / avg_file_tokens)

        token_status_msg = (
            f"\n[SYSTEM METRICS]\n"
            f"- Current Token Usage: {current_context_tokens} / 131072\n"
            f"- Remaining Buffer: ~{safe_files_buffer} files can be read safely.\n"
        )
        
        # LOGGING TO STDOUT FOR CI VISIBILITY
        print(f"[INFO] Token Usage: {current_context_tokens} / 131072. Buffer: ~{safe_files_buffer} files.")
        
        if current_context_tokens > 90000:
            warn_msg = "⚠️ CRITICAL WARNING: MEMORY IS FULL (>90k). YOU MUST TRIGGER 'Summarize_Memory' NOW."
            token_status_msg += f"\n{warn_msg}\n(Do not continue reading new files until you have summarized previous insights)."
            print(f"[WARNING] {warn_msg}")
        
        user_input += token_status_msg
            
        # Run Agent
        try:
            print(f"[INFO] Invoking AgentExecutor for {filename}...")
            result = self.agent_executor.invoke({
                "input": user_input, 
                "memory_context": context_str
            })
            output = result['output']
            
            # Check for memory updates (ADD_MEMORY pattern) in the output
            if "ADD_MEMORY:" in output:
                lines = output.split('\n')
                for line in lines:
                    if "ADD_MEMORY:" in line:
                         insight = line.split("ADD_MEMORY:", 1)[1].strip()
                         self.memory_strategy.log_insight(insight)
                         print(f"[INFO] Agent stored new insight: {insight}")
            
            # Save interaction/summary
            self.memory_strategy.save_context(user_input, output)
            
            return output
            
        except Exception as e:
            print(f"[ERROR] AgentExecutor failed: {e}")
            return f"Agent failed: {e}"
