import os
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[2]
SKIP = {'.venv', 'venv', 'migrations', 'tests', 'node_modules', '__pycache__'}


class AtomicCounterTests(SimpleTestCase):
    def test_no_show_count_is_never_read_modify_written(self):
        offenders = []
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [d for d in dirnames if d not in SKIP]
            for name in filenames:
                if name.endswith('.py'):
                    path = Path(dirpath) / name
                    if 'no_show_count +=' in path.read_text():
                        offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])
