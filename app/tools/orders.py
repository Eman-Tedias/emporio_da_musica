import re
from dataclasses import asdict
from datetime import date

from app.calculators.rules import check_return_eligibility
from app.tools.db import agent_connection


def get_order(
    order_id: int, email: str | None = None, phone: str | None = None, today: date | None = None
) -> dict | None:
    phone_digits = re.sub(r"\D", "", phone) if phone else None
    with agent_connection() as conn:
        order = conn.execute(
            "SELECT * FROM get_authorized_order(%s, %s, %s)", (order_id, email, phone_digits)
        ).fetchone()
    if order is None:
        return None

    if order["status"] == "delivered":
        today = today or date.today()
        received_on = order["estimated_delivery"] or order["order_date"]
        order["return_eligibility"] = {
            "regret": asdict(check_return_eligibility("regret", received_on, today)),
            "preference": asdict(check_return_eligibility("preference", received_on, today)),
            "defect": asdict(check_return_eligibility("defect", order["order_date"], today)),
        }
    return order