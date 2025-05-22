import os
from dotenv import load_dotenv
import discord
from discord.ext import commands
import subprocess

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
ZYTRONIUM_ID = os.getenv("ZYTRONIUM_ID")

intents = discord.Intents.default()
intents.message_content = True  # Required to read message content

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

def is_allowed_user():
    def predicate(ctx):
        return str(ctx.author.id) == ZYTRONIUM_ID
    return commands.check(predicate)

@bot.command()
@commands.has_role("TerminalUser")  # IMPORTANT: Only give this role to trusted users! The bot currently does not run in any kind of container or sandbox, and can therefore execute harmful commands!
@is_allowed_user()
async def run(ctx, *, cmd):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
        output = (result.stdout or result.stderr)[:1999] or "No output."
        await ctx.send(
            f"```bash\n{output.replace('`', 'ˋ')}```"
            f"{"\n-# **Important Note:** To avoid messing up this message's formatting, all `` ` characters have been replaced with the similar-looking `ˋ` character." if output.__contains__("`") else ""}"
        )
    except subprocess.TimeoutExpired:
        await ctx.send("⏱️ Command timed out.")
    except Exception as e:
        await ctx.send(f"⚠️ Error: {str(e)}")

bot.run(TOKEN)
