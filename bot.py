import os
import discord
import asyncio
import random
import base64
import json
import logging
from pathlib import Path
from discord.ext import commands
from cryptography.fernet import Fernet

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("apocalypse-bot")

# ENV
TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID")  # string, convert later if present
ASSETS_DIR = Path("assets")
MESSAGES_FILE = "messages.json"
KEY_FILE = Path("fernet.key")
STATE_FILE = Path("state.json")

# Fernet key (persistent)
if KEY_FILE.exists():
    KEY = KEY_FILE.read_bytes()
else:
    KEY = Fernet.generate_key()
    KEY_FILE.write_bytes(KEY)
FERNET = Fernet(KEY)

# Intents & Bot
intents = discord.Intents.all()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Load messages
def load_messages():
    if not Path(MESSAGES_FILE).exists():
        return ["o mundo está em silêncio."]
    with open(MESSAGES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("messages", [])

MESSAGES = load_messages()

# Helpers (ciphers)
def to_binary(s: str) -> str:
    return " ".join(format(ord(c), "08b") for c in s)

def to_hex(s: str) -> str:
    return s.encode().hex()

def rot13(s: str) -> str:
    return s.translate(str.maketrans(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
        "NOPQRSTUVWXYZABCDEFGHIJKLMnopqrstuvwxyzabcdefghijklm"))

def apply_cipher(s: str) -> str:
    c = random.choice(["plain","base64","b64url","binary","hex","rot13","fernet","mixed"])
    if c == "plain":
        return s
    if c == "base64":
        return "BASE64: " + base64.b64encode(s.encode()).decode()
    if c == "b64url":
        return "B64URL: " + base64.urlsafe_b64encode(s.encode()).decode()
    if c == "binary":
        return "BINARY: " + to_binary(s)
    if c == "hex":
        return "HEX: " + to_hex(s)
    if c == "rot13":
        return "ROT13: " + rot13(s)
    if c == "fernet":
        return "FERNET: " + FERNET.encrypt(s.encode()).decode()
    if c == "mixed":
        half = s[:len(s)//2]
        return "MIXED: " + base64.b64encode((half + "..." ).encode()).decode()
    return s

# Utilities
def list_assets():
    if not ASSETS_DIR.exists():
        return []
    return [p for p in ASSETS_DIR.iterdir() if p.suffix.lower() in [".png",".jpg",".jpeg",".gif",".webp",".mp3",".wav"]]

# ---------------- State persistence and interval control ----------------
DEFAULT_INTERVALS = {
    "min_normal": 600,   # 10 min
    "max_normal": 7200,  # 2 h
    "min_apoc": 300,     # 5 min
    "max_apoc": 3600     # 1 h
}

def load_state_file() -> dict:
    if not STATE_FILE.exists():
        st = {"apocalypse": False, "enabled": True, "intervals": DEFAULT_INTERVALS.copy()}
        STATE_FILE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
        return st
    try:
        st = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        st = {"apocalypse": False, "enabled": True, "intervals": DEFAULT_INTERVALS.copy()}
    # normalize
    st.setdefault("intervals", DEFAULT_INTERVALS.copy())
    for k,v in DEFAULT_INTERVALS.items():
        st["intervals"].setdefault(k, v)
    st.setdefault("apocalypse", False)
    st.setdefault("enabled", True)
    return st

def save_state_file(st: dict):
    STATE_FILE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")

# global STATE loaded from file
STATE = load_state_file()

def compute_wait_seconds() -> int:
    intervals = STATE.get("intervals", DEFAULT_INTERVALS)
    if STATE.get("apocalypse", False):
        a = int(intervals.get("min_apoc", DEFAULT_INTERVALS["min_apoc"]))
        b = int(intervals.get("max_apoc", DEFAULT_INTERVALS["max_apoc"]))
    else:
        a = int(intervals.get("min_normal", DEFAULT_INTERVALS["min_normal"]))
        b = int(intervals.get("max_normal", DEFAULT_INTERVALS["max_normal"]))
    if a <= 0:
        a = 1
    if b < a:
        b = a
    return random.randint(a, b)

# ---------------- Avatar / nickname helper ----------------
async def set_own_nick_and_avatar(apocalypse_on: bool):
    try:
        avatar_path = None
        assets = list_assets()
        for p in assets:
            if p.name.startswith("avatar"):
                avatar_path = p
                break
        if avatar_path and apocalypse_on:
            try:
                b = avatar_path.read_bytes()
                await bot.user.edit(avatar=b)
            except Exception as e:
                logger.debug(f"Não foi possível alterar avatar: {e}")
        # change nickname only for bot's member in guilds
        for guild in bot.guilds:
            try:
                me = guild.get_member(bot.user.id)
                if not me:
                    continue
                if apocalypse_on:
                    nick = random.choice(["TRANSMISSÃO CORROMPIDA", "ELE_VEM", "SINAL_PERDIDO"])
                    await me.edit(nick=nick)
                else:
                    await me.edit(nick=None)
            except Exception as e:
                logger.debug(f"Não foi possível editar nickname em guild {guild.name}: {e}")
    except Exception as e:
        logger.exception("Erro ao mudar avatar/nick: %s", e)

# ---------------- Main message loop ----------------
async def message_loop():
    await bot.wait_until_ready()
    channel = None
    if CHANNEL_ID:
        try:
            channel = bot.get_channel(int(CHANNEL_ID))
        except Exception:
            logger.error("DISCORD_CHANNEL_ID inválido.")
    assets = list_assets()
    logger.info(f"Assets carregados: {[p.name for p in assets]}")
    while True:
        try:
            if not STATE.get("enabled", True):
                await asyncio.sleep(10)
                continue

            base = random.choice(MESSAGES)
            payload = apply_cipher(base)

            # apocalypse special (rare)
            if STATE.get("apocalypse", False) and random.random() < 0.08:
                if channel:
                    try:
                        async for m in channel.history(limit=30):
                            if m.author.id == bot.user.id:
                                await m.delete()
                                break
                    except Exception as e:
                        logger.debug("Erro ao buscar/remover mensagens próprias: %s", e)
                payload = apply_cipher("ISTO NÃO ERA PARA EXISTIR")
                if channel:
                    try:
                        await channel.send(payload)
                    except Exception as e:
                        logger.debug("Erro ao enviar payload apocalipse: %s", e)
            else:
                if channel:
                    r = random.random()
                    if assets and r < 0.45:
                        asset = random.choice(assets)
                        try:
                            if asset.suffix.lower() in [".mp3",".wav"]:
                                await channel.send(payload, file=discord.File(asset))
                            else:
                                await channel.send(payload, file=discord.File(asset))
                        except discord.Forbidden:
                            logger.error("Missing Permissions to send attachments in the channel.")
                        except Exception as e:
                            logger.exception("Erro ao enviar attachment: %s", e)
                    else:
                        try:
                            await channel.send(payload)
                        except discord.Forbidden:
                            logger.error("Missing Permissions to send messages in the channel.")
                        except Exception as e:
                            logger.exception("Erro ao enviar mensagem: %s", e)

            # small chance to trigger 'apagon' offline period
            if STATE.get("apocalypse", False) and random.random() < 0.01:
                logger.warning("APAGÃO: going offline for 66s")
                await bot.close()
                await asyncio.sleep(66)

            # use persisted intervals
            wait = compute_wait_seconds()
            logger.info(f"Próxima mensagem em {wait} segundos (apocalypse={STATE.get('apocalypse')}).")
            await asyncio.sleep(wait)
        except Exception as e:
            logger.exception("Erro no loop de mensagens: %s", e)
            await asyncio.sleep(10)

# ---------------- Triggers and commands ----------------
@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    lc = message.content.lower()

    # detect midnight speakers for log
    if 0 <= message.created_at.hour <= 4:
        try:
            with open("night_log.txt", "a", encoding="utf-8") as f:
                f.write(f"{message.created_at.isoformat()} - {message.author} - {message.content}\n")
        except:
            pass

    # emergency triggers
    triggers = ["ele", "medo", "olhos", "onde você está", "estou com medo", "socorro"]
    if any(t in lc for t in triggers):
        STATE["apocalypse"] = True
        save_state_file(STATE)
        await set_own_nick_and_avatar(True)
        reply = apply_cipher("O DIA DA TRANSMISSÃO ESTÁ PRÓXIMO.")
        try:
            await message.channel.send(reply)
        except Exception:
            pass

    # PROCESS COMMANDS (important)
    await bot.process_commands(message)

# admin-only check
def is_admin():
    async def pred(ctx):
        return ctx.author.guild_permissions.administrator
    return commands.check(pred)

# --- ADMIN COMMANDS ---
@bot.command(name="alerta")
@is_admin()
async def cmd_alerta(ctx):
    STATE["apocalypse"] = True
    save_state_file(STATE)
    await set_own_nick_and_avatar(True)
    await ctx.send(apply_cipher("ALERTA ATIVADO: TRANSMISSÃO CORROMPIDA"))

@bot.command(name="silencio")
@is_admin()
async def cmd_silencio(ctx):
    STATE["apocalypse"] = False
    save_state_file(STATE)
    await set_own_nick_and_avatar(False)
    await ctx.send(apply_cipher("SILÊNCIO RESTAURADO."))

@bot.command(name="corromper")
@is_admin()
async def cmd_corromper(ctx, member: discord.Member = None):
    target = member or ctx.author
    items = []
    async for m in ctx.channel.history(limit=50):
        if m.author.id == target.id:
            items.append(m.content)
            if len(items) >= 5:
                break
    if not items:
        await ctx.send(apply_cipher("Nenhuma mensagem encontrada para corromper."))
        return
    for it in items:
        await ctx.send(apply_cipher(it))
    await ctx.send(apply_cipher(f"CORRUPÇÃO COMPLETA: {target.display_name}"))

@bot.command(name="interferencia")
@is_admin()
async def cmd_interferencia(ctx):
    assets = list_assets()
    if not assets:
        await ctx.send(apply_cipher("Nenhuma imagem disponível."))
        return
    a = random.choice(assets)
    await ctx.send(apply_cipher("INTERFERÊNCIA..."), file=discord.File(a))

@bot.command(name="statusx")
@is_admin()
async def cmd_statusx(ctx):
    await ctx.send(apply_cipher(f"APOCALYPSE: {STATE.get('apocalypse',False)} - ENABLED: {STATE.get('enabled',True)}"))

@bot.command(name="sendnow")
@is_admin()
async def cmd_sendnow(ctx):
    msg = random.choice(MESSAGES)
    await ctx.send(apply_cipher(msg))

# ------------- Avatar commands -------------
@bot.command(name="avatar")
@is_admin()
async def cmd_avatar(ctx, *, asset_name: str = None):
    """
    Use: !avatar avatar_glitch.png
    If asset_name omitted, lists candidate avatar files in assets/.
    """
    assets = list_assets()
    avatar_files = [p.name for p in assets if p.name.startswith("avatar")]
    if not asset_name:
        if not avatar_files:
            await ctx.send(apply_cipher("Nenhum arquivo de avatar disponível. Coloque arquivos em assets/ com prefixo 'avatar'."))
            return
        await ctx.send(apply_cipher("Avatares disponíveis: " + ", ".join(avatar_files)))
        return
    # find file
    path = ASSETS_DIR / asset_name
    if not path.exists():
        await ctx.send(apply_cipher("Arquivo não encontrado em assets/: " + asset_name))
        return
    try:
        b = path.read_bytes()
        await bot.user.edit(avatar=b)
        await ctx.send(apply_cipher("Avatar alterado."))
    except discord.Forbidden:
        await ctx.send(apply_cipher("Sem permissão para alterar avatar. Verifique token / permissões."))
    except Exception as e:
        await ctx.send(apply_cipher("Erro ao alterar avatar: " + str(e)))

@bot.command(name="cycleavatar")
@is_admin()
async def cmd_cycleavatar(ctx):
    assets = list_assets()
    avatar_candidates = [p for p in assets if p.name.startswith("avatar")]
    if not avatar_candidates:
        await ctx.send(apply_cipher("Nenhum avatar encontrado em assets/."))
        return
    chosen = random.choice(avatar_candidates)
    try:
        await bot.user.edit(avatar=chosen.read_bytes())
        await ctx.send(apply_cipher(f"Avatar trocado para {chosen.name}"))
    except Exception as e:
        await ctx.send(apply_cipher("Erro ao trocar avatar: " + str(e)))

# ------------- Interval commands -------------
@bot.command(name="setinterval")
@is_admin()
async def cmd_setinterval(ctx, mode: str, min_s: int, max_s: int):
    """
    Uso: !setinterval normal 60000 300000
    mode: normal | apoc
    """
    mode = mode.lower()
    if min_s <= 0 or max_s <= 0 or max_s < min_s:
        return await ctx.send(apply_cipher("Intervalos inválidos. min > 0 e max >= min."))

    st = load_state_file()
    if mode == "normal":
        st["intervals"]["min_normal"] = min_s
        st["intervals"]["max_normal"] = max_s
    elif mode in ("apoc","apocalypse"):
        st["intervals"]["min_apoc"] = min_s
        st["intervals"]["max_apoc"] = max_s
    else:
        return await ctx.send(apply_cipher("Modo inválido. Use 'normal' ou 'apoc'."))

    save_state_file(st)
    global STATE
    STATE = st
    await ctx.send(apply_cipher(f"Intervalos atualizados: {mode} - {min_s}s a {max_s}s"))

@bot.command(name="getinterval")
@is_admin()
async def cmd_getinterval(ctx):
    st = load_state_file()
    ints = st.get("intervals", DEFAULT_INTERVALS)
    await ctx.send(apply_cipher(
        f"Normal: {ints['min_normal']}s - {ints['max_normal']}s\n"
        f"Apocalypse: {ints['min_apoc']}s - {ints['max_apoc']}s"
    ))

# ---------------- Boot hooks ----------------
@bot.event
async def setup_hook():
    asyncio.create_task(message_loop())

@bot.event
async def on_ready():
    logger.info(f"Bot online: {bot.user} (apocalypse={STATE.get('apocalypse')})")

# ---------------- Safety checks & start ----------------
if not TOKEN or not CHANNEL_ID:
    logger.critical("DISCORD_TOKEN or DISCORD_CHANNEL_ID not set. Set environment variables before running.")
else:
    bot.run(TOKEN)
