from datetime import datetime, timedelta


async def check_referral_reward(pool, user_id: int):

    data = await pool.fetchrow(
        """
        SELECT referral_count,
               ref_10_claimed,
               ref_20_claimed,
               ref_50_claimed
        FROM users
        WHERE user_id=$1
        """,
        user_id
    )

    if not data:
        return None

    total = data["referral_count"] or 0

    # Database uses naive TIMESTAMP; keep reward calculations naive too.
    now = datetime.now()

    reward_text = None

    # =========================
    # 10 REF
    # =========================
    if total >= 10 and not data["ref_10_claimed"]:

        vip_until = now + timedelta(days=1)

        await pool.execute(
            """
            UPDATE users
            SET vip=TRUE,
                is_vip=TRUE,
                vip_until=$1,
                vip_expired=$1,
                paid_quota = COALESCE(paid_quota,0) + 1,
                ref_10_claimed=TRUE
            WHERE user_id=$2
            """,
            vip_until,
            user_id
        )

        reward_text = "🎉 VIP 1 hari + 1 quota"

    # =========================
    # 20 REF
    # =========================
    elif total >= 20 and not data["ref_20_claimed"]:

        vip_until = now + timedelta(days=2)

        await pool.execute(
            """
            UPDATE users
            SET vip=TRUE,
                is_vip=TRUE,
                vip_until=$1,
                vip_expired=$1,
                paid_quota = COALESCE(paid_quota,0) + 3,
                ref_20_claimed=TRUE
            WHERE user_id=$2
            """,
            vip_until,
            user_id
        )

        reward_text = "🔥 VIP 2 hari + 3 quota"

    # =========================
    # 50 REF
    # =========================
    elif total >= 50 and not data["ref_50_claimed"]:

        vvip_until = now + timedelta(days=7)

        await pool.execute(
            """
            UPDATE users
            SET vvip=TRUE,
                is_vvip=TRUE,
                vip=TRUE,
                is_vip=TRUE,
                vvip_until=$1,
                vvip_expired=$1,
                ref_50_claimed=TRUE
            WHERE user_id=$2
            """,
            vvip_until,
            user_id
        )

        reward_text = "👑 VVIP 7 hari"

    return reward_text
