import json
from datetime import datetime, timedelta

from utils.redis_client import safe_get, safe_set
from database import get_pool


def default_user():
    return {
        "level": "free",
        "expired_at": 0,
        "paid_quota": 0
    }


async def get_user_data(user_id:int):
    data = await safe_get(f"user:{user_id}")

    if not data:
        return default_user()

    if isinstance(data, bytes):
        data = data.decode()

    try:
        return json.loads(data)
    except Exception:
        return default_user()


async def save_user_data(user_id:int,data:dict):
    await safe_set(
        f"user:{user_id}",
        json.dumps(data)
    )


def fix_datetime(dt):
    if not dt:
        return None

    # postgres timestamp tanpa timezone
    # jadikan naive juga
    return dt.replace(tzinfo=None)



# =========================
# GET USER STATUS
# =========================
async def get_user_status(pool,user_id:int):

    user = await pool.fetchrow(
        """
        SELECT
            vip,
            vip_until,
            vvip,
            vvip_until,
            is_vip,
            vip_expired,
            is_vvip,
            vvip_expired
        FROM users
        WHERE user_id=$1
        """,
        user_id
    )

    if not user:
        return "free"


    now = datetime.utcnow()


    vip_until = fix_datetime(user["vip_until"])
    vvip_until = fix_datetime(user["vvip_until"])
    vip_expired = fix_datetime(user["vip_expired"])
    vvip_expired = fix_datetime(user["vvip_expired"])



    # =========================
    # VVIP
    # =========================

    if (
        user["is_vvip"] is True
        and vvip_expired
        and vvip_expired > now
    ):
        return "vvip"


    if (
        user["vvip"] is True 
        and vvip_until
        and vvip_until > now
    ):
        return "vvip"



    # =========================
    # VIP
    # =========================

    if (
        user["is_vip"] is True
        and vip_expired
        and vip_expired > now
    ):
        return "vip"


    if (
        user["vip"] is True
        and vip_until
        and vip_until > now
    ):
        return "vip"



    # expired reset

    await pool.execute(
        """
        UPDATE users
        SET
            vip=false,
            vvip=false,
            is_vip=false,
            is_vvip=false,
            plan='free'
        WHERE user_id=$1
        """,
        user_id
    )


    return "free"




# =========================
# SET VIP
# =========================

async def set_vip(user_id:int,days:int=30):

    pool = await get_pool()

    now = datetime.utcnow()


    user = await pool.fetchrow(
        """
        SELECT vip_until
        FROM users
        WHERE user_id=$1
        """,
        user_id
    )


    old = fix_datetime(
        user["vip_until"]
    ) if user else None


    if old and old > now:
        expired = old + timedelta(days=days)
    else:
        expired = now + timedelta(days=days)



    await pool.execute(
        """
        UPDATE users
        SET
            vip=true,
            is_vip=true,
            vip_until=$1,
            vip_expired=$1,
            plan='vip',
            expired_at=$1
        WHERE user_id=$2
        """,
        expired,
        user_id
    )


    return expired




# =========================
# SET VVIP
# =========================

async def set_vvip(user_id:int,days:int=7):

    pool = await get_pool()

    now = datetime.utcnow()


    user = await pool.fetchrow(
        """
        SELECT vvip_expired
        FROM users
        WHERE user_id=$1
        """,
        user_id
    )


    old = fix_datetime(
        user["vvip_expired"]
    ) if user else None



    if old and old > now:
        expired = old + timedelta(days=days)
    else:
        expired = now + timedelta(days=days)



    await pool.execute(
        """
        UPDATE users
        SET
            vvip=true,
            is_vvip=true,
            vvip_until=$1,
            vvip_expired=$1,

            vip=true,
            is_vip=true,
            vip_until=$1,
            vip_expired=$1,

            plan='vvip',
            expired_at=$1

        WHERE user_id=$2
        """,
        expired,
        user_id
    )


    return expired




# =========================
# SET FREE
# =========================

async def set_free(user_id:int):

    pool = await get_pool()

    await pool.execute(
        """
        UPDATE users
        SET
            vip=false,
            vvip=false,
            is_vip=false,
            is_vvip=false,
            vip_until=NULL,
            vvip_until=NULL,
            vip_expired=NULL,
            vvip_expired=NULL,
            plan='free',
            expired_at=NULL
        WHERE user_id=$1
        """,
        user_id
    )





# =========================
# CHECK
# =========================

async def is_vip(user_id:int):

    pool = await get_pool()

    status = await get_user_status(
        pool,
        user_id
    )

    return status in [
        "vip",
        "vvip"
    ]



async def is_vvip(user_id:int):

    pool = await get_pool()

    status = await get_user_status(
        pool,
        user_id
    )

    return status == "vvip"





# =========================
# QUOTA REDIS
# =========================

async def add_quota(user_id:int,amount:int):

    data = await get_user_data(user_id)

    data["paid_quota"] = data.get(
        "paid_quota",
        0
    ) + amount

    await save_user_data(
        user_id,
        data
    )



async def get_quota(user_id:int):

    data = await get_user_data(user_id)

    return data.get(
        "paid_quota",
        0
    )



async def use_quota(user_id:int):

    data = await get_user_data(user_id)

    quota = data.get(
        "paid_quota",
        0
    )

    if quota > 0:

        data["paid_quota"] = quota - 1

        await save_user_data(
            user_id,
            data
        )

        return True


    return False
