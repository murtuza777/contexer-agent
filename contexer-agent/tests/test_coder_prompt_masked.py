"""What the coding agent is sent is masked, and is the same text as the copy that is kept.

A repair prompt carries what the browser saw. A page can show a token, and an ``[auth]`` password can be
written literally in ``contexer.toml``; neither may reach the coding agent, which is another program
and, usually, another company's model.
"""

from pathlib import Path

import pytest

from contexer.controller import RunSettings
from contexer.controller.prompts import implement_prompt, masked_for_agent, restated_prompt
from contexer.evidence.rundir import PROMPT_FILE
from contexer.graph import GraphController
from contexer.verification.checks import MASK
from tests.loop_helpers import COUNT_BUG_JS, GOOD_JS, RecordingAgent, contract, copy_todo, fast_runner

MADE_UP_TOKEN = "made-up-token-0123456789"
MADE_UP_PASSWORD = "made-up-pass-Zx9"
MADE_UP_KEY = "sk-" + "a1B2" * 8


def test_a_prompt_with_no_secret_in_it_is_sent_byte_for_byte(tmp_path: Path) -> None:
    project = copy_todo(tmp_path)
    for prompt in (
        implement_prompt(contract(project), None, []),
        restated_prompt(contract(project), [], "Count only the tasks that are not done."),
    ):
        assert masked_for_agent(prompt, []) == prompt
        # A secret that is known but not in the text changes nothing either: the checks and rules stay as code wrote them.
        assert masked_for_agent(prompt, [MADE_UP_PASSWORD]) == prompt


def test_names_that_only_look_like_a_key_are_left_alone() -> None:
    prompt = 'Click [data-testid="task-remaining-count-label"] and read `.risk-score-total-outstanding-value`.\r\n\tDone.\n'
    assert masked_for_agent(prompt, [MADE_UP_PASSWORD]) == prompt


def test_a_known_secret_and_a_key_shape_are_masked() -> None:
    prompt = f"The page showed: password {MADE_UP_PASSWORD}, key {MADE_UP_KEY}."
    sent = masked_for_agent(prompt, [MADE_UP_PASSWORD])
    assert MADE_UP_PASSWORD not in sent and MADE_UP_KEY not in sent
    assert sent.startswith("The page showed: password " + MASK)


@pytest.mark.anyio
async def test_the_repair_prompt_that_is_sent_is_masked_and_is_the_kept_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = copy_todo(tmp_path)
    monkeypatch.setenv("GITHUB_TOKEN", MADE_UP_TOKEN)
    # The page shows a token next to the count, so what the browser saw, and with it the repair prompt, holds it.
    leaking = COUNT_BUG_JS.replace("${left} left", "${left} left " + MADE_UP_TOKEN)
    assert leaking != COUNT_BUG_JS
    agent = RecordingAgent([{"app.js": leaking}, {"app.js": GOOD_JS}])
    outcome = await GraphController(project, agent, RunSettings(max_repair_rounds=2), runner=fast_runner()).run(contract(project))

    assert outcome.terminal == "succeeded", outcome.reason
    assert len(agent.prompts) == 2
    assert MADE_UP_TOKEN not in agent.prompts[1] and MASK in agent.prompts[1]
    assert "complete-decrements" in agent.prompts[1]  # the failure is still told
    run_dir = Path(outcome.run_dir)
    for n, sent in enumerate(agent.prompts, start=1):
        assert (run_dir / f"attempt-{n}" / PROMPT_FILE).read_text(encoding="utf-8") == sent
    assert MASK not in agent.prompts[0]  # the first instruction had no secret in it
