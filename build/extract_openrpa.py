"""Extract a verified OpenRPA MSI using read-only MSI APIs, never install it.

Build-machine utility. Writes only below the explicitly supplied output directory.
"""
import argparse
import ctypes as C
from ctypes import wintypes as W
from pathlib import Path
import hashlib
import json
import subprocess
import shutil

VERSION = '1.4.57.13'


def extract(msi: Path, output: Path):
    dll = C.WinDLL('msi')
    handle = W.UINT
    for name, types in {
        'MsiOpenDatabaseW': [W.LPCWSTR, W.LPCWSTR, C.POINTER(handle)],
        'MsiDatabaseOpenViewW': [handle, W.LPCWSTR, C.POINTER(handle)],
        'MsiViewExecute': [handle, handle],
        'MsiViewFetch': [handle, C.POINTER(handle)],
        'MsiRecordGetStringW': [handle, W.UINT, W.LPWSTR, C.POINTER(W.DWORD)],
        'MsiRecordReadStream': [handle, W.UINT, C.c_void_p, C.POINTER(W.DWORD)],
        'MsiCloseHandle': [handle],
    }.items():
        fn = getattr(dll, name); fn.argtypes = types; fn.restype = W.UINT

    def check(code):
        if code != 0: raise RuntimeError('MSI read error ' + str(code))

    db = handle()
    check(dll.MsiOpenDatabaseW(str(msi.resolve()), None, C.byref(db)))
    def rows(sql, columns):
        view = handle(); check(dll.MsiDatabaseOpenViewW(db, sql, C.byref(view)))
        try:
            check(dll.MsiViewExecute(view, 0))
            while True:
                record = handle(); code = dll.MsiViewFetch(view, C.byref(record))
                if code == 259: break
                check(code)
                try:
                    values = []
                    for i in range(1, columns + 1):
                        buf = C.create_unicode_buffer(32768); size = W.DWORD(len(buf))
                        check(dll.MsiRecordGetStringW(record, i, buf, C.byref(size)))
                        values.append(buf.value)
                    yield values
                finally: dll.MsiCloseHandle(record)
        finally: dll.MsiCloseHandle(view)

    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    temp = output / '_cabinet'
    temp.mkdir(exist_ok=True)
    try:
        directories = {r[0]: (r[1], r[2]) for r in rows('SELECT `Directory`,`Directory_Parent`,`DefaultDir` FROM `Directory`', 3)}
        components = {r[0]: r[1] for r in rows('SELECT `Component`,`Directory_` FROM `Component`', 2)}
        files = list(rows('SELECT `File`,`Component_`,`FileName` FROM `File`', 3))
        for (cabinet,) in rows('SELECT `Cabinet` FROM `Media`', 1):
            if not cabinet.startswith('#'): raise RuntimeError('External cabinet not supported')
            name = cabinet[1:]
            if Path(name).name != name: raise ValueError('Invalid cabinet name')
            view = handle(); check(dll.MsiDatabaseOpenViewW(db, "SELECT `Data` FROM `_Streams` WHERE `Name`='" + name.replace("'", "''") + "'", C.byref(view)))
            record = handle()
            try:
                check(dll.MsiViewExecute(view, 0)); check(dll.MsiViewFetch(view, C.byref(record)))
                cab = temp / name
                with cab.open('wb') as dest:
                    while True:
                        buf = C.create_string_buffer(65536); size = W.DWORD(len(buf))
                        check(dll.MsiRecordReadStream(record, 1, buf, C.byref(size)))
                        if not size.value: break
                        dest.write(buf.raw[:size.value])
                subprocess.run(['expand.exe', '-F:*', str(cab), str(temp)], check=True,
                               stdout=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
            finally:
                if record.value: dll.MsiCloseHandle(record)
                dll.MsiCloseHandle(view)

        def target_dir(key):
            parent, name = directories[key]
            part = name.split(':')[0].split('|')[-1]
            # MSI root properties are logical roots, not paths to write to the machine.
            return (target_dir(parent) if parent else Path()) / ('' if part in {'.', 'SourceDir'} else part)

        mapped = [(fileid, target_dir(components[component]) / name.split('|')[-1]) for fileid, component, name in files]
        robot_path = next(path for _, path in mapped if path.name.lower() == 'openrpa.exe')
        install_root = robot_path.parent
        copied = []
        for fileid, path in mapped:
            if not path.is_relative_to(install_root): continue
            relative = path.relative_to(install_root)
            target = (output / relative).resolve()
            if not target.is_relative_to(output): raise ValueError('MSI path outside output')
            source = temp / fileid
            if not source.is_file(): raise FileNotFoundError(fileid)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            copied.append(relative.as_posix())
        manifest = {'version': VERSION, 'source_sha256': hashlib.sha256(msi.read_bytes()).hexdigest(),
                    'files': copied, 'note': 'Extracted, not installed; optional integrations may require system prerequisites.'}
        (output / 'extraction-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        print('Extracted', len(copied), 'files into', output)
    finally:
        dll.MsiCloseHandle(db)
        # Keep build intermediate cabinets; no recursive deletion in this utility.


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('msi', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    extract(args.msi, args.output)
