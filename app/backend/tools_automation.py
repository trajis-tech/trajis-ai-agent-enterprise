from __future__ import annotations
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import PurePosixPath

from .tools_file import write_file
from .tools_n8n import write_workflow_json, publish_workflow


def validate_artifact(artifact):
    if not isinstance(artifact, dict) or not isinstance(artifact.get('name'), str) or not artifact['name'].strip():
        raise ValueError('請提供 OpenRPA 流程名稱')
    xaml = artifact.get('xaml')
    if not isinstance(xaml, str) or not 1 <= len(xaml) <= 500000:
        raise ValueError('OpenRPA XAML 需為 1–500000 字元')
    if '<!DOCTYPE' in xaml.upper() or '<!ENTITY' in xaml.upper(): raise ValueError('不允許 XML DTD/entity')
    root = ET.fromstring(xaml)
    if root.tag != '{http://schemas.microsoft.com/netfx/2009/xaml/activities}Activity':
        raise ValueError('必須提供 OpenRPA 可載入的 Activity XAML')
    params = artifact.get('parameters', [])
    if not isinstance(params, list) or any(not isinstance(p, dict) for p in params): raise ValueError('parameters 必須為物件陣列')
    # Runtime compilation and desktop effects are authorized by the bundle publish review.
    return artifact


def deployment_id(project_id, artifact):
    raw = json.dumps(artifact, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256((project_id + '\n' + raw).encode()).hexdigest()[:32]


def write_bundle(ctx, path, artifact, inputs, policy):
    validate_artifact(artifact)
    if not path.endswith('.json'): raise ValueError('部署包路徑須為 .json')
    ctx.jail.resolve(path, 'write')
    if not isinstance(inputs, dict): raise ValueError('預設輸入必須為 JSON object')
    workflow_path = str(PurePosixPath(path.replace('\\', '/')).with_suffix('.n8n.json'))
    ident = deployment_id(ctx.project_id, artifact)
    workflow = {'name': artifact['name'], 'active': False, 'nodes': [
        {'id': 'start', 'name': '手動開始', 'type': 'n8n-nodes-base.manualTrigger', 'typeVersion': 1, 'position': [200, 240], 'parameters': {}},
        {'id': 'openrpa', 'name': 'Local OpenRPA', 'type': 'CUSTOM.localOpenRpa', 'typeVersion': 1, 'position': [450, 240],
         'parameters': {'operation': 'run', 'deploymentId': ident, 'input': json.dumps(inputs, ensure_ascii=False), 'waitForCompletion': True}},
    ], 'connections': {'手動開始': {'main': [[{'node': 'Local OpenRPA', 'type': 'main', 'index': 0}]]}}, 'settings': {'executionOrder': 'v1'}}
    write_workflow_json(ctx, workflow_path, workflow, policy)
    manifest = {'schema_version': 1, 'openrpa': artifact, 'n8n_path': workflow_path,
                'execution_notice': '批准部署後，可由本機 n8n 手動執行此 OpenRPA 流程。桌面動作使用目前 Windows 使用者權限。'}
    write_file(ctx, path, json.dumps(manifest, ensure_ascii=False, indent=2))
    return json.dumps({'manifest': path, 'n8n_path': workflow_path, 'deployment_id': ident,
                       'status': 'prepared', 'next': '檢查兩端內容後呼叫 publish_automation_bundle 要求批准'}, ensure_ascii=False)


def read_bundle(ctx, path):
    manifest_raw = ctx.jail.resolve(path, 'read').read_text(encoding='utf-8')
    manifest = json.loads(manifest_raw)
    if manifest.get('schema_version') != 1: raise ValueError('不支援的部署包版本')
    validate_artifact(manifest['openrpa'])
    workflow_raw = ctx.jail.resolve(manifest['n8n_path'], 'read').read_text(encoding='utf-8')
    doc = json.loads(workflow_raw)
    ident = deployment_id(ctx.project_id, manifest['openrpa'])
    nodes = [n for n in doc.get('nodes', []) if n.get('type') == 'CUSTOM.localOpenRpa']
    if not nodes or any(n.get('parameters', {}).get('operation') != 'run' or n.get('parameters', {}).get('deploymentId') != ident for n in nodes):
        raise ValueError('n8n OpenRPA 節點必須對應此部署包的流程版本')
    digest = hashlib.sha256(json.dumps([manifest_raw, workflow_raw], ensure_ascii=False).encode()).hexdigest()
    return manifest, digest


def publish_bundle(ctx, path, policy, client, db, runtime, approved):
    if not approved: raise PermissionError('整合部署需要批准')
    if runtime is None: raise RuntimeError('本機 OpenRPA 橋接服務尚未啟動')
    if not runtime.health()['installed']: raise RuntimeError('OpenRPA runtime 尚未就緒')
    manifest, digest = read_bundle(ctx, path)
    ident = runtime.register(ctx.project_id, manifest['openrpa'])
    # Register disabled first. A crash or rejected n8n publish cannot execute an uncommitted robot.
    # Retrying the same immutable bundle resumes safely through the existing n8n idempotency record.
    result = json.loads(publish_workflow(ctx, manifest['n8n_path'], policy, client, db, approved=True))
    runtime.enable(ident)
    return json.dumps({**result, 'deployment_id': ident, 'bundle_hash': digest, 'status': 'deployed', 'active': False})
