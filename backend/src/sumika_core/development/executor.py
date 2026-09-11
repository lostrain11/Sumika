from __future__ import annotations

import json
from copy import deepcopy

from quality_routing import RoutingError
from quality_routing.development import run_development

from .contracts import LEGACY_EXECUTOR_ID
from .workspace import development_spec


class ApiDevelopmentExecutor:
    executor_id = LEGACY_EXECUTOR_ID

    def __init__(self, workspace_factory):
        self._workspace_factory = workspace_factory

    def preflight(self, directory, options):
        return development_spec(directory, options)

    def inspect(self, spec, prepared):
        workspace = self._workspace_factory(deepcopy(spec), lambda: True)
        return workspace.inspect_saved(deepcopy(prepared))

    def run(self, goal, *, spec, skills, invoke, helper, cancelled, prepared, journal, event):
        spec, skills = deepcopy(spec), deepcopy(skills)
        if cancelled():
            raise RoutingError("development cancelled before preparation")
        workspace = self._workspace_factory(spec, cancelled)
        workspace_state = workspace.prepare()
        prepared(deepcopy(workspace_state))
        extra_tools = []
        if skills:
            extra_tools.append({"type": "function", "function": {"name": "load_skill", "description": "Load an enabled Skill only when relevant to the current task.",
                "parameters": {"type": "object", "properties": {"skill_id": {"type": "string", "enum": [row["id"] for row in skills]}}, "required": ["skill_id"], "additionalProperties": False}}})
        if any(row.get("helpers") for row in skills):
            extra_tools.append({"type": "function", "function": {"name": "run_skill_helper", "description": "Run an enabled Skill's read-only path check. Does not configure, download or execute tools.",
                "parameters": {"type": "object", "properties": {"skill_id": {"type": "string"}, "helper": {"type": "string"}, "operation": {"type": "string", "enum": ["reuse", "cache"]}},
                               "required": ["skill_id", "helper", "operation"], "additionalProperties": False}}})

        def execute(name, arguments):
            if cancelled():
                raise RoutingError("work cancelled")
            if name == "load_skill" and set(arguments) == {"skill_id"}:
                row = next((item for item in skills if item["id"] == arguments["skill_id"]), None)
                if not row:
                    raise RoutingError("Skill is not enabled for this request")
                return {key: row[key] for key in ("id", "content", "directory", "helpers")}
            if name == "run_skill_helper" and set(arguments) == {"skill_id", "helper", "operation"}:
                return helper(arguments["skill_id"], arguments["helper"], arguments["operation"])
            return workspace.execute(name, arguments)

        def publish(item):
            difference = workspace.diff() if item.get("name") in {"write_file", "run_test", "get_diff"} else None
            event(item, difference)

        result = run_development(goal, invoke=invoke, execute=execute, cancelled=cancelled,
            context=json.dumps({"workspace": workspace_state, "authorization": spec,
                "enabled_skills": [{"id": row["id"], "description": row["description"]} for row in skills]}, ensure_ascii=False),
            max_calls=spec["max_calls"], required_tests=len(spec["test_commands"]), event=publish,
            extra_tools=extra_tools, workspace_digest=workspace.source_digest, journal=journal)
        difference = workspace.diff()
        if result["status"] == "completed" and result["workspace_digest"] != workspace.source_digest():
            result["status"] = "review-required"
            result["verification_error"] = "source-changed-before-delivery"
        return {"schema_version": "development-execution/v1", "executor_id": self.executor_id,
                "result": result, "diff": difference}
