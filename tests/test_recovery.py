from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from backend.atomic import atomic_write_bytes
from backend.jail import FilesystemJail
from backend.snapshot import SnapshotStore, SnapshotConflict, controlled_write, controlled_delete


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = self.root / 'projects' / 'Ab3K9-demo'
        self.project.mkdir(parents=True)
        self.jail = FilesystemJail(self.root, self.root / 'system', self.project)
        self.store = SnapshotStore(self.root / '.runtime' / 'snapshots')

    def write(self, name, text):
        controlled_write(self.jail, name, text.encode(), self.store, 'Ab3K9', 't1')

    def test_restore_existing_and_new_files_once(self):
        (self.project / 'a.txt').write_text('before')
        self.write('a.txt', 'after')
        self.write('new.txt', 'created')
        self.assertEqual(set(self.store.restore_turn('Ab3K9', 't1', self.jail)), {'a.txt', 'new.txt'})
        self.assertEqual((self.project / 'a.txt').read_text(), 'before')
        self.assertFalse((self.project / 'new.txt').exists())
        with self.assertRaises(SnapshotConflict):
            self.store.restore_turn('Ab3K9', 't1', self.jail)

    def test_conflict_preflights_all_files(self):
        self.write('a.txt', 'first')
        self.write('z.txt', 'second')
        (self.project / 'z.txt').write_text('user edit')
        with self.assertRaises(SnapshotConflict):
            self.store.restore_turn('Ab3K9', 't1', self.jail)
        self.assertEqual((self.project / 'a.txt').read_text(), 'first')
        self.assertEqual((self.project / 'z.txt').read_text(), 'user edit')

    def test_deleted_file_recreated_by_user_is_preserved(self):
        path = self.project / 'a.txt'
        path.write_text('original')
        controlled_delete(self.jail, 'a.txt', self.store, 'Ab3K9', 't1')
        path.write_text('replacement')
        with self.assertRaises(SnapshotConflict):
            self.store.restore_turn('Ab3K9', 't1', self.jail)
        self.assertEqual(path.read_text(), 'replacement')

    def test_backup_corruption_does_not_mutate_project(self):
        (self.project / 'a.txt').write_text('original')
        self.write('a.txt', 'changed')
        (self.store.turn_dir('Ab3K9', 't1') / 'before' / 'a.txt').write_text('corrupt')
        with self.assertRaises(SnapshotConflict):
            self.store.restore_turn('Ab3K9', 't1', self.jail)
        self.assertEqual((self.project / 'a.txt').read_text(), 'changed')

    def test_reject_invalid_identifiers(self):
        for value in (None, '', '../escape', 'x/../../escape', 'C:\\escape'):
            with self.assertRaises(ValueError):
                self.store.restore_turn('Ab3K9', value, self.jail)

    def test_atomic_write_preserves_neighbor_tmp_file(self):
        neighbor = self.project / 'a.txt.tmp'
        neighbor.write_text('user data')
        atomic_write_bytes(self.project / 'a.txt', b'new data')
        self.assertEqual(neighbor.read_text(), 'user data')
        self.assertEqual(list(self.project.glob('.agent-*.tmp')), [])
