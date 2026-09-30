"""Foreign-exchange data tool.

Uses Frankfurter (https://www.frankfurter.app), a free, no-API-key rates
service backed by the European Central Bank reference rates, so this tool
works out of the box in dev. It does **not** cover every African currency
(the ECB reference set is limited) — for production, swap the underlying
call for a provider with fuller African-currency coverage (e.g.
exchangerate.host, a central-bank API, or a paid FX data vendor) behind
the same function signature.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from time import perf_counter

import requests

from afrivest_ai.config import settings

logger = logging.getLogger(__name__)
_TIMEOUT_SECONDS = 15


def get_exchange_rate_snapshot(local_currency: str) -> dict:
    """Fetch the latest exchange rate and recent volatility for USD to local currency.

    Args:
        local_currency: ISO 4217 code of the local currency, e.g. "GHS", "NGN", "KES".

    Returns:
        A dict with `latest_rate` (USD to local), `as_of_date`, `thirty_day_change_pct`, and
        `history` (a list of `{date, rate}` points for the trailing 30 days).
    """
    local_currency = local_currency.strip().upper()

    end = date.today()
    start = end - timedelta(days=30)

    url = (
        f"{settings.fx_api_base_url}/{start.isoformat()}..{end.isoformat()}"
        f"?from=USD&to={local_currency}"
    )

    started_at = perf_counter()
    logger.info("FX snapshot requested base=USD target=%s", local_currency)
    try:
        resp = requests.get(url, timeout=_TIMEOUT_SECONDS)
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning(
            "FX snapshot request failed target=%s error=%s",
            local_currency,
            exc,
        )
        return {
            "error": (
                f"Could not fetch FX data for USD/{local_currency}: {exc}. "
                "This currency pair may not be covered by the reference source. "
                "Use internet_search for qualitative volatility reporting instead."
            )
        }

    rates_by_date: dict[str, float] = {}
    for day, rates in (payload.get("rates") or {}).items():
        value = rates.get(local_currency)
        if value is not None:
            rates_by_date[day] = value

    if not rates_by_date:
        logger.warning("FX provider returned no rates target=%s", local_currency)
        return {
            "error": (
                f"No rates returned for USD/{local_currency}. "
                "This pair is likely not covered by the reference source. "
                "Use internet_search for qualitative FX risk reporting instead."
            )
        }

    ordered_days = sorted(rates_by_date)
    history = [{"date": d, "rate": rates_by_date[d]} for d in ordered_days]
    latest_date = ordered_days[-1]
    earliest_date = ordered_days[0]
    latest_rate = rates_by_date[latest_date]
    earliest_rate = rates_by_date[earliest_date]

    change_pct = (
        ((latest_rate - earliest_rate) / earliest_rate) * 100 if earliest_rate else None
    )

    logger.info(
        "FX snapshot completed target=%s as_of=%s observations=%d "
        "duration_seconds=%.2f",
        local_currency,
        latest_date,
        len(history),
        perf_counter() - started_at,
    )
    return {
        "base_currency": "USD",
        "target_currency": local_currency,
        "latest_rate": latest_rate,
        "as_of_date": latest_date,
        "thirty_day_change_pct": round(change_pct, 2) if change_pct is not None else None,
        "history": history,
    }
