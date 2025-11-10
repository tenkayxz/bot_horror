
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

TOKEN = os.getenv("DISCORD_TOKEN")
CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID")  # should be numeric string
ASSETS_DIR = Path("assets")
MESSAGES_FILE = "messages.json"

# generate or load a persistent key file for Fernet in repo (if exists)
KEY_FILE = Path("fernet.key")
if KEY_FILE.exists():
    KEY = KEY_FILE.read_bytes()
else:
    KEY = Fernet.generate_key()
    KEY_FILE.write_bytes(KEY)
FERNET = Fernet(KEY)

intents = discord.Intents.all()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# load messages
def load_messages():
    if not Path(MESSAGES_FILE).exists():
        return ["o mundo está em silêncio."]
    with open(MESSAGES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("messages", [])

MESSAGES = load_messages()

# helper ciphers
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
        # partial obfuscation + base64
        half = s[:len(s)//2]
        return "MIXED: " + base64.b64encode((half + "..." ).encode()).decode()
    return s

# state
STATE = {"apocalypse": False, "enabled": True}

# utilities
def list_assets():
    if not ASSETS_DIR.exists():
        return []
    return [p for p in ASSETS_DIR.iterdir() if p.suffix.lower() in [".png",".jpg",".jpeg",".gif",".webp",".mp3",".wav"]]

async def set_own_nick_and_avatar(apocalypse_on: bool):
    # change nickname in all guilds to an ominous name and avatar if assets exist
    try:
        avatar_path = None
        assets = list_assets()
        for p in assets:
            if p.name.startswith("avatar"):
                avatar_path = p
                break
        if avatar_path and apocalypse_on:
            b = avatar_path.read_bytes()
            await bot.user.edit(avatar=b)
        else:
            # optionally reset avatar -- skipping to avoid removing custom avatar
            pass

        # change nick in each guild (bot's member)
        for guild in bot.guilds:
            me = guild.get_member(bot.user.id)
            try:
                if apocalypse_on:
                    nick = random.choice(["TRANSMISSÃO CORROMPIDA", "ELE_VEM", "SINAL_PERDIDO"])
                    await me.edit(nick=nick)
                else:
                    await me.edit(nick=None)
            except Exception as e:
                logger.debug(f"Não foi possível editar nickname em guild {guild.name}: {e}")
    except Exception as e:
        logger.exception("Erro ao mudar avatar/nick: %s", e)

# main loop - sends messages with chance of special events
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
                # delete last own message and replace with encrypted corrected one
                if channel:
                    try:
                        # find last own message in channel history and delete then re-post encrypted
                        async for m in channel.history(limit=30):
                            if m.author.id == bot.user.id:
                                await m.delete()
                                break
                    except Exception as e:
                        logger.debug("Erro ao buscar/remover mensagens próprias: %s", e)

                payload = apply_cipher("ISTO NÃO ERA PARA EXISTIR")
                if channel:
                    await channel.send(payload)
            else:
                # normal send
                if channel:
                    # sometimes send image+audio
                    r = random.random()
                    if assets and r < 0.45:
                        asset = random.choice(assets)
                        if asset.suffix.lower() in [".mp3",".wav"]:
                            # send audio file as attachment in text channel
                            await channel.send(payload, file=discord.File(asset))
                        else:
                            await channel.send(payload, file=discord.File(asset))
                    else:
                        await channel.send(payload)

            # small chance to trigger 'apagon' offline period
            if STATE.get("apocalypse", False) and random.random() < 0.01:
                # go offline for 66 seconds
                logger.warning("APAGÃO: going offline for 66s")
                await bot.close()
                await asyncio.sleep(66)
                # after closing, the process will usually end; we keep loop for conceptual purpose
            # wait random time (shorter in apocalypse)
            wait = random.randint(600, 7200) if not STATE.get("apocalypse", False) else random.randint(300, 3600)
            await asyncio.sleep(wait)
        except Exception as e:
            logger.exception("Erro no loop de mensagens: %s", e)
            await asyncio.sleep(10)

# triggers and responses
@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    lc = message.content.lower()

    # detect midnight speakers for log
    if 0 <= message.created_at.hour <= 4:
        # simplistic logging
        try:
            with open("night_log.txt", "a", encoding="utf-8") as f:
                f.write(f"{message.created_at.isoformat()} - {message.author} - {message.content}\\n")
        except:
            pass

    # emergency triggers
    triggers = ["ele", "medo", "olhos", "onde você está", "estou com medo", "socorro"]
    if any(t in lc for t in triggers):
        # escalate: enable apocalypse temporarily
        STATE["apocalypse"] = True
        await set_own_nick_and_avatar(True)
        # immediate ominous reply
        reply = apply_cipher("O DIA DA TRANSMISSÃO ESTÁ PRÓXIMO.")
        try:
            await message.channel.send(reply)
        except:
            pass

    # secret commands hidden (only admins allowed)
    await bot.process_commands(message)

# admin-only checks
def is_admin():
    async def pred(ctx):
        return ctx.author.guild_permissions.administrator
    return commands.check(pred)

# admin commands
@bot.command(name="alerta")
@is_admin()
async def cmd_alerta(ctx):
    STATE["apocalypse"] = True
    await set_own_nick_and_avatar(True)
    await ctx.send(apply_cipher("ALERTA ATIVADO: TRANSMISSÃO CORROMPIDA"))

@bot.command(name="silencio")
@is_admin()
async def cmd_silencio(ctx):
    STATE["apocalypse"] = False
    await set_own_nick_and_avatar(False)
    await ctx.send(apply_cipher("SILÊNCIO RESTAURADO."))

@bot.command(name="corromper")
@is_admin()
async def cmd_corromper(ctx, member: discord.Member = None):
    # corrompe as últimas mensagens do alvo e devolve em forma corrompida
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

# setup_hook to start loops properly
@bot.event
async def setup_hook():
    asyncio.create_task(message_loop())

@bot.event
async def on_ready():
    logger.info(f"Bot online: {bot.user} (apocalypse={STATE.get('apocalypse')})")

# safety checks
if not TOKEN or not CHANNEL_ID:
    logger.critical("DISCORD_TOKEN or DISCORD_CHANNEL_ID not set. Set environment variables before running.")
else:
    bot.run(TOKEN)
