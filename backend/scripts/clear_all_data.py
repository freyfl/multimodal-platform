"""Explicit, non-interactive MySQL and Milvus record cleanup utility."""

from __future__ import annotations

import argparse
import asyncio
import inspect
import os
import ssl
import sys
from dataclasses import dataclass
from typing import Awaitable, Callable, Sequence


BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from app.config import Settings, settings
from app.errors import MissingConfigurationError


MYSQL = "mysql"
MILVUS = "milvus"
TARGET_ORDER = (MYSQL, MILVUS)


@dataclass(frozen=True)
class CleanupPlan:
    targets: tuple[str, ...]
    mysql_database: str | None
    milvus_database: str | None
    milvus_collection: str | None

    @property
    def confirmation(self) -> str:
        parts = []
        if MYSQL in self.targets:
            parts.append(f"mysql/{self.mysql_database}")
        if MILVUS in self.targets:
            parts.append(f"milvus/{self.milvus_database}/{self.milvus_collection}")
        return "DELETE:" + "+".join(parts)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Preview or delete records from explicitly named MySQL and Milvus "
            "targets. Collections and schemas are always retained."
        )
    )
    parser.add_argument(
        "--target",
        action="append",
        choices=TARGET_ORDER,
        help="Service to clean; repeat to select both services.",
    )
    parser.add_argument("--mysql-database", help="Exact configured MySQL database name.")
    parser.add_argument("--milvus-database", help="Exact configured Milvus database name.")
    parser.add_argument("--milvus-collection", help="Exact configured Milvus collection name.")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Perform record deletion. Without this flag, only the plan is printed.",
    )
    parser.add_argument(
        "--confirm",
        help="Target-bound confirmation string printed by the preview.",
    )
    return parser


def make_plan(args: argparse.Namespace) -> CleanupPlan:
    targets = tuple(target for target in TARGET_ORDER if target in set(args.target or ()))
    if not targets:
        raise ValueError("at least one explicit --target is required")
    if len(args.target or ()) != len(set(args.target or ())):
        raise ValueError("each --target may be selected only once")

    if MYSQL in targets and not args.mysql_database:
        raise ValueError("--mysql-database is required for target mysql")
    if MYSQL not in targets and args.mysql_database:
        raise ValueError("--mysql-database requires --target mysql")
    if MILVUS in targets and (not args.milvus_database or not args.milvus_collection):
        raise ValueError(
            "--milvus-database and --milvus-collection are required for target milvus"
        )
    if MILVUS not in targets and (args.milvus_database or args.milvus_collection):
        raise ValueError("Milvus target names require --target milvus")

    return CleanupPlan(
        targets=targets,
        mysql_database=args.mysql_database,
        milvus_database=args.milvus_database,
        milvus_collection=args.milvus_collection,
    )


def describe_plan(plan: CleanupPlan, output: Callable[[str], None] = print) -> None:
    output("Cleanup plan (records only):")
    if MYSQL in plan.targets:
        output(f"  mysql: database={plan.mysql_database}; all application tables")
    if MILVUS in plan.targets:
        output(
            "  milvus: "
            f"database={plan.milvus_database}; collection={plan.milvus_collection}; "
            "collection retained"
        )
    output(f"Required confirmation: {plan.confirmation}")


def validate_plan(plan: CleanupPlan, config: Settings) -> None:
    if MYSQL in plan.targets:
        config.require_config("mysql")
        if plan.mysql_database != config.MYSQL_DATABASE:
            raise ValueError("explicit MySQL database does not match configured target")
    if MILVUS in plan.targets:
        config.require_config("milvus")
        if (
            plan.milvus_database != config.MILVUS_DB_NAME
            or plan.milvus_collection != config.MILVUS_COLLECTION
        ):
            raise ValueError("explicit Milvus database or collection does not match configured target")


def _create_mysql_engine(config: Settings):
    from sqlalchemy.ext.asyncio import create_async_engine

    connect_args = {"connect_timeout": config.MYSQL_CONNECT_TIMEOUT}
    if config.MYSQL_SSL_ENABLED:
        connect_args["ssl"] = ssl.create_default_context(cafile=config.MYSQL_SSL_CA or None)
    return create_async_engine(
        config.mysql_url,
        echo=False,
        hide_parameters=True,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


async def clear_mysql_records(
    config: Settings,
    *,
    engine_factory: Callable[[Settings], object] = _create_mysql_engine,
) -> dict[str, int]:
    """Delete rows from every application table in one MySQL transaction."""
    from sqlalchemy import delete, func, select

    from app.models.database import Base
    import app.models.models  # noqa: F401 - registers all application tables

    engine = engine_factory(config)
    counts: dict[str, int] = {}
    try:
        async with engine.begin() as connection:
            for table in reversed(Base.metadata.sorted_tables):
                count = await connection.scalar(select(func.count()).select_from(table))
                counts[table.name] = int(count or 0)
                await connection.execute(delete(table))
    finally:
        await engine.dispose()
    return counts


def _create_milvus_client(config: Settings):
    from pymilvus import MilvusClient

    options = {
        "uri": config.MILVUS_URI,
        "db_name": config.MILVUS_DB_NAME,
        "timeout": config.MILVUS_TIMEOUT,
        "secure": config.MILVUS_SECURE,
    }
    if config.MILVUS_AUTH_ENABLED:
        if config.MILVUS_TOKEN:
            options["token"] = config.MILVUS_TOKEN
        else:
            options.update(user=config.MILVUS_USER, password=config.MILVUS_PASSWORD)
    if config.MILVUS_CA_CERT:
        options["ca_pem_path"] = config.MILVUS_CA_CERT
    if config.MILVUS_SERVER_NAME:
        options["server_name"] = config.MILVUS_SERVER_NAME
    return MilvusClient(**options)


def _milvus_count(client, config: Settings) -> int:
    response = client.query(
        collection_name=config.MILVUS_COLLECTION,
        filter="",
        output_fields=["count(*)"],
        consistency_level=config.MILVUS_CONSISTENCY_LEVEL,
        timeout=config.MILVUS_TIMEOUT,
    )
    if (
        not isinstance(response, list)
        or len(response) != 1
        or type(response[0].get("count(*)")) is not int
        or response[0]["count(*)"] < 0
    ):
        raise RuntimeError("invalid count response")
    return response[0]["count(*)"]


def clear_milvus_records(
    config: Settings,
    *,
    client_factory: Callable[[Settings], object] = _create_milvus_client,
) -> int:
    """Delete entities while retaining the explicitly selected collection."""
    client = client_factory(config)
    try:
        exists = client.has_collection(
            collection_name=config.MILVUS_COLLECTION,
            timeout=config.MILVUS_TIMEOUT,
        )
        if type(exists) is not bool:
            raise RuntimeError("invalid collection response")
        if not exists:
            return 0

        before = _milvus_count(client, config)
        response = client.delete(
            collection_name=config.MILVUS_COLLECTION,
            filter='media_id >= ""',
            timeout=config.MILVUS_TIMEOUT,
        )
        if not isinstance(response, (dict, list)):
            raise RuntimeError("invalid delete response")
        if _milvus_count(client, config) != 0:
            raise RuntimeError("records remain after deletion")
        return before
    finally:
        client.close()


async def _call_cleaner(cleaner, config: Settings):
    result = cleaner(config)
    if inspect.isawaitable(result):
        return await result
    return result


async def run(
    argv: Sequence[str] | None = None,
    *,
    config: Settings | None = None,
    output: Callable[[str], None] = print,
    mysql_cleaner: Callable[[Settings], Awaitable[dict[str, int]]] | None = None,
    milvus_cleaner: Callable[[Settings], int] | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    try:
        plan = make_plan(args)
    except ValueError as error:
        output(f"REFUSED: {error}")
        return 2

    describe_plan(plan, output)
    if not args.execute:
        output("DRY-RUN: no connection opened and no records deleted.")
        return 0
    if args.confirm != plan.confirmation:
        output("REFUSED: --confirm does not exactly match the target-bound confirmation.")
        return 2

    config = config or settings
    try:
        validate_plan(plan, config)
    except MissingConfigurationError as error:
        fields = ",".join(error.missing_fields) or "required fields"
        output(f"REFUSED: {error.service} configuration missing: {fields}")
        return 2
    except ValueError as error:
        output(f"REFUSED: {error}")
        return 2

    cleaners = {
        MYSQL: mysql_cleaner or clear_mysql_records,
        MILVUS: milvus_cleaner or clear_milvus_records,
    }
    failed = False
    for target in plan.targets:
        try:
            result = await _call_cleaner(cleaners[target], config)
            if target == MYSQL:
                total = sum(result.values())
                detail = ", ".join(f"{table}={count}" for table, count in result.items())
                output(f"RESULT mysql: deleted={total}; {detail or 'no application tables'}")
            else:
                output(
                    f"RESULT milvus: deleted={result}; "
                    f"collection={plan.milvus_collection}; collection_retained=true"
                )
        except Exception:
            failed = True
            output(f"RESULT {target}: failed; diagnostic details suppressed")
    return 1 if failed else 0


def main(argv: Sequence[str] | None = None) -> int:
    return asyncio.run(run(argv))


if __name__ == "__main__":
    raise SystemExit(main())
