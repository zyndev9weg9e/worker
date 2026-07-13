import requests
import json
import threading
import time
import random
from datetime import datetime
from queue import Queue
import os
import sys

try:
    import discord
except ImportError:  # pragma: no cover
    discord = None

try:
    from colorama import init, Fore, Style
    init(autoreset=True)
except ImportError:
    class Fore:
        GREEN = YELLOW = RED = WHITE = ""
    class Style:
        RESET_ALL = ""

class DiscordBotController:
    def __init__(self, manager):
        self.manager = manager
        self.bot_token = os.getenv("PROXIFY_BOT_TOKEN", "").strip()
        self.control_channel_id = os.getenv("PROXIFY_CONTROL_CHANNEL", "").strip()
        self.prefix = os.getenv("PROXIFY_BOT_PREFIX", "!").strip() or "!"
        self.allowed_user_ids = {item.strip() for item in os.getenv("PROXIFY_ALLOWED_USER_IDS", "").split(",") if item.strip()}
        self.client = None
        self.thread = None

    def is_configured(self):
        return bool(self.bot_token and self.control_channel_id and discord is not None)

    def start(self):
        if not self.is_configured():
            if self.bot_token and self.control_channel_id and discord is None:
                print("[-] discord.py is not installed. Install it with: pip install discord.py")
            return False

        intents = discord.Intents.default()
        intents.message_content = True
        self.client = discord.Client(intents=intents)

        @self.client.event
        async def on_ready():
            print(f"[+] Discord bot connected as {self.client.user}")
            channel = self.client.get_channel(int(self.control_channel_id))
            if channel is not None:
                await channel.send("✅ Proxify worker connected. Use !help for commands.")

        @self.client.event
        async def on_message(message):
            if message.author.bot:
                return
            if self.allowed_user_ids and str(message.author.id) not in self.allowed_user_ids:
                return
            if str(message.channel.id) != self.control_channel_id:
                return
            if not message.content.startswith(self.prefix):
                return

            content = message.content[len(self.prefix):].strip()
            if not content:
                await message.reply("Use !help to see available commands.")
                return

            command, *args = content.split(maxsplit=10)
            try:
                reply = self.manager.handle_bot_command(command, args)
            except Exception as e:
                error_message = f"Command failed: {type(e).__name__}: {e}"
                print(error_message)
                await message.reply(error_message)
                return
            await message.reply(reply)

        self.thread = threading.Thread(target=lambda: self.client.run(self.bot_token), daemon=True)
        self.thread.start()
        return True


class DiscordAccountManager:
    def __init__(self):
        self.tokens = []
        self.accounts = {}
        self.running = True
        self.lock = threading.Lock()
        self.heartbeat_threads = []
        self.selected_accounts = []
        self.bot_controller = DiscordBotController(self)
        self.token_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tokens.txt")
        self.cwd_token_file = os.path.join(os.getcwd(), "tokens.txt")
        
        self.status_types = ["online", "idle", "dnd", "invisible"]
        self.activity_types = ["playing", "streaming", "listening", "watching", "competing"]
        
        self.load_tokens()
        self.setup_menu()
    
    def load_tokens(self):
        """Load Discord bot tokens from tokens.txt"""
        try:
            self.tokens = []
            token_path = self.token_file if os.path.exists(self.token_file) else self.cwd_token_file
            if not os.path.exists(token_path):
                print(f"[-] tokens.txt not found at {self.token_file} or current working directory")
                return
            
            with open(token_path, "r") as f:
                for line in f:
                    token = line.strip()
                    if token and not token.startswith("#"):
                        if token not in self.tokens:
                            self.tokens.append(token)
            print(f"[+] Loaded {len(self.tokens)} tokens from {token_path}")
        except Exception as e:
            print(f"[-] Error loading tokens: {e}")
            self.tokens = []
    
    def save_tokens(self):
        """Save tokens back to file"""
        try:
            token_path = self.token_file if os.path.exists(self.token_file) else self.cwd_token_file
            with open(token_path, "w") as f:
                for token in self.tokens:
                    f.write(token + "\n")
            print(f"[+] Tokens saved to {token_path}")
        except Exception as e:
            print(f"[-] Error saving tokens: {e}")
    
    def get_headers(self, token):
        """Get request headers with token authorization"""
        return {
            "Authorization": token,
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
    
    def get_user_info(self, token):
        """Fetch user info from token"""
        try:
            resp = requests.get(
                "https://discord.com/api/v10/users/@me",
                headers=self.get_headers(token),
                timeout=10
            )
            if resp.status_code == 200:
                return resp.json()
            print(f"[-] Token validation failed (status {resp.status_code})")
            return None
        except Exception as e:
            print(f"[-] Error fetching user info: {e}")
            return None
    
    def set_presence(self, token, status="online", activity=None):
        """Set user status and activity"""
        payload = {
            "status": status,
            "afk": False,
            "since": 0
        }
        
        if activity:
            payload["activities"] = [{
                "name": activity.get("name", ""),
                "type": activity.get("type", 0),
                "state": activity.get("state", ""),
                "details": activity.get("details", ""),
                "assets": activity.get("assets", {})
            }]
        else:
            payload["activities"] = []
        
        try:
            resp = requests.patch(
                "https://discord.com/api/v10/users/@me/settings",
                headers=self.get_headers(token),
                json=payload,
                timeout=10
            )
            return resp.status_code in [200, 204]
        except Exception as e:
            return False
    
    def set_avatar(self, token, avatar_data):
        """Set user avatar"""
        try:
            resp = requests.patch(
                "https://discord.com/api/v10/users/@me",
                headers=self.get_headers(token),
                json={"avatar": avatar_data},
                timeout=10
            )
            return resp.status_code in [200, 204]
        except Exception as e:
            print(f"[-] Avatar error: {e}")
            return False
    
    def set_bio(self, token, bio):
        """Set user profile bio"""
        try:
            resp = requests.patch(
                "https://discord.com/api/v10/users/@me/profile",
                headers=self.get_headers(token),
                json={"bio": bio},
                timeout=10
            )
            return resp.status_code in [200, 204]
        except Exception as e:
            return False
    
    def set_username(self, token, username):
        """Change username"""
        try:
            resp = requests.patch(
                "https://discord.com/api/v10/users/@me",
                headers=self.get_headers(token),
                json={"username": username},
                timeout=10
            )
            return resp.status_code in [200, 204]
        except Exception as e:
            return False
    
    def set_display_name(self, token, display_name):
        """Set global display name"""
        try:
            resp = requests.patch(
                "https://discord.com/api/v10/users/@me",
                headers=self.get_headers(token),
                json={"global_name": display_name},
                timeout=10
            )
            return resp.status_code in [200, 204]
        except Exception as e:
            return False
    
    def join_server(self, token, invite_code):
        """Join Discord server via invite code"""
        try:
            resp = requests.post(
                f"https://discord.com/api/v10/invites/{invite_code}",
                headers=self.get_headers(token),
                timeout=10
            )
            return resp.status_code in [200, 201]
        except Exception as e:
            return False
    
    def heartbeat_loop(self, token, account_id):
        """Keep account alive with periodic status updates"""
        stop_event = None
        with self.lock:
            account = self.accounts.get(account_id)
            if account:
                stop_event = account.get("stop_event")

        while self.running and (stop_event is None or not stop_event.is_set()):
            try:
                self.set_presence(token, "online")
                time.sleep(60)
            except Exception:
                time.sleep(5)
    
    def start_account(self, token):
        """Initialize account and start heartbeat"""
        user_info = self.get_user_info(token)
        if user_info:
            account_id = user_info.get("id")
            username = user_info.get("username")
            discriminator = user_info.get("discriminator", "0000")

            with self.lock:
                if account_id in self.accounts:
                    print(f"[-] Account already started: {username}#{discriminator}")
                    return False

                stop_event = threading.Event()
                self.accounts[account_id] = {
                    "token": token,
                    "username": username,
                    "discriminator": discriminator,
                    "display_name": user_info.get("global_name", username),
                    "status": "online",
                    "activity": None,
                    "bio": "",
                    "avatar": user_info.get("avatar"),
                    "online": True,
                    "thread": None,
                    "stop_event": stop_event
                }
            
            thread = threading.Thread(target=self.heartbeat_loop, args=(token, account_id), daemon=True)
            thread.start()
            
            with self.lock:
                self.accounts[account_id]["thread"] = thread
            
            print(f"[+] Started: {username}#{discriminator}")
            return True
        return False
    
    def start_all_accounts(self):
        """Start all loaded accounts"""
        print("[+] Starting all accounts...")
        for token in self.tokens:
            self.start_account(token)
            time.sleep(random.uniform(0.5, 1.5))
        return len(self.accounts)
    
    def stop_all_accounts(self):
        """Stop all active accounts"""
        self.running = False
        print("[+] Stopping all accounts...")
        with self.lock:
            for data in self.accounts.values():
                stop_event = data.get("stop_event")
                if stop_event is not None:
                    stop_event.set()
    
    def restart_all_accounts(self):
        """Restart all account heartbeats"""
        print("[+] Restarting all accounts...")
        self.stop_all_accounts()
        time.sleep(1)
        with self.lock:
            self.accounts = {}
        self.running = True
        started = self.start_all_accounts()
        return started

    def remove_token(self, identifier):
        """Remove a token by exact token or username#discriminator"""
        identifier = identifier.strip()
        if not identifier:
            return False, "Usage: !removetoken <token|username#discriminator>"

        matched_token = None
        matched_acc_id = None

        with self.lock:
            for acc_id, data in self.accounts.items():
                username_tag = f"{data['username']}#{data['discriminator']}"
                if identifier == data['token'] or identifier.lower() == username_tag.lower():
                    matched_token = data['token']
                    matched_acc_id = acc_id
                    break

        if matched_token is None:
            if identifier in self.tokens:
                matched_token = identifier

        if matched_token is None:
            return False, "Token or account not found."

        if matched_token in self.tokens:
            self.tokens.remove(matched_token)
            self.save_tokens()

        if matched_acc_id is not None:
            with self.lock:
                account = self.accounts.pop(matched_acc_id, None)
            if account is not None:
                stop_event = account.get("stop_event")
                if stop_event is not None:
                    stop_event.set()

        return True, "Token removed and account stopped."

    def list_accounts(self):
        """Display all active accounts with status"""
        with self.lock:
            if not self.accounts:
                print("[-] No accounts loaded")
                return
            
            print("\n" + "="*70)
            print(f"{'#':<4} {'Username':<20} {'Status':<12} {'Display Name':<20}")
            print("-"*70)
            
            for i, (acc_id, data) in enumerate(self.accounts.items(), 1):
                status = data.get("status", "offline")
                status_color = Fore.GREEN if status == "online" else Fore.YELLOW if status == "idle" else Fore.RED if status == "dnd" else Fore.WHITE
                print(f"{i:<4} {data['username']:<20} {status_color}{status:<12}{Style.RESET_ALL} {data.get('display_name', 'N/A'):<20}")
            
            print("="*70)
    
    def select_accounts(self):
        """Prompt user to select accounts for bulk operations"""
        self.list_accounts()
        print("\n[+] Select accounts (comma-separated numbers, 'all' for all, 'none' to cancel)")
        choice = input(">>> ").strip()
        
        if choice.lower() == "none":
            return []
        
        if choice.lower() == "all":
            return list(self.accounts.keys())
        
        try:
            indices = [int(x.strip()) for x in choice.split(",")]
            acc_ids = list(self.accounts.keys())
            selected = []
            for idx in indices:
                if 1 <= idx <= len(acc_ids):
                    selected.append(acc_ids[idx-1])
            return selected
        except:
            print("[-] Invalid input")
            return []
    
    def set_status_for_accounts(self, account_ids, status):
        """Set status for multiple accounts"""
        if status not in self.status_types:
            print(f"[-] Invalid status. Options: {', '.join(self.status_types)}")
            return 0
        
        count = 0
        for acc_id in account_ids:
            data = self.accounts.get(acc_id)
            if data:
                success = self.set_presence(data["token"], status)
                if success:
                    with self.lock:
                        data["status"] = status
                    count += 1
                time.sleep(random.uniform(0.3, 0.8))
        
        print(f"[+] Updated status to '{status}' for {count} accounts")
        return count
    
    def set_presence_for_accounts(self, account_ids, activity_type, activity_name, state="", details=""):
        """Set custom presence/activity for multiple accounts"""
        activity_map = {
            "playing": 0,
            "streaming": 1,
            "listening": 2,
            "watching": 3,
            "competing": 5
        }
        
        activity_type_id = activity_map.get(activity_type.lower(), 0)
        activity = {
            "name": activity_name,
            "type": activity_type_id,
            "state": state,
            "details": details
        }
        
        count = 0
        for acc_id in account_ids:
            data = self.accounts.get(acc_id)
            if data:
                success = self.set_presence(data["token"], data.get("status", "online"), activity)
                if success:
                    with self.lock:
                        data["activity"] = activity
                    count += 1
                time.sleep(random.uniform(0.3, 0.8))
        
        print(f"[+] Updated presence for {count} accounts")
        return count
    
    def set_bio_for_accounts(self, account_ids, bio):
        """Set bio for multiple accounts"""
        count = 0
        for acc_id in account_ids:
            data = self.accounts.get(acc_id)
            if data:
                success = self.set_bio(data["token"], bio)
                if success:
                    with self.lock:
                        data["bio"] = bio
                    count += 1
                time.sleep(random.uniform(0.5, 1.0))
        
        print(f"[+] Updated bio for {count} accounts")
        return count
    
    def join_server_for_accounts(self, account_ids, invite_code):
        """Join server for multiple accounts"""
        count = 0
        for acc_id in account_ids:
            data = self.accounts.get(acc_id)
            if data:
                success = self.join_server(data["token"], invite_code)
                if success:
                    count += 1
                time.sleep(random.uniform(0.5, 1.0))
        
        print(f"[+] Joined server for {count} accounts")
        return count
    
    def change_avatar_for_accounts(self, account_ids, image_path):
        """Change avatar for multiple accounts"""
        try:
            import base64
            if not os.path.exists(image_path):
                print(f"[-] File not found: {image_path}")
                return 0
            
            with open(image_path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")
                avatar_data = f"data:image/png;base64,{image_data}"
            
            count = 0
            for acc_id in account_ids:
                data = self.accounts.get(acc_id)
                if data:
                    success = self.set_avatar(data["token"], avatar_data)
                    if success:
                        count += 1
                    time.sleep(random.uniform(0.5, 1.0))
            
            print(f"[+] Changed avatar for {count} accounts")
            return count
        except Exception as e:
            print(f"[-] Avatar error: {e}")
            return 0
    
    def view_account_details(self):
        """Display detailed info for a specific account"""
        self.list_accounts()
        print("\n[+] Enter account number to view details:")
        choice = input(">>> ").strip()
        
        try:
            idx = int(choice)
            acc_ids = list(self.accounts.keys())
            if 1 <= idx <= len(acc_ids):
                acc_id = acc_ids[idx-1]
                data = self.accounts.get(acc_id)
                if data:
                    print("\n" + "="*60)
                    print(f"Username: {data['username']}#{data['discriminator']}")
                    print(f"Display Name: {data.get('display_name', 'N/A')}")
                    print(f"Status: {data.get('status', 'offline')}")
                    print(f"Activity: {data.get('activity', 'None')}")
                    print(f"Bio: {data.get('bio', 'N/A')}")
                    print(f"Avatar: {data.get('avatar', 'N/A')}")
                    print("="*60)
        except:
            print("[-] Invalid selection")

    def get_accounts_summary(self):
        """Return a compact status summary for Discord bot replies."""
        with self.lock:
            if not self.accounts:
                return "No accounts loaded."
            lines = [f"Accounts online: {len(self.accounts)}"]
            for acc_id, data in list(self.accounts.items())[:10]:
                lines.append(f"- {data['username']}#{data['discriminator']} [{data.get('status', 'offline')}]")
            if len(self.accounts) > 10:
                lines.append(f"... and {len(self.accounts) - 10} more")
            return "\n".join(lines)

    def add_token(self, token):
        """Add a token to the manager and save it."""
        token = token.strip()
        if not token:
            return False, "Token cannot be empty."
        if token in self.tokens:
            return False, "Token already exists."

        # Validate token before saving
        user_info = self.get_user_info(token)
        if not user_info:
            return False, "Invalid token or failed validation."

        self.tokens.append(token)
        self.save_tokens()

        if not self.running:
            self.running = True

        started = self.start_account(token)
        if not started:
            return False, "Token saved but failed to start the account."

        return True, f"Token added, saved, and started as {user_info.get('username')}#{user_info.get('discriminator', '0000')}"

    def handle_bot_command(self, command, args):
        """Process commands issued from the Discord bot."""
        cmd = (command or "").lower()
        if cmd in ["help", "?", "h"]:
            return "Commands: !status, !start, !stop, !restart, !addtoken <token>, !removetoken <token|user#1234>, !select all|1,2, !setstatus online|idle|dnd|invisible, !setpresence online|idle|dnd|invisible, !setbio text, !setdisplay name, !join invite, !refresh"

        if cmd == "status":
            return self.get_accounts_summary()

        if cmd == "start":
            self.running = True
            self.start_all_accounts()
            return f"Started accounts. Active: {len(self.accounts)}"

        if cmd == "stop":
            self.stop_all_accounts()
            return "Stopped account heartbeat loop."

        if cmd == "restart":
            started = self.restart_all_accounts()
            return f"Restarted accounts. Active: {started}"

        if cmd == "addtoken":
            if not args:
                return "Usage: !addtoken <token>"
            token = args[0]
            success, message = self.add_token(token)
            return message

        if cmd == "removetoken":
            if not args:
                return "Usage: !removetoken <token|username#discriminator>"
            success, message = self.remove_token(" ".join(args))
            return message

        if cmd == "setpresence":
            if len(args) < 1:
                return "Usage: !setpresence <status>"
            target_ids = self.selected_accounts or list(self.accounts.keys())
            status = args[0].lower()
            if status not in self.status_types:
                return f"Invalid presence type. Use: {', '.join(self.status_types)}"
            count = self.set_status_for_accounts(target_ids, status)
            return f"Updated presence for {count} account(s)."

        if cmd == "select":
            if not args:
                return "Usage: !select all or !select 1,2"
            if args[0].lower() == "all":
                self.selected_accounts = list(self.accounts.keys())
                return f"Selected {len(self.selected_accounts)} account(s)."
            try:
                indices = [int(item.strip()) for item in args[0].split(",") if item.strip()]
                acc_ids = list(self.accounts.keys())
                self.selected_accounts = [acc_ids[idx - 1] for idx in indices if 1 <= idx <= len(acc_ids)]
                return f"Selected {len(self.selected_accounts)} account(s)."
            except Exception:
                return "Invalid selection format."

        if cmd == "setstatus":
            if not args:
                return "Usage: !setstatus online"
            target_ids = self.selected_accounts or list(self.accounts.keys())
            count = self.set_status_for_accounts(target_ids, args[0].lower())
            return f"Updated {count} account(s)."

        if cmd == "setbio":
            if not args:
                return "Usage: !setbio Hello"
            target_ids = self.selected_accounts or list(self.accounts.keys())
            count = self.set_bio_for_accounts(target_ids, " ".join(args))
            return f"Updated {count} account(s)."

        if cmd == "setdisplay":
            if not args:
                return "Usage: !setdisplay MyName"
            target_ids = self.selected_accounts or list(self.accounts.keys())
            count = 0
            for acc_id in target_ids:
                data = self.accounts.get(acc_id)
                if data:
                    if self.set_display_name(data["token"], " ".join(args)):
                        with self.lock:
                            data["display_name"] = " ".join(args)
                        count += 1
                    time.sleep(random.uniform(0.5, 1.0))
            return f"Updated {count} account(s)."

        if cmd == "join":
            if not args:
                return "Usage: !join discord"
            target_ids = self.selected_accounts or list(self.accounts.keys())
            count = self.join_server_for_accounts(target_ids, args[0])
            return f"Joined for {count} account(s)."

        if cmd == "refresh":
            self.load_tokens()
            return f"Reloaded tokens. Available: {len(self.tokens)}"

        return "Unknown command. Use !help."
    
    def setup_menu(self):
        """Setup menu placeholder"""
        pass
    
    def run_console(self):
        """Main console interface"""
        print("\n" + "="*70)
        print("     DISCORD ACCOUNT MANAGER - 2BC WORKER TOOL")
        print("     " + "="*70)
        print(f"\n[+] Tokens loaded: {len(self.tokens)}")
        
        if self.tokens:
            print("[+] Starting accounts...")
            self.start_all_accounts()
            print(f"[+] Accounts active: {len(self.accounts)}")
        else:
            print("[-] No tokens loaded. Waiting for !addtoken commands via Discord bot or local input.")

        if self.bot_controller.is_configured():
            self.bot_controller.start()
            print("[+] Discord bot control is enabled. Set PROXIFY_BOT_TOKEN and PROXIFY_CONTROL_CHANNEL first.")
        
        while True:
            try:
                print("\n" + "-"*70)
                print("COMMANDS:")
                print("  status        - Show all accounts with status")
                print("  select        - Select accounts for management")
                print("  setstatus     - Set status (online/idle/dnd/invisible)")
                print("  setpresence   - Set custom presence (playing/listening/watching)")
                print("  setbio        - Set bio for selected accounts")
                print("  setavatar     - Change avatar for selected accounts")
                print("  setdisplay    - Change display name")
                print("  join          - Join server with invite code")
                print("  start         - Start all accounts")
                print("  stop          - Stop all accounts")
                print("  view          - View account details")
                print("  refresh       - Reload tokens from file")
                print("  help          - Show this help")
                print("  exit          - Quit")
                print("-"*70)
                
                cmd = input(">>> ").strip().lower()
                
                if cmd == "exit":
                    self.stop_all_accounts()
                    print("[+] Exiting...")
                    break
                
                elif cmd == "help":
                    continue
                
                elif cmd == "status":
                    self.list_accounts()
                
                elif cmd == "select":
                    selected = self.select_accounts()
                    if selected:
                        print(f"[+] Selected {len(selected)} accounts")
                        self.selected_accounts = selected
                
                elif cmd == "setstatus":
                    if not self.selected_accounts:
                        print("[-] No accounts selected. Use 'select' first")
                        continue
                    
                    print("[+] Status options: online, idle, dnd, invisible")
                    status = input("Enter status: ").strip().lower()
                    self.set_status_for_accounts(self.selected_accounts, status)
                
                elif cmd == "setpresence":
                    if not self.selected_accounts:
                        print("[-] No accounts selected. Use 'select' first")
                        continue
                    
                    print("[+] Activity types: playing, streaming, listening, watching, competing")
                    act_type = input("Enter activity type: ").strip()
                    act_name = input("Enter activity name: ").strip()
                    act_state = input("Enter state (optional): ").strip()
                    act_details = input("Enter details (optional): ").strip()
                    
                    self.set_presence_for_accounts(
                        self.selected_accounts,
                        act_type,
                        act_name,
                        act_state,
                        act_details
                    )
                
                elif cmd == "setbio":
                    if not self.selected_accounts:
                        print("[-] No accounts selected. Use 'select' first")
                        continue
                    
                    bio = input("Enter new bio: ").strip()
                    self.set_bio_for_accounts(self.selected_accounts, bio)
                
                elif cmd == "setavatar":
                    if not self.selected_accounts:
                        print("[-] No accounts selected. Use 'select' first")
                        continue
                    
                    img_path = input("Enter image path: ").strip()
                    self.change_avatar_for_accounts(self.selected_accounts, img_path)
                
                elif cmd == "setdisplay":
                    if not self.selected_accounts:
                        print("[-] No accounts selected. Use 'select' first")
                        continue
                    
                    display = input("Enter new display name: ").strip()
                    count = 0
                    for acc_id in self.selected_accounts:
                        data = self.accounts.get(acc_id)
                        if data:
                            success = self.set_display_name(data["token"], display)
                            if success:
                                with self.lock:
                                    data["display_name"] = display
                                count += 1
                            time.sleep(random.uniform(0.5, 1.0))
                    print(f"[+] Updated display name for {count} accounts")
                
                elif cmd == "join":
                    if not self.selected_accounts:
                        print("[-] No accounts selected. Use 'select' first")
                        continue
                    
                    invite = input("Enter invite code (e.g., discord): ").strip()
                    self.join_server_for_accounts(self.selected_accounts, invite)
                
                elif cmd == "start":
                    self.running = True
                    self.start_all_accounts()
                
                elif cmd == "stop":
                    self.stop_all_accounts()
                
                elif cmd == "view":
                    self.view_account_details()
                
                elif cmd == "refresh":
                    self.load_tokens()
                    print("[+] Tokens reloaded")
                
                else:
                    print("[-] Unknown command. Type 'help' for commands")
            
            except KeyboardInterrupt:
                print("\n[+] Exiting...")
                self.stop_all_accounts()
                break
            except Exception as e:
                print(f"[-] Error: {e}")

if __name__ == "__main__":
    manager = DiscordAccountManager()
    manager.run_console()
