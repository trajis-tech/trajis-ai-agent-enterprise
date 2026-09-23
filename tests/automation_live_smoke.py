"""Real n8n -> loopback broker -> offline OpenRPA test, isolated ui_preview only."""
from pathlib import Path
import json
import sys
import time
from uuid import uuid4
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
import httpx
from backend.n8n_client import N8nSession, N8nClient
from backend.tools_automation import deployment_id

XAML = '''<Activity xmlns="http://schemas.microsoft.com/netfx/2009/xaml/activities" xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">
<x:Members><x:Property Name="text" Type="InArgument(x:String)"/><x:Property Name="result" Type="OutArgument(x:String)"/></x:Members>
<Sequence><Assign x:TypeArguments="x:String" To="[result]" Value="[text]"/></Sequence></Activity>'''


def main():
    cancellation = '--cancel' in sys.argv
    n8n = N8nSession('http://127.0.0.1:5688')
    n8n.request('POST', '/rest/login', {'emailOrLdapLoginId': 'ui-test@example.invalid', 'password': 'UiTest2026!OnlyLocal'})
    nodes = n8n.request('GET', '/types/nodes.json')
    assert 'CUSTOM.localOpenRpa' in json.dumps(nodes), 'Bundled node was not registered by real n8n'
    created = n8n.request('POST', '/rest/api-keys', {'label': 'automation-test-' + uuid4().hex[:8], 'expiresAt': None,
                                                  'scopes': ['workflow:create', 'workflow:read', 'workflow:update']})
    key = created.get('rawApiKey') or created.get('apiKey')
    with httpx.Client(base_url='http://127.0.0.1:8766', timeout=120) as client:
        client.post('/api/n8n', json={'action': 'key', 'key': key}).raise_for_status()
        project = client.post('/api/projects/create', json={'topic': 'Automation integration'}).json()
        assert Path(project['path']).resolve().is_relative_to(Path(__file__).resolve().parent)
        client.headers['X-Agent-Session'] = project['session_id']
        artifact = {'name': '中文輸入輸出測試', 'xaml': XAML.replace('<Sequence>', '<Sequence><Delay Duration="00:00:30"/>') if cancellation else XAML, 'parameters': []}
        ident = deployment_id(project['id'], artifact)
        workflow = {'name': 'Isolated OpenRPA integration', 'active': False, 'settings': {'executionOrder': 'v1'},
                    'nodes': [{'id': 'start', 'name': 'Start', 'type': 'n8n-nodes-base.manualTrigger', 'typeVersion': 1, 'position': [0, 0], 'parameters': {}},
                              {'id': 'rpa', 'name': 'Local OpenRPA', 'type': 'CUSTOM.localOpenRpa', 'typeVersion': 1, 'position': [260, 0],
                               'parameters': {'operation': 'run', 'deploymentId': ident, 'input': json.dumps({'text': '本機整合成功'}, ensure_ascii=False), 'waitForCompletion': True}}],
                    'connections': {'Start': {'main': [[{'node': 'Local OpenRPA', 'type': 'main', 'index': 0}]]}}}
        manifest = {'schema_version': 1, 'openrpa': artifact, 'n8n_path': 'automation/demo.n8n.json'}
        for path, payload in [('automation/demo.json', manifest), ('automation/demo.n8n.json', workflow)]:
            client.post('/api/files/import', params={'path': path}, content=json.dumps(payload, ensure_ascii=False).encode()).raise_for_status()
        stream = client.post('/api/chat', json={'message': '/deploy-automation automation/demo.json'})
        approval = next(json.loads(block.split('data: ', 1)[1])['approval_id'] for block in stream.text.split('\n\n') if 'event: approval' in block)
        approved = client.post('/api/approve', json={'approval_id': approval, 'decision': 'approve'})
        approved.raise_for_status()
        result = approved.json()['result']
        assert result['deployment_id'] == ident
        remote = N8nClient('http://127.0.0.1:5688', key)
        assert remote.get_workflow(result['n8n_workflow_id'])['active'] is False
        run = n8n.request('POST', '/rest/workflows/' + result['n8n_workflow_id'] + '/run', {'triggerToStartFrom': {'name': 'Start'}})
        print('N8N_MANUAL_EXECUTION', run, flush=True)
        deadline = time.monotonic() + 150
        latest = None
        cancelled = False
        while time.monotonic() < deadline:
            runs = client.get('/api/automation').json()['runs']
            latest = next((r for r in runs if r['deployment_id'] == ident), None)
            if cancellation and latest and latest['status'] == 'running' and not cancelled:
                time.sleep(2)
                client.post('/api/automation', json={'action': 'cancel', 'run_id': latest['run_id']}).raise_for_status()
                cancelled = True
            if latest and latest['status'] not in {'queued', 'starting', 'running', 'cancel_requested'}: break
            time.sleep(1)
        if cancellation:
            assert cancelled and latest['status'] in {'cancelled', 'unknown'}, latest
            if latest['status'] == 'unknown':
                assert client.get('/api/automation').json()['health']['quarantined']
                recovery = client.post('/api/automation', json={'action': 'recover'})
                recovery.raise_for_status()
                assert not recovery.json()['quarantined'] and not recovery.json()['running']
                print('REAL CANCEL: confirmation unavailable; quarantine and explicit recovery passed', flush=True)
            else:
                print('REAL OPENRPA CANCELLATION: confirmed', flush=True)
            return
        assert latest and latest['status'] == 'succeeded', latest
        assert latest['output']['result'] == '本機整合成功', latest
        execution = None
        for _ in range(20):
            execution = n8n.request('GET', '/rest/executions/' + str(run['executionId']))
            if execution.get('status') == 'success': break
            time.sleep(.5)
        assert execution.get('status') == 'success', {'status': execution.get('status')}
        report = {'project': project['id'], 'deployment_id': ident, 'n8n_workflow_id': result['n8n_workflow_id'],
                  'execution_id': run['executionId'], 'openrpa': latest, 'status': 'passed'}
        output = Path(project['path']).parents[2] / 'automation-integration-result.json'
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print('REAL N8N -> LOCAL BROKER -> OPENRPA: passed, Chinese input/output, inactive deployment', flush=True)


if __name__ == '__main__': main()
