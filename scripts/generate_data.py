"""Regenerate the synthetic dataset.

    uv run python scripts/generate_data.py --seed 42

Every table is dropped and recreated, so running this repeatedly produces a
logically equivalent database without duplicating any records.
"""

import sys
from argparse import ArgumentParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.app.data_seed import DEFAULT_SEED, seed_database  # noqa: E402
from src.config.settings import settings  # noqa: E402
from src.repositories.session import build_engine  # noqa: E402


def main() -> None:
    parser = ArgumentParser(description="Generate the synthetic financial dataset.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="Random seed (default: 42).")
    parser.add_argument(
        "--database-path",
        type=str,
        default=None,
        help="Override the SQLite file to write. Defaults to DATABASE_PATH.",
    )
    args = parser.parse_args()

    if args.database_path:
        database_path = Path(args.database_path).resolve()
        database_url = f"sqlite+pysqlite:///{database_path}"
    else:
        database_path = settings.resolved_database_path
        database_url = settings.database_url

    summary = seed_database(build_engine(database_url), seed=args.seed)

    print(f"Synthetic dataset written to {database_path}")
    print(f"  seed:                  {summary.seed}")
    print(f"  customers:             {summary.customers}")
    print(f"  accounts:              {summary.accounts}")
    print(f"  merchants:             {summary.merchants}")
    print(f"  random transactions:   {summary.random_transactions}")
    print(f"  interesting txns:      {summary.interesting_transactions}")
    print(f"  scenario transactions: {summary.scenario_transactions}")
    print(f"  total transactions:    {summary.total_transactions}")
    print("\nAll records are fictional and synthetically generated.")


if __name__ == "__main__":
    main()
