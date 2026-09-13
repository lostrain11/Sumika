"""Harness-neutral adapter for the selected MemMachine self-hosted client."""
import os

class MemMachineAdapter:
    def __init__(self, base_url=None):
        from memmachine_client import MemMachineClient
        self.client = MemMachineClient(base_url=base_url or os.environ.get('MEMMACHINE_URL','http://127.0.0.1:8080'))
    def memory(self, *, org_id, project_id, group_id, agent_id, user_id, session_id):
        project = self.client.get_or_create_project(org_id=org_id, project_id=project_id)
        return project.memory(group_id=group_id, agent_id=agent_id, user_id=user_id, session_id=session_id)
