"""
src/discord_bot.py — Discord Bot Bridge for CSMID Market Copilot
"""

import os
import requests
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"✅ CSMID Discord Bot online as {bot.user}")


@bot.command(name="inspect")
async def inspect_skin(ctx, *, skin_name: str):
    """Command: !inspect Glock-18 | Block-18 (Field-Tested)"""
    async with ctx.typing():
        try:
            res = requests.post(
                f"{API_BASE_URL}/api/v1/chat",
                json={"message": f"Inspect {skin_name}"},
                timeout=10,
            )
            if res.status_code == 200:
                reply = res.json().get("reply", "No response.")
                await ctx.send(reply)
            else:
                await ctx.send(f"⚠️ API Error: {res.status_code}")
        except Exception as exc:
            await ctx.send(f"❌ Connection Error: {exc}")


@bot.command(name="buy")
async def recommend_buys(ctx, budget: float = 50.0):
    """Command: !buy 30"""
    async with ctx.typing():
        try:
            res = requests.post(
                f"{API_BASE_URL}/api/v1/chat",
                json={"message": f"Recommend buys", "budget": budget},
                timeout=10,
            )
            if res.status_code == 200:
                reply = res.json().get("reply", "No response.")
                await ctx.send(reply)
            else:
                await ctx.send(f"⚠️ API Error: {res.status_code}")
        except Exception as exc:
            await ctx.send(f"❌ Connection Error: {exc}")


if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)