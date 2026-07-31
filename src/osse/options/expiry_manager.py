import calendar
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class ExpiryManager:
    """
    Calculates Weekly, Next Weekly, and Monthly option expiry dates and DTE (Days to Expiry)
    for Indian Indices (NIFTY, BANKNIFTY, FINNIFTY, SENSEX) and Equities.
    """

    EXPIRY_WEEKDAY_MAP = {
        "NIFTY": 1,      # Tuesday (0=Mon, 1=Tue, 2=Wed, 3=Thu)
        "BANKNIFTY": 2, # Wednesday
        "FINNIFTY": 1,  # Tuesday
        "SENSEX": 4,    # Friday
        "DEFAULT": 1    # Tuesday
    }

    @staticmethod
    def get_expiry_weekday(symbol: str) -> int:
        sym_clean = symbol.upper().split(".")[0]
        return ExpiryManager.EXPIRY_WEEKDAY_MAP.get(sym_clean, ExpiryManager.EXPIRY_WEEKDAY_MAP["DEFAULT"])

    @staticmethod
    def get_weekly_expiry(base_date: datetime, symbol: str) -> datetime:
        """Finds the upcoming weekly expiry date on or after base_date."""
        target_weekday = ExpiryManager.get_expiry_weekday(symbol)
        days_ahead = (target_weekday - base_date.weekday()) % 7
        return base_date + timedelta(days=days_ahead)

    @staticmethod
    def get_next_weekly_expiry(base_date: datetime, symbol: str) -> datetime:
        """Finds the weekly expiry date for the following week."""
        weekly = ExpiryManager.get_weekly_expiry(base_date, symbol)
        return weekly + timedelta(days=7)

    @staticmethod
    def get_monthly_expiry(base_date: datetime, symbol: str) -> datetime:
        """Finds the last expiry weekday of the current month."""
        target_weekday = ExpiryManager.get_expiry_weekday(symbol)
        year, month = base_date.year, base_date.month
        last_day = calendar.monthrange(year, month)[1]
        last_date = datetime(year, month, last_day)

        # Walk backward to find the last target weekday of the month
        days_back = (last_date.weekday() - target_weekday) % 7
        monthly_exp = last_date - timedelta(days=days_back)

        # If base_date is past this month's expiry, return next month's monthly expiry
        if base_date > monthly_exp:
            next_month = month + 1 if month < 12 else 1
            next_year = year if month < 12 else year + 1
            last_day_next = calendar.monthrange(next_year, next_month)[1]
            last_date_next = datetime(next_year, next_month, last_day_next)
            days_back_next = (last_date_next.weekday() - target_weekday) % 7
            monthly_exp = last_date_next - timedelta(days=days_back_next)

        return monthly_exp

    @classmethod
    def calculate_all_expiries(cls, date_input: str or datetime, symbol: str = "NIFTY") -> dict:
        """
        Calculates all 3 expiry types (WEEKLY, NEXT_WEEKLY, MONTHLY) along with DTE in days.
        """
        if isinstance(date_input, str):
            try:
                base_dt = datetime.strptime(date_input, "%Y-%m-%d")
            except ValueError:
                base_dt = datetime.now()
        else:
            base_dt = date_input

        weekly_dt = cls.get_weekly_expiry(base_dt, symbol)
        next_weekly_dt = cls.get_next_weekly_expiry(base_dt, symbol)
        monthly_dt = cls.get_monthly_expiry(base_dt, symbol)

        # If current weekly expiry is the same date as monthly expiry (last week of month),
        # advance MONTHLY to next month's monthly expiry date for distinct contract selection.
        if weekly_dt.date() == monthly_dt.date():
            next_month_base = monthly_dt + timedelta(days=10)
            monthly_dt = cls.get_monthly_expiry(next_month_base, symbol)

        def make_payload(exp_dt: datetime):
            dte = max(1, (exp_dt.date() - base_dt.date()).days)
            return {
                "expiry_date": exp_dt.strftime("%Y-%m-%d"),
                "formatted_date": exp_dt.strftime("%d %b %Y"),
                "dte_days": dte
            }

        return {
            "WEEKLY": make_payload(weekly_dt),
            "NEXT_WEEKLY": make_payload(next_weekly_dt),
            "MONTHLY": make_payload(monthly_dt)
        }
