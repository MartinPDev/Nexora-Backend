import unittest
from datetime import date

from app.eligibility import age_on_date, is_eligible_adult


class EligibilityTests(unittest.TestCase):
    def test_account_is_allowed_on_eighteenth_birthday(self):
        today = date(2026, 7, 21)
        self.assertTrue(is_eligible_adult(date(2008, 7, 21), today))

    def test_account_is_rejected_before_eighteenth_birthday(self):
        today = date(2026, 7, 21)
        self.assertFalse(is_eligible_adult(date(2008, 7, 22), today))

    def test_leap_day_birth_date_is_handled(self):
        self.assertEqual(age_on_date(date(2008, 2, 29), date(2026, 2, 28)), 17)
        self.assertEqual(age_on_date(date(2008, 2, 29), date(2026, 3, 1)), 18)


if __name__ == "__main__":
    unittest.main()
