from database import get_pool

async def can_open_media(user_id: int, file, paid_override: bool = False) -> tuple[bool, str]:
    """Canonical access gate shared by direct CODE, Open Page and Open All.

    Free codes: owner/VIP/creator can open without a point charge; ordinary
    users pay exactly 1 point per media, once per code.
    Paid codes: owner or an existing paid purchase / point unlock can open;
    payment itself is handled by the existing purchase flow.
    """
    uid = int(user_id)
    owner_id = int(file.get("owner_id") or 0)
    if owner_id == uid:
        return True, "owner"

    code = str(file.get("code") or "").strip()
    pool = await get_pool()
    is_paid = bool(file.get("is_paid"))

    if is_paid:
        if paid_override:
            return True, "paid"
        paid = await pool.fetchval(
            """SELECT EXISTS(SELECT 1 FROM file_purchases
               WHERE user_id=$1 AND (LOWER(TRIM(COALESCE(file_code,'')))=LOWER(TRIM($2))
               OR LOWER(TRIM(COALESCE(code,'')))=LOWER(TRIM($2))) AND status='paid')""",
            uid, code,
        )
        if paid:
            return True, "paid"
        unlocked = await pool.fetchval(
            "SELECT EXISTS(SELECT 1 FROM point_code_unlocks WHERE user_id=$1 AND LOWER(TRIM(code))=LOWER(TRIM($2)))",
            uid, code,
        )
        if unlocked:
            return True, "points"
        return False, "payment_required"

    # VIP/VVIP and approved Creator can open free codes without charging points.
    try:
        from utils.user import get_user_status
        level = await get_user_status(pool, uid)
    except Exception:
        level = "free"
    creator = False
    try:
        creator = bool(await pool.fetchval(
            """SELECT COALESCE(is_creator,FALSE) AND COALESCE(creator_status,'none')='approved'
               FROM users WHERE chat_id=$1 LIMIT 1""", uid
        ))
    except Exception:
        creator = False
    if level in ("vip", "vvip"):
        return True, "vip"
    if creator:
        return True, "creator"

    count = int(file.get("media_count") or 0)
    if count <= 0:
        raw = file.get("media") or []
        if isinstance(raw, str):
            import json
            try: raw = json.loads(raw)
            except Exception: raw = []
        count = len(raw) if isinstance(raw, list) else 0
    from utils.points import unlock_free_code
    ok, balance, charged = await unlock_free_code(pool, uid, code, count)
    if ok:
        return True, "points"
    return False, "points_required"

async def reward_owner_for_open(user_id: int, file) -> bool:
    """Give the code owner one reward point for the first successful open by a user."""
    uid = int(user_id)
    owner = int(file.get("owner_id") or 0)
    code = str(file.get("code") or "").strip()
    if not code or not owner or owner == uid:
        return False
    try:
        async with (await get_pool()).acquire() as conn:
            async with conn.transaction():
                inserted = await conn.fetchval(
                    """INSERT INTO code_share_events(code,owner_id,new_member_id)
                       VALUES($1,$2,$3)
                       ON CONFLICT(code,owner_id,new_member_id) DO NOTHING
                       RETURNING id""",
                    code, owner, uid,
                )
                if not inserted:
                    return False
                ref = f"share_open:{code.lower()}:{owner}:{uid}"
                await conn.fetchval(
                    "SELECT public.add_points($1,1,'share_open',$2,$3)",
                    owner, ref, f"Code {code} opened by {uid}",
                )
                return True
    except Exception:
        import logging
        logging.getLogger(__name__).exception("CODE OWNER REWARD ERROR | code=%s | owner=%s | opener=%s", code, owner, uid)
        return False
