from django.test import SimpleTestCase

from drivers.tests.test_traffic import COORDS, drive, levels_at
from drivers.traffic import compute_traffic


class SybilOracle(SimpleTestCase):
    """A rival with two fake drivers must not learn a lone victim bus's speed."""

    def _run(self, victim_kmh):
        pings = drive(1, 900, 0.5, 60) + drive(2, 900, 50, 60)  # fakes: heavy / moving
        if victim_kmh is not None:
            pings += drive(99, 900, victim_kmh, 60)
        pings.sort(key=lambda r: (r[0], r[3]))
        return levels_at(compute_traffic(
            COORDS, [], pings, own_driver_id=None, company_of={1: 'rival', 2: 'rival', 99: 'victim'},
        ), 920)

    def test_victim_presence_not_revealed(self):
        self.assertEqual(self._run(None), self._run(15))
