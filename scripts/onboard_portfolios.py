# scripts/onboard_portfolios.py
# ---------------------------------------------------------------
# Register portfolios from src/seeds/portfolios.csv into dim_portfolio
# without a full bootstrap. Idempotent: ON CONFLICT (procode, source)
# DO NOTHING preserves the status of already-registered portfolios.
#
# Use after editing portfolios.csv (e.g. a new FMS fund) so the
# forwards run can resolve it instead of dropping it.
#
# Usage:
#   python scripts/onboard_portfolios.py
# ---------------------------------------------------------------

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.db.bootstrap import load_dim_portfolio
from src.db.connection import get_connection
from src.shared.logging import setup_logging
from src.shared.seed_loader import load_portfolios_seed


def main() -> None:
    portfolios_df = load_portfolios_seed()
    with get_connection() as conn:
        load_dim_portfolio(conn, portfolios_df)


if __name__ == "__main__":
    setup_logging('onboard_portfolios')
    main()
