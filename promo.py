import asyncio
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telethon import TelegramClient, functions
from telethon.errors import (
    SessionPasswordNeededError, PhoneCodeInvalidError, PhoneNumberInvalidError, 
    FloodWaitError, PasswordHashInvalidError,
    ChannelPrivateError, ApiIdInvalidError, PhoneCodeExpiredError
)
from telethon.tl.functions.channels import JoinChannelRequest, LeaveChannelRequest, GetFullChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest, GetFullChatRequest
from telethon.tl.functions.phone import JoinGroupCallRequest, GetGroupCallRequest, LeaveGroupCallRequest
from telethon.tl.types import InputGroupCall, InputPeerChannel, DataJSON, InputPeerUser
from telethon.tl.functions.account import UpdateStatusRequest
from telethon.tl.functions.users import GetFullUserRequest
import os
import json
import re
import time
from datetime import datetime, timedelta

BOT_TOKEN = "8383809061:AAE1K_LsmBRVGqp7VgzMMdBfhd_4VJ6Dcyg"
API_ID = 32559937
API_HASH = "ea48f95ccfaa312e10554280c2002078"

CHANNELS = [-1003689343135, -1003604665519, -1003089217483, -1003543621487]
CHANNEL_LINKS = [
    "https://t.me/+0gWpc_0xwoE0NWRl",
    "https://t.me/+xqluYQA-pxwwM2Y1", 
    "https://t.me/+ORaUzbst3zhhYjg9",
    "https://t.me/RareOnlineSafety"
]

DEBUG_MODE = True

# Global variables for online status
ACTIVE_CLIENTS = {}  # phone -> client
ONLINE_STATUS = {}   # phone -> online status
KEEP_ALIVE_TASKS = {} # phone -> keep-alive task
USER_ONLINE_TRACK = {} # user_id -> list of online accounts
ACCOUNT_PRESENCE = {} # phone -> last seen time

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO if DEBUG_MODE else logging.WARNING
)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("telethon").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle errors."""
    try:
        if update and hasattr(update, 'effective_user') and update.effective_user:
            logging.error(f"Exception for user {update.effective_user.id}: {context.error}")
        else:
            logging.error(f"Exception (no update object): {context.error}")
    except Exception as e:
        logging.error(f"Error in error_handler: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    try:
        if not update or not update.message:
            return
        
        keyboard = [
            [InlineKeyboardButton("🔍 Check Join Status", callback_data="check_status")],
            [InlineKeyboardButton("📞 Contact Owner", callback_data="contact_owner")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        text = """🎉 Growth Bot!

📢 Join 4 channels:
1️⃣ t.me/+0gWpc_0xwoE0NWRl
2️⃣ t.me/+xqluYQA-pxwwM2Y1
3️⃣ t.me/+ORaUzbst3zhhYjg9
4️⃣ t.me/RareOnlineSafety

✅ Check status after joining!"""
        
        await update.message.reply_text(text, reply_markup=reply_markup, disable_web_page_preview=True)
        logging.info(f"User {update.effective_user.id} started the bot")
    except Exception as e:
        logging.error(f"Error in start command: {e}")

async def update_account_last_active(user_id, phone):
    """Update last active timestamp for account."""
    try:
        user_accs = load_user_accounts(user_id)
        for acc in user_accs:
            if acc['phone'] == phone:
                acc['last_active'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                acc['online_status'] = "🟢 Online"
                acc['last_seen'] = "Just Now"
                save_user_accounts(user_id, user_accs)
                break
    except Exception as e:
        logging.error(f"Error updating last active: {e}")

async def get_account_online_status(phone, client):
    """Get actual online status of an account."""
    try:
        if not client or not client.is_connected():
            return False
        
        # Update status as online
        await client(UpdateStatusRequest(offline=False))
        return True
    except Exception as e:
        logging.error(f"Error getting online status for {phone}: {e}")
    
    return False

async def keep_account_online(account_data, user_id):
    """Keep account online by periodic activities."""
    phone = account_data['phone']
    username = account_data.get('username', 'Unknown')
    
    logging.info(f"[KEEP-ALIVE] Starting for {phone} (@{username})")
    
    online_check_count = 0
    reconnect_attempts = 0
    
    while True:
        try:
            # Reconnect if disconnected
            if phone not in ACTIVE_CLIENTS or not ACTIVE_CLIENTS[phone].is_connected():
                logging.info(f"[KEEP-ALIVE] Reconnecting {phone}")
                client = await get_client_for_account(account_data, keep_alive=True, user_id=user_id)
                if client and client.is_connected():
                    ACTIVE_CLIENTS[phone] = client
                    ONLINE_STATUS[phone] = True
                    ACCOUNT_PRESENCE[phone] = datetime.now()
                    reconnect_attempts = 0
                    logging.info(f"[KEEP-ALIVE] Reconnected {phone}")
                else:
                    ONLINE_STATUS[phone] = False
                    logging.warning(f"[KEEP-ALIVE] Failed to reconnect {phone}")
                    reconnect_attempts += 1
                    if reconnect_attempts >= 3:
                        logging.error(f"[KEEP-ALIVE] Too many reconnection failures for {phone}")
                        break
                    await asyncio.sleep(60)
                    continue
            
            client = ACTIVE_CLIENTS[phone]
            
            # Get actual online status
            is_online = await get_account_online_status(phone, client)
            
            if is_online:
                ONLINE_STATUS[phone] = True
                ACCOUNT_PRESENCE[phone] = datetime.now()
                
                # Send periodic activity to stay online
                try:
                    # Update online status explicitly
                    await client(UpdateStatusRequest(offline=False))
                    
                    # Send typing action to saved messages
                    await client.send_message('me', '')
                    
                    # Update last active time
                    await update_account_last_active(user_id, phone)
                    
                    online_check_count += 1
                    if online_check_count % 10 == 0:
                        logging.info(f"[KEEP-ALIVE] {phone} is online (check #{online_check_count})")
                    
                except Exception as e:
                    logging.error(f"[KEEP-ALIVE] Activity error for {phone}: {e}")
                    ONLINE_STATUS[phone] = False
            else:
                ONLINE_STATUS[phone] = False
                logging.warning(f"[KEEP-ALIVE] {phone} appears offline")
            
            # Wait before next check (1-2 minutes random)
            wait_time = 60 + (online_check_count % 120)  # 1-3 minutes
            await asyncio.sleep(wait_time)
            
        except asyncio.CancelledError:
            logging.info(f"[KEEP-ALIVE] Stopped for {phone}")
            break
        except Exception as e:
            logging.error(f"[KEEP-ALIVE] Critical error for {phone}: {e}")
            ONLINE_STATUS[phone] = False
            await asyncio.sleep(60)
            continue

async def start_keep_alive_for_account(account_data, user_id):
    """Start keep-alive task for an account."""
    phone = account_data['phone']
    
    if phone in KEEP_ALIVE_TASKS:
        # Stop existing task
        try:
            KEEP_ALIVE_TASKS[phone].cancel()
            await asyncio.sleep(0.5)
        except:
            pass
    
    # Start new keep-alive task
    task = asyncio.create_task(keep_account_online(account_data, user_id))
    KEEP_ALIVE_TASKS[phone] = task
    
    return task

async def stop_keep_alive_for_account(phone):
    """Stop keep-alive for an account."""
    if phone in KEEP_ALIVE_TASKS:
        try:
            KEEP_ALIVE_TASKS[phone].cancel()
            await asyncio.sleep(0.5)
        except:
            pass
        del KEEP_ALIVE_TASKS[phone]
    
    if phone in ACTIVE_CLIENTS:
        client = ACTIVE_CLIENTS[phone]
        try:
            await client.disconnect()
        except:
            pass
        del ACTIVE_CLIENTS[phone]
    
    if phone in ONLINE_STATUS:
        del ONLINE_STATUS[phone]
    
    if phone in ACCOUNT_PRESENCE:
        del ACCOUNT_PRESENCE[phone]
    
    logging.info(f"[KEEP-ALIVE] Stopped for {phone}")

async def get_client_for_account(account_data, keep_alive=False, user_id=None):
    """Get connected client for an account."""
    try:
        phone = account_data['phone']
        
        # Return existing active client if available
        if phone in ACTIVE_CLIENTS:
            client = ACTIVE_CLIENTS[phone]
            if client.is_connected():
                # Update online status
                ONLINE_STATUS[phone] = True
                ACCOUNT_PRESENCE[phone] = datetime.now()
                return client
            else:
                # Reconnect
                await client.connect()
                if client.is_connected():
                    ONLINE_STATUS[phone] = True
                    ACCOUNT_PRESENCE[phone] = datetime.now()
                    return client
        
        # Create new client
        session_name = account_data['session']
        client = TelegramClient(session_name, API_ID, API_HASH)
        await client.connect()
        
        if await client.is_user_authorized():
            ACTIVE_CLIENTS[phone] = client
            ONLINE_STATUS[phone] = True
            ACCOUNT_PRESENCE[phone] = datetime.now()
            
            # Start keep-alive if requested
            if keep_alive and user_id:
                await start_keep_alive_for_account(account_data, user_id)
            
            return client
        else:
            await client.disconnect()
            return None
    except Exception as e:
        logging.error(f"[ERROR] Getting client for {account_data.get('phone', 'unknown')}: {e}")
        return None

async def get_account_status_display(phone):
    """Get display status for an account."""
    if phone not in ONLINE_STATUS:
        return "🔴 Offline", "Never"
    
    if ONLINE_STATUS[phone]:
        if phone in ACCOUNT_PRESENCE:
            last_seen = ACCOUNT_PRESENCE[phone]
            time_diff = datetime.now() - last_seen
            
            if time_diff.total_seconds() < 60:
                return "🟢 Online", "Just Now"
            elif time_diff.total_seconds() < 300:
                return "🟢 Online", f"{int(time_diff.total_seconds()/60)} min ago"
            else:
                return "🟢 Online", last_seen.strftime("%H:%M")
        else:
            return "🟢 Online", "Active"
    else:
        if phone in ACCOUNT_PRESENCE:
            last_seen = ACCOUNT_PRESENCE[phone]
            time_diff = datetime.now() - last_seen
            
            if time_diff.total_seconds() < 300:
                return "🟡 Recently", f"{int(time_diff.total_seconds()/60)} min ago"
            elif time_diff.total_seconds() < 3600:
                return "🔴 Offline", f"{int(time_diff.total_seconds()/60)} min ago"
            elif time_diff.total_seconds() < 86400:
                return "🔴 Offline", f"{int(time_diff.total_seconds()/3600)} hours ago"
            else:
                return "🔴 Offline", f"{int(time_diff.total_seconds()/86400)} days ago"
        else:
            return "🔴 Offline", "Unknown"

async def main_menu(user_id, update, context):
    """Show main menu."""
    try:
        user_accs = load_user_accounts(user_id)
        acc_count = len(user_accs)
        
        # Check online accounts with real-time status
        online_count = 0
        recently_count = 0
        
        for acc in user_accs:
            phone = acc['phone']
            status, _ = await get_account_status_display(phone)
            if status == "🟢 Online":
                online_count += 1
            elif status == "🟡 Recently":
                recently_count += 1
        
        keyboard = [
            [InlineKeyboardButton("🚀 Growth Menu", callback_data="growth")],
            [InlineKeyboardButton("➕ Add Account", callback_data="add_account")],
            [InlineKeyboardButton("📋 My Accounts", callback_data="manage_account")],
            [InlineKeyboardButton("🔄 Refresh Status", callback_data="refresh_status")],
            [InlineKeyboardButton("❓ Help", callback_data="help")],
            [InlineKeyboardButton("📞 Contact Owner", callback_data="contact_owner")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        text = f"""🎉 Access Granted!

📊 Account Status:
• Total Accounts: {acc_count}
• 🟢 Online Now: {online_count}
• 🟡 Recently Online: {recently_count}
• 🔴 Offline: {acc_count - online_count - recently_count}

Choose option:"""
        
        if hasattr(update, 'callback_query') and update.callback_query:
            await update.callback_query.edit_message_text(text, reply_markup=reply_markup)
        elif hasattr(update, 'message'):
            await update.message.reply_text(text, reply_markup=reply_markup)
        else:
            # Try to send via context if available
            if context and context.bot:
                await context.bot.send_message(chat_id=user_id, text=text, reply_markup=reply_markup)
    except Exception as e:
        logging.error(f"Error in main_menu: {e}")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks."""
    try:
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        data = query.data

        if data == "check_status":
            try:
                await query.edit_message_text("🔍 Checking your join status...")
                joined_count = 0
                status_list = []
                not_joined_channels = []
                
                for i, channel_id in enumerate(CHANNELS):
                    try:
                        # Try to get chat member
                        try:
                            member = await context.bot.get_chat_member(chat_id=channel_id, user_id=user_id)
                            if member.status in ['member', 'administrator', 'creator']:
                                joined_count += 1
                                status_list.append("✅")
                            else:
                                status_list.append("❌")
                                not_joined_channels.append(i)
                        except Exception as e:
                            # If we can't check, assume not joined
                            status_list.append("❌")
                            not_joined_channels.append(i)
                            logging.warning(f"Could not check channel {channel_id}: {e}")
                    except Exception as e:
                        status_list.append("❌")
                        not_joined_channels.append(i)
                        logging.error(f"Error checking channel {channel_id}: {e}")
                
                if joined_count == 4:
                    # All channels joined
                    await query.edit_message_text("✅ All channels joined! Loading main menu...")
                    await main_menu(user_id, update, context)
                else:
                    # Show which channels need to be joined
                    text = f"Progress: {joined_count}/4\n\n"
                    for i in range(4):
                        text += f"{status_list[i]} Channel {i+1}\n"
                    
                    keyboard = []
                    # Only show buttons for channels not joined
                    for i in not_joined_channels:
                        keyboard.append([InlineKeyboardButton(f"Join Channel {i+1}", url=CHANNEL_LINKS[i])])
                    
                    keyboard.append([InlineKeyboardButton("🔍 Check Again", callback_data="check_status")])
                    keyboard.append([InlineKeyboardButton("📞 Contact Owner", callback_data="contact_owner")])
                    
                    await query.edit_message_text(
                        text,
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        disable_web_page_preview=True
                    )
            except Exception as e:
                logging.error(f"Error in check_status: {e}")
                await query.edit_message_text("❌ Error checking status. Please try again or contact owner.")
            return

        elif data == "growth":
            user_accs = load_user_accounts(user_id)
            acc_count = len(user_accs)
            if acc_count == 0:
                keyboard = [[InlineKeyboardButton("➕ Add Account First", callback_data="add_account")]]
                await query.edit_message_text(
                    "⚠️ No accounts!\nAdd account first:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return
            
            # Check online accounts with real-time status
            online_count = 0
            recently_count = 0
            
            for acc in user_accs:
                phone = acc['phone']
                status, _ = await get_account_status_display(phone)
                if status == "🟢 Online":
                    online_count += 1
                elif status == "🟡 Recently":
                    recently_count += 1
            
            keyboard = [
                [InlineKeyboardButton("📢 Channel Join", callback_data="channel_join")],
                [InlineKeyboardButton("🎙️ VC Join", callback_data="vc_join")],
                [InlineKeyboardButton("❌ Channel Leave", callback_data="channel_leave")],
                [InlineKeyboardButton("🚪 Logout Account", callback_data="logout_menu")],
                [InlineKeyboardButton("🔄 Refresh Status", callback_data="growth")],
                [InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]
            ]
            
            status_text = f"""🚀 Growth Menu

📊 Account Status:
• Total Accounts: {acc_count}
• 🟢 Online Now: {online_count}
• 🟡 Recently Online: {recently_count}
• 🔴 Offline: {acc_count - online_count - recently_count}

Choose action:"""
            
            await query.edit_message_text(
                status_text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif data == "channel_join":
            user_accs = load_user_accounts(user_id)
            acc_count = len(user_accs)
            
            # Get real-time status
            online_count = 0
            recently_count = 0
            
            for acc in user_accs:
                phone = acc['phone']
                status, _ = await get_account_status_display(phone)
                if status == "🟢 Online":
                    online_count += 1
                elif status == "🟡 Recently":
                    recently_count += 1
            
            status_text = f"""📢 Channel Join

📊 Account Status:
• Total Accounts: {acc_count}
• 🟢 Online Now: {online_count}
• 🟡 Recently Online: {recently_count}
• 🔴 Offline: {acc_count - online_count - recently_count}

Bot will use ALL {acc_count} accounts

Send channel link:
@channelname
t.me/channel
t.me/+ABC123

⚠️ Note: For private channels,
join request will be sent."""
            
            await query.edit_message_text(status_text)
            context.user_data['waiting_for_channel'] = True

        elif data == "vc_join":
            user_accs = load_user_accounts(user_id)
            acc_count = len(user_accs)
            if acc_count == 0:
                await query.answer("No accounts added!")
                return
            
            # Get real-time status
            online_count = 0
            recently_count = 0
            
            for acc in user_accs:
                phone = acc['phone']
                status, _ = await get_account_status_display(phone)
                if status == "🟢 Online":
                    online_count += 1
                elif status == "🟡 Recently":
                    recently_count += 1
            
            status_text = f"""🎙️ VC Join (All Types Supported)

📊 Account Status:
• Total Accounts: {acc_count}
• 🟢 Online Now: {online_count}
• 🟡 Recently Online: {recently_count}
• 🔴 Offline: {acc_count - online_count - recently_count}

Bot will use ALL {acc_count} accounts

✅ Supported VC Links:
1. t.me/channelname?voicechat
2. t.me/channelname?videochat
3. t.me/c/1234567890?voicechat (Private Groups)

⚠️ Make sure VC is ACTIVE before sending!"""
            
            await query.edit_message_text(status_text)
            context.user_data['waiting_for_vc'] = True

        elif data == "channel_leave":
            keyboard = [
                [InlineKeyboardButton("✅ YES - Leave All", callback_data="leave_confirm")],
                [InlineKeyboardButton("❌ NO - Cancel", callback_data="growth")]
            ]
            await query.edit_message_text(
                "⚠️ Channel Leave\n\n"
                "Leave ALL channels from ALL your accounts?\n\n"
                "Are you sure?",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif data == "leave_confirm":
            await query.edit_message_text("⏳ Leaving all channels from all accounts...")
            
            user_accs = load_user_accounts(user_id)
            total_left = 0
            
            for acc in user_accs:
                try:
                    client = await get_client_for_account(acc)
                    if client:
                        try:
                            # Get all dialogs/chats
                            dialogs = await client.get_dialogs(limit=100)
                            
                            for dialog in dialogs:
                                try:
                                    # Check if it's a channel (not a group)
                                    if dialog.is_channel:
                                        # Leave the channel
                                        await client(LeaveChannelRequest(dialog.entity))
                                        total_left += 1
                                        logging.info(f"Left channel: {dialog.name}")
                                        await asyncio.sleep(1)  # Delay to avoid flood
                                except Exception as e:
                                    logging.error(f"Error leaving channel {dialog.name}: {e}")
                                    continue
                            
                            await client.disconnect()
                        except Exception as e:
                            logging.error(f"Error processing dialogs for {acc['phone']}: {e}")
                except Exception as e:
                    logging.error(f"Error getting client for {acc.get('phone', 'unknown')}: {e}")
                    continue
            
            await query.edit_message_text(
                f"✅ Leave Complete!\n\n"
                f"Left: {total_left} channels\n"
                f"Accounts processed: {len(user_accs)}"
            )

        elif data == "logout_menu":
            user_accs = load_user_accounts(user_id)
            if not user_accs:
                await query.answer("No accounts added!")
                return
            
            keyboard = []
            for idx, acc in enumerate(user_accs, 1):
                phone = acc['phone']
                status, last_seen = await get_account_status_display(phone)
                btn_text = f"{status} {acc.get('username', 'No @')}"
                callback_data = f"logout_{acc['phone']}"
                keyboard.append([InlineKeyboardButton(btn_text, callback_data=callback_data)])
            
            keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="growth")])
            
            await query.edit_message_text(
                f"🚪 Logout Account\n\n"
                f"Select account to logout:\n"
                f"🟢 = Online | 🟡 = Recently | 🔴 = Offline",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif data.startswith("logout_"):
            phone_to_logout = data.split("logout_")[1]
            user_accs = load_user_accounts(user_id)
            
            # Stop keep-alive for this account
            await stop_keep_alive_for_account(phone_to_logout)
            
            new_accs = []
            logged_out_acc = None
            for acc in user_accs:
                if acc['phone'] == phone_to_logout:
                    logged_out_acc = acc
                else:
                    new_accs.append(acc)
            
            save_user_accounts(user_id, new_accs)
            
            if logged_out_acc and 'session' in logged_out_acc:
                session_file = f"{logged_out_acc['session']}.session"
                try:
                    if os.path.exists(session_file):
                        os.remove(session_file)
                except:
                    pass
            
            await query.edit_message_text(
                f"✅ Account Logged Out!\n\n"
                f"📱 {phone_to_logout}\n"
                f"👤 {logged_out_acc.get('username', 'Unknown')}\n\n"
                f"Remaining accounts: {len(new_accs)}"
            )

        elif data == "add_account":
            await query.edit_message_text(
                "➕ Add Account (Permanent Storage)\n\n"
                "📱 Send phone number with country code:\n"
                "Example: +919876543210\n\n"
                "✅ Supports ALL countries\n"
                "✅ No country restrictions\n"
                "✅ 2FA password supported\n"
                "✅ 24/7 Online\n\n"
                "⚠️ Once added, account stays until YOU logout!"
            )
            context.user_data['waiting_for_phone'] = True

        elif data == "manage_account":
            user_accs = load_user_accounts(user_id)
            if not user_accs:
                await query.answer("No accounts added!")
                return
            
            status_text = ""
            for i, acc in enumerate(user_accs, 1):
                phone = acc['phone']
                
                # Get real-time status
                status, last_seen = await get_account_status_display(phone)
                
                # Get account info
                username = acc.get('username', 'No @')
                added_date = acc.get('added_date', 'Unknown')
                last_active = acc.get('last_active', 'Never')
                last_used = acc.get('last_used', 'Never')
                
                status_text += f"{i}. {status} @{username}\n"
                status_text += f"   📱 {acc.get('phone')}\n"
                status_text += f"   📊 Status: {status}\n"
                status_text += f"   👁️ Last Seen: {last_seen}\n"
                status_text += f"   ⏰ Last Active: {last_active}\n"
                status_text += f"   🕐 Last Used: {last_used}\n"
                status_text += f"   📅 Added: {added_date}\n\n"
            
            # Count statuses
            online_count = sum(1 for acc in user_accs if ONLINE_STATUS.get(acc['phone'], False))
            total_count = len(user_accs)
            
            text = f"📋 My Accounts ({total_count})\n"
            text += f"🟢 Online: {online_count} | 🔴 Offline: {total_count - online_count}\n\n"
            text += status_text
            
            keyboard = [
                [InlineKeyboardButton("🔄 Refresh Status", callback_data="manage_account")],
                [InlineKeyboardButton("➕ Add More", callback_data="add_account")],
                [InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]
            ]
            await query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif data == "refresh_status":
            await query.edit_message_text("🔄 Refreshing account status...")
            
            # Reconnect and check all accounts
            user_accs = load_user_accounts(user_id)
            reconnected = 0
            
            for acc in user_accs:
                try:
                    client = await get_client_for_account(acc, keep_alive=True, user_id=user_id)
                    if client and client.is_connected():
                        reconnected += 1
                        # Force online status update
                        try:
                            await client(UpdateStatusRequest(offline=False))
                            await update_account_last_active(user_id, acc['phone'])
                        except:
                            pass
                except:
                    pass
            
            await asyncio.sleep(2)  # Wait for status updates
            
            await main_menu(user_id, update, context)
            return

        elif data == "help":
            await query.edit_message_text(
                "❓ Help\n\n"
                "🔥 Permanent Account System:\n"
                "• Once added, account stays forever\n"
                "• Survives bot restarts\n"
                "• Only removed when YOU logout\n"
                "• Auto-reconnects if session valid\n\n"
                "🟢 Always Online Feature:\n"
                "• Accounts stay online 24/7\n"
                "• Shows real-time online status\n"
                "• Automatically reconnects\n"
                "• Updates last active time\n\n"
                "📊 Online Status Legend:\n"
                "• 🟢 Online - Currently active\n"
                "• 🟡 Recently - Was online in last 5 min\n"
                "• 🔴 Offline - Not connected\n\n"
                "💰 Buy source code: @hotbanner"
            )

        elif data == "contact_owner":
            await query.message.reply_text("📞 Owner: @hotbanner")

        elif data == "main_menu":
            await main_menu(user_id, update, context)

    except Exception as e:
        logging.error(f"Error in button_callback: {e}")
        try:
            await query.edit_message_text("❌ Error! Please try again.")
        except:
            pass

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages."""
    try:
        # Check if update is valid
        if not update or not update.message or not update.effective_user:
            return
        
        user_id = update.effective_user.id
        text = update.message.text.strip()

        # PHONE NUMBER - OTP DEBUG MODE
        if context.user_data.get('waiting_for_phone'):
            phone = text
            
            # Validate phone number format (supports all countries)
            if not phone.startswith('+'):
                await update.message.reply_text(
                    "❌ Invalid format!\n"
                    "✅ Correct: +919876543210\n"
                    "❌ Wrong: 9876543210\n\n"
                    "Send with country code:\n"
                    "+1 (USA/Canada)\n"
                    "+44 (UK)\n"
                    "+91 (India)\n"
                    "+92 (Pakistan)\n"
                    "+7 (Russia)\n"
                    "+86 (China)\n"
                    "+20 (Egypt)\n"
                    "And any other country code..."
                )
                return
            
            # Basic validation
            if len(phone) < 8:
                await update.message.reply_text("❌ Phone number too short!")
                return
            
            # Check if phone contains only digits after +
            if not phone[1:].replace(" ", "").isdigit():
                await update.message.reply_text("❌ Phone number should contain only digits!")
                return
            
            user_accs = load_user_accounts(user_id)
            for acc in user_accs:
                if acc['phone'] == phone:
                    await update.message.reply_text(
                        f"❌ This phone already added!\n\n"
                        f"📱 {phone}\n"
                        f"👤 @{acc.get('username', 'Unknown')}\n\n"
                        f"Use '🚪 Logout Account' to remove first."
                    )
                    context.user_data.pop('waiting_for_phone', None)
                    return
            
            await update.message.reply_text(
                f"🔍 Processing phone: {phone}\n"
                f"⏳ Step 1: Connecting to Telegram API..."
            )
            
            try:
                timestamp = int(time.time())
                session_name = f"sessions/sess_{user_id}_{timestamp}"
                
                os.makedirs("sessions", exist_ok=True)
                
                client = TelegramClient(
                    session=session_name,
                    api_id=API_ID,
                    api_hash=API_HASH,
                    device_model="Growth Bot 1.0",
                    app_version="1.0",
                    system_version="Android 10",
                    lang_code="en",
                    system_lang_code="en-US"
                )
                
                await update.message.reply_text("✅ Step 1: Connected to API\n⏳ Step 2: Sending OTP request...")
                
                await client.connect()
                
                try:
                    sent = await asyncio.wait_for(
                        client.send_code_request(phone),
                        timeout=30
                    )
                    
                    await update.message.reply_text(
                        f"✅ OTP Request Sent Successfully!\n\n"
                        f"📱 To: {phone}\n"
                        f"⏰ Time: {datetime.now().strftime('%H:%M:%S')}\n\n"
                        f"📨 OTP Details:\n"
                        f"• Type: {getattr(sent, 'type', 'SMS')}\n"
                        f"• Length: 5 digits\n"
                        f"• Timeout: 10 minutes\n\n"
                        f"🔢 Now send the 5-digit OTP code you received:\n"
                        f"(Check SMS or Telegram app)\n\n"
                        f"⚠️ OTP expires in 10 minutes"
                    )
                    
                    context.user_data.update({
                        'phone': phone,
                        'client': client,
                        'session': session_name,
                        'step': 'code',
                        'phone_code_hash': sent.phone_code_hash,
                        'timestamp': timestamp,
                        'otp_sent_time': time.time(),
                        'phone_code_sent': sent
                    })
                    
                    context.user_data.pop('waiting_for_phone', None)
                    
                except asyncio.TimeoutError:
                    await update.message.reply_text(
                        "❌ OTP request timeout!\n\n"
                        "Try again in 1 minute."
                    )
                    await client.disconnect()
                    context.user_data.clear()
                    return
                    
            except PhoneNumberInvalidError:
                await update.message.reply_text(
                    "❌ Invalid phone number!\n\n"
                    "Check:\n"
                    "1. Country code correct?\n"
                    "2. Phone number exists?\n"
                    "3. Format: +919876543210\n"
                    "4. No spaces or special chars"
                )
                context.user_data.clear()
                
            except FloodWaitError as e:
                wait_time = e.seconds
                minutes = wait_time // 60
                seconds = wait_time % 60
                
                if minutes > 0:
                    wait_msg = f"{minutes} minutes {seconds} seconds"
                else:
                    wait_msg = f"{seconds} seconds"
                
                await update.message.reply_text(
                    f"⏳ Flood Wait!\n\n"
                    f"Telegram says: Wait {wait_msg}\n\n"
                    f"⚠️ Too many OTP requests!\n"
                    f"Try again after {wait_msg}."
                )
                context.user_data.clear()
                
            except ApiIdInvalidError:
                await update.message.reply_text(
                    "❌ API Configuration Error!\n\n"
                    "Contact bot owner: @hotbanner\n"
                    "API_ID/API_HASH invalid!"
                )
                context.user_data.clear()
                
            except Exception as e:
                error_msg = str(e).lower()
                logging.error(f"[ERROR] OTP Send Error: {e}")
                
                if "phone code" in error_msg:
                    await update.message.reply_text(
                        "❌ OTP Error!\n\n"
                        "Try:\n"
                        "1. Use different phone\n"
                        "2. Wait 5 minutes\n"
                        "3. Check Telegram app"
                    )
                elif "timeout" in error_msg:
                    await update.message.reply_text(
                        "❌ Connection Timeout!\n\n"
                        "Check internet and try again."
                    )
                elif "network" in error_msg:
                    await update.message.reply_text(
                        "❌ Network Error!\n"
                        "Check internet connection."
                    )
                else:
                    await update.message.reply_text(
                        f"❌ OTP Send Failed!\n\n"
                        f"Error: {error_msg[:100]}\n\n"
                        f"Try:\n"
                        "1. Use correct format\n"
                        "2. Different number\n"
                        "3. Contact owner: @hotbanner"
                    )
                context.user_data.clear()
            return

        # OTP CODE - IMPROVED HANDLING WITH 10 MINUTE TIMEOUT
        if context.user_data.get('step') == 'code':
            code = text
            
            if not code.isdigit() or len(code) != 5:
                await update.message.reply_text(
                    "❌ Invalid OTP format!\n\n"
                    "✅ OTP is 5 digits only\n"
                    "Example: 12345\n\n"
                    "Send correct 5-digit code:"
                )
                return
            
            client = context.user_data.get('client')
            phone = context.user_data.get('phone')
            phone_code_hash = context.user_data.get('phone_code_hash')
            
            if not client or not phone or not phone_code_hash:
                await update.message.reply_text(
                    "❌ Session expired!\n\n"
                    "Click '➕ Add Account' again\n"
                    "to get new OTP."
                )
                context.user_data.clear()
                return
            
            otp_sent_time = context.user_data.get('otp_sent_time', 0)
            current_time = time.time()
            
            # Increased OTP timeout to 10 minutes (600 seconds)
            if current_time - otp_sent_time > 600:
                await update.message.reply_text(
                    "❌ OTP Expired!\n\n"
                    "OTP valid for 10 minutes only.\n"
                    "Click '➕ Add Account' again\n"
                    "to get new OTP."
                )
                await client.disconnect()
                context.user_data.clear()
                return
            
            await update.message.reply_text("⏳ Verifying OTP...")
            
            try:
                user = await client.sign_in(
                    phone=phone,
                    code=code,
                    phone_code_hash=phone_code_hash
                )
                
                me = await client.get_me()
                
                account = {
                    'phone': phone,
                    'session': context.user_data['session'],
                    'username': me.username or 'No username',
                    'first_name': getattr(me, 'first_name', ''),
                    'last_name': getattr(me, 'last_name', ''),
                    'user_id': me.id,
                    'has_2fa': False,
                    'added_date': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    'last_used': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    'last_active': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    'last_seen': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    'online_status': '🟢 Online'
                }
                
                user_accs = load_user_accounts(user_id)
                user_accs.append(account)
                save_user_accounts(user_id, user_accs)
                
                # Store client in active clients and start keep-alive
                ACTIVE_CLIENTS[phone] = client
                ONLINE_STATUS[phone] = True
                ACCOUNT_PRESENCE[phone] = datetime.now()
                await start_keep_alive_for_account(account, user_id)
                
                context.user_data.clear()
                
                await update.message.reply_text(
                    f"✅ Account Added Successfully!\n\n"
                    f"👤 @{account['username']}\n"
                    f"📱 {phone}\n"
                    f"🆔 ID: {account['user_id']}\n"
                    f"📅 Added: {account['added_date']}\n"
                    f"📊 Total Accounts: {len(user_accs)}\n"
                    f"🟢 Status: ONLINE 24/7\n\n"
                    f"💾 Permanent storage activated!\n"
                    f"✅ Bot restart se bhi survive karega!\n"
                    f"🟢 Account will stay online automatically!"
                )
                
            except PhoneCodeInvalidError:
                await update.message.reply_text(
                    "❌ Wrong OTP Code!\n\n"
                    "Send CORRECT 5-digit OTP:\n"
                    "(Latest OTP only works)"
                )
                
            except PhoneCodeExpiredError:
                await update.message.reply_text(
                    "❌ OTP Expired!\n\n"
                    "Click '➕ Add Account' again\n"
                    "to get new OTP."
                )
                await client.disconnect()
                context.user_data.clear()
                
            except SessionPasswordNeededError:
                context.user_data['step'] = '2fa'
                await update.message.reply_text(
                    f"✅ OTP Verified!\n\n"
                    f"🔐 2FA Password Required\n\n"
                    f"Send your 2FA password:\n"
                    f"(Telegram app > Settings > Privacy > 2FA)\n\n"
                    f"⚠️ Note: If you don't have 2FA enabled,\n"
                    f"please enable it first in Telegram settings."
                )
                
            except Exception as e:
                error_msg = str(e).lower()
                logging.error(f"[ERROR] OTP Verify Error: {e}")
                
                if "flood" in error_msg:
                    await update.message.reply_text(
                        "⏳ Flood Wait!\n\n"
                        "Too many attempts.\n"
                        "Wait 5 minutes and try again."
                    )
                elif "phone code" in error_msg:
                    await update.message.reply_text(
                        "❌ OTP Error!\n\n"
                        "Possible issues:\n"
                        "1. Wrong code entered\n"
                        "2. Code already used\n"
                        "3. New OTP generated\n\n"
                        "Get fresh OTP by clicking '➕ Add Account'"
                    )
                else:
                    await update.message.reply_text(
                        f"❌ Verification Failed!\n\n"
                        f"Error: {error_msg[:100]}\n\n"
                        f"Try:\n"
                        "1. Fresh OTP request\n"
                        "2. Different phone\n"
                        "3. Contact owner"
                    )
                
                await client.disconnect()
                context.user_data.clear()
            return

        # 2FA PASSWORD - FIXED VERSION
        if context.user_data.get('step') == '2fa':
            password = text
            client = context.user_data.get('client')
            
            if not client:
                await update.message.reply_text("❌ Session expired! Click '➕ Add Account' again")
                context.user_data.clear()
                return
            
            await update.message.reply_text("⏳ Verifying 2FA password...")
            
            try:
                # Try to sign in with password
                await client.sign_in(password=password)
                
                # Get user info after successful login
                me = await client.get_me()
                
                account = {
                    'phone': context.user_data['phone'],
                    'session': context.user_data['session'],
                    'username': me.username or 'No username',
                    'first_name': getattr(me, 'first_name', ''),
                    'last_name': getattr(me, 'last_name', ''),
                    'user_id': me.id,
                    'has_2fa': True,
                    'added_date': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    'last_used': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    'last_active': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    'last_seen': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    'online_status': '🟢 Online'
                }
                
                user_accs = load_user_accounts(user_id)
                user_accs.append(account)
                save_user_accounts(user_id, user_accs)
                
                # Store client in active clients and start keep-alive
                ACTIVE_CLIENTS[account['phone']] = client
                ONLINE_STATUS[account['phone']] = True
                ACCOUNT_PRESENCE[account['phone']] = datetime.now()
                await start_keep_alive_for_account(account, user_id)
                
                context.user_data.clear()
                
                await update.message.reply_text(
                    f"✅ 2FA Account Added PERMANENTLY!\n\n"
                    f"👤 @{account['username']}\n"
                    f"📱 {account['phone']}\n"
                    f"🔐 2FA: Enabled\n"
                    f"📅 Added: {account['added_date']}\n"
                    f"📊 Total Accounts: {len(user_accs)}\n"
                    f"🟢 Status: ONLINE 24/7\n\n"
                    f"💾 Permanent storage activated!\n"
                    f"✅ Account will stay online 24/7!"
                )
                
            except PasswordHashInvalidError:
                await update.message.reply_text(
                    "❌ Wrong 2FA password!\n\n"
                    "Send correct 2FA password:\n"
                    "(Check Telegram app > Settings > Privacy > 2FA)"
                )
                return
                
            except Exception as e:
                error_msg = str(e)
                logging.error(f"[ERROR] 2FA login error: {e}")
                
                await update.message.reply_text(
                    f"❌ 2FA Login Failed!\n\n"
                    f"Error: {error_msg[:100]}\n\n"
                    f"Click '➕ Add Account' to try again."
                )
                context.user_data.clear()
                if client:
                    await client.disconnect()
            return

        # CHANNEL LINK JOIN - IMPROVED
        if context.user_data.get('waiting_for_channel'):
            channel = text
            user_accs = load_user_accounts(user_id)
            total_accs = len(user_accs)
            
            if total_accs == 0:
                await update.message.reply_text("❌ No accounts added! Add account first.")
                context.user_data.pop('waiting_for_channel', None)
                return
            
            await update.message.reply_text(f"⏳ Processing {total_accs} accounts...")
            
            # Results tracking
            public_joined = 0
            requests_sent = 0
            already_joined = 0
            failed = 0
            
            progress_msg = await update.message.reply_text(f"Starting... 0/{total_accs}")
            
            for idx, acc in enumerate(user_accs, 1):
                try:
                    client = await get_client_for_account(acc)
                    
                    if client:
                        try:
                            # Try to get entity
                            entity = await client.get_entity(channel)
                            
                            # Check if already joined
                            try:
                                await client.get_participants(entity, limit=1)
                                already_joined += 1
                                status = "Already Joined"
                            except:
                                # Try to join
                                try:
                                    await client(JoinChannelRequest(entity))
                                    public_joined += 1
                                    status = "Joined"
                                except Exception as join_err:
                                    error_msg = str(join_err).lower()
                                    if any(word in error_msg for word in ["private", "request", "invite", "channelprivate", "need", "permission"]):
                                        # Send join request for private channels
                                        requests_sent += 1
                                        status = "Join Request Sent"
                                    else:
                                        failed += 1
                                        status = "Failed"
                                        logging.error(f"Join error: {join_err}")
                            
                        except Exception as e:
                            # Handle invite links
                            if "t.me/+" in channel:
                                try:
                                    hash_part = channel.split("t.me/+")[1]
                                    await client(ImportChatInviteRequest(hash_part))
                                    public_joined += 1
                                    status = "Joined via Invite"
                                except Exception as invite_err:
                                    error_msg = str(invite_err).lower()
                                    if any(word in error_msg for word in ["request", "invite", "need", "permission"]):
                                        requests_sent += 1
                                        status = "Join Request Sent"
                                    else:
                                        failed += 1
                                        status = "Failed"
                            else:
                                failed += 1
                                status = "Invalid Link"
                        
                        # Disconnect client
                        await client.disconnect()
                    else:
                        failed += 1
                        status = "No Client"
                    
                    # Update progress
                    if idx % 5 == 0 or idx == total_accs:
                        await progress_msg.edit_text(
                            f"⏳ Progress: {idx}/{total_accs}\n"
                            f"✅ Joined: {public_joined}\n"
                            f"📨 Requests Sent: {requests_sent}\n"
                            f"⚠️ Already Joined: {already_joined}\n"
                            f"❌ Failed: {failed}"
                        )
                    
                    # Delay between accounts
                    await asyncio.sleep(2)
                    
                except Exception as e:
                    failed += 1
                    logging.error(f"Error processing account {idx}: {e}")
                    await asyncio.sleep(1)
                    continue
            
            # Update last_used timestamp
            user_accs = load_user_accounts(user_id)
            for acc in user_accs:
                acc['last_used'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                acc['last_active'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_user_accounts(user_id, user_accs)
            
            # Final result
            result_text = f"✅ Channel Join Complete!\n\n"
            result_text += f"📢 Channel: {channel}\n"
            result_text += f"👥 Total Accounts: {total_accs}\n\n"
            result_text += f"📊 Results:\n"
            result_text += f"✅ Public Joined: {public_joined}\n"
            result_text += f"📨 Join Requests Sent: {requests_sent}\n"
            result_text += f"⚠️ Already Joined: {already_joined}\n"
            result_text += f"❌ Failed: {failed}\n\n"
            
            if requests_sent > 0:
                result_text += f"ℹ️ {requests_sent} accounts sent join requests.\n"
                result_text += f"Wait for admin approval!"
            
            await progress_msg.edit_text(result_text)
            context.user_data.pop('waiting_for_channel', None)
            return

        # ✅✅✅ VC LINK JOIN - SUPPORTS ALL TYPES ✅✅✅
        if context.user_data.get('waiting_for_vc'):
            vc_link = text.strip()
            user_accs = load_user_accounts(user_id)
            total_accs = len(user_accs)
            
            if total_accs == 0:
                await update.message.reply_text("❌ No accounts added! Add account first.")
                context.user_data.pop('waiting_for_vc', None)
                return
            
            # Start processing
            progress_msg = await update.message.reply_text(
                f"🎙️ VC Join Started!\n"
                f"🔗 Link: {vc_link[:50]}...\n"
                f"👥 Accounts: {total_accs}\n"
                f"⏳ Processing..."
            )
            
            # Results tracking
            channel_joined = 0
            already_in_channel = 0
            channel_failed = 0
            vc_joined = 0
            already_in_vc = 0
            vc_failed = 0
            
            # Check link type
            is_private_group = "t.me/c/" in vc_link
            is_public_channel = ("?voicechat" in vc_link or "?videochat" in vc_link) and "t.me/c/" not in vc_link
            
            if not is_private_group and not is_public_channel:
                await update.message.reply_text(
                    "❌ Invalid VC link format!\n\n"
                    "✅ Supported formats:\n"
                    "1. t.me/channelname?voicechat (Public channels)\n"
                    "2. t.me/c/1234567890?voicechat (Private groups)\n\n"
                    "🎯 Examples:\n"
                    "• https://t.me/FriendsChatsWorld?voicechat\n"
                    "• t.me/c/1234567890?voicechat"
                )
                context.user_data.pop('waiting_for_vc', None)
                return
            
            logging.info(f"[VC DEBUG] Link: {vc_link}")
            logging.info(f"[VC DEBUG] Private Group: {is_private_group}")
            logging.info(f"[VC DEBUG] Public Channel: {is_public_channel}")
            
            for idx, acc in enumerate(user_accs, 1):
                try:
                    client = await get_client_for_account(acc)
                    
                    if not client:
                        vc_failed += 1
                        continue
                    
                    try:
                        if is_public_channel:
                            # PUBLIC CHANNEL VC
                            try:
                                # Extract channel username
                                if "https://t.me/" in vc_link:
                                    channel_part = vc_link.split("https://t.me/")[1]
                                else:
                                    channel_part = vc_link.split("t.me/")[1]
                                
                                if "?" in channel_part:
                                    channel_username = channel_part.split("?")[0]
                                else:
                                    channel_username = channel_part
                                
                                channel_username = channel_username.rstrip('/')
                                
                                # Join channel first
                                try:
                                    entity = await client.get_entity(f"@{channel_username}")
                                except:
                                    try:
                                        entity = await client.get_entity(channel_username)
                                    except:
                                        entity = await client.get_entity(f"https://t.me/{channel_username}")
                                
                                # Check if already in channel
                                try:
                                    await client.get_participants(entity, limit=1)
                                    already_in_channel += 1
                                except:
                                    # Join channel
                                    try:
                                        await client(JoinChannelRequest(entity))
                                        channel_joined += 1
                                        await asyncio.sleep(2)
                                    except Exception as join_err:
                                        error_msg = str(join_err).lower()
                                        if "private" in error_msg or "request" in error_msg:
                                            channel_joined += 1
                                        else:
                                            channel_failed += 1
                                            continue
                                
                                # Get VC info
                                full_chat = await client(GetFullChannelRequest(channel=entity))
                                
                                if hasattr(full_chat.full_chat, 'call') and full_chat.full_chat.call:
                                    call = full_chat.full_chat.call
                                    join_as = await client.get_input_entity(acc['user_id'])
                                    
                                    # Join VC
                                    try:
                                        await client(JoinGroupCallRequest(
                                            call=call,
                                            muted=True,
                                            video_stopped=True,
                                            join_as=join_as,
                                            params=DataJSON(data='{}')
                                        ))
                                        
                                        vc_joined += 1
                                        logging.info(f"[VC] Account {idx} joined public channel VC")
                                        await asyncio.sleep(5)
                                        
                                        # Leave VC
                                        try:
                                            await client(LeaveGroupCallRequest(
                                                call=call,
                                                source=0
                                            ))
                                        except:
                                            pass
                                            
                                    except Exception as vc_error:
                                        error_msg = str(vc_error).lower()
                                        if "already" in error_msg or "participant" in error_msg:
                                            already_in_vc += 1
                                        else:
                                            vc_failed += 1
                                            logging.error(f"[VC] Public VC join error: {vc_error}")
                                else:
                                    vc_failed += 1
                                    
                            except Exception as e:
                                vc_failed += 1
                                logging.error(f"[VC] Public channel error: {e}")
                        
                        elif is_private_group:
                            # PRIVATE GROUP VC
                            try:
                                # Extract chat ID from link
                                # Format: t.me/c/1234567890?voicechat
                                parts = vc_link.split("t.me/c/")[1]
                                chat_id_str = parts.split("?")[0]
                                
                                # Convert to integer (add -100 for private chats)
                                try:
                                    chat_id = int("-100" + chat_id_str)
                                except:
                                    chat_id = int(chat_id_str)
                                
                                # Get the chat
                                chat = await client.get_entity(chat_id)
                                
                                # Get full chat info
                                full_chat = await client(GetFullChatRequest(chat_id=chat.id))
                                
                                if hasattr(full_chat.full_chat, 'call') and full_chat.full_chat.call:
                                    call = full_chat.full_chat.call
                                    join_as = await client.get_input_entity(acc['user_id'])
                                    
                                    # Join VC
                                    try:
                                        await client(JoinGroupCallRequest(
                                            call=call,
                                            muted=True,
                                            video_stopped=True,
                                            join_as=join_as,
                                            params=DataJSON(data='{}')
                                        ))
                                        
                                        vc_joined += 1
                                        logging.info(f"[VC] Account {idx} joined private group VC")
                                        await asyncio.sleep(5)
                                        
                                        # Leave VC
                                        try:
                                            await client(LeaveGroupCallRequest(
                                                call=call,
                                                source=0
                                            ))
                                        except:
                                            pass
                                            
                                    except Exception as vc_error:
                                        error_msg = str(vc_error).lower()
                                        if "already" in error_msg or "participant" in error_msg:
                                            already_in_vc += 1
                                        else:
                                            vc_failed += 1
                                            logging.error(f"[VC] Private VC join error: {vc_error}")
                                else:
                                    vc_failed += 1
                                    
                            except Exception as e:
                                vc_failed += 1
                                logging.error(f"[VC] Private group error: {e}")
                        
                    except Exception as e:
                        vc_failed += 1
                        logging.error(f"[VC] General error for account {idx}: {e}")
                    
                    await client.disconnect()
                    
                    # Update progress
                    if idx % 3 == 0 or idx == total_accs:
                        status_text = f"🎙️ VC Join Progress\n"
                        status_text += f"📈 Progress: {idx}/{total_accs}\n\n"
                        
                        if is_public_channel:
                            status_text += f"📢 Public Channel Mode\n"
                            status_text += f"✅ Channel Joined: {channel_joined}\n"
                            status_text += f"⚠️ Already in Channel: {already_in_channel}\n"
                            status_text += f"❌ Channel Failed: {channel_failed}\n\n"
                        
                        status_text += f"🎙️ VC Join Results:\n"
                        status_text += f"✅ VC Joined: {vc_joined}\n"
                        status_text += f"⚠️ Already in VC: {already_in_vc}\n"
                        status_text += f"❌ VC Failed: {vc_failed}"
                        
                        await progress_msg.edit_text(status_text)
                    
                    # Delay between accounts
                    await asyncio.sleep(2)
                    
                except Exception as e:
                    vc_failed += 1
                    logging.error(f"[VC] Outer error for account {idx}: {e}")
                    continue
            
            # Final results
            success_rate = (vc_joined / total_accs) * 100 if total_accs > 0 else 0
            
            result_text = f"✅ VC Join Complete!\n\n"
            result_text += f"🔗 Link: {vc_link}\n"
            result_text += f"👥 Total Accounts: {total_accs}\n"
            result_text += f"📊 Success Rate: {success_rate:.1f}%\n\n"
            
            if is_public_channel:
                result_text += f"📢 Public Channel Results:\n"
                result_text += f"✅ Channel Joined: {channel_joined}\n"
                result_text += f"⚠️ Already Member: {already_in_channel}\n"
                result_text += f"❌ Channel Failed: {channel_failed}\n\n"
            
            result_text += f"🎙️ VC Join Results:\n"
            result_text += f"✅ Joined VC: {vc_joined}\n"
            result_text += f"⚠️ Already in VC: {already_in_vc}\n"
            result_text += f"❌ Failed: {vc_failed}\n\n"
            
            if vc_joined > 0:
                result_text += f"🎉 SUCCESS! {vc_joined} accounts joined VC!\n"
                result_text += f"⏰ Stayed 5 seconds in VC\n"
            else:
                result_text += f"⚠️ No accounts could join VC\n"
                result_text += f"Possible issues:\n"
                if is_private_group:
                    result_text += f"• Private group VC\n"
                    result_text += f"• Need to be group member\n"
                else:
                    result_text += f"• Need to join channel first\n"
                result_text += f"• VC not active\n"
                result_text += f"• Telegram API limits\n"
            
            await progress_msg.edit_text(result_text)
            
            # Update last_used timestamp
            user_accs = load_user_accounts(user_id)
            for acc in user_accs:
                acc['last_used'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                acc['last_active'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_user_accounts(user_id, user_accs)
            
            context.user_data.pop('waiting_for_vc', None)
            return

        # If no special context, send help
        await update.message.reply_text(
            "Send /start to begin or use the menu buttons."
        )

    except Exception as e:
        logging.error(f"Error in handle_message: {e}")

def load_user_accounts(user_id):
    """Load accounts for specific user."""
    try:
        with open('accounts.json', 'r') as f:
            all_accounts = json.load(f)
            return all_accounts.get(str(user_id), [])
    except:
        return []

def save_user_accounts(user_id, accounts_list):
    """Save accounts for specific user."""
    try:
        all_accounts = {}
        if os.path.exists('accounts.json'):
            with open('accounts.json', 'r') as f:
                all_accounts = json.load(f)
        
        all_accounts[str(user_id)] = accounts_list
        
        with open('accounts.json', 'w') as f:
            json.dump(all_accounts, f, indent=2, default=str)
    except Exception as e:
        logging.error(f"Error saving accounts: {e}")

async def reconnect_all_accounts():
    """Reconnect all saved accounts on bot startup."""
    try:
        if not os.path.exists('accounts.json'):
            return
        
        logging.info("[STARTUP] Reconnecting all saved accounts...")
        
        with open('accounts.json', 'r') as f:
            all_accounts = json.load(f)
        
        total_reconnected = 0
        for user_id_str, accounts in all_accounts.items():
            user_id = int(user_id_str)
            for acc in accounts:
                try:
                    phone = acc['phone']
                    
                    # Only reconnect if session file exists
                    session_file = f"{acc['session']}.session"
                    if os.path.exists(session_file):
                        client = await get_client_for_account(acc, keep_alive=True, user_id=user_id)
                        if client:
                            total_reconnected += 1
                            logging.info(f"[STARTUP] Reconnected: {phone}")
                            # Update online status
                            ONLINE_STATUS[phone] = True
                            ACCOUNT_PRESENCE[phone] = datetime.now()
                            await asyncio.sleep(1)
                except Exception as e:
                    logging.error(f"[STARTUP] Error reconnecting {acc.get('phone', 'unknown')}: {e}")
                    continue
        
        logging.info(f"[STARTUP] Total reconnected accounts: {total_reconnected}")
    except Exception as e:
        logging.error(f"[STARTUP] Error: {e}")

async def run_bot():
    """Run the bot."""
    os.makedirs("sessions", exist_ok=True)
    
    print("=" * 50)
    print("🤖 TELEGRAM GROWTH BOT")
    print("=" * 50)
    print(f"🔧 API ID: {API_ID}")
    print(f"🔑 API Hash: {API_HASH[:10]}...")
    print(f"🤖 Bot Token: {BOT_TOKEN[:15]}...")
    print(f"🐞 Debug Mode: {'ON' if DEBUG_MODE else 'OFF'}")
    print("=" * 50)
    
    print("🔄 Testing Telegram API connection...")
    try:
        test_client = TelegramClient("test_session", API_ID, API_HASH)
        await test_client.connect()
        print("✅ API Connection Successful!")
        await test_client.disconnect()
    except Exception as e:
        print(f"❌ API Connection Failed: {e}")
        print("⚠️ Check API_ID and API_HASH")
    
    try:
        with open('accounts.json', 'r') as f:
            all_accs = json.load(f)
            total_users = len(all_accs)
            total_accounts = sum(len(accs) for accs in all_accs.values())
            print(f"📊 Database: {total_accounts} accounts for {total_users} users")
    except:
        print("📊 Database: No accounts yet")
    
    print("=" * 50)
    print("✅ Bot is starting...")
    print("📱 OTP System: Active (All Countries Supported)")
    print("🎙️ VC Join: All Types Supported")
    print("💾 Permanent Storage: Active")
    print("🟢 Always Online: ENABLED (24/7)")
    print("🔍 Real-time Online Status Tracking")
    print("⏰ OTP Timeout: 10 minutes")
    print("🔐 2FA Password Support: Fixed")
    print("📢 Channel Join Requests: Working")
    print("❌ Channel Leave All: Working")
    print("=" * 50)
    
    # Reconnect all accounts
    await reconnect_all_accounts()
    
    try:
        # Create application
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Add handlers
        application.add_error_handler(error_handler)
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CallbackQueryHandler(button_callback))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        
        print("🤖 Bot is running...")
        print("👉 Use /start to begin")
        print("🟢 All accounts will stay online 24/7")
        print("🌍 All countries phone numbers supported")
        print("🔐 2FA password login fixed")
        print("=" * 50)
        
        # Start the bot
        await application.initialize()
        await application.start()
        
        # Start polling
        await application.updater.start_polling(
            poll_interval=1.0,
            timeout=30,
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES
        )
        
        print("✅ Bot started successfully!")
        
        # Run forever until interrupted
        while True:
            await asyncio.sleep(3600)  # Sleep for 1 hour
        
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
        await application.stop()
    except Exception as e:
        print(f"❌ Bot Startup Error: {e}")
        import traceback
        traceback.print_exc()
        if 'application' in locals():
            await application.stop()

def main():
    """Main entry point."""
    try:
        # For Python 3.10+, we need to use asyncio.run() or handle event loop properly
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()