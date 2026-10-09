from decimal import Decimal
from django.test import SimpleTestCase
from core.templatetags.avatars import point_display

class PointDisplayTests(SimpleTestCase):
    def test_rounds_only_display_to_two_decimals(self):
        for value, expected in [('12.36', '12.36'), ('10', '10.00'), ('0.15', '0.15'), ('100.000000', '100.00'), ('-0.01', '-0.01'), ('NaN', ''), ('Infinity', ''), ('bad', '')]:
            self.assertEqual(point_display(value), expected)
        amount = Decimal('12.365001')
        self.assertEqual(point_display(amount), '12.37')
        self.assertEqual(amount, Decimal('12.365001'))
