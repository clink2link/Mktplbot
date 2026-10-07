"""Code sharing only. Sharing never unlocks or rewards by itself."""
from urllib.parse import quote
from database import get_pool

def share_payload(code:str, sharer_id:int)->str:
    return f"s_{int(sharer_id)}_{code}"

def share_url(bot_username:str, code:str, sharer_id:int, title:str="") -> str:
    username=(bot_username or "").lstrip("@")
    deep=f"https://t.me/{username}?start={share_payload(code,sharer_id)}"
    text=f"📦 {title or 'Code Telegram'}\n\nBuka code melalui bot."
    return f"https://t.me/share/url?url={quote(deep)}&text={quote(text)}"

def required_shares(*args,**kwargs): return 0
async def ensure_share_progress(*args,**kwargs): return None
async def get_share_status(*args,**kwargs): return 0,0,True
async def gate_message(*args,**kwargs): return "",None
async def telegram_setting(key, default=None):
    try:
        pool=await get_pool(); v=await pool.fetchval("SELECT value FROM settings WHERE key=$1",key)
        return default if v is None else v
    except Exception: return default

async def record_new_member_open(pool, code, owner_id, opener_id, *, media_count=0, is_paid=False):
    if int(owner_id)==int(opener_id): return False
    ref=f"share_open:{code.lower()}:{owner_id}:{opener_id}"
    async with pool.acquire() as conn:
        async with conn.transaction():
            inserted=await conn.fetchval("""INSERT INTO code_share_events(code,owner_id,new_member_id) VALUES($1,$2,$3) ON CONFLICT(code,owner_id,new_member_id) DO NOTHING RETURNING id""",code,int(owner_id),int(opener_id))
            if not inserted: return False
            try:
                await conn.fetchval("SELECT public.add_points($1,1,'share_open',$2,$3)",int(owner_id),ref,f"Shared code opened by {opener_id}")
            except Exception:
                raise
    return True
