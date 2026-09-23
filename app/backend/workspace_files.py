"""Project file APIs, sharing the Agent jail and snapshot pipeline."""
from io import BytesIO
import os
from pathlib import Path
from uuid import uuid4
import zipfile

from starlette.responses import JSONResponse, Response, FileResponse
from .jail import JailError
from .locks import ProjectLockBusy
from .snapshot import controlled_write

IMPORT_LIMIT = 20 * 1024 * 1024
EXPORT_LIMIT = 100 * 1024 * 1024


def visible_files(root, jail):
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [name for name in sorted(dirs)
                   if not ((Path(directory) / name).lstat().st_file_attributes & 0x400)] if os.name == "nt" else [
                       name for name in sorted(dirs) if not (Path(directory) / name).is_symlink()]
        for name in sorted(files):
            source = Path(directory) / name
            if source.is_symlink():
                continue
            rel = source.relative_to(root).as_posix()
            try:
                target = jail.resolve(rel, 'read')
                if not target.is_relative_to(root.resolve()):
                    continue
                yield rel, target
            except (JailError, OSError):
                continue


async def export_project(request):
    from . import server
    project = request.state.workspace['project']
    if not project:
        return JSONResponse({'error': '請先開啟專案'}, status_code=400)
    root = Path(project['path'])
    acquired = False
    try:
        server.LOCKS.acquire(project['id'], 'export-' + str(uuid4()), timeout=0)
        acquired = True
        output = BytesIO()
        total = 0
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            for rel, target in visible_files(root, server._jail(root)):
                total += target.stat().st_size
                if total > EXPORT_LIMIT:
                    return JSONResponse({'error': '專案超過 100 MB，請從本機資料夾複製'}, status_code=413)
                archive.write(target, rel)
        return Response(output.getvalue(), media_type='application/zip', headers={
            'Content-Disposition': f'attachment; filename="project-{project["id"]}.zip"'})
    except ProjectLockBusy:
        return JSONResponse({'error': '專案執行中，請完成後再匯出'}, status_code=409)
    finally:
        if acquired:
            server.LOCKS.release(project['id'])


async def import_file(request):
    from . import server
    project = request.state.workspace['project']
    if not project:
        return JSONResponse({'error': '請先開啟專案'}, status_code=400)
    rel = request.query_params.get('path', '')
    jail = server._jail(Path(project['path']))
    acquired = False
    try:
        target = jail.resolve(rel, 'write')
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > IMPORT_LIMIT:
                return JSONResponse({'error': '單一檔案上限 20 MB'}, status_code=413)
        turn_id = str(uuid4())[:8]
        server.LOCKS.acquire(project['id'], turn_id, timeout=0)
        acquired = True
        if target.exists():
            return JSONResponse({'error': '已有同名檔案，請重新命名後匯入'}, status_code=409)
        controlled_write(jail, rel, bytes(data), server.SNAPSHOTS, project['id'], turn_id)
        server.AUDIT.write({'tool': 'import_file', 'project_id': project['id'],
                            'turn_id': turn_id, 'target': rel, 'result': 'ok'})
        server.DB.append_message(request.state.workspace['session'], 'system',
                                 {'content': f'已匯入 {rel}'}, turn_id)
        return JSONResponse({'path': rel, 'turn_id': turn_id})
    except JailError as exc:
        return JSONResponse({'error': exc.message, 'code': exc.code}, status_code=403)
    except ProjectLockBusy:
        return JSONResponse({'error': '專案正在執行，請稍後匯入'}, status_code=409)
    finally:
        if acquired:
            server.LOCKS.release(project['id'])


async def download_file(request):
    from . import server
    project = request.state.workspace['project']
    if not project:
        return JSONResponse({'error': '請先開啟專案'}, status_code=400)
    try:
        target = server._jail(Path(project['path'])).resolve(request.query_params.get('path', ''), 'read')
        if not target.is_file() or not target.is_relative_to(Path(project['path']).resolve()):
            return JSONResponse({'error': '找不到檔案'}, status_code=404)
        return FileResponse(target, filename=target.name, media_type='application/octet-stream')
    except JailError as exc:
        return JSONResponse({'error': exc.message}, status_code=403)
