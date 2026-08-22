"""Reproducible synthetic data generation.

Everything here is invented. Names, merchants, descriptors and amounts were
written for this project and correspond to no real person or business.

Two properties matter:

* **Deterministic.** A given seed always produces the same rows. Dates derive
  from a fixed reference date, never from today, so the dataset does not drift.
* **Idempotent.** Every table is dropped and recreated before inserting, so
  running the generator repeatedly yields a logically equivalent database
  without duplicating anything.

Approximate volumes (seed 42):

* 100 customers, 150 accounts, 75 merchants
* 5,000 ordinary background transactions
* ~150 deliberately interesting transactions (plus 12 hand-written scenarios)
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from ..domain.enums import AccountStatus, AccountType, TransactionStatus
from ..domain.money import to_minor_units
from ..repositories.models import AccountRow, Base, CustomerRow, MerchantRow, TransactionRow

DEFAULT_SEED = 42
# Catalogues are fixed so a different transaction seed only changes transactions.
CATALOG_SEED = 42
REFERENCE_DATE = date(2026, 6, 30)

TARGET_CUSTOMERS = 100
TARGET_ACCOUNTS = 150
TARGET_MERCHANTS = 75
RANDOM_TRANSACTION_COUNT = 5_000
INTERESTING_TRANSACTION_TARGET = 150
INTERESTING_TRANSACTION_MAX = 200
RANDOM_HISTORY_DAYS = 180

CURRENCY_BY_COUNTRY = {
    "US": "USD",
    "FR": "EUR",
    "IE": "EUR",
    "CA": "CAD",
    "GB": "GBP",
    "DE": "EUR",
    "JP": "JPY",
    "AU": "AUD",
}

CITIES = (
    ("SEATTLE", "WA"),
    ("AUSTIN", "TX"),
    ("BROOKLYN", "NY"),
    ("ATLANTA", "GA"),
    ("SAN JOSE", "CA"),
    ("CHICAGO", "IL"),
    ("ANN ARBOR", "MI"),
    ("TAMPA", "FL"),
    ("BOULDER", "CO"),
    ("PORTLAND", "OR"),
    ("DENVER", "CO"),
    ("PHOENIX", "AZ"),
    ("BOSTON", "MA"),
    ("MIAMI", "FL"),
    ("NASHVILLE", "TN"),
)

FIRST_NAMES = (
    "Avery",
    "Rosa",
    "Ingrid",
    "Desmond",
    "Priya",
    "Tomas",
    "Noor",
    "Elena",
    "Marcus",
    "Yuki",
    "Jordan",
    "Samira",
    "Chen",
    "Amelia",
    "Omar",
    "Lucia",
    "Noah",
    "Fatima",
    "Ethan",
    "Sofia",
    "Liam",
    "Aisha",
    "Mateo",
    "Grace",
    "Kai",
    "Nina",
    "Owen",
    "Zara",
    "Leo",
    "Maya",
    "Hugo",
    "Imani",
    "Felix",
    "Anika",
    "Ravi",
    "Clara",
    "Diego",
    "Helen",
    "Ivan",
    "Jade",
    "Kenji",
    "Lara",
    "Malik",
    "Nora",
    "Oscar",
    "Paula",
    "Quinn",
    "Rita",
    "Soren",
    "Tara",
)

LAST_NAMES = (
    "Lindholm",
    "Mbeki",
    "Vasquez",
    "Achebe",
    "Raghunathan",
    "Wierzbicki",
    "Haddad",
    "Petrova",
    "Odhiambo",
    "Tanaka",
    "Nguyen",
    "Silva",
    "Andersen",
    "Okoye",
    "Bergstrom",
    "Castillo",
    "Dubois",
    "Edwards",
    "Fernandez",
    "Garcia",
    "Hassan",
    "Ibrahim",
    "Johansson",
    "Kowalski",
    "Lopez",
    "Moreau",
    "Nielsen",
    "Okafor",
    "Patel",
    "Quinn",
    "Romero",
    "Singh",
    "Torres",
    "Ueda",
    "Volkov",
    "Williams",
    "Xu",
    "Yamamoto",
    "Zimmerman",
    "Brennan",
    "Cho",
    "Diaz",
)

US_STATES = (
    "WA",
    "TX",
    "NY",
    "GA",
    "CA",
    "IL",
    "MI",
    "FL",
    "CO",
    "OR",
    "AZ",
    "MA",
    "TN",
    "NC",
    "PA",
    "OH",
    "VA",
    "NJ",
    "MN",
    "WI",
)

MERCHANT_PREFIXES = (
    "North",
    "River",
    "Halcyon",
    "Lumen",
    "Cascade",
    "Iron",
    "Solstice",
    "Blue",
    "Corner",
    "Vantage",
    "Paper",
    "Kestrel",
    "Alpine",
    "Sable",
    "Cedar",
    "Pine",
    "Oak",
    "Maple",
    "Copper",
    "Silver",
    "Golden",
    "Harbor",
    "Summit",
    "Valley",
    "Canyon",
    "Prairie",
    "Bay",
    "Lake",
    "Stone",
    "Bright",
    "Quiet",
    "Swift",
    "Redwood",
    "Ember",
    "Frost",
    "Granite",
)

MERCHANT_SUFFIXES = (
    "Grocery",
    "Coffee",
    "Electronics",
    "Streaming",
    "Hotel",
    "Hardware",
    "Fitness",
    "Airlines",
    "Pharmacy",
    "Fuel",
    "Books",
    "Rides",
    "Outfitters",
    "Cloud",
    "Market",
    "Bistro",
    "Studio",
    "Motors",
    "Goods",
    "Supply",
    "Workshop",
    "Gallery",
    "Labs",
    "Transit",
    "Dining",
    "Apparel",
    "Tools",
    "Services",
    "Media",
    "Retail",
)

MERCHANT_CATEGORIES = (
    "grocery",
    "dining",
    "electronics",
    "digital_subscription",
    "lodging",
    "home_improvement",
    "fitness",
    "travel",
    "pharmacy",
    "fuel",
    "retail",
    "transport",
    "apparel",
    "software",
    "entertainment",
    "utilities",
    "education",
    "healthcare",
)

MERCHANT_COUNTRIES = ("US", "US", "US", "US", "US", "US", "CA", "FR", "IE", "GB", "DE", "AU", "JP")


@dataclass(frozen=True, slots=True)
class CustomerSpec:
    """One fictional customer."""

    customer_id: str
    first_name: str
    last_name: str
    state: str


@dataclass(frozen=True, slots=True)
class AccountSpec:
    """One fictional account. ``card_suffix`` is a last-four, never a full number."""

    account_id: str
    customer_id: str
    account_type: AccountType
    account_status: AccountStatus
    open_date: date
    card_suffix: str


@dataclass(frozen=True, slots=True)
class MerchantSpec:
    """One fictional merchant and the descriptor fragments it bills under."""

    merchant_id: str
    display_name: str
    category: str
    country: str
    descriptor_patterns: tuple[str, ...]


# Hand-written base catalogue. Expansion fills up to the target volumes.
_BASE_CUSTOMERS: tuple[CustomerSpec, ...] = (
    CustomerSpec("CUST-0001", "Avery", "Lindholm", "WA"),
    CustomerSpec("CUST-0002", "Rosa", "Mbeki", "TX"),
    CustomerSpec("CUST-0003", "Ingrid", "Vasquez", "NY"),
    CustomerSpec("CUST-0004", "Desmond", "Achebe", "GA"),
    CustomerSpec("CUST-0005", "Priya", "Raghunathan", "CA"),
    CustomerSpec("CUST-0006", "Tomas", "Wierzbicki", "IL"),
    CustomerSpec("CUST-0007", "Noor", "Haddad", "MI"),
    CustomerSpec("CUST-0008", "Elena", "Petrova", "FL"),
    CustomerSpec("CUST-0009", "Marcus", "Odhiambo", "CO"),
    CustomerSpec("CUST-0010", "Yuki", "Tanaka", "OR"),
)

_BASE_ACCOUNTS: tuple[AccountSpec, ...] = (
    AccountSpec(
        "ACCT-0001", "CUST-0001", AccountType.CONSUMER_CREDIT_CARD, AccountStatus.ACTIVE, date(2021, 3, 14), "4412"
    ),
    AccountSpec(
        "ACCT-0002", "CUST-0002", AccountType.CONSUMER_CREDIT_CARD, AccountStatus.ACTIVE, date(2019, 11, 2), "8830"
    ),
    AccountSpec(
        "ACCT-0003", "CUST-0003", AccountType.BUSINESS_CREDIT_CARD, AccountStatus.ACTIVE, date(2022, 6, 21), "1157"
    ),
    AccountSpec(
        "ACCT-0004", "CUST-0004", AccountType.CONSUMER_CHARGE_CARD, AccountStatus.ACTIVE, date(2018, 1, 9), "6642"
    ),
    AccountSpec(
        "ACCT-0005", "CUST-0005", AccountType.CONSUMER_CREDIT_CARD, AccountStatus.ACTIVE, date(2023, 4, 30), "2098"
    ),
    AccountSpec(
        "ACCT-0006", "CUST-0006", AccountType.CONSUMER_CREDIT_CARD, AccountStatus.SUSPENDED, date(2020, 8, 17), "7731"
    ),
    AccountSpec(
        "ACCT-0007", "CUST-0007", AccountType.BUSINESS_CREDIT_CARD, AccountStatus.ACTIVE, date(2021, 12, 5), "3364"
    ),
    AccountSpec(
        "ACCT-0008", "CUST-0008", AccountType.CONSUMER_CREDIT_CARD, AccountStatus.CLOSED, date(2017, 5, 23), "9915"
    ),
    AccountSpec(
        "ACCT-0009", "CUST-0009", AccountType.CONSUMER_CHARGE_CARD, AccountStatus.ACTIVE, date(2022, 2, 11), "5507"
    ),
    AccountSpec(
        "ACCT-0010", "CUST-0010", AccountType.CONSUMER_CREDIT_CARD, AccountStatus.ACTIVE, date(2024, 1, 19), "6273"
    ),
    AccountSpec(
        "ACCT-0011", "CUST-0001", AccountType.BUSINESS_CREDIT_CARD, AccountStatus.ACTIVE, date(2023, 9, 8), "4489"
    ),
    AccountSpec(
        "ACCT-0012", "CUST-0005", AccountType.CONSUMER_CREDIT_CARD, AccountStatus.ACTIVE, date(2020, 10, 27), "1120"
    ),
)

_BASE_MERCHANTS: tuple[MerchantSpec, ...] = (
    MerchantSpec("MERCH-0001", "Northwind Grocery Co", "grocery", "US", ("NORTHWIND GROCERY", "NW GROCERY")),
    MerchantSpec("MERCH-0002", "Riverbend Coffee Roasters", "dining", "US", ("RVRBND COFFEE", "RIVERBEND COFFEE")),
    MerchantSpec("MERCH-0003", "Halcyon Electronics", "electronics", "US", ("HALCYON ELEC", "HALCYON ELECTRONICS")),
    MerchantSpec("MERCH-0004", "Lumen Streaming", "digital_subscription", "US", ("LUMEN STREAM", "LUMENSTREAMING")),
    MerchantSpec("MERCH-0005", "Cascade Hotel Group", "lodging", "US", ("CASCADE HOTEL", "CASCADE HTL")),
    MerchantSpec("MERCH-0006", "Maison Verte Paris", "dining", "FR", ("MAISON VERTE", "MSN VERTE PARIS")),
    MerchantSpec("MERCH-0007", "Ironwood Hardware", "home_improvement", "US", ("IRONWOOD HDWR", "IRONWOOD HARDWARE")),
    MerchantSpec("MERCH-0008", "Solstice Fitness Club", "fitness", "US", ("SOLSTICE FIT", "SOLSTICE FITNESS")),
    MerchantSpec("MERCH-0009", "Bluepeak Airlines", "travel", "US", ("BLUEPEAK AIR", "BLUEPEAK AIRLINES")),
    MerchantSpec("MERCH-0010", "Corner Pharmacy Group", "pharmacy", "US", ("CORNER PHARMACY", "CORNER RX")),
    MerchantSpec("MERCH-0011", "Vantage Fuel Stop", "fuel", "US", ("VANTAGE FUEL", "VANTAGE FUEL STOP")),
    MerchantSpec("MERCH-0012", "Paperjam Bookshop", "retail", "US", ("PAPERJAM BOOKS", "PAPERJAM BOOKSHOP")),
    MerchantSpec("MERCH-0013", "Kestrel Rideshare", "transport", "US", ("KESTREL RIDE", "KESTREL RIDESHARE")),
    MerchantSpec("MERCH-0014", "Alpine Outfitters", "apparel", "CA", ("ALPINE OUTFIT", "ALPINE OUTFITTERS")),
    MerchantSpec("MERCH-0015", "Sable Cloud Services", "software", "IE", ("SABLE CLOUD", "SABLECLOUD")),
)

# The scenario account is reserved: random/interesting background never uses these
# merchants on ACCT-0001, so the deterministic scenarios cannot be disturbed.
SCENARIO_ACCOUNT = "ACCT-0001"
SCENARIO_MERCHANTS = frozenset(
    {"MERCH-0001", "MERCH-0002", "MERCH-0003", "MERCH-0004", "MERCH-0005", "MERCH-0006", "MERCH-0011"}
)
# Dates and USD amounts used by hand-written ACCT-0001 scenarios stay exclusive.
SCENARIO_DATES = frozenset(
    {
        date(2026, 4, 5),
        date(2026, 5, 5),
        date(2026, 6, 2),
        date(2026, 6, 5),
        date(2026, 6, 8),
        date(2026, 6, 12),
        date(2026, 6, 18),
        date(2026, 6, 20),
        date(2026, 6, 22),
        date(2026, 6, 28),
    }
)
SCENARIO_AMOUNT_MINOR = frozenset({675, 1599, 4810, 6420, 8999, 13247, 35000})

RECURRING_MERCHANTS = frozenset({"MERCH-0004", "MERCH-0015"})


@dataclass(frozen=True, slots=True)
class ScenarioTransaction:
    """A hand-written transaction backing one documented scenario."""

    transaction_id: str
    account_id: str
    merchant_id: str
    raw_descriptor: str
    amount: str
    currency: str
    transaction_date: date
    posted_date: date | None
    status: TransactionStatus
    card_present: bool
    recurring: bool
    scenario: str


SCENARIOS: tuple[ScenarioTransaction, ...] = (
    ScenarioTransaction(
        transaction_id="TXN-SCN-DUP-A",
        account_id=SCENARIO_ACCOUNT,
        merchant_id="MERCH-0003",
        raw_descriptor="HALCYON ELEC 0417 SEATTLE WA",
        amount="89.99",
        currency="USD",
        transaction_date=date(2026, 6, 12),
        posted_date=date(2026, 6, 14),
        status=TransactionStatus.POSTED,
        card_present=True,
        recurring=False,
        scenario="exact duplicate charge",
    ),
    ScenarioTransaction(
        transaction_id="TXN-SCN-DUP-B",
        account_id=SCENARIO_ACCOUNT,
        merchant_id="MERCH-0003",
        raw_descriptor="HALCYON ELEC 0417 SEATTLE WA",
        amount="89.99",
        currency="USD",
        transaction_date=date(2026, 6, 12),
        posted_date=date(2026, 6, 14),
        status=TransactionStatus.POSTED,
        card_present=True,
        recurring=False,
        scenario="exact duplicate charge",
    ),
    ScenarioTransaction(
        transaction_id="TXN-SCN-SUB-01",
        account_id=SCENARIO_ACCOUNT,
        merchant_id="MERCH-0004",
        raw_descriptor="LUMEN STREAM MONTHLY",
        amount="15.99",
        currency="USD",
        transaction_date=date(2026, 6, 5),
        posted_date=date(2026, 6, 6),
        status=TransactionStatus.POSTED,
        card_present=False,
        recurring=True,
        scenario="recurring subscription",
    ),
    ScenarioTransaction(
        transaction_id="TXN-SCN-SUB-02",
        account_id=SCENARIO_ACCOUNT,
        merchant_id="MERCH-0004",
        raw_descriptor="LUMEN STREAM MONTHLY",
        amount="15.99",
        currency="USD",
        transaction_date=date(2026, 5, 5),
        posted_date=date(2026, 5, 6),
        status=TransactionStatus.POSTED,
        card_present=False,
        recurring=True,
        scenario="recurring subscription",
    ),
    ScenarioTransaction(
        transaction_id="TXN-SCN-SUB-03",
        account_id=SCENARIO_ACCOUNT,
        merchant_id="MERCH-0004",
        raw_descriptor="LUMEN STREAM MONTHLY",
        amount="15.99",
        currency="USD",
        transaction_date=date(2026, 4, 5),
        posted_date=date(2026, 4, 6),
        status=TransactionStatus.POSTED,
        card_present=False,
        recurring=True,
        scenario="recurring subscription",
    ),
    ScenarioTransaction(
        transaction_id="TXN-SCN-DESC-01",
        account_id=SCENARIO_ACCOUNT,
        merchant_id="MERCH-0002",
        raw_descriptor="SQ *RVRBND COFFEE 8821 SEATTLE WA",
        amount="6.75",
        currency="USD",
        transaction_date=date(2026, 6, 18),
        posted_date=date(2026, 6, 19),
        status=TransactionStatus.POSTED,
        card_present=True,
        recurring=False,
        scenario="merchant descriptor differs from display name",
    ),
    ScenarioTransaction(
        transaction_id="TXN-SCN-HOLD-01",
        account_id=SCENARIO_ACCOUNT,
        merchant_id="MERCH-0005",
        raw_descriptor="CASCADE HOTEL 221 PORTLAND OR",
        amount="350.00",
        currency="USD",
        transaction_date=date(2026, 6, 20),
        posted_date=None,
        status=TransactionStatus.AUTHORIZATION_HOLD,
        card_present=True,
        recurring=False,
        scenario="hotel authorization hold",
    ),
    ScenarioTransaction(
        transaction_id="TXN-SCN-HOLD-02",
        account_id=SCENARIO_ACCOUNT,
        merchant_id="MERCH-0005",
        raw_descriptor="CASCADE HOTEL 221 PORTLAND OR",
        amount="350.00",
        currency="USD",
        transaction_date=date(2026, 6, 22),
        posted_date=date(2026, 6, 23),
        status=TransactionStatus.POSTED,
        card_present=True,
        recurring=False,
        scenario="hotel authorization hold settled",
    ),
    ScenarioTransaction(
        transaction_id="TXN-SCN-FX-01",
        account_id=SCENARIO_ACCOUNT,
        merchant_id="MERCH-0006",
        raw_descriptor="MAISON VERTE PARIS FR",
        amount="64.20",
        currency="EUR",
        transaction_date=date(2026, 6, 8),
        posted_date=date(2026, 6, 11),
        status=TransactionStatus.POSTED,
        card_present=True,
        recurring=False,
        scenario="foreign transaction",
    ),
    ScenarioTransaction(
        transaction_id="TXN-SCN-POSTED-01",
        account_id=SCENARIO_ACCOUNT,
        merchant_id="MERCH-0001",
        raw_descriptor="NORTHWIND GROCERY 118 SEATTLE WA",
        amount="132.47",
        currency="USD",
        transaction_date=date(2026, 6, 2),
        posted_date=date(2026, 6, 3),
        status=TransactionStatus.POSTED,
        card_present=True,
        recurring=False,
        scenario="posted transaction",
    ),
    ScenarioTransaction(
        transaction_id="TXN-SCN-PENDING-01",
        account_id=SCENARIO_ACCOUNT,
        merchant_id="MERCH-0011",
        raw_descriptor="VANTAGE FUEL 77 TACOMA WA",
        amount="48.10",
        currency="USD",
        transaction_date=date(2026, 6, 28),
        posted_date=None,
        status=TransactionStatus.PENDING,
        card_present=True,
        recurring=False,
        scenario="pending transaction",
    ),
    ScenarioTransaction(
        transaction_id="TXN-SCN-OTHER-01",
        account_id="ACCT-0002",
        merchant_id="MERCH-0003",
        raw_descriptor="HALCYON ELEC 0417 AUSTIN TX",
        amount="89.99",
        currency="USD",
        transaction_date=date(2026, 6, 12),
        posted_date=date(2026, 6, 14),
        status=TransactionStatus.POSTED,
        card_present=True,
        recurring=False,
        scenario="same charge on another account",
    ),
)


@dataclass(frozen=True, slots=True)
class SeedSummary:
    """Row counts produced by one generation run."""

    seed: int
    customers: int
    accounts: int
    merchants: int
    random_transactions: int
    interesting_transactions: int
    scenario_transactions: int

    @property
    def total_transactions(self) -> int:
        return self.random_transactions + self.interesting_transactions + self.scenario_transactions


def _abbreviate(name: str) -> str:
    """Build a short billing fragment from a display name."""
    tokens = [token for token in name.upper().replace("&", " ").split() if token.isalpha()]
    if len(tokens) >= 2:
        return f"{tokens[0][:6]} {tokens[1][:6]}"
    return (tokens[0] if tokens else "MERCHANT")[:12]


def _build_catalog() -> tuple[tuple[CustomerSpec, ...], tuple[AccountSpec, ...], tuple[MerchantSpec, ...]]:
    """Expand the hand-written base catalogue to the target volumes."""
    rng = random.Random(CATALOG_SEED)

    customers = list(_BASE_CUSTOMERS)
    used_names = {(spec.first_name, spec.last_name) for spec in customers}
    index = len(customers) + 1
    while len(customers) < TARGET_CUSTOMERS:
        first = rng.choice(FIRST_NAMES)
        last = rng.choice(LAST_NAMES)
        if (first, last) in used_names:
            continue
        used_names.add((first, last))
        customers.append(
            CustomerSpec(
                customer_id=f"CUST-{index:04d}",
                first_name=first,
                last_name=last,
                state=rng.choice(US_STATES),
            )
        )
        index += 1

    accounts = list(_BASE_ACCOUNTS)
    account_types = (
        AccountType.CONSUMER_CREDIT_CARD,
        AccountType.BUSINESS_CREDIT_CARD,
        AccountType.CONSUMER_CHARGE_CARD,
    )
    statuses = (
        AccountStatus.ACTIVE,
        AccountStatus.ACTIVE,
        AccountStatus.ACTIVE,
        AccountStatus.ACTIVE,
        AccountStatus.SUSPENDED,
        AccountStatus.CLOSED,
    )
    index = len(accounts) + 1
    customer_ids = [spec.customer_id for spec in customers]
    while len(accounts) < TARGET_ACCOUNTS:
        customer_id = customer_ids[(index - 1) % len(customer_ids)]
        open_date = date(2016, 1, 1) + timedelta(days=rng.randrange(0, 365 * 9))
        accounts.append(
            AccountSpec(
                account_id=f"ACCT-{index:04d}",
                customer_id=customer_id,
                account_type=rng.choice(account_types),
                account_status=rng.choice(statuses),
                open_date=open_date,
                card_suffix=f"{rng.randrange(0, 10000):04d}",
            )
        )
        index += 1

    merchants = list(_BASE_MERCHANTS)
    used_display = {spec.display_name for spec in merchants}
    index = len(merchants) + 1
    while len(merchants) < TARGET_MERCHANTS:
        prefix = rng.choice(MERCHANT_PREFIXES)
        suffix = rng.choice(MERCHANT_SUFFIXES)
        display = f"{prefix}{suffix} {rng.choice(('Co', 'Group', 'LLC', 'Inc', 'Shop'))}"
        if display in used_display:
            continue
        used_display.add(display)
        country = rng.choice(MERCHANT_COUNTRIES)
        short = _abbreviate(f"{prefix} {suffix}")
        long = f"{prefix.upper()} {suffix.upper()}"
        merchants.append(
            MerchantSpec(
                merchant_id=f"MERCH-{index:04d}",
                display_name=display,
                category=rng.choice(MERCHANT_CATEGORIES),
                country=country,
                descriptor_patterns=(short, long),
            )
        )
        index += 1

    return tuple(customers), tuple(accounts), tuple(merchants)


CUSTOMERS, ACCOUNTS, MERCHANTS = _build_catalog()


def _eligible_merchants(account_id: str, merchants: tuple[MerchantSpec, ...]) -> list[MerchantSpec]:
    """Merchants allowed on an account (scenario merchants protected on ACCT-0001)."""
    return [
        merchant
        for merchant in merchants
        if not (account_id == SCENARIO_ACCOUNT and merchant.merchant_id in SCENARIO_MERCHANTS)
    ]


def _build_descriptor(rng: random.Random, merchant: MerchantSpec, *, aggregator: bool = False) -> str:
    """Compose a plausible statement descriptor for a merchant."""
    pattern = rng.choice(merchant.descriptor_patterns)
    if merchant.country != "US":
        body = f"{pattern} {merchant.country}"
    else:
        city, state = rng.choice(CITIES)
        body = f"{pattern} {rng.randrange(100, 999)} {city} {state}"
    if aggregator:
        return f"SQ *{body}"
    return body


def _tx_row(
    *,
    transaction_id: str,
    account_id: str,
    merchant: MerchantSpec,
    raw_descriptor: str,
    amount_minor: int,
    transaction_date: date,
    posted_date: date | None,
    status: TransactionStatus,
    card_present: bool,
    recurring: bool,
) -> TransactionRow:
    return TransactionRow(
        transaction_id=transaction_id,
        account_id=account_id,
        merchant_id=merchant.merchant_id,
        raw_descriptor=raw_descriptor,
        amount_minor=amount_minor,
        currency=CURRENCY_BY_COUNTRY.get(merchant.country, "USD"),
        transaction_date=transaction_date,
        posted_date=posted_date,
        status=status.value,
        card_present=card_present,
        recurring=recurring,
    )


def _random_transaction_date(rng: random.Random, account_id: str) -> date:
    """Pick a history date, avoiding reserved scenario dates on ACCT-0001."""
    for _ in range(40):
        candidate = REFERENCE_DATE - timedelta(days=rng.randrange(1, RANDOM_HISTORY_DAYS))
        if account_id != SCENARIO_ACCOUNT or candidate not in SCENARIO_DATES:
            return candidate
    # Extremely unlikely; fall back off the reserved window.
    return REFERENCE_DATE - timedelta(days=RANDOM_HISTORY_DAYS)


def _random_amount_minor(rng: random.Random, account_id: str) -> int:
    """Pick an amount, avoiding reserved scenario amounts on ACCT-0001."""
    for _ in range(40):
        amount = rng.randrange(299, 45000)
        if account_id != SCENARIO_ACCOUNT or amount not in SCENARIO_AMOUNT_MINOR:
            return amount
    return 45123


def _pick_account_and_merchant(
    rng: random.Random,
    accounts: tuple[AccountSpec, ...],
    merchants: tuple[MerchantSpec, ...],
) -> tuple[str, MerchantSpec]:
    account_id = rng.choice([account.account_id for account in accounts])
    eligible = _eligible_merchants(account_id, merchants)
    return account_id, rng.choice(eligible)


def _interesting_transactions(
    rng: random.Random,
    accounts: tuple[AccountSpec, ...],
    merchants: tuple[MerchantSpec, ...],
) -> list[TransactionRow]:
    """Generate deliberately interesting cases: duplicates, holds, FX, etc."""
    rows: list[TransactionRow] = []
    counter = 1

    def next_id() -> str:
        nonlocal counter
        value = f"TXN-INT-{counter:04d}"
        counter += 1
        return value

    pattern_index = 0
    while len(rows) < INTERESTING_TRANSACTION_TARGET:
        account_id, merchant = _pick_account_and_merchant(rng, accounts, merchants)
        txn_date = _random_transaction_date(rng, account_id)
        # Keep hold settlements off reserved dates as well.
        if account_id == SCENARIO_ACCOUNT:
            while txn_date in SCENARIO_DATES or (txn_date + timedelta(days=2)) in SCENARIO_DATES:
                txn_date = _random_transaction_date(rng, account_id)
        amount_minor = _random_amount_minor(rng, account_id)
        if account_id == SCENARIO_ACCOUNT:
            amount_minor = rng.randrange(45_100, 90_000)
        descriptor = _build_descriptor(rng, merchant)
        pattern = pattern_index % 9
        pattern_index += 1
        batch: list[TransactionRow] = []

        if pattern == 0:
            for _ in range(2):
                batch.append(
                    _tx_row(
                        transaction_id=next_id(),
                        account_id=account_id,
                        merchant=merchant,
                        raw_descriptor=descriptor,
                        amount_minor=amount_minor,
                        transaction_date=txn_date,
                        posted_date=txn_date + timedelta(days=1),
                        status=TransactionStatus.POSTED,
                        card_present=True,
                        recurring=False,
                    )
                )
        elif pattern == 1:
            for offset in (0, rng.randrange(1, 3)):
                batch.append(
                    _tx_row(
                        transaction_id=next_id(),
                        account_id=account_id,
                        merchant=merchant,
                        raw_descriptor=descriptor,
                        amount_minor=amount_minor,
                        transaction_date=txn_date + timedelta(days=offset),
                        posted_date=txn_date + timedelta(days=offset + 1),
                        status=TransactionStatus.POSTED,
                        card_present=True,
                        recurring=False,
                    )
                )
        elif pattern == 2:
            for month_offset in (0, 1, 2):
                series_date = txn_date - timedelta(days=30 * month_offset)
                if account_id == SCENARIO_ACCOUNT and series_date in SCENARIO_DATES:
                    series_date = _random_transaction_date(rng, account_id)
                batch.append(
                    _tx_row(
                        transaction_id=next_id(),
                        account_id=account_id,
                        merchant=merchant,
                        raw_descriptor=f"{merchant.descriptor_patterns[0]} MONTHLY",
                        amount_minor=amount_minor,
                        transaction_date=series_date,
                        posted_date=series_date + timedelta(days=1),
                        status=TransactionStatus.POSTED,
                        card_present=False,
                        recurring=True,
                    )
                )
        elif pattern == 3:
            batch.append(
                _tx_row(
                    transaction_id=next_id(),
                    account_id=account_id,
                    merchant=merchant,
                    raw_descriptor=_build_descriptor(rng, merchant, aggregator=True),
                    amount_minor=amount_minor,
                    transaction_date=txn_date,
                    posted_date=txn_date + timedelta(days=1),
                    status=TransactionStatus.POSTED,
                    card_present=True,
                    recurring=False,
                )
            )
        elif pattern == 4:
            batch.append(
                _tx_row(
                    transaction_id=next_id(),
                    account_id=account_id,
                    merchant=merchant,
                    raw_descriptor=descriptor,
                    amount_minor=amount_minor,
                    transaction_date=txn_date,
                    posted_date=None,
                    status=TransactionStatus.AUTHORIZATION_HOLD,
                    card_present=True,
                    recurring=False,
                )
            )
            batch.append(
                _tx_row(
                    transaction_id=next_id(),
                    account_id=account_id,
                    merchant=merchant,
                    raw_descriptor=descriptor,
                    amount_minor=amount_minor,
                    transaction_date=txn_date + timedelta(days=2),
                    posted_date=txn_date + timedelta(days=3),
                    status=TransactionStatus.POSTED,
                    card_present=True,
                    recurring=False,
                )
            )
        elif pattern == 5:
            foreign = [item for item in _eligible_merchants(account_id, merchants) if item.country != "US"]
            fx_merchant = rng.choice(foreign) if foreign else merchant
            batch.append(
                _tx_row(
                    transaction_id=next_id(),
                    account_id=account_id,
                    merchant=fx_merchant,
                    raw_descriptor=_build_descriptor(rng, fx_merchant),
                    amount_minor=amount_minor,
                    transaction_date=txn_date,
                    posted_date=txn_date + timedelta(days=2),
                    status=TransactionStatus.POSTED,
                    card_present=True,
                    recurring=False,
                )
            )
        elif pattern == 6:
            batch.append(
                _tx_row(
                    transaction_id=next_id(),
                    account_id=account_id,
                    merchant=merchant,
                    raw_descriptor=descriptor,
                    amount_minor=amount_minor,
                    transaction_date=txn_date,
                    posted_date=None,
                    status=TransactionStatus.PENDING,
                    card_present=True,
                    recurring=False,
                )
            )
        elif pattern == 7:
            batch.append(
                _tx_row(
                    transaction_id=next_id(),
                    account_id=account_id,
                    merchant=merchant,
                    raw_descriptor=descriptor,
                    amount_minor=amount_minor,
                    transaction_date=txn_date,
                    posted_date=txn_date + timedelta(days=1),
                    status=TransactionStatus.REVERSED,
                    card_present=False,
                    recurring=False,
                )
            )
        else:
            for card_present in (True, False):
                batch.append(
                    _tx_row(
                        transaction_id=next_id(),
                        account_id=account_id,
                        merchant=merchant,
                        raw_descriptor=descriptor,
                        amount_minor=amount_minor,
                        transaction_date=txn_date,
                        posted_date=txn_date + timedelta(days=1),
                        status=TransactionStatus.POSTED,
                        card_present=card_present,
                        recurring=False,
                    )
                )

        if len(rows) + len(batch) > INTERESTING_TRANSACTION_MAX:
            break
        rows.extend(batch)

    return rows


def _random_transactions(
    rng: random.Random,
    accounts: tuple[AccountSpec, ...],
    merchants: tuple[MerchantSpec, ...],
) -> list[TransactionRow]:
    """Generate the ordinary background population."""
    rows: list[TransactionRow] = []
    account_ids = [account.account_id for account in accounts]

    for index in range(1, RANDOM_TRANSACTION_COUNT + 1):
        account_id = account_ids[(index - 1) % len(account_ids)]
        eligible = _eligible_merchants(account_id, merchants)
        merchant = rng.choice(eligible)

        transaction_date = _random_transaction_date(rng, account_id)
        is_pending = rng.random() < 0.12
        status = TransactionStatus.PENDING if is_pending else TransactionStatus.POSTED
        posted_date = None if is_pending else transaction_date + timedelta(days=rng.randrange(1, 4))

        rows.append(
            _tx_row(
                transaction_id=f"TXN-{index:04d}",
                account_id=account_id,
                merchant=merchant,
                raw_descriptor=_build_descriptor(rng, merchant),
                amount_minor=_random_amount_minor(rng, account_id),
                transaction_date=transaction_date,
                posted_date=posted_date,
                status=status,
                card_present=rng.random() < 0.6,
                recurring=merchant.merchant_id in RECURRING_MERCHANTS and rng.random() < 0.5,
            )
        )
    return rows


def _scenario_transactions() -> list[TransactionRow]:
    """Materialize the hand-written scenarios."""
    return [
        TransactionRow(
            transaction_id=scenario.transaction_id,
            account_id=scenario.account_id,
            merchant_id=scenario.merchant_id,
            raw_descriptor=scenario.raw_descriptor,
            amount_minor=to_minor_units(Decimal(scenario.amount)),
            currency=scenario.currency,
            transaction_date=scenario.transaction_date,
            posted_date=scenario.posted_date,
            status=scenario.status.value,
            card_present=scenario.card_present,
            recurring=scenario.recurring,
        )
        for scenario in SCENARIOS
    ]


def seed_database(engine: Engine, *, seed: int = DEFAULT_SEED) -> SeedSummary:
    """Drop, recreate and repopulate every table. Safe to run repeatedly."""
    rng = random.Random(seed)

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    customers = [
        CustomerRow(
            customer_id=spec.customer_id,
            first_name=spec.first_name,
            last_name=spec.last_name,
            state=spec.state,
        )
        for spec in CUSTOMERS
    ]
    accounts = [
        AccountRow(
            account_id=spec.account_id,
            customer_id=spec.customer_id,
            account_type=spec.account_type.value,
            account_status=spec.account_status.value,
            open_date=spec.open_date,
            card_last_four=spec.card_suffix,
        )
        for spec in ACCOUNTS
    ]
    merchant_rows = [
        MerchantRow(
            merchant_id=spec.merchant_id,
            display_name=spec.display_name,
            category=spec.category,
            country=spec.country,
            descriptor_patterns=list(spec.descriptor_patterns),
        )
        for spec in MERCHANTS
    ]

    random_rows = _random_transactions(rng, ACCOUNTS, MERCHANTS)
    interesting_rows = _interesting_transactions(rng, ACCOUNTS, MERCHANTS)
    scenario_rows = _scenario_transactions()

    with Session(engine) as session:
        session.add_all(customers)
        session.add_all(accounts)
        session.add_all(merchant_rows)
        session.add_all(random_rows)
        session.add_all(interesting_rows)
        session.add_all(scenario_rows)
        session.commit()

    return SeedSummary(
        seed=seed,
        customers=len(customers),
        accounts=len(accounts),
        merchants=len(merchant_rows),
        random_transactions=len(random_rows),
        interesting_transactions=len(interesting_rows),
        scenario_transactions=len(scenario_rows),
    )
