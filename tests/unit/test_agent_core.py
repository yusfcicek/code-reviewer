import sys
import unittest
from unittest.mock import MagicMock, patch

# Mock langchain dependencies BEFORE importing agent
sys.modules['langchain'] = MagicMock()
sys.modules['langchain.agents'] = MagicMock()
sys.modules['langchain.agents.output_parsers'] = MagicMock()
sys.modules['langchain.agents.format_scratchpad'] = MagicMock()
sys.modules['langchain.tools'] = MagicMock()
sys.modules['langchain_core'] = MagicMock()
sys.modules['langchain_core.prompts'] = MagicMock()
sys.modules['langchain_core.agents'] = MagicMock()
sys.modules['langchain_core.runnables'] = MagicMock()

# Mocking AgentOutputParser for HermesToolOutputParser inheritance
class MockAgentOutputParser:
    pass
sys.modules['langchain.agents'].AgentOutputParser = MockAgentOutputParser

# Now we can safely import ReviewAgent
from openhands.agent.core.agent import ReviewAgent
from openhands.agent.core.interfaces import LLMProvider, MemoryStrategy

class TestReviewAgent(unittest.TestCase):
    def setUp(self):
        self.mock_provider = MagicMock(spec=LLMProvider)
        self.mock_memory = MagicMock(spec=MemoryStrategy)
        self.mock_llm = MagicMock()
        self.mock_llm.get_num_tokens_from_messages.return_value = 1000
        self.mock_provider.get_chat_model.return_value = self.mock_llm
        
        # Mock get_tools to avoid importing real tools which might have other deps
        with patch('openhands.agent.core.agent.get_tools') as mock_get_tools:
            mock_get_tools.return_value = []
            self.agent = ReviewAgent(self.mock_provider, self.mock_memory)

    def test_review_diff_basic(self):
        # Setup mocks
        self.mock_memory.load_context.return_value = "Existing Context"
        self.agent.agent_executor = MagicMock()
        self.agent.agent_executor.invoke.return_value = {"output": "Agent Review Output"}
        
        # Run method
        diff = "+ change"
        filename = "test.py"
        output = self.agent.review_diff(filename, diff)
        
        # Verify interactions
        self.mock_memory.load_context.assert_called()
        self.agent.agent_executor.invoke.assert_called_once()
        
        # Check input passed to agent
        call_args = self.agent.agent_executor.invoke.call_args
        inputs = call_args[0][0]
        self.assertIn(f"Review the changes in `{filename}`", inputs['input'])
        self.assertIn("DIFF:\n+ change", inputs['input'])
        
        self.assertEqual(output, "Agent Review Output")

    def test_review_diff_with_context_files(self):
        # Setup
        self.mock_memory.load_context.return_value = ""
        self.agent.agent_executor = MagicMock()
        self.agent.agent_executor.invoke.return_value = {"output": "Done"}
        
        # Run with other files
        other_files = ["test.py", "other_file.py", "README.md"]
        self.agent.review_diff("test.py", "+ diff", other_files=other_files)
        
        # Verify correct context injection
        call_args = self.agent.agent_executor.invoke.call_args
        inputs = call_args[0][0]
        prompt = inputs['input']
        
        self.assertIn("CONTEXT: The following files are ALSO modified in this MR:", prompt)
        self.assertIn("- other_file.py", prompt)
        self.assertIn("- README.md", prompt)
        # Should not include itself
        self.assertNotIn("- test.py", prompt)

    def test_memory_logging(self):
        # Test if ADD_MEMORY output is captured
        self.mock_memory.load_context.return_value = ""
        self.agent.agent_executor = MagicMock()
        self.agent.agent_executor.invoke.return_value = {
            "output": "Review...\nADD_MEMORY: [RISK] Risk found\n...More review"
        }
        
        self.agent.review_diff("test.py", "+ diff")
        
        # Verify log_insight called
        self.mock_memory.log_insight.assert_any_call("[RISK] Risk found")

    def test_auto_dependency_imports(self):
        # Mock dependency tools
        with patch('openhands.agent.tools.definitions.DependencyAnalysisTools') as mock_tools:
            mock_tools.get_file_imports.return_value = ["import os", "import sys"]
            mock_tools.find_references.return_value = "No references"
            
            self.agent.agent_executor = MagicMock()
            self.agent.agent_executor.invoke.return_value = {"output": "Done"}
            
            self.agent.review_diff("test.py", "diff")
            
            # Verify dependency logging
            self.mock_memory.log_insight.assert_any_call(
                "ADD_MEMORY: [DEPENDENCY] test.py DEPENDS ON:\n['import os', 'import sys']"
            )

if __name__ == '__main__':
    unittest.main()
