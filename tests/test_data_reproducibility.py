"""The generator must be deterministic and idempotent."""

from sqlalchemy import select

from src.app.data_seed import (
    DEFAULT_SEED,
    INTERESTING_TRANSACTION_MAX,
    INTERESTING_TRANSACTION_TARGET,
    RANDOM_TRANSACTION_COUNT,
    SCENARIOS,
    TARGET_ACCOUNTS,
    TARGET_CUSTOMERS,
    TARGET_MERCHANTS,
    seed_database,
)
from src.repositories.models import AccountRow, CustomerRow, MerchantRow, TransactionRow
from src.repositories.session import build_engine, build_session_factory


def snapshot(engine) -> dict[str, list[tuple]]:
    """A comparable view of every generated row."""
    factory = build_session_factory(engine)
    with factory() as session:
        return {
            "customers": [
                (row.customer_id, row.first_name, row.last_name, row.state)
                for row in session.execute(select(CustomerRow).order_by(CustomerRow.customer_id)).scalars()
            ],
            "accounts": [
                (row.account_id, row.customer_id, row.account_type, row.account_status, row.open_date)
                for row in session.execute(select(AccountRow).order_by(AccountRow.account_id)).scalars()
            ],
            "merchants": [
                (row.merchant_id, row.display_name, row.category, row.country, tuple(row.descriptor_patterns))
                for row in session.execute(select(MerchantRow).order_by(MerchantRow.merchant_id)).scalars()
            ],
            "transactions": [
                (
                    row.transaction_id,
                    row.account_id,
                    row.merchant_id,
                    row.raw_descriptor,
                    row.amount_minor,
                    row.currency,
                    row.transaction_date,
                    row.posted_date,
                    row.status,
                    row.card_present,
                    row.recurring,
                )
                for row in session.execute(select(TransactionRow).order_by(TransactionRow.transaction_id)).scalars()
            ],
        }


def seeded(path, seed: int = DEFAULT_SEED):
    engine = build_engine(f"sqlite+pysqlite:///{path}")
    seed_database(engine, seed=seed)
    return engine


def test_the_expected_volumes_are_generated(engine):
    data = snapshot(engine)

    assert len(data["customers"]) == TARGET_CUSTOMERS
    assert len(data["accounts"]) == TARGET_ACCOUNTS
    assert len(data["merchants"]) == TARGET_MERCHANTS

    scenario_ids = {scenario.transaction_id for scenario in SCENARIOS}
    interesting = [row for row in data["transactions"] if str(row[0]).startswith("TXN-INT-")]
    background = [
        row
        for row in data["transactions"]
        if str(row[0]).startswith("TXN-") and row[0] not in scenario_ids and not str(row[0]).startswith("TXN-INT-")
    ]

    assert len(background) == RANDOM_TRANSACTION_COUNT
    assert INTERESTING_TRANSACTION_TARGET <= len(interesting) <= INTERESTING_TRANSACTION_MAX
    assert len(data["transactions"]) == len(background) + len(interesting) + len(SCENARIOS)


def test_the_same_seed_produces_identical_data(tmp_path):
    first = seeded(tmp_path / "first.db")
    second = seeded(tmp_path / "second.db")

    assert snapshot(first) == snapshot(second)


def test_regenerating_in_place_does_not_duplicate_records(tmp_path):
    """Running the generator repeatedly is safe."""
    path = tmp_path / "repeat.db"
    engine = seeded(path)
    before = snapshot(engine)

    seed_database(engine, seed=DEFAULT_SEED)
    seed_database(engine, seed=DEFAULT_SEED)

    assert snapshot(engine) == before


def test_a_different_seed_changes_the_random_population_only(tmp_path):
    default = snapshot(seeded(tmp_path / "default.db"))
    alternate = snapshot(seeded(tmp_path / "alternate.db", seed=7))

    assert default["customers"] == alternate["customers"]
    assert default["accounts"] == alternate["accounts"]
    assert default["merchants"] == alternate["merchants"]
    assert default["transactions"] != alternate["transactions"]


def test_scenario_transactions_are_identical_across_seeds(tmp_path):
    scenario_ids = {scenario.transaction_id for scenario in SCENARIOS}

    def scenarios_of(snapshot_data):
        return [row for row in snapshot_data["transactions"] if row[0] in scenario_ids]

    default = snapshot(seeded(tmp_path / "default.db"))
    alternate = snapshot(seeded(tmp_path / "alternate.db", seed=7))

    assert scenarios_of(default) == scenarios_of(alternate)
    assert len(scenarios_of(default)) == len(SCENARIOS)


def test_dates_do_not_drift_with_the_current_date(engine):
    """Dates derive from a fixed reference date, not from today."""
    data = snapshot(engine)
    duplicate_rows = [row for row in data["transactions"] if row[0] == "TXN-SCN-DUP-A"]

    assert duplicate_rows[0][6].isoformat() == "2026-06-12"
