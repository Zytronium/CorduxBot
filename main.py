import os
import sqlite3
import subprocess
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
import discord
from discord import app_commands
from discord.ext import commands, tasks
import hashlib
import re

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
ZYTRONIUM_ID = int(os.getenv("ZYTRONIUM_ID"))

# Database setup
def init_db():
    conn = sqlite3.connect('sandboxes.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS sandboxes
                 (user_id INTEGER,container_id TEXT,thread_id INTEGER,
                  created_at TIMESTAMP,expires_at TIMESTAMP,sandbox_type TEXT,
                  current_dir TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS global_sandbox
                 (container_id TEXT, channel_id INTEGER, created_at TIMESTAMP, current_dir TEXT)''')
    conn.commit()
    conn.close()

init_db()

# Intents
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# Dangerous command patterns for global sandbox
DANGEROUS_PATTERNS = [
    r'\brm\s+-rf',
    r'\b:>',
    r'>\s*/dev/sd',
    r'\bmkfs',
    r'\bdd\s+if=',
    r'fork\s*\(\s*\)',
    r'while\s+true.*do',
]

class SandboxManager:
    def __init__(self):
        self.global_container = None
        self.global_channel_id = None
        self.global_cwd = "/"

    def create_sandbox(self, user_id: int, sandbox_type: str = "personal") -> dict:
        """Create a new Docker sandbox container"""
        try:
            # Create a unique container name
            container_name = f"sandbox_{user_id}_{hashlib.md5(str(datetime.now()).encode()).hexdigest()[:8]}"

            # Create container with resource limits
            cmd = [
                'docker', 'run',
                '--name', container_name,
                '-d',
                '-t',
                '-i',
                '--memory=256m',
                '--cpus=0.5',
                '--network=none',
                '--security-opt=no-new-privileges',
                '--cap-drop=ALL',
                '--tmpfs', '/tmp:size=50M,mode=1777',
                'alpine:latest',
                '/bin/sh'
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode != 0:
                print(f"Error creating container: {result.stderr}")
                return None

            container_id = result.stdout.strip()

            # Install basic tools
            subprocess.run(
                ['docker', 'exec', container_id, 'apk', 'add', '--no-cache', 'bash', 'vim', 'nano', 'python3'],
                capture_output=True, timeout=60
            )

            return {
                "container_id": container_id,
                "container_name": container_name,
                "status": "running"
            }
        except Exception as e:
            print(f"Error creating sandbox: {e}")
            return None

    def execute_command(self, container_id: str, command: str, cwd: str = "/", timeout: int = 10) -> dict:
        """Execute a command in the sandbox and return output + new cwd"""
        try:
            # Wrap command to change directory first and then capture the new directory
            wrapped_command = f"cd {cwd} && {command} && pwd"
            
            result = subprocess.run(
                ['docker', 'exec', container_id, '/bin/sh', '-c', wrapped_command],
                capture_output=True,
                text=True,
                timeout=timeout
            )

            full_output = (result.stdout + result.stderr).strip()
            
            # Split output to separate the command output from the final 'pwd' result
            lines = full_output.splitlines()
            new_cwd = cwd
            output = full_output

            if result.returncode == 0 and lines:
                new_cwd = lines[-1]
                output = "\n".join(lines[:-1])

            return {
                "exit_code": result.returncode,
                "output": output[:1990] or "No output.",
                "success": result.returncode == 0,
                "new_cwd": new_cwd
            }
        except subprocess.TimeoutExpired:
            return {"exit_code": -1, "output": "Command timed out.", "success": False}
        except Exception as e:
            return {"exit_code": -1, "output": f"Error: {str(e)}", "success": False}

    def destroy_sandbox(self, container_id: str):
        """Stop and remove a sandbox container"""
        try:
            subprocess.run(['docker', 'stop', container_id], capture_output=True, timeout=10)
            subprocess.run(['docker', 'rm', container_id], capture_output=True, timeout=10)
            return True
        except Exception as e:
            print(f"Error destroying sandbox: {e}")
            return False

    def is_dangerous_command(self, command: str) -> bool:
        """Check if command matches dangerous patterns"""
        for pattern in DANGEROUS_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return True
        return False

    def save_sandbox(self, user_id: int, container_id: str, thread_id: int,
                     expires_in_minutes: int = 20, sandbox_type: str = "personal"):
        """Save sandbox info to database"""
        conn = sqlite3.connect('sandboxes.db')
        c = conn.cursor()
        created_at = datetime.now().isoformat()
        expires_at = (datetime.now() + timedelta(minutes=expires_in_minutes)).isoformat()
        c.execute("INSERT INTO sandboxes VALUES (?, ?, ?, ?, ?, ?, ?)",
                  (user_id, container_id, thread_id, created_at, expires_at,
                   sandbox_type, "/"))
        conn.commit()
        conn.close()

    def update_sandbox_dir(self, user_id: int, new_dir: str):
        """Update the current working directory for a user sandbox"""
        conn = sqlite3.connect('sandboxes.db')
        c = conn.cursor()
        c.execute("UPDATE sandboxes SET current_dir = ? WHERE user_id = ?", (new_dir, user_id))
        conn.commit()
        conn.close()

    def get_user_sandbox(self, user_id: int):
        """Get active sandbox for user"""
        conn = sqlite3.connect('sandboxes.db')
        c = conn.cursor()
        c.execute("SELECT * FROM sandboxes WHERE user_id = ? AND expires_at > ?",
                  (user_id, datetime.now().isoformat()))
        result = c.fetchone()
        conn.close()
        return result

    def extend_sandbox(self, user_id: int, additional_minutes: int) -> bool:
        """Extend sandbox expiration time"""
        conn = sqlite3.connect('sandboxes.db')
        c = conn.cursor()
        sandbox = self.get_user_sandbox(user_id)
        if not sandbox:
            conn.close()
            return False

        current_expires = datetime.fromisoformat(sandbox[4])
        new_expires = current_expires + timedelta(minutes=additional_minutes)
        max_expires = datetime.fromisoformat(sandbox[3]) + timedelta(hours=8)

        if new_expires > max_expires:
            new_expires = max_expires

        c.execute("UPDATE sandboxes SET expires_at = ? WHERE user_id = ?",
                  (new_expires.isoformat(), user_id))
        conn.commit()
        conn.close()
        return True

    def delete_user_sandbox(self, user_id: int):
        """Delete user's sandbox from database and Docker"""
        sandbox = self.get_user_sandbox(user_id)
        if sandbox:
            self.destroy_sandbox(sandbox[1])
            conn = sqlite3.connect('sandboxes.db')
            c = conn.cursor()
            c.execute("DELETE FROM sandboxes WHERE user_id = ?", (user_id,))
            conn.commit()
            conn.close()
            return True
        return False

sandbox_manager = SandboxManager()

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    print("✅ Docker connection verified via subprocess!")
    await tree.sync()
    cleanup_expired_sandboxes.start()
    print("Commands synced!")

@tasks.loop(minutes=5)
async def cleanup_expired_sandboxes():
    """Clean up expired sandboxes"""
    conn = sqlite3.connect('sandboxes.db')
    c = conn.cursor()
    c.execute("SELECT * FROM sandboxes WHERE expires_at < ?", (datetime.now().isoformat(),))
    expired = c.fetchall()

    for sandbox in expired:
        container_id = sandbox[1]
        thread_id = sandbox[2]
        sandbox_manager.destroy_sandbox(container_id)

        # Try to close thread
        try:
            thread = bot.get_channel(thread_id)
            if thread:
                await thread.send("⏱️ Sandbox expired and has been destroyed.")
                await thread.edit(archived=True)
        except:
            pass

    c.execute("DELETE FROM sandboxes WHERE expires_at < ?", (datetime.now().isoformat(),))
    conn.commit()
    conn.close()

@tree.command(name="sandbox", description="Manage your personal sandbox")
@app_commands.describe(
    action="Action to perform",
    time="Time extension in minutes (for extend action)"
)
@app_commands.choices(action=[
    app_commands.Choice(name="start", value="start"),
    app_commands.Choice(name="enter", value="enter"),
    app_commands.Choice(name="extend", value="extend"),
    app_commands.Choice(name="delete", value="delete"),
    app_commands.Choice(name="status", value="status"),
])
async def sandbox(interaction: discord.Interaction, action: str, time: int = 20):
    user_id = interaction.user.id

    if action == "start":
        existing = sandbox_manager.get_user_sandbox(user_id)
        if existing:
            await interaction.response.send_message("❌ You already have an active sandbox!", ephemeral=True)
            return

        await interaction.response.defer()
        sandbox_info = sandbox_manager.create_sandbox(user_id)

        if not sandbox_info:
            await interaction.followup.send("❌ Failed to create sandbox!", ephemeral=True)
            return

        # Create a thread for this sandbox
        thread = await interaction.channel.create_thread(
            name=f"🔒 {interaction.user.name}'s Sandbox",
            type=discord.ChannelType.private_thread,
            invitable=False
        )

        await thread.add_user(interaction.user)

        sandbox_manager.save_sandbox(user_id, sandbox_info["container_id"], thread.id)

        await interaction.followup.send(
            f"✅ Sandbox created! Thread: {thread.mention}\n"
            f"⏱️ Expires in 20 minutes. Use `/sandbox extend` to add time (max 8h total).",
            ephemeral=True
        )

        await thread.send(
            f"🎉 Welcome to your sandbox, {interaction.user.mention}!\n\n"
            f"📝 Type commands here and I'll execute them in your isolated container.\n"
            f"⚡ Container ID: `{sandbox_info['container_id'][:12]}`\n"
            f"⏱️ Expires: <t:{int((datetime.now() + timedelta(minutes=20)).timestamp())}:R>"
        )

    elif action == "enter":
        sandbox = sandbox_manager.get_user_sandbox(user_id)
        if not sandbox:
            await interaction.response.send_message("❌ No active sandbox found! Use `/sandbox start` first.", ephemeral=True)
            return

        thread = bot.get_channel(sandbox[2])
        if thread:
            await interaction.response.send_message(f"🔗 Your sandbox thread: {thread.mention}", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Thread not found! Your sandbox may have expired.", ephemeral=True)

    elif action == "extend":
        if time < 1 or time > 480:
            await interaction.response.send_message("❌ Time must be between 1-480 minutes!", ephemeral=True)
            return

        if sandbox_manager.extend_sandbox(user_id, time):
            await interaction.response.send_message(f"✅ Sandbox extended by {time} minutes!", ephemeral=True)
        else:
            await interaction.response.send_message("❌ No active sandbox to extend!", ephemeral=True)

    elif action == "delete":
        if sandbox_manager.delete_user_sandbox(user_id):
            await interaction.response.send_message("✅ Sandbox destroyed!", ephemeral=True)
        else:
            await interaction.response.send_message("❌ No active sandbox found!", ephemeral=True)

    elif action == "status":
        sandbox = sandbox_manager.get_user_sandbox(user_id)
        if not sandbox:
            await interaction.response.send_message("❌ No active sandbox!", ephemeral=True)
            return

        expires_at = datetime.fromisoformat(sandbox[4])
        time_left = expires_at - datetime.now()
        minutes_left = int(time_left.total_seconds() / 60)

        await interaction.response.send_message(
            f"✅ **Sandbox Status**\n"
            f"📦 Container: `{sandbox[1][:12]}`\n"
            f"⏱️ Time remaining: {minutes_left} minutes\n"
            f"🔗 Thread: <#{sandbox[2]}>",
            ephemeral=True
        )

@tree.command(name="run", description="Execute a command in a one-time sandbox")
@app_commands.describe(command="Command to execute")
async def run(interaction: discord.Interaction, command: str):
    await interaction.response.defer()

    # Create temporary sandbox
    sandbox_info = sandbox_manager.create_sandbox(interaction.user.id, "oneshot")

    if not sandbox_info:
        await interaction.followup.send("❌ Failed to create sandbox!")
        return

    # Execute command
    result = sandbox_manager.execute_command(sandbox_info["container_id"], command)

    # Clean up
    sandbox_manager.destroy_sandbox(sandbox_info["container_id"])

    # Send result
    await interaction.followup.send(
        f"**One-shot sandbox result:**\n```bash\n{result['output']}```"
    )

@tree.command(name="global", description="Manage the global experimental sandbox")
@app_commands.describe(action="Action to perform")
@app_commands.choices(action=[
    app_commands.Choice(name="join", value="join"),
    app_commands.Choice(name="leave", value="leave"),
])
async def global_sandbox(interaction: discord.Interaction, action: str):
    if action == "join":
        # Create global sandbox if it doesn't exist
        if not sandbox_manager.global_container:
            sandbox_info = sandbox_manager.create_sandbox(0, "global")
            if sandbox_info:
                sandbox_manager.global_container = sandbox_info["container_id"]
                sandbox_manager.global_channel_id = interaction.channel_id

                conn = sqlite3.connect('sandboxes.db')
                c = conn.cursor()
                c.execute("DELETE FROM global_sandbox")
                c.execute("INSERT INTO global_sandbox VALUES (?, ?, ?)",
                         (sandbox_info["container_id"], interaction.channel_id, datetime.now().isoformat()))
                conn.commit()
                conn.close()

                await interaction.response.send_message(
                    "🌍 **Global sandbox activated in this channel!**\n"
                    "All messages will be executed in the shared sandbox.\n"
                    "⚠️ Destructive commands are filtered.\n"
                    "♻️ Resets every 2 weeks."
                )
            else:
                await interaction.response.send_message("❌ Failed to create global sandbox!")
        else:
            sandbox_manager.global_channel_id = interaction.channel_id
            await interaction.response.send_message("🌍 Global sandbox moved to this channel!")

    elif action == "leave":
        if sandbox_manager.global_channel_id == interaction.channel_id:
            sandbox_manager.global_channel_id = None
            await interaction.response.send_message("👋 Global sandbox monitoring stopped in this channel.")
        else:
            await interaction.response.send_message("❌ This channel isn't monitoring the global sandbox!")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Check if message is in a sandbox thread
    if isinstance(message.channel, discord.Thread):
        conn = sqlite3.connect('sandboxes.db')
        c = conn.cursor()
        c.execute("SELECT * FROM sandboxes WHERE thread_id = ?", (message.channel.id,))
        sandbox = c.fetchone()
        conn.close()

        if sandbox and sandbox[0] == message.author.id:
            # Execute command in user's sandbox with saved cwd
            cwd = sandbox[6] if len(sandbox) > 6 else "/"
            result = sandbox_manager.execute_command(sandbox[1], message.content, cwd=cwd)
            
            if result["success"]:
                sandbox_manager.update_sandbox_dir(message.author.id, result["new_cwd"])
            
            await message.reply(f"```bash\n{result['output']}```")
            return

    # Check if message is in global sandbox channel
    if sandbox_manager.global_channel_id == message.channel.id and sandbox_manager.global_container:
        if sandbox_manager.is_dangerous_command(message.content):
            await message.reply("⛔ Command blocked: Potentially destructive operation detected!")
            return

        result = sandbox_manager.execute_command(
            sandbox_manager.global_container, 
            message.content, 
            cwd=sandbox_manager.global_cwd
        )
        
        if result["success"]:
            sandbox_manager.global_cwd = result["new_cwd"]
            
        await message.reply(f"```bash\n{result['output']}```")
        return

    await bot.process_commands(message)

bot.run(TOKEN)
