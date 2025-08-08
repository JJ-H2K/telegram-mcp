import os, threading, asyncio, traceback, sys, uvicorn
import json, aiohttp
from datetime import datetime, timedelta
from main import client, mcp, send_message
from telethon import events

# ===============================================================================
# SATYA PUBLIC GROUP ROUTING SYSTEM - FOCUSED IMPLEMENTATION
# ===============================================================================

# Configuration from environment
SUPER_USER_ID = int(os.getenv("SUPER_USER_TELEGRAM_ID", "0"))
SATYA_GROUP_PUBLIC = -1002536132364  # Public group ID
BOT_USERNAME = "satya_agent"  # Bot username (without @)

# Burst coalescing settings
DIRECT_COALESCE_SECONDS = 30  # Direct messages burst coalescing
MENTIONS_COALESCE_SECONDS = 60  # Mentions burst coalescing

# Burst tracking storage
burst_tracker = {
    "direct_messages": [],  # List of pending direct messages
    "mentions": [],         # List of pending mentions
    "last_direct_send": None,
    "last_mention_send": None,
    "direct_timer": None,
    "mention_timer": None
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
# PUBLIC GROUP MESSAGE DETECTION FUNCTIONS
# ===============================================================================

def is_from_public_group(event):
    """Check if message is from the monitored public group"""
    return event.chat_id == SATYA_GROUP_PUBLIC

def is_superuser_message(event):
    """Check if message is from superuser (always priority)"""
    return event.sender_id == SUPER_USER_ID

def is_direct_to_satya(event, message_data):
    """
    Check if message is direct to SATYA:
    - Contains @satya_agent
    - Is a reply to SATYA's messages
    """
    try:
        text = message_data["message_text"].lower()
        
        # Check for @satya_agent mention
        if f"@{BOT_USERNAME.lower()}" in text:
            print(f"[DIRECT] @{BOT_USERNAME} mention detected from {event.sender_id}")
            return True
            
        # Check if it's a reply to SATYA's message
        if hasattr(event.message, 'reply_to') and event.message.reply_to:
            # We would need to check if the reply is to our bot's message
            # For now, we'll mark replies as potential direct messages
            print(f"[DIRECT] Reply detected from {event.sender_id}")
            return True
            
        return False
        
    except Exception as e:
        print(f"[ERROR] Direct detection failed: {e}")
        return False

def is_mention_about_satya(event, message_data):
    """
    Check if message mentions SATYA but is NOT direct:
    - Contains "satya" (case-insensitive)
    - Does NOT contain @satya_agent
    - Is NOT a reply to SATYA
    """
    try:
        text = message_data["message_text"].lower()
        
        # Skip if it's already a direct message
        if is_direct_to_satya(event, message_data):
            return False
            
        # Check for "satya" mentions
        if "satya" in text:
            print(f"[MENTION] 'satya' mentioned by {event.sender_id}")
            return True
            
        return False
        
    except Exception as e:
        print(f"[ERROR] Mention detection failed: {e}")
        return False

# ===============================================================================
# BURST COALESCING SYSTEM
# ===============================================================================

async def send_coalesced_direct_messages():
    """Send coalesced direct messages after burst period"""
    try:
        if not burst_tracker["direct_messages"]:
            return
            
        # Prepare coalesced payload
        messages = burst_tracker["direct_messages"].copy()
        burst_tracker["direct_messages"].clear()
        burst_tracker["last_direct_send"] = datetime.utcnow()
        burst_tracker["direct_timer"] = None
        
        print(f"[COALESCE] Sending {len(messages)} additional direct messages as follow-up")
        
        # Create coalesced payload
        coalesced_payload = {
            "workflow_type": f"group_{SATYA_GROUP_PUBLIC}_chatbot",
            "burst_mode": True,
            "message_count": len(messages),
            "messages": messages,
            "timestamp": datetime.utcnow().isoformat(),
            "chat_id": SATYA_GROUP_PUBLIC,
            "is_follow_up": True
        }
        
        await route_to_n8n_workflow(f"group_{SATYA_GROUP_PUBLIC}_chatbot", coalesced_payload)
        
    except Exception as e:
        print(f"[ERROR] Failed to send coalesced direct messages: {e}")

async def send_coalesced_mentions():
    """Send coalesced mentions after burst period"""
    try:
        if not burst_tracker["mentions"]:
            return
            
        # Prepare coalesced payload
        messages = burst_tracker["mentions"].copy()
        burst_tracker["mentions"].clear()
        burst_tracker["last_mention_send"] = datetime.utcnow()
        burst_tracker["mention_timer"] = None
        
        print(f"[COALESCE] Sending {len(messages)} additional mentions as follow-up")
        
        # Create coalesced payload
        coalesced_payload = {
            "workflow_type": f"group_{SATYA_GROUP_PUBLIC}_mentions",
            "burst_mode": True,
            "message_count": len(messages),
            "messages": messages,
            "timestamp": datetime.utcnow().isoformat(),
            "chat_id": SATYA_GROUP_PUBLIC,
            "is_follow_up": True
        }
        
        await route_to_n8n_workflow(f"group_{SATYA_GROUP_PUBLIC}_mentions", coalesced_payload)
        
    except Exception as e:
        print(f"[ERROR] Failed to send coalesced mentions: {e}")

async def handle_direct_message(message_data):
    """Handle direct message: immediate first, coalesce additional"""
    try:
        # Check if this is the first message in a while
        now = datetime.utcnow()
        is_first_message = (
            burst_tracker["last_direct_send"] is None or 
            (now - burst_tracker["last_direct_send"]).total_seconds() > DIRECT_COALESCE_SECONDS
        )
        
        if is_first_message:
            # Send immediate response for first message
            print(f"[IMMEDIATE] First direct message - sending immediately")
            await route_with_fallback(f"group_{SATYA_GROUP_PUBLIC}_chatbot", {
                **message_data,
                "workflow_type": f"group_{SATYA_GROUP_PUBLIC}_chatbot",
                "burst_mode": False,
                "message_count": 1,
                "is_first_in_burst": True
            })
            burst_tracker["last_direct_send"] = now
            
            # Start timer for additional messages
            if burst_tracker["direct_timer"] is None:
                print(f"[COALESCE] Starting timer for additional direct messages ({DIRECT_COALESCE_SECONDS}s)")
                burst_tracker["direct_timer"] = asyncio.create_task(
                    asyncio.sleep(DIRECT_COALESCE_SECONDS)
                )
                
                # Wait for timer and send any additional messages
                await burst_tracker["direct_timer"]
                if burst_tracker["direct_messages"]:
                    await send_coalesced_direct_messages()
                burst_tracker["direct_timer"] = None
        else:
            # Add to burst queue for follow-up response
            print(f"[COALESCE] Adding to direct message burst queue")
            burst_tracker["direct_messages"].append(message_data)
        
    except Exception as e:
        print(f"[ERROR] Failed to handle direct message: {e}")

async def handle_mention_message(message_data):
    """Handle mention message: immediate first, coalesce additional"""
    try:
        # Check if this is the first message in a while
        now = datetime.utcnow()
        is_first_message = (
            burst_tracker["last_mention_send"] is None or 
            (now - burst_tracker["last_mention_send"]).total_seconds() > MENTIONS_COALESCE_SECONDS
        )
        
        if is_first_message:
            # Send immediate response for first message
            print(f"[IMMEDIATE] First mention - sending immediately")
            await route_with_fallback(f"group_{SATYA_GROUP_PUBLIC}_mentions", {
                **message_data,
                "workflow_type": f"group_{SATYA_GROUP_PUBLIC}_mentions",
                "burst_mode": False,
                "message_count": 1,
                "is_first_in_burst": True
            })
            burst_tracker["last_mention_send"] = now
            
            # Start timer for additional messages
            if burst_tracker["mention_timer"] is None:
                print(f"[COALESCE] Starting timer for additional mentions ({MENTIONS_COALESCE_SECONDS}s)")
                burst_tracker["mention_timer"] = asyncio.create_task(
                    asyncio.sleep(MENTIONS_COALESCE_SECONDS)
                )
                
                # Wait for timer and send any additional messages
                await burst_tracker["mention_timer"]
                if burst_tracker["mentions"]:
                    await send_coalesced_mentions()
                burst_tracker["mention_timer"] = None
        else:
            # Add to burst queue for follow-up response
            print(f"[COALESCE] Adding to mention burst queue")
            burst_tracker["mentions"].append(message_data)
        
    except Exception as e:
        print(f"[ERROR] Failed to handle mention message: {e}")

# ===============================================================================
# WORKFLOW ROUTING SYSTEM
# ===============================================================================

# n8n webhook endpoints configuration
N8N_WEBHOOK_BASE_URL = os.getenv("N8N_WEBHOOK_BASE_URL", "https://your-n8n-instance.com")
WEBHOOK_ENDPOINTS = {
    "superuser": f"{N8N_WEBHOOK_BASE_URL}/webhook/satya/superuser",
    f"group_{SATYA_GROUP_PUBLIC}_chatbot": f"{N8N_WEBHOOK_BASE_URL}/webhook/satya/group/{SATYA_GROUP_PUBLIC}/chatbot", 
    f"group_{SATYA_GROUP_PUBLIC}_mentions": f"{N8N_WEBHOOK_BASE_URL}/webhook/satya/group/{SATYA_GROUP_PUBLIC}/mentions"
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
# SIMPLE ADMIN TOOLS FOR PUBLIC GROUP
# ===============================================================================

@mcp.tool()
async def get_public_group_status() -> str:
    """Get current status of SATYA public group monitoring."""
    try:
        status_report = f"""
🤖 SATYA Public Group Status Report

📍 Public Group: {SATYA_GROUP_PUBLIC}
👤 Superuser ID: {SUPER_USER_ID}
🤖 Bot Username: @{BOT_USERNAME}

⏱️ Burst Coalescing:
  • Direct Messages: {DIRECT_COALESCE_SECONDS}s
  • Mentions: {MENTIONS_COALESCE_SECONDS}s

📊 Current Burst Status:
  • Pending Direct: {len(burst_tracker['direct_messages'])}
  • Pending Mentions: {len(burst_tracker['mentions'])}
  • Direct Timer Active: {'Yes' if burst_tracker['direct_timer'] else 'No'}
  • Mention Timer Active: {'Yes' if burst_tracker['mention_timer'] else 'No'}

🔗 Webhook Endpoints:
  • Superuser: {WEBHOOK_ENDPOINTS['superuser']}
  • Group {SATYA_GROUP_PUBLIC} Chatbot: {WEBHOOK_ENDPOINTS[f'group_{SATYA_GROUP_PUBLIC}_chatbot']}
  • Group {SATYA_GROUP_PUBLIC} Mentions: {WEBHOOK_ENDPOINTS[f'group_{SATYA_GROUP_PUBLIC}_mentions']}
"""
        
        print(f"[STATUS] Public group status requested")
        return status_report.strip()
        
    except Exception as e:
        error_msg = f"❌ Failed to get status: {e}"
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
async def force_send_pending_messages() -> str:
    """
    Force send all pending messages immediately (bypass coalescing).
    """
    try:
        direct_count = len(burst_tracker["direct_messages"])
        mention_count = len(burst_tracker["mentions"])
        
        if direct_count > 0:
            await send_coalesced_direct_messages()
        
        if mention_count > 0:
            await send_coalesced_mentions()
        
        result = f"✅ Force-sent {direct_count} direct messages and {mention_count} mentions"
        print(f"[ADMIN] {result}")
        return result
        
    except Exception as e:
        error_msg = f"❌ Failed to force send messages: {e}"
        print(f"[ERROR] {error_msg}")
        return error_msg

# ===============================================================================


# Global variable to store the telegram event loop
telegram_loop = None

async def _telegram_runner():
    global telegram_loop
    telegram_loop = asyncio.get_event_loop()
    
    await client.start()
    me = await client.get_me()
    print(f"[TG] Signed in as {me.username or me.first_name} ({me.id})")
    await client.run_until_disconnected()

def _start_telegram():
    asyncio.run(_telegram_runner())

@client.on(events.NewMessage)
async def public_group_message_router(event):
    """Focused message router for SATYA public group with burst coalescing"""
    
    # PRESERVE EXISTING LOGGING
    print(f"[TG] ↪️  Msg from {event.sender_id} in {event.chat_id}: {event.raw_text!r}")
    
    try:
        # STEP 1: Only process messages from public group or superuser
        if not is_from_public_group(event) and not is_superuser_message(event):
            print(f"[IGNORE] Message not from public group or superuser: {event.chat_id}")
            return
        
        # STEP 2: Capture structured message data
        message_data = await capture_structured_message_data(event)
        
        # STEP 3: SUPERUSER always gets immediate response (override burst coalescing)
        if is_superuser_message(event):
            print(f"[SUPERUSER] Priority message from {event.sender_id}")
            await route_with_fallback("superuser", message_data)
            return
        
        # STEP 4: Check if direct message to SATYA
        if is_direct_to_satya(event, message_data):
            print(f"[DIRECT] Direct message to SATYA from {event.sender_id}")
            # Use burst coalescing for direct messages
            asyncio.create_task(handle_direct_message(message_data))
            return
        
        # STEP 5: Check if mention about SATYA  
        if is_mention_about_satya(event, message_data):
            print(f"[MENTION] Mention about SATYA from {event.sender_id}")
            # Use burst coalescing for mentions
            asyncio.create_task(handle_mention_message(message_data))
            return
        
        # STEP 6: Ignore all other messages from public group
        print(f"[IGNORE] No SATYA trigger detected from {event.sender_id}")
        
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
            print(f"[FATAL-LOG] Original message: {event.raw_text!r} from {event.sender_id}")


# ===============================================================================
# REST API ENDPOINTS FOR N8N INTEGRATION  
# ===============================================================================

# Add REST endpoint using FastMCP's custom route system
@mcp.custom_route("/send_telegram_message", methods=["POST"])
async def send_telegram_message_rest(request):
    """
    Simple REST endpoint for n8n to send Telegram messages.
    This bypasses MCP protocol for easier integration.
    
    POST /send_telegram_message
    Body: {"chat_id": 123456, "message": "Hello from SATYA!"}
    """
    try:
        # Parse JSON from request body
        request_data = await request.json()
        
        # Extract data from request
        chat_id = request_data.get("chat_id")
        message = request_data.get("message")
        
        if not chat_id or not message:
            from starlette.responses import JSONResponse
            return JSONResponse({
                "success": False, 
                "error": "Missing required fields: chat_id and message"
            }, status_code=400)
        
        print(f"[REST] Sending message to chat {chat_id}: {message}")
        
        # Call the MCP tool in the correct event loop
        if telegram_loop is None:
            result = "Error: Telegram client not ready"
        else:
            future = asyncio.run_coroutine_threadsafe(
                send_message(chat_id, message), 
                telegram_loop
            )
            result = future.result(timeout=30)  # 30 second timeout
        
        print(f"[REST] Message sent successfully: {result}")
        
        from starlette.responses import JSONResponse
        return JSONResponse({
            "success": True, 
            "result": result,
            "chat_id": chat_id,
            "message": message
        })
        
    except Exception as e:
        error_msg = f"Failed to send message: {str(e)}"
        print(f"[REST ERROR] {error_msg}")
        
        from starlette.responses import JSONResponse
        return JSONResponse({
            "success": False,
            "error": error_msg
        }, status_code=500)

# Health check endpoint
@mcp.custom_route("/health", methods=["GET"])
async def health_check(request):
    """Health check endpoint for monitoring"""
    from starlette.responses import JSONResponse
    return JSONResponse({"status": "healthy", "service": "satya-telegram-mcp"})

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
