"""Project skills: what Contexer learned about one app, kept as advice for the next run. Never proof."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from contexer.appserver import open_app
from contexer.browser.tools import BrowserSession
from contexer.crew.tester import run_tester
from contexer.skills.store import MAX_PROPOSED, Skill, SkillError, SkillStore
from tests.fakes import ScriptedChatModel, submit

FIXTURES = Path(__file__).resolve().parents[1] / "bench" / "fixtures"
INTENT = "Members can sign in, see a dashboard and create projects"

SIGN_IN = Skill(
    name="sign-in",
    description="How to sign in as the demo member",
    body="Open /login.html, fill Email and Password, press Sign in. The password is in ${MEMBERS_PASSWORD}.",
)
CART = Skill(name="cart-total", description="How the cart total is computed", body="The total is under the cart icon.")


# -- the store -----------------------------------------------------------------


def test_a_skill_is_a_markdown_file_with_a_one_line_description(tmp_path: Path) -> None:
    store = SkillStore(tmp_path)
    assert store.list() == []
    path = store.save(SIGN_IN)

    assert path == tmp_path / ".contexer" / "skills" / "sign-in.md"
    text = path.read_text(encoding="utf-8")
    assert text.splitlines()[0] == "# sign-in" and "> How to sign in as the demo member" in text
    assert store.load("sign-in") == SIGN_IN
    assert [s.name for s in store.list()] == ["sign-in"]

    # A person can edit it, or delete it.
    path.write_text(text.replace("press Sign in", "click the Sign in button"), encoding="utf-8")
    assert "click the Sign in button" in store.load("sign-in").body
    store.delete("sign-in")
    assert store.list() == [] and not path.exists()


def test_names_are_made_safe_and_the_description_stays_one_line(tmp_path: Path) -> None:
    store = SkillStore(tmp_path)
    path = store.save(Skill(name="../Reset the  DATA!", description="How to reset\nthe data", body="POST /api/reset"))

    assert path.name == "reset-the-data.md" and path.parent == tmp_path / ".contexer" / "skills"
    assert store.load("reset-the-data").description == "How to reset the data"
    with pytest.raises(SkillError):
        store.save(Skill(name="!!!", description="nameless", body="x"))
    with pytest.raises(SkillError):
        store.save(Skill(name="empty", description="  ", body="x"))


def test_a_skill_holding_a_configured_secret_is_rejected_and_env_names_are_kept(tmp_path: Path) -> None:
    store = SkillStore(tmp_path)
    leaking = Skill(name="sign-in", description="How to sign in", body="Email demo@example.com, password correct-horse.")

    with pytest.raises(SkillError, match="secret"):
        store.save(leaking, secrets=["correct-horse"])
    assert store.list() == []
    # In the description too, and anything shaped like an API key even when nobody configured it.
    with pytest.raises(SkillError):
        store.save(Skill(name="a", description="Use correct-horse", body="x"), secrets=["correct-horse"])
    with pytest.raises(SkillError):
        store.save(Skill(name="b", description="Call the API", body="key sk-or-v1-" + "a1b2c3d4" * 6))

    # The name of the variable is not the secret.
    store.save(SIGN_IN, secrets=["correct-horse"])
    assert "${MEMBERS_PASSWORD}" in store.load("sign-in").body


def test_only_skills_whose_description_matches_the_intent_are_loaded(tmp_path: Path) -> None:
    store = SkillStore(tmp_path)
    assert store.matching(INTENT) == []
    store.save(SIGN_IN)
    store.save(CART)
    store.save(Skill(name="projects", description="Creating projects needs a name of 3 letters or more", body="..."))

    assert [s.name for s in store.matching(INTENT)] == ["projects", "sign-in"]
    assert store.matching("Shoppers see a correct cart total")[0].name == "cart-total"
    assert store.matching("Completely unrelated words here") == []
    assert len(store.matching(INTENT, limit=1)) == 1


# -- the Tester ------------------------------------------------------------------


@pytest.mark.anyio
async def test_matching_skills_are_added_to_the_testers_task_as_advice_and_proposals_come_back(tmp_path: Path) -> None:
    work = tmp_path / "todo"
    shutil.copytree(FIXTURES / "todo" / "app", work, ignore=shutil.ignore_patterns("runs"))
    proposals = [{"name": f"skill-{n}", "description": f"Thing {n}", "body": "..."} for n in range(5)]
    with open_app(work) as running:
        async with BrowserSession(running.url) as browser:
            plain = ScriptedChatModel(submit(summary="Nothing."))
            first = await run_tester(INTENT, plain, browser, run_dir=None)
            informed = ScriptedChatModel(submit(summary="Nothing.", skills=proposals))
            second = await run_tester(INTENT, informed, browser, run_dir=None, skills=[SIGN_IN])

    without, with_skill = plain.seen[0][1].content, informed.seen[0][1].content
    assert "earlier runs" not in without.lower() and first.skills == []
    assert "How to sign in as the demo member" in with_skill and "${MEMBERS_PASSWORD}" in with_skill
    assert "advice" in with_skill.lower()
    # Without skills the task is exactly a first run's task.
    assert with_skill.replace(with_skill[with_skill.index("## What earlier runs") : with_skill.index("Test it.")], "") == without
    assert MAX_PROPOSED == 3 and [s.name for s in second.skills] == ["skill-0", "skill-1", "skill-2"]
