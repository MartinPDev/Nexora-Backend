from datetime import date


MINIMUM_ACCOUNT_AGE = 18


def age_on_date(date_of_birth: date, today: date | None = None) -> int:
    today = today or date.today()
    return today.year - date_of_birth.year - (
        (today.month, today.day) < (date_of_birth.month, date_of_birth.day)
    )


def is_eligible_adult(date_of_birth: date, today: date | None = None) -> bool:
    return age_on_date(date_of_birth, today) >= MINIMUM_ACCOUNT_AGE
