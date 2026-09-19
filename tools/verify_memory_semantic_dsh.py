"""Real managed DSH session using the semantic memory provider.

Proves inside a real harness session, not a unit test: a fact written earlier is
recalled when the user asks with different wording, and a superseded value is
not injected anymore.
"""
import json
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests_next")]

from p2_fixture import ModelFixture
from sumika_next.dsh import Dsh
from verify_dsh_recovery import finish, prompt

MEMORY_PYTHON = ROOT / ".sumika-next" / "memory-env" / "Scripts" / "python.exe"
SEED = """
import sys
sys.path.insert(0, r"{root}")
from extensions.memory.semantic_memory import SemanticMemory
memory = SemanticMemory(r"{database}", cache_dir=r"{cache}")
memory.add("用户喜欢晚上九点看动画。", user_id="u", role_id="test-role", project_id="p",
           fact_key="user.anime")
memory.add("用户以前喝乌龙茶。", user_id="u", role_id="test-role", project_id="p",
           fact_key="user.drink")
memory.add("用户现在改喝白水了。", user_id="u", role_id="test-role", project_id="p",
           fact_key="user.drink")
memory.close()
"""


def main():
    if not MEMORY_PYTHON.is_file():
        raise SystemExit(f"memory environment interpreter missing: {MEMORY_PYTHON}")
    base = ROOT / ".sumika-next" / ("memory-semantic-" + uuid.uuid4().hex)
    base.mkdir()
    home, work, role = base / "home", base / "work", base / "role"
    for folder in (home, work, role):
        folder.mkdir()
    (role / "role.json").write_text(json.dumps(
        dict(id="test-role", name="Synthetic Role", persona="Fixture persona",
             worldbook=[], assets={})), encoding="utf8")
    database = base / "memory.db"
    # Reuse the weights already installed for this project; runtime never downloads.
    cache = ROOT / ".sumika-next" / "embedding-models"
    if not list(cache.rglob("*.onnx")):
        raise SystemExit(f"local embedding weights missing under {cache}")
    seed = subprocess.run([str(MEMORY_PYTHON), "-c",
                           SEED.format(root=str(ROOT), database=str(database), cache=str(cache))],
                          capture_output=True, text=True, encoding="utf-8", timeout=600)
    if seed.returncode:
        raise SystemExit("seeding failed: " + (seed.stderr or "")[-400:])
    config = base / "role-config.json"
    config.write_text(json.dumps(dict(
        role_dir=str(role), database=str(database), user_id="u", project_id="p",
        work_model="work", role_model="role", enabled=True,
        memory_provider="semantic", embedding_cache=str(cache),
        card_context_enabled=False)), encoding="utf8")
    patches = [
        {"id": "session-title-llm", "disabled": True},
        {"id": "llm-deepseek", "config": {"baseURL": None}},
        {"id": "session-telemetry-otel", "disabled": True},
        {"insert": [{"id": "sumika-roles", "name": str(ROOT / "extensions/roles/dsh.mjs"),
                     "config": dict(enabled=True, memoryWrites=False,
                                    projects={str(work): str(config)},
                                    python=str(MEMORY_PYTHON),
                                    core=str(ROOT / "extensions/roles/bridge.py"),
                                    runtimeEntry=str(ROOT / "runtime/dsh/node_modules/"
                                                     "@deepseek-ai/dsh/package.json"))}]}]
    report = {"semantic_provider_in_dsh": False, "paraphrase_recall": False,
              "stale_value_not_injected": False, "artifact": str(base)}
    with ModelFixture() as model:
        patches[1]["config"]["baseURL"] = model.url
        (home / ".env").write_text("DEEPSEEK_API_KEY=local-fixture-not-a-secret\n")
        patch = home / "cordis.patch.yml"
        patch.write_text(json.dumps(patches), encoding="utf8")
        adapter = Dsh(ROOT, home)

        def turn(session, text):
            adapter._rpc("session/create", {"sessionId": session, "cwd": str(work)})
            stream = adapter.stream("session/follow",
                                    {"address": {"kind": "session", "sessionId": session}},
                                    timeout=60)
            try:
                next(stream)
                prompt(adapter, session, text)
                finish(stream)
            finally:
                stream.close()
            return json.dumps(model.requests[-1], ensure_ascii=False)

        try:
            adapter.start()
            wire = turn("semantic-paraphrase", "我一般几点看动画来着？")
            report["semantic_provider_in_dsh"] = "SUMIKA_ROLE_CONTEXT" in wire
            report["paraphrase_recall"] = "九点" in wire
            wire = turn("semantic-update", "我现在喝什么？")
            report["stale_value_not_injected"] = ("白水" in wire) and ("乌龙茶" not in wire)
        except Exception:
            print("\n".join(adapter.startup_messages), file=sys.stderr)
            raise
        finally:
            adapter.close()
    report["passed"] = all(value for key, value in report.items() if isinstance(value, bool))
    (ROOT / "docs/project/memory-semantic-dsh-evidence.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
