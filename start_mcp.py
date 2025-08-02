import os, threading, asyncio, traceback, sys, uvicorn
import json, aiohttp
from datetime import datetime
from main import client, mcp
from telethon import events

# ===============================================================================
# INTELLIGENT FILTERING SYSTEM - INFRASTRUCTURE
# ===============================================================================

# Get super user ID from environment (your Telegram ID)
SUPER_USER_ID = int(os.getenv("SUPER_USER_TELEGRAM_ID", "0"))  # Set this in your env

# Filtering rules storage - can be made dynamic later
FILTERING_RULES = {
    "blocked_users": [],  # User IDs to completely ignore
    "blocked_chats": [],  # Chat IDs to ignore
    "allowed_groups": [],  # Group chat IDs where SATYA can operate
    "chatbot_enabled_chats": [],  # Where SATYA can use chatbot mode
    "agent_enabled_chats": [],  # Where SATYA has full agent powers
    "workflow_states": {
        "superuser": True,   # Always ON for super user
        "agent": False,      # OFF by default - enable manually
        "chatbot": False,    # OFF by default - enable manually  
        "mention": False,    # OFF by default - enable manually
        "logging": True      # Always ON for data collection
    }
}

async def capture_structured_message_data(event):
    """Capture and structure message data for processing"""
    try:
        # Get sender info safely
        sender_username = None
        if event.sender:
            sender_username = getattr(event.sender, 'username', None)
        
        # Get chat info safely  
        chat_title = None
        if hasattr(event.chat, 'title'):
            chat_title = event.chat.title
        elif hasattr(event.chat, 'first_name'):
            chat_title = event.chat.first_name
            
        message_data = {
            "sender_id": event.sender_id,
            "chat_id": event.chat_id,
            "message_text": event.raw_text or "",
            "message_id": event.id,
            "timestamp": datetime.utcnow().isoformat(),
            "is_private": event.is_private,
            "is_group": event.is_group,
            "is_channel": event.is_channel,
            "sender_username": sender_username,
            "chat_title": chat_title,
            "has_media": bool(event.media)
        }
        
        return message_data
        
    except Exception as e:
        print(f"[ERROR] Failed to capture message data: {e}")
        # Return minimal data if capture fails
        return {
            "sender_id": event.sender_id,
            "chat_id": event.chat_id, 
            "message_text": event.raw_text or "",
            "timestamp": datetime.utcnow().isoformat(),
            "error": str(e)
        }

# ===============================================================================
# 5-TIER MESSAGE DETECTION FUNCTIONS
# ===============================================================================

async def is_junk_message(event, message_data):
    """TIER 0: Filter out spam, blocked users, unwanted content - NO n8n call"""
    try:
        # Check blocked users
        if event.sender_id in FILTERING_RULES["blocked_users"]:
            print(f"[FILTER] Blocked user: {event.sender_id}")
            return True
            
        # Check blocked chats
        if event.chat_id in FILTERING_RULES["blocked_chats"]:
            print(f"[FILTER] Blocked chat: {event.chat_id}")
            return True
            
        # Basic spam patterns (no AI needed)
        text = message_data["message_text"].lower()
        spam_patterns = [
            "crypto", "bitcoin", "investment", "click here", "join now", 
            "make money", "free money", "urgent", "limited time",
            "congratulations", "you won", "claim now"
        ]
        
        if any(pattern in text for pattern in spam_patterns):
            print(f"[FILTER] Spam pattern detected: {event.sender_id}")
            return True
            
        # Filter very short messages in groups (likely spam)
        if event.is_group and len(text.strip()) < 3:
            return True
            
        return False
        
    except Exception as e:
        print(f"[ERROR] Junk filter failed: {e}")
        return False  # Don't filter on errors

async def should_trigger_superuser_workflow(event, message_data):
    """TIER 5: Super-user messages (YOU) - highest priority, full access"""
    try:
        is_superuser = event.sender_id == SUPER_USER_ID
        workflow_enabled = FILTERING_RULES["workflow_states"]["superuser"]
        
        if is_superuser and workflow_enabled:
            print(f"[ROUTE] Super-user message detected from {event.sender_id}")
            return True
            
        return False
        
    except Exception as e:
        print(f"[ERROR] Superuser detection failed: {e}")
        return False

async def should_trigger_agent_workflow(event, message_data):
    """TIER 4: Complex tasks - full SATYA agent capabilities"""
    try:
        # Check if agent mode is enabled globally
        if not FILTERING_RULES["workflow_states"]["agent"]:
            return False
            
        # Check if this chat is enabled for agent mode
        if event.chat_id not in FILTERING_RULES["agent_enabled_chats"]:
            return False
            
        text = message_data["message_text"].lower()
        
        # Agent-level task triggers
        agent_triggers = [
            "help me", "can you", "please", "analyze", "create", "build",
            "research", "find", "generate", "write", "explain", "how to",
            "what is", "tell me about", "summary", "summarize"
        ]
        
        if any(trigger in text for trigger in agent_triggers):
            print(f"[ROUTE] Agent workflow triggered by: {event.sender_id}")
            return True
            
        # Long messages likely need agent-level processing
        if len(text) > 100:
            print(f"[ROUTE] Long message for agent processing: {event.sender_id}")
            return True
            
        return False
        
    except Exception as e:
        print(f"[ERROR] Agent detection failed: {e}")
        return False

async def should_trigger_chatbot_workflow(event, message_data):
    """TIER 3: Conversational messages - AI chatbot responses"""
    try:
        # Check if chatbot mode is enabled globally
        if not FILTERING_RULES["workflow_states"]["chatbot"]:
            return False
            
        # Check if this chat is enabled for chatbot mode
        if event.chat_id not in FILTERING_RULES["chatbot_enabled_chats"]:
            return False
            
        text = message_data["message_text"].lower()
        
        # Social/conversational triggers
        chatbot_triggers = [
            "hi", "hello", "hey", "good morning", "good night",
            "how are you", "what's up", "thanks", "thank you",
            "cool", "nice", "awesome", "interesting", "lol", "haha"
        ]
        
        if any(trigger in text for trigger in chatbot_triggers):
            print(f"[ROUTE] Chatbot workflow triggered by: {event.sender_id}")
            return True
            
        # Questions directed at the group
        question_patterns = ["?", "what do you think", "anyone know", "thoughts?"]
        if any(pattern in text for pattern in question_patterns):
            print(f"[ROUTE] Question detected for chatbot: {event.sender_id}")
            return True
            
        return False
        
    except Exception as e:
        print(f"[ERROR] Chatbot detection failed: {e}")
        return False

async def should_trigger_mention_workflow(event, message_data):
    """TIER 2: Direct mentions - basic acknowledgment"""
    try:
        # Check if mention mode is enabled globally
        if not FILTERING_RULES["workflow_states"]["mention"]:
            return False
            
        text = message_data["message_text"].lower()
        
        # Direct mentions of SATYA
        mention_patterns = [
            "satya", "@satya", "hey satya", "hi satya", 
            "satya!", "satya?", "satya,"
        ]
        
        if any(mention in text for mention in mention_patterns):
            print(f"[ROUTE] Mention workflow triggered by: {event.sender_id}")
            return True
            
        return False
        
    except Exception as e:
        print(f"[ERROR] Mention detection failed: {e}")
        return False

async def should_log_only(event, message_data):
    """TIER 1: Messages to log but not process - storage only, no n8n call"""
    try:
        # Check if logging is enabled
        if not FILTERING_RULES["workflow_states"]["logging"]:
            return False
            
        # Private messages from non-super users (log for learning)
        if event.is_private and event.sender_id != SUPER_USER_ID:
            print(f"[LOG] Private message logged from: {event.sender_id}")
            return True
            
        # Group messages without any triggers (background logging)
        if event.is_group:
            print(f"[LOG] Group message logged from: {event.sender_id}")
            return True
            
        # Channel messages (monitoring)
        if event.is_channel:
            print(f"[LOG] Channel message logged from: {event.chat_id}")
            return True
            
        return False
        
    except Exception as e:
        print(f"[ERROR] Log detection failed: {e}")
        return False

# ===============================================================================
# WORKFLOW ROUTING SYSTEM
# ===============================================================================

# n8n webhook endpoints configuration
N8N_WEBHOOK_BASE_URL = os.getenv("N8N_WEBHOOK_BASE_URL", "https://your-n8n-instance.com")
WEBHOOK_ENDPOINTS = {
    "superuser": f"{N8N_WEBHOOK_BASE_URL}/webhook/telegram-superuser",
    "agent": f"{N8N_WEBHOOK_BASE_URL}/webhook/telegram-agent", 
    "chatbot": f"{N8N_WEBHOOK_BASE_URL}/webhook/telegram-chatbot",
    "mention": f"{N8N_WEBHOOK_BASE_URL}/webhook/telegram-mention"
}

async def route_to_n8n_workflow(workflow_type: str, message_data: dict):
    """Route message to specific n8n workflow based on tier"""
    try:
        webhook_url = WEBHOOK_ENDPOINTS.get(workflow_type)
        if not webhook_url:
            print(f"[ERROR] Unknown workflow type: {workflow_type}")
            return False
            
        # Prepare payload for n8n
        payload = {
            "workflow_type": workflow_type,
            "message_data": message_data,
            "timestamp": datetime.utcnow().isoformat(),
            "mcp_server": "satya-telegram-mcp.onrender.com"
        }
        
        print(f"[ROUTE] Sending to {workflow_type} workflow")
        print(f"[PAYLOAD] {json.dumps(payload, indent=2)}")
        
        # Make actual HTTP call to n8n webhook
        timeout = aiohttp.ClientTimeout(total=10)  # 10 second timeout
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(webhook_url, json=payload) as response:
                if response.status == 200:
                    response_text = await response.text()
                    print(f"[SUCCESS] n8n webhook response: {response_text}")
                    return True
                else:
                    print(f"[ERROR] n8n webhook failed: {response.status}")
                    return False
        
    except asyncio.TimeoutError:
        print(f"[ERROR] Timeout calling n8n webhook for {workflow_type}")
        return False
    except Exception as e:
        print(f"[ERROR] Failed to route to n8n workflow {workflow_type}: {e}")
        traceback.print_exc()
        return False

async def store_message_locally(message_data: dict, storage_type: str = "log"):
    """Store message locally for logging/backup purposes"""
    try:
        # Add storage metadata
        storage_record = {
            **message_data,
            "storage_type": storage_type,
            "stored_timestamp": datetime.utcnow().isoformat(),
            "mcp_version": "v1.0"
        }
        
        # For now, just pretty print to console
        # TODO: Replace with actual database/file storage
        print(f"[STORAGE] {storage_type.upper()} - Message stored:")
        print(f"{json.dumps(storage_record, indent=2)}")
        
        # TODO: Implement actual storage
        """
        # Option 1: File-based storage
        log_file = f"telegram_messages_{datetime.now().strftime('%Y%m%d')}.jsonl"
        with open(log_file, 'a') as f:
            f.write(json.dumps(storage_record) + '\n')
            
        # Option 2: SQLite database storage
        # INSERT INTO telegram_messages (...) VALUES (...)
        """
        
        return True
        
    except Exception as e:
        print(f"[ERROR] Failed to store message locally: {e}")
        traceback.print_exc()
        return False

async def handle_routing_failure(message_data: dict, intended_workflow: str, error: str):
    """Handle cases where routing to n8n fails - ensure no message is lost"""
    try:
        print(f"[FALLBACK] Routing to {intended_workflow} failed: {error}")
        
        # Always store the message locally as fallback
        fallback_data = {
            **message_data,
            "intended_workflow": intended_workflow,
            "routing_error": error,
            "fallback_timestamp": datetime.utcnow().isoformat()
        }
        
        await store_message_locally(fallback_data, "fallback")
        
        # If super-user message failed, try to notify via logs
        if intended_workflow == "superuser":
            print(f"[CRITICAL] Super-user message routing failed! Message stored for manual review.")
            
        return True
        
    except Exception as e:
        print(f"[CRITICAL] Even fallback handling failed: {e}")
        return False

async def route_with_fallback(workflow_type: str, message_data: dict):
    """Route to n8n with comprehensive fallback handling"""
    try:
        # Attempt primary routing
        success = await route_to_n8n_workflow(workflow_type, message_data)
        
        if success:
            # Also store locally for backup/analysis
            await store_message_locally(message_data, workflow_type)
            return True
        else:
            # Handle routing failure
            await handle_routing_failure(message_data, workflow_type, "n8n webhook failed")
            return False
            
    except Exception as e:
        # Handle any unexpected errors
        await handle_routing_failure(message_data, workflow_type, str(e))
        return False

# ===============================================================================
# DYNAMIC FILTERING MANAGEMENT - MCP TOOLS
# ===============================================================================

@mcp.tool()
async def enable_workflow(workflow_type: str, chat_id: int = None) -> str:
    """
    Enable a SATYA workflow globally or for a specific chat.
    
    Args:
        workflow_type: Type of workflow ('agent', 'chatbot', 'mention', 'logging')
        chat_id: Optional chat ID for chat-specific enablement
    """
    try:
        valid_workflows = ['agent', 'chatbot', 'mention', 'logging']
        if workflow_type not in valid_workflows:
            return f"Invalid workflow type. Valid options: {valid_workflows}"
        
        if chat_id is None:
            # Enable globally
            FILTERING_RULES["workflow_states"][workflow_type] = True
            result = f"✅ Enabled {workflow_type} workflow globally"
        else:
            # Enable for specific chat
            if workflow_type == 'agent':
                if chat_id not in FILTERING_RULES["agent_enabled_chats"]:
                    FILTERING_RULES["agent_enabled_chats"].append(chat_id)
                result = f"✅ Enabled {workflow_type} workflow for chat {chat_id}"
            elif workflow_type == 'chatbot':
                if chat_id not in FILTERING_RULES["chatbot_enabled_chats"]:
                    FILTERING_RULES["chatbot_enabled_chats"].append(chat_id)
                result = f"✅ Enabled {workflow_type} workflow for chat {chat_id}"
            else:
                result = f"❌ Chat-specific enablement only available for 'agent' and 'chatbot' workflows"
        
        print(f"[ADMIN] {result}")
        return result
        
    except Exception as e:
        error_msg = f"❌ Failed to enable workflow: {e}"
        print(f"[ERROR] {error_msg}")
        return error_msg

@mcp.tool()
async def disable_workflow(workflow_type: str, chat_id: int = None) -> str:
    """
    Disable a SATYA workflow globally or for a specific chat.
    
    Args:
        workflow_type: Type of workflow ('agent', 'chatbot', 'mention', 'logging')
        chat_id: Optional chat ID for chat-specific disabling
    """
    try:
        valid_workflows = ['agent', 'chatbot', 'mention', 'logging']
        if workflow_type not in valid_workflows:
            return f"Invalid workflow type. Valid options: {valid_workflows}"
        
        # Protect super-user workflow
        if workflow_type == 'superuser':
            return "❌ Cannot disable super-user workflow (security protection)"
        
        if chat_id is None:
            # Disable globally
            FILTERING_RULES["workflow_states"][workflow_type] = False
            result = f"🔒 Disabled {workflow_type} workflow globally"
        else:
            # Disable for specific chat
            if workflow_type == 'agent':
                if chat_id in FILTERING_RULES["agent_enabled_chats"]:
                    FILTERING_RULES["agent_enabled_chats"].remove(chat_id)
                result = f"🔒 Disabled {workflow_type} workflow for chat {chat_id}"
            elif workflow_type == 'chatbot':
                if chat_id in FILTERING_RULES["chatbot_enabled_chats"]:
                    FILTERING_RULES["chatbot_enabled_chats"].remove(chat_id)
                result = f"🔒 Disabled {workflow_type} workflow for chat {chat_id}"
            else:
                result = f"❌ Chat-specific disabling only available for 'agent' and 'chatbot' workflows"
        
        print(f"[ADMIN] {result}")
        return result
        
    except Exception as e:
        error_msg = f"❌ Failed to disable workflow: {e}"
        print(f"[ERROR] {error_msg}")
        return error_msg

@mcp.tool()
async def get_workflow_status() -> str:
    """Get current status of all SATYA workflows and filtering rules."""
    try:
        status_report = {
            "workflow_states": FILTERING_RULES["workflow_states"].copy(),
            "super_user_id": SUPER_USER_ID,
            "blocked_users": len(FILTERING_RULES["blocked_users"]),
            "blocked_chats": len(FILTERING_RULES["blocked_chats"]),
            "allowed_groups": len(FILTERING_RULES["allowed_groups"]),
            "agent_enabled_chats": FILTERING_RULES["agent_enabled_chats"].copy(),
            "chatbot_enabled_chats": FILTERING_RULES["chatbot_enabled_chats"].copy(),
        }
        
        formatted_status = f"""
🤖 SATYA Telegram MCP - Workflow Status Report

🔧 Global Workflow States:
  • Super-user: {'✅ ENABLED' if FILTERING_RULES['workflow_states']['superuser'] else '🔒 DISABLED'}
  • Agent Mode: {'✅ ENABLED' if FILTERING_RULES['workflow_states']['agent'] else '🔒 DISABLED'}
  • Chatbot Mode: {'✅ ENABLED' if FILTERING_RULES['workflow_states']['chatbot'] else '🔒 DISABLED'}
  • Mention Detection: {'✅ ENABLED' if FILTERING_RULES['workflow_states']['mention'] else '🔒 DISABLED'}
  • Message Logging: {'✅ ENABLED' if FILTERING_RULES['workflow_states']['logging'] else '🔒 DISABLED'}

👤 Super-user ID: {SUPER_USER_ID}

🚫 Filtering Rules:
  • Blocked Users: {len(FILTERING_RULES['blocked_users'])}
  • Blocked Chats: {len(FILTERING_RULES['blocked_chats'])}
  • Allowed Groups: {len(FILTERING_RULES['allowed_groups'])}

🎯 Chat-Specific Enablement:
  • Agent-enabled Chats: {len(FILTERING_RULES['agent_enabled_chats'])}
  • Chatbot-enabled Chats: {len(FILTERING_RULES['chatbot_enabled_chats'])}
"""
        
        print(f"[STATUS] Workflow status requested")
        return formatted_status.strip()
        
    except Exception as e:
        error_msg = f"❌ Failed to get workflow status: {e}"
        print(f"[ERROR] {error_msg}")
        return error_msg

@mcp.tool()
async def add_blocked_user(user_id: int, reason: str = "manual block") -> str:
    """
    Add a user to the blocked list (junk filter).
    
    Args:
        user_id: Telegram user ID to block
        reason: Reason for blocking (for logging)
    """
    try:
        if user_id == SUPER_USER_ID:
            return "❌ Cannot block super-user (security protection)"
        
        if user_id not in FILTERING_RULES["blocked_users"]:
            FILTERING_RULES["blocked_users"].append(user_id)
            result = f"🚫 Blocked user {user_id} (reason: {reason})"
        else:
            result = f"ℹ️ User {user_id} already blocked"
        
        print(f"[ADMIN] {result}")
        return result
        
    except Exception as e:
        error_msg = f"❌ Failed to block user: {e}"
        print(f"[ERROR] {error_msg}")
        return error_msg

@mcp.tool()
async def remove_blocked_user(user_id: int) -> str:
    """
    Remove a user from the blocked list.
    
    Args:
        user_id: Telegram user ID to unblock
    """
    try:
        if user_id in FILTERING_RULES["blocked_users"]:
            FILTERING_RULES["blocked_users"].remove(user_id)
            result = f"✅ Unblocked user {user_id}"
        else:
            result = f"ℹ️ User {user_id} was not blocked"
        
        print(f"[ADMIN] {result}")
        return result
        
    except Exception as e:
        error_msg = f"❌ Failed to unblock user: {e}"
        print(f"[ERROR] {error_msg}")
        return error_msg

@mcp.tool()
async def add_allowed_group(chat_id: int, description: str = "manual addition") -> str:
    """
    Add a group to the allowed groups list.
    
    Args:
        chat_id: Telegram chat ID to allow
        description: Description of the group (for logging)
    """
    try:
        if chat_id not in FILTERING_RULES["allowed_groups"]:
            FILTERING_RULES["allowed_groups"].append(chat_id)
            result = f"✅ Added allowed group {chat_id} ({description})"
        else:
            result = f"ℹ️ Group {chat_id} already in allowed list"
        
        print(f"[ADMIN] {result}")
        return result
        
    except Exception as e:
        error_msg = f"❌ Failed to add allowed group: {e}"
        print(f"[ERROR] {error_msg}")
        return error_msg

@mcp.tool()
async def remove_allowed_group(chat_id: int) -> str:
    """
    Remove a group from the allowed groups list.
    
    Args:
        chat_id: Telegram chat ID to remove
    """
    try:
        if chat_id in FILTERING_RULES["allowed_groups"]:
            FILTERING_RULES["allowed_groups"].remove(chat_id)
            result = f"🔒 Removed group {chat_id} from allowed list"
        else:
            result = f"ℹ️ Group {chat_id} was not in allowed list"
        
        print(f"[ADMIN] {result}")
        return result
        
    except Exception as e:
        error_msg = f"❌ Failed to remove allowed group: {e}"
        print(f"[ERROR] {error_msg}")
        return error_msg

@mcp.tool()
async def update_super_user(new_user_id: int) -> str:
    """
    Update the super-user ID (USE WITH EXTREME CAUTION).
    
    Args:
        new_user_id: New Telegram user ID for super-user privileges
    """
    try:
        global SUPER_USER_ID
        old_user_id = SUPER_USER_ID
        SUPER_USER_ID = new_user_id
        
        result = f"⚠️ CRITICAL: Super-user changed from {old_user_id} to {new_user_id}"
        print(f"[CRITICAL] {result}")
        return result
        
    except Exception as e:
        error_msg = f"❌ Failed to update super-user: {e}"
        print(f"[ERROR] {error_msg}")
        return error_msg

@mcp.tool()
async def get_filtering_rules() -> str:
    """Get complete filtering rules configuration (for backup/analysis)."""
    try:
        rules_data = {
            "super_user_id": SUPER_USER_ID,
            "filtering_rules": FILTERING_RULES.copy(),
            "webhook_endpoints": WEBHOOK_ENDPOINTS.copy(),
            "timestamp": datetime.utcnow().isoformat()
        }
        
        print(f"[ADMIN] Filtering rules exported")
        return json.dumps(rules_data, indent=2)
        
    except Exception as e:
        error_msg = f"❌ Failed to get filtering rules: {e}"
        print(f"[ERROR] {error_msg}")
        return error_msg

@mcp.tool()
async def emergency_reset_workflows() -> str:
    """
    Emergency reset: disable all workflows except super-user and logging.
    USE ONLY IN EMERGENCY SITUATIONS.
    """
    try:
        # Reset to safe defaults
        FILTERING_RULES["workflow_states"].update({
            "superuser": True,   # Keep super-user enabled
            "agent": False,      # Disable agent mode
            "chatbot": False,    # Disable chatbot mode
            "mention": False,    # Disable mention detection
            "logging": True      # Keep logging enabled
        })
        
        # Clear chat-specific enablements
        FILTERING_RULES["agent_enabled_chats"].clear()
        FILTERING_RULES["chatbot_enabled_chats"].clear()
        
        result = "🚨 EMERGENCY RESET: All workflows disabled except super-user and logging"
        print(f"[EMERGENCY] {result}")
        return result
        
    except Exception as e:
        error_msg = f"❌ Failed to perform emergency reset: {e}"
        print(f"[ERROR] {error_msg}")
        return error_msg

# ===============================================================================


async def _telegram_runner():
    await client.start()
    me = await client.get_me()
    print(f"[TG] Signed in as {me.username or me.first_name} ({me.id})")
    await client.run_until_disconnected()



def _start_telegram():
    asyncio.run(_telegram_runner())

@client.on(events.NewMessage)
async def intelligent_message_router(event):
    """Master message router - processes all messages through 5-tier filtering system"""
    
    # PRESERVE EXISTING LOGGING (non-breaking)
    print(f"[TG] ↪️  Msg from {event.sender_id} in {event.chat_id}: {event.raw_text!r}")
    
    try:
        # STEP 1: Capture structured message data
        message_data = await capture_structured_message_data(event)
        
        # STEP 2: TIER 0 - Junk Filter (block immediately, no processing)
        if await is_junk_message(event, message_data):
            print(f"[FILTER] Junk message blocked from {event.sender_id}")
            return  # Stop processing - no storage, no n8n calls
        
        # STEP 3: TIER 5 - Super-User (highest priority)
        if await should_trigger_superuser_workflow(event, message_data):
            print(f"[PRIORITY] Super-user message - routing to priority workflow")
            await route_with_fallback("superuser", message_data)
            return  # Super-user messages get exclusive handling
        
        # STEP 4: TIER 4 - Agent Mode (complex tasks)
        if await should_trigger_agent_workflow(event, message_data):
            print(f"[AGENT] Complex task detected - routing to agent workflow")
            await route_with_fallback("agent", message_data)
            return  # Agent-level processing complete
        
        # STEP 5: TIER 3 - Chatbot Mode (conversational)
        if await should_trigger_chatbot_workflow(event, message_data):
            print(f"[CHATBOT] Social message detected - routing to chatbot workflow")
            await route_with_fallback("chatbot", message_data)
            return  # Chatbot processing complete
        
        # STEP 6: TIER 2 - Mention Detection (basic acknowledgment)
        if await should_trigger_mention_workflow(event, message_data):
            print(f"[MENTION] Direct mention detected - routing to mention workflow")
            await route_with_fallback("mention", message_data)
            return  # Mention processing complete
        
        # STEP 7: TIER 1 - Log Only (storage, no n8n call)
        if await should_log_only(event, message_data):
            print(f"[LOG] Message logged for analysis")
            await store_message_locally(message_data, "log")
            return  # Logging complete
        
        # STEP 8: DEFAULT - Unhandled message type
        print(f"[UNHANDLED] Message from {event.sender_id} - no tier matched")
        # Store unhandled messages for analysis
        await store_message_locally(message_data, "unhandled")
        
    except Exception as e:
        print(f"[CRITICAL] Message router failed: {e}")
        traceback.print_exc()
        
        # CRITICAL FALLBACK - ensure no message is completely lost
        try:
            fallback_data = {
                "sender_id": event.sender_id,
                "chat_id": event.chat_id,
                "message_text": event.raw_text or "",
                "timestamp": datetime.utcnow().isoformat(),
                "router_error": str(e),
                "critical_fallback": True
            }
            await store_message_locally(fallback_data, "critical_error")
            print(f"[RECOVERY] Message saved to critical error log")
        except Exception as critical_error:
            print(f"[FATAL] Even critical fallback failed: {critical_error}")
            # At this point, just ensure the original logging happens
            print(f"[FATAL-LOG] Original message: {event.raw_text!r} from {event.sender_id}")


if __name__ == "__main__":
    threading.Thread(target=_start_telegram, name="tg-loop", daemon=True).start()

    try:
        # FastMCP exposes the ASGI app here
        app = mcp.streamable_http_app()

        uvicorn.run(
            app,
            host="0.0.0.0",
            port=int(os.environ["PORT"]),
            log_level="info",
        )
    except Exception:
        traceback.print_exc()
        sys.exit(1)
