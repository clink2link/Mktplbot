"""Atomic point economy for Mektpl."""
from __future__ import annotations
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional
from database import get_pool

CHECKIN_REWARDS = [
    Decimal("0.5"), Decimal("0.5"), Decimal("1"),
    Decimal("1"), Decimal("1.5"), Decimal("2"), Decimal("3")
]
MEDIA_COST = Decimal("1")
# Upload itself does NOT cost points. Reward is granted only for batches of 50 media.
UPLOAD_REWARD_PER_50 = Decimal("10")


def fmt_points(v) -> str:
    d=Decimal(str(v or 0)).quantize(Decimal("0.01"))
    return f"{d:,.2f}".rstrip("0").rstrip(".")

async def get_points(pool, user_id:int) -> Decimal:
    v=await pool.fetchval("SELECT COALESCE(points,0) FROM users WHERE user_id=$1", int(user_id))
    return Decimal(str(v or 0))

async def add_points(pool, user_id:int, amount, type_:str, reference:str, description:str=""):
    return await pool.fetchval("SELECT public.add_points($1,$2,$3,$4,$5)", int(user_id), Decimal(str(amount)), type_, reference, description)

async def charge_points(pool, user_id:int, amount, type_:str, reference:str, description:str=""):
    return await add_points(pool,user_id,-abs(Decimal(str(amount))),type_,reference,description)

async def checkin(pool,user_id:int):
    async with pool.acquire() as conn:
        async with conn.transaction():
            row=await conn.fetchrow("SELECT points,last_checkin_date,checkin_streak FROM users WHERE user_id=$1 FOR UPDATE",int(user_id))
            if not row: return None,"user_not_found"
            today=date.today()
            if row['last_checkin_date']==today: return Decimal(str(row['points'] or 0)),"already"
            streak=int(row['checkin_streak'] or 0)
            if row['last_checkin_date']==today-timedelta(days=1): streak=(streak%7)+1
            else: streak=1
            reward=CHECKIN_REWARDS[streak-1]
            new_balance=Decimal(str(row['points'] or 0))+reward
            await conn.execute("UPDATE users SET points=$1,last_checkin_date=$2,checkin_streak=$3,updated_at=NOW() WHERE user_id=$4",new_balance,today,streak,int(user_id))
            ref=f"checkin:{user_id}:{today.isoformat()}"
            await conn.execute("""INSERT INTO point_checkins(user_id,checkin_date,day_number,points) VALUES($1,$2,$3,$4) ON CONFLICT(user_id,checkin_date) DO NOTHING""",int(user_id),today,streak,reward)
            await conn.execute("""INSERT INTO point_transactions(user_id,amount,balance_after,type,reference,description) VALUES($1,$2,$3,'checkin',$4,$5) ON CONFLICT(reference) DO NOTHING""",int(user_id),reward,new_balance,ref,f"Daily check-in day {streak}")
            return new_balance,streak

async def charge_media(pool,user_id:int,count:int,code:str,offset:int=0):
    amount=(MEDIA_COST*Decimal(count)).quantize(Decimal("0.01"))
    ref=f"media:{user_id}:{code}:{offset}:{count}"
    return await charge_points(pool,user_id,amount,"media_open",ref,f"Open {count} media from {code}")


async def unlock_free_code(pool, user_id: int, code: str, media_count: int):
    """Unlock a free code exactly once. Charges 1 point per media.

    Returns (ok, balance, charged). Repeated opens of the same code by the
    same user are idempotent and do not charge again.
    """
    uid = int(user_id)
    count = max(0, int(media_count or 0))
    normalized = str(code or '').strip()
    if not normalized or count <= 0:
        return True, await get_points(pool, uid), Decimal('0')
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Lock the user row first. This serializes concurrent unlocks even
            # when the unique (user_id, lower(code)) row does not exist yet.
            row = await conn.fetchrow("SELECT points FROM users WHERE user_id=$1 FOR UPDATE", uid)
            if not row:
                return False, Decimal('0'), Decimal(count)
            existing = await conn.fetchval(
                "SELECT 1 FROM point_code_unlocks WHERE user_id=$1 AND LOWER(code)=LOWER($2) LIMIT 1",
                uid, normalized,
            )
            if existing:
                bal = Decimal(str(row['points'] or 0))
                return True, bal, Decimal('0')
            bal = Decimal(str(row['points'] or 0))
            cost = (MEDIA_COST * Decimal(count)).quantize(Decimal('0.01'))
            if bal < cost:
                return False, bal, cost
            new = bal - cost
            await conn.execute(
                "UPDATE users SET points=$1,updated_at=NOW() WHERE user_id=$2",
                new, uid,
            )
            await conn.execute(
                "INSERT INTO point_code_unlocks(user_id,code,amount) VALUES($1,$2,$3) ON CONFLICT DO NOTHING",
                uid, normalized, cost,
            )
            ref = f"media_unlock:{uid}:{normalized.lower()}"
            await conn.execute(
                """INSERT INTO point_transactions(user_id,amount,balance_after,type,reference,description)
                   VALUES($1,$2,$3,'media_open',$4,$5) ON CONFLICT(reference) DO NOTHING""",
                uid, -cost, new, ref, f"Open free code {normalized} ({count} media)",
            )
            return True, new, cost

async def unlock_paid_code_status(pool, user_id:int, code:str, price:int):
    """Atomically unlock a paid code.

    Returns ``(ok, balance, charged_this_request)``.  The user row is locked
    for the complete transaction, so concurrent requests cannot both charge
    the same code.  The charged flag is decided inside that same transaction;
    callers must never perform a separate pre-check to infer it.
    """
    uid = int(user_id)
    normalized = str(code or "").strip()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT points FROM users WHERE user_id=$1 FOR UPDATE", uid
            )
            if not row:
                return False, Decimal("0"), False

            existing = await conn.fetchval(
                "SELECT 1 FROM point_code_unlocks "
                "WHERE user_id=$1 AND LOWER(code)=LOWER($2) LIMIT 1",
                uid, normalized,
            )
            balance = Decimal(str(row["points"] or 0))
            if existing:
                return True, balance, False

            cost = Decimal(str(price or 0))
            if cost < 0:
                cost = Decimal("0")
            if balance < cost:
                return False, balance, False

            new_balance = balance - cost
            await conn.execute(
                "UPDATE users SET points=$1, updated_at=NOW() WHERE user_id=$2",
                new_balance, uid,
            )
            ref = f"paid_unlock:{uid}:{normalized.lower()}"
            await conn.execute(
                """INSERT INTO point_code_unlocks(user_id,code,amount)
                   VALUES($1,$2,$3) ON CONFLICT DO NOTHING""",
                uid, normalized, cost,
            )
            await conn.execute(
                """INSERT INTO point_transactions(
                       user_id,amount,balance_after,type,reference,description
                   )
                   VALUES($1,$2,$3,'paid_unlock',$4,$5)
                   ON CONFLICT(reference) DO NOTHING""",
                uid, -cost, new_balance, ref,
                f"Unlock paid code {normalized}",
            )
            return True, new_balance, True


async def unlock_paid_code(pool,user_id:int,code:str,price:int):
    """Backward-compatible wrapper returning the historic (ok, balance)."""
    ok, balance, _charged = await unlock_paid_code_status(
        pool, user_id, code, price
    )
    return ok, balance

async def rollback_code_unlock(pool, user_id: int, code: str):
    """Atomically undo a newly-created code unlock.

    Used when media was prepared successfully but Telegram delivery failed.
    If the code was already unlocked before this request, nothing is changed.
    Returns (rolled_back, amount).
    """
    uid = int(user_id)
    normalized = str(code or '').strip()
    if not normalized:
        return False, Decimal('0')
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT points FROM users WHERE user_id=$1 FOR UPDATE", uid
            )
            if not row:
                return False, Decimal('0')
            unlock = await conn.fetchrow(
                "SELECT amount FROM point_code_unlocks WHERE user_id=$1 AND LOWER(code)=LOWER($2) LIMIT 1",
                uid, normalized,
            )
            if not unlock:
                return False, Decimal('0')
            amount = Decimal(str(unlock['amount'] or 0))
            if amount <= 0:
                return False, Decimal('0')
            deleted = await conn.execute(
                "DELETE FROM point_code_unlocks WHERE user_id=$1 AND LOWER(code)=LOWER($2)",
                uid, normalized,
            )
            if not deleted.endswith('1'):
                return False, Decimal('0')
            new_balance = Decimal(str(row['points'] or 0)) + amount
            await conn.execute(
                "UPDATE users SET points=$1, updated_at=NOW() WHERE user_id=$2",
                new_balance, uid,
            )
            ref = f"unlock_rollback:{uid}:{normalized.lower()}"
            await conn.execute(
                """INSERT INTO point_transactions(user_id,amount,balance_after,type,reference,description)
                   VALUES($1,$2,$3,'media_refund',$4,$5) ON CONFLICT(reference) DO NOTHING""",
                uid, amount, new_balance, ref,
                f"Refund failed media delivery for {normalized}",
            )
            return True, amount


async def charge_upload(pool,user_id:int,count:int,code:str):
    """Upload reward only: no upload cost.

    Reward is +10 points for every completed block of 50 media.
    Examples: 1-49 => 0, 50-99 => 10, 100 => 20.
    """
    blocks = int(count) // 50
    reward = (Decimal(blocks) * UPLOAD_REWARD_PER_50).quantize(Decimal("0.01"))
    if reward <= 0:
        return True, await get_points(pool, user_id), Decimal("0")
    async with pool.acquire() as conn:
        async with conn.transaction():
            row=await conn.fetchrow("SELECT points FROM users WHERE user_id=$1 FOR UPDATE",int(user_id))
            if not row:
                return False,Decimal("0"),reward
            bal=Decimal(str(row['points'] or 0))
            new=bal+reward
            await conn.execute("UPDATE users SET points=$1,updated_at=NOW() WHERE user_id=$2",new,int(user_id))
            ref=f"upload_reward:{user_id}:{code}"
            await conn.execute(
                """INSERT INTO point_transactions(user_id,amount,balance_after,type,reference,description)
                   VALUES($1,$2,$3,'upload_reward',$4,$5)
                   ON CONFLICT(reference) DO NOTHING""",
                int(user_id),reward,new,ref,
                f"Upload reward: {blocks} x 50 media = +{fmt_points(reward)} points"
            )
            return True,new,reward

async def can_afford(pool,user_id:int,required): return (await get_points(pool,user_id)) >= Decimal(str(required))
