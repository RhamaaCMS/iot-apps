from django.test import SimpleTestCase

from ..versioning import natural_version_key, version_in_range


class HardwareVersionTests(SimpleTestCase):
    def test_natural_numeric_order(self):
        self.assertLess(natural_version_key("rev2"), natural_version_key("rev10"))

    def test_range(self):
        self.assertTrue(version_in_range("rev10", "rev2", "rev12"))
        self.assertFalse(version_in_range("rev20", "rev2", "rev12"))
