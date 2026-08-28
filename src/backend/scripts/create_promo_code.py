#!/usr/bin/env python
"""Mint or manage promo codes — the free-account path for account gating (see
app/api/routes/auth.py::register and docs/PAYMENT_PROCESSOR_SETUP.md). There's
no admin UI for this yet, so it's a script run against the same database as
the backend:

    docker compose exec backend python scripts/create_promo_code.py create BETA2026 --max-redemptions 50
    docker compose exec backend python scripts/create_promo_code.py create UNLIMITED-FRIENDS --note "friends & family"
    docker compose exec backend python scripts/create_promo_code.py list
    docker compose exec backend python scripts/create_promo_code.py deactivate BETA2026

(On a bare-metal/venv install, drop the `docker compose exec backend` prefix
and just run `python scripts/create_promo_code.py ...` from src/backend/.)
"""

import argparse
import asyncio
import secrets
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

sys.path.insert(0, ".")  # run from src/backend/

from app.db.session import AsyncSessionLocal  # noqa: E402
from app.db.models.promo_code import PromoCode  # noqa: E402


def _random_code() -> str:
    return secrets.token_hex(4).upper()  # e.g. "A1B2C3D4"


async def create(args: argparse.Namespace) -> None:
    code = (args.code or _random_code()).strip().upper()
    expires_at = None
    if args.expires_days:
        expires_at = datetime.now(timezone.utc) + timedelta(days=args.expires_days)

    async with AsyncSessionLocal() as db:
        existing = await db.execute(select(PromoCode).where(PromoCode.code == code))
        if existing.scalar_one_or_none():
            print(f"✗ Code '{code}' already exists.")
            return
        promo = PromoCode(
            code=code,
            max_redemptions=args.max_redemptions,
            expires_at=expires_at,
            note=args.note,
        )
        db.add(promo)
        await db.commit()
        print(f"✓ Created promo code: {code}")
        print(f"  max redemptions: {promo.max_redemptions or 'unlimited'}")
        print(f"  expires: {promo.expires_at or 'never'}")


async def list_codes(_: argparse.Namespace) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(PromoCode).order_by(PromoCode.created_at.desc()))
        codes = list(result.scalars().all())
        if not codes:
            print("No promo codes yet.")
            return
        for c in codes:
            state = "active" if c.is_redeemable() else ("inactive" if not c.active else "exhausted/expired")
            uses = f"{c.redemption_count}/{c.max_redemptions or '∞'}"
            print(f"  {c.code:<24} {state:<10} uses={uses:<10} note={c.note or ''}")


async def deactivate(args: argparse.Namespace) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(PromoCode).where(PromoCode.code == args.code.strip().upper()))
        promo = result.scalar_one_or_none()
        if not promo:
            print(f"✗ Code '{args.code}' not found.")
            return
        promo.active = False
        await db.commit()
        print(f"✓ Deactivated {promo.code}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create", help="Mint a new promo code")
    p_create.add_argument("code", nargs="?", help="Code text (default: random 8-char hex)")
    p_create.add_argument("--max-redemptions", type=int, default=None, help="Default: unlimited")
    p_create.add_argument("--expires-days", type=int, default=None, help="Default: never expires")
    p_create.add_argument("--note", default=None, help="Operator-facing label, e.g. 'beta testers'")
    p_create.set_defaults(func=create)

    p_list = sub.add_parser("list", help="List all promo codes")
    p_list.set_defaults(func=list_codes)

    p_deact = sub.add_parser("deactivate", help="Deactivate a code (stops future redemptions)")
    p_deact.add_argument("code")
    p_deact.set_defaults(func=deactivate)

    args = parser.parse_args()
    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
