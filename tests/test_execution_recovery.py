from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from backend.audit import AuditLog
from backend.jail import FilesystemJail, JailError
from backend.job_object import JobLimits
from backend.snapshot import SnapshotStore, controlled_write, controlled_delete
from backend.staging import run_in_staging


class ExecutionRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / 'projects' / 'Ab3K9-demo'
        self.project.mkdir(parents=True)
        self.jail = FilesystemJail(self.root, self.root / 'system', self.project)
        self.snap = SnapshotStore(self.root / '.runtime' / 'snapshots')

    def run_script(self, code, cancel=None):
        (self.project / 'test.py').write_text(code, encoding='utf-8')
        return run_in_staging(interpreter=Path(sys.executable), script_rel='test.py', args=[],
            project_root=self.project, staging_root=self.root / '.runtime' / 'staging', jail=self.jail,
            snapshots=self.snap, project_id='Ab3K9', turn_id='t1', audit=AuditLog(self.root / 'audit.jsonl'),
            timeout=5, limits=JobLimits(), stdout_limit=2000, pythonhome=Path(sys.executable).parent,
            cancel_event=cancel)

    def test_failed_script_does_not_commit_partial_output(self):
        result = self.run_script("from pathlib import Path\nPath('partial.txt').write_text('partial')\nraise RuntimeError('failed')")
        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(result.committed, [])
        self.assertFalse((self.project / 'partial.txt').exists())

    def test_cancelled_script_does_not_commit(self):
        cancel = threading.Event()
        cancel.set()
        result = self.run_script("import time\ntime.sleep(30)", cancel)
        self.assertNotEqual(result.exit_code, 0)
        self.assertEqual(result.committed, [])

    def test_absolute_project_write_snapshots_relative_path(self):
        target = self.project / 'output.txt'
        controlled_write(self.jail, str(target), b'new', self.snap, 'Ab3K9', 't1')
        self.assertEqual(self.snap.restore_turn('Ab3K9', 't1', self.jail), ['output.txt'])

    def test_directory_and_project_root_delete_are_rejected(self):
        folder = self.project / 'folder'
        folder.mkdir()
        (folder / 'keep.txt').write_text('keep')
        for name in ('.', 'folder'):
            with self.assertRaises(JailError):
                controlled_delete(self.jail, name, self.snap, 'Ab3K9', 't1')
        self.assertEqual((folder / 'keep.txt').read_text(), 'keep')
