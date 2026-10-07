from decimal import Decimal
from django.test import SimpleTestCase
from core.templatetags.avatars import point_display

class PointDisplayTests(SimpleTestCase):
    def test_rounds_only_display_to_one_decimal(self):
        for value, expected in [('12.36', '12.4'), ('10', '10'), ('0.15', '0.2'), ('100.000000', '100'), ('-0.01', '0'), ('NaN', ''), ('Infinity', ''), ('bad', '')]:
            self.assertEqual(point_display(value), expected)
        amount = Decimal('12.365001')
        self.assertEqual(point_display(amount), '12.4')
        self.assertEqual(amount, Decimal('12.365001'))
