"""Live publish check against ui_preview.py --n8n, using isolated test credentials."""
from pathlib import Path
import sys
import json
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import httpx
from backend.n8n_client import N8nSession, N8nClient

if __name__ == '__main__':
    session = N8nSession('http://127.0.0.1:5688')
    session.request('POST', '/rest/login', {'emailOrLdapLoginId': 'ui-test@example.invalid', 'password': 'UiTest2026!OnlyLocal'})
    created = session.request('POST', '/rest/api-keys', {'label': 'isolated-smoke-' + uuid4().hex[:8], 'expiresAt': None, 'scopes': ['workflow:create', 'workflow:read', 'workflow:update']})
    key = created.get('rawApiKey') or created.get('apiKey')
    if not key:
        raise RuntimeError('API key response did not contain a key')
    with httpx.Client(base_url='http://127.0.0.1:8766', timeout=120) as client:
        client.post('/api/n8n', json={'action': 'key', 'key': key}).raise_for_status()
        project = client.post('/api/projects/create', json={'topic': 'Publish smoke'}).json()
        client.headers['X-Agent-Session'] = project['session_id']
        workflow = {'name': 'Isolated QA workflow', 'nodes': [{'id': 'start', 'name': 'Manual Trigger',
            'type': 'n8n-nodes-base.manualTrigger', 'typeVersion': 1, 'position': [0, 0], 'parameters': {}}],
            'connections': {}, 'settings': {}}
        client.post('/api/files/import?path=n8n/workflows/smoke.json', content=json.dumps(workflow)).raise_for_status()
        response = client.post('/api/chat', json={'message': '/publish n8n/workflows/smoke.json'})
        response.raise_for_status()
        approval = None
        for block in response.text.split('\n\n'):
            if 'event: approval' in block:
                approval = json.loads(block.split('data: ', 1)[1])['approval_id']
        if not approval:
            raise RuntimeError('No approval returned: ' + response.text)
        result = client.post('/api/approve', json={'approval_id': approval, 'decision': 'approve'})
        if result.status_code != 200:
            raise RuntimeError(result.text)
        first = result.json()['result']
        remote = N8nClient('http://127.0.0.1:5688', key)
        workflow_id = first['n8n_workflow_id']
        assert remote.get_workflow(workflow_id)['active'] is False
        target = Path(project['path']).resolve() / 'n8n/workflows/smoke.json'
        assert target.is_relative_to((Path(__file__).resolve().parent).resolve())
        workflow['name'] = 'Isolated QA workflow updated'
        target.write_text(json.dumps(workflow), encoding='utf-8')
        def publish_again():
            stream = client.post('/api/chat', json={'message': '/publish n8n/workflows/smoke.json'})
            approval_id = next(json.loads(block.split('data: ', 1)[1])['approval_id']
                for block in stream.text.split('\n\n') if 'event: approval' in block)
            return client.post('/api/approve', json={'approval_id': approval_id, 'decision': 'approve'})
        updated = publish_again()
        assert updated.status_code == 200, updated.text
        assert updated.json()['result']['action'] == 'UPDATE'
        assert updated.json()['result']['n8n_workflow_id'] == workflow_id
        assert remote.get_workflow(workflow_id)['active'] is False
        idempotent = publish_again()
        assert idempotent.json()['result']['action'] == 'idempotent'
        remote.update_workflow(workflow_id, {**workflow, 'name': 'Remote manual change'})
        workflow['name'] = 'Local conflicting change'
        target.write_text(json.dumps(workflow), encoding='utf-8')
        conflict = publish_again()
        assert conflict.status_code == 409, conflict.text
        assert remote.get_workflow(workflow_id)['name'] == 'Remote manual change'
        print('LIVE PUBLISH OK: CREATE, UPDATE same ID, inactive, idempotent retry, remote conflict preserved')
