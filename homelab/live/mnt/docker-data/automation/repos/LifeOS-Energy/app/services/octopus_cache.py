from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable, Mapping
from typing import Any

ACCOUNT_CACHE_TTL_SECONDS = 6 * 60 * 60
PRICE_CACHE_TTL_SECONDS = 24 * 60 * 60


def initialise(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS octopus_import_tariff_cache (
            cache_key TEXT PRIMARY KEY,
            tariff_code TEXT NOT NULL,
            fetched_at INTEGER NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS octopus_tariff_price_cache (
            tariff_code TEXT NOT NULL,
            valid_from INTEGER NOT NULL,
            rate_p_per_kwh REAL NOT NULL,
            fetched_at INTEGER NOT NULL,
            PRIMARY KEY (tariff_code, valid_from)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_octopus_tariff_price_valid_from "
        "ON octopus_tariff_price_cache(valid_from)"
    )


def import_tariff_code(
    connection: sqlite3.Connection,
    *,
    now: int,
    fetch_tariff_code: Callable[[], str],
) -> tuple[str, str, int]:
    row = connection.execute(
        "SELECT tariff_code, fetched_at FROM octopus_import_tariff_cache "
        "WHERE cache_key = 'import'"
    ).fetchone()
    cached_code = str(row[0]) if row else None
    cached_at = int(row[1]) if row else None
    if cached_code and cached_at is not None and now - cached_at < ACCOUNT_CACHE_TTL_SECONDS:
        return cached_code, "cached", max(0, now - cached_at)

    try:
        tariff_code = str(fetch_tariff_code()).strip()
        if not tariff_code:
            raise ValueError("empty import tariff code")
    except Exception:
        if cached_code and cached_at is not None:
            return cached_code, "stale_cache", max(0, now - cached_at)
        raise

    connection.execute(
        """
        INSERT INTO octopus_import_tariff_cache(cache_key, tariff_code, fetched_at)
        VALUES ('import', ?, ?)
        ON CONFLICT(cache_key) DO UPDATE SET
            tariff_code=excluded.tariff_code,
            fetched_at=excluded.fetched_at
        """,
        (tariff_code, now),
    )
    connection.commit()
    return tariff_code, "fresh", 0


def tariff_rates(
    connection: sqlite3.Connection,
    tariff_code: str,
    timestamps: Iterable[int],
    *,
    now: int,
    fetch_rates: Callable[[], Mapping[int, float]],
) -> tuple[dict[int, float], str, int | None, bool]:
    requested = sorted({int(stamp) for stamp in timestamps})
    if not requested:
        return {}, "unavailable", None, False

    rows = connection.execute(
        """
        SELECT valid_from, rate_p_per_kwh, fetched_at
        FROM octopus_tariff_price_cache
        WHERE tariff_code = ? AND valid_from >= ? AND valid_from <= ?
        """,
        (tariff_code, requested[0], requested[-1]),
    ).fetchall()
    cached = {int(row[0]): (float(row[1]), int(row[2])) for row in rows}
    requested_cached = {stamp: cached[stamp] for stamp in requested if stamp in cached}
    fresh = all(
        stamp in requested_cached
        and now - requested_cached[stamp][1] < PRICE_CACHE_TTL_SECONDS
        for stamp in requested
    )
    if fresh:
        rates = {stamp: item[0] for stamp, item in requested_cached.items()}
        age = max((max(0, now - item[1]) for item in requested_cached.values()), default=None)
        return rates, "cached", age, False

    fetch_failed = False
    try:
        fetched = {
            int(stamp): float(rate)
            for stamp, rate in fetch_rates().items()
            if rate is not None
        }
    except Exception:
        fetched = {}
        fetch_failed = True

    if fetched:
        connection.executemany(
            """
            INSERT INTO octopus_tariff_price_cache(
                tariff_code, valid_from, rate_p_per_kwh, fetched_at
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(tariff_code, valid_from) DO UPDATE SET
                rate_p_per_kwh=excluded.rate_p_per_kwh,
                fetched_at=excluded.fetched_at
            """,
            [
                (tariff_code, stamp, rate, now)
                for stamp, rate in fetched.items()
            ],
        )
        connection.commit()

    merged = dict(requested_cached)
    for stamp, rate in fetched.items():
        if stamp in requested:
            merged[stamp] = (rate, now)
    rates = {stamp: item[0] for stamp, item in merged.items()}
    age = max((max(0, now - item[1]) for item in merged.values()), default=None)

    if fetch_failed:
        status = "stale_cache" if rates else "unavailable"
    elif all(stamp in merged for stamp in requested):
        status = "fresh"
    else:
        status = "partial"
    return rates, status, age, fetch_failed
