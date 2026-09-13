"""Tests for Contexer system prompt builder."""

from contexer.llm.prompts import BASE_IDENTITY, ENGINEERING_PRINCIPLES, build_system_prompt


class TestSystemPrompts:
    """Prompt builder unit tests."""

    def test_base_prompt_contains_identity_and_principles(self) -> None:
        prompt = build_system_prompt()
        assert "Contexer" in prompt
        assert "autonomous engineering agent" in prompt
        assert "Inspect Context First" in prompt
        assert "Strict Verification" in prompt
        assert "Conservative with Destructive Actions" in prompt

    def test_prompt_includes_repository_context(self) -> None:
        prompt = build_system_prompt(repository_context="Project: my-app\nFiles: src/ main.py")
        assert "Repository Context:" in prompt
        assert "Project: my-app" in prompt
        assert "main.py" in prompt

    def test_prompt_includes_tool_and_task_instructions(self) -> None:
        prompt = build_system_prompt(
            tool_instructions="Run bash with safe commands",
            task_instructions="Fix login bug",
        )
        assert "Tool Instructions:" in prompt
        assert "Run bash with safe commands" in prompt
        assert "Task Instructions:" in prompt
        assert "Fix login bug" in prompt
