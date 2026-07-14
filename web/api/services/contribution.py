
# web/api/services/contribution.py
# ---------------------------------------------------------------------------
# Contribution service : thin facade over the contribution provider.
# ---------------------------------------------------------------------------
# All data access lives behind a provider (see contribution_providers.py) so the
# calculation source can move from the on-the-fly derivation to a precomputed
# fact_contribution table with NO change here, in the route, or in the front end.
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging

from web.api.services.contribution_providers import get_contribution_provider

logger = logging.getLogger(__name__)


def get_contribution(
    portfolio_id: int,
    date_from: str,
    date_to: str,
    source: str | None = None,
) -> dict:
    """Return {portfolio, period, portfolio_return, holdings[], by_asset_class[]}."""
    return get_contribution_provider().get_contribution(portfolio_id, date_from, date_to, source)

