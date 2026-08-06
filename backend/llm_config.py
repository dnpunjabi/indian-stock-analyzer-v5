import os
import base64
import json
import sqlite3
import threading
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Task-type constants for hybrid routing
TASK_HEAVY = "heavy"   # CFA Fundamentals, CIO Synthesis, Portfolio Doctor
TASK_FAST  = "fast"    # Co-Pilot Chat, Sentiment, Technical, News synthesis

# Dynamic Key Rotation State Manager Structures
_rotation_lock = threading.Lock()
_active_key_index = 0

GEMINI_KEYS_COOLDOWN = {}   # key_mask -> datetime
GEMINI_KEYS_BLACKLIST = set() # key_mask

def _decode_key(encoded_str: str) -> str:
    if not encoded_str:
        return ""
    try:
        if encoded_str.startswith("b64_"):
            return base64.b64decode(encoded_str[4:].encode("utf-8")).decode("utf-8")
        return encoded_str
    except Exception:
        return encoded_str

def _mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) < 10:
        return f"{key[:3]}...{key[-3:]}" if len(key) > 6 else key
    return f"{key[:6]}...{key[-4:]}"

def _get_gemini_keys_pool() -> list:
    """Aggregates all Gemini keys from environment variables and the database."""
    pool = []
    
    # 1. Load from environment variables (GEMINI_API_KEY, GEMINI_API_KEY_1, GEMINI_API_KEY_99, etc.)
    for k, v in os.environ.items():
        if k.startswith("GEMINI_API_KEY"):
            val = v.strip()
            if val and val not in pool:
                pool.append(val)
        
    # 2. Load from SQLite database
    db_dir = os.environ.get("DATABASE_DIR", os.path.join(os.path.dirname(__file__), "data"))
    db_path = os.path.join(db_dir, "watchlist_database.db")
    
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM alert_settings WHERE key = 'gemini_keys_pool'")
            row = cursor.fetchone()
            if row and row["value"]:
                encoded_list = json.loads(row["value"])
                if isinstance(encoded_list, list):
                    for k in encoded_list:
                        decoded = _decode_key(k)
                        if decoded and decoded not in pool:
                            pool.append(decoded)
            conn.close()
        except Exception as e:
            print(f"[LLM Rotation] Error loading keys from database: {e}")
            
    return pool

def get_gemini_keys_health() -> list:
    """Returns the masked status of all configured keys for dynamic health API."""
    keys = _get_gemini_keys_pool()
    health_list = []
    now = datetime.now()
    
    with _rotation_lock:
        for k in keys:
            mask = _mask_key(k)
            status = "active"
            cooldown_rem = 0
            
            if mask in GEMINI_KEYS_BLACKLIST:
                status = "blacklisted"
            elif mask in GEMINI_KEYS_COOLDOWN:
                rem = (GEMINI_KEYS_COOLDOWN[mask] - now).total_seconds()
                if rem > 0:
                    status = "cooldown"
                    cooldown_rem = int(rem)
                else:
                    # Cooldown expired
                    GEMINI_KEYS_COOLDOWN.pop(mask, None)
                    
            health_list.append({
                "masked_key": mask,
                "status": status,
                "cooldown_remaining": cooldown_rem
            })
            
    return health_list

def _select_gemini_key(keys: list) -> tuple:
    """Selects the next available key that is not blacklisted and not in cooldown."""
    global _active_key_index
    if not keys:
        return None, None
        
    now = datetime.now()
    
    with _rotation_lock:
        strategy = os.environ.get("GEMINI_ROTATION_STRATEGY", "sequential").lower()
        start_idx = _active_key_index if strategy == "round_robin" else 0
        pool_len = len(keys)
        
        for offset in range(pool_len):
            idx = (start_idx + offset) % pool_len
            candidate_key = keys[idx]
            mask = _mask_key(candidate_key)
            
            if mask in GEMINI_KEYS_BLACKLIST:
                continue
                
            if mask in GEMINI_KEYS_COOLDOWN:
                if GEMINI_KEYS_COOLDOWN[mask] > now:
                    continue
                else:
                    GEMINI_KEYS_COOLDOWN.pop(mask, None)
                    
            if strategy == "round_robin":
                _active_key_index = (idx + 1) % pool_len
            else:
                _active_key_index = idx
                
            return candidate_key, mask
            
    return None, None

def _format_model_label(model_id: str) -> str:
    if not model_id:
        return "Gemini"
    name = model_id.split("/")[-1]
    parts = [p.capitalize() if p not in ("pro", "flash", "lite") else p.title() for p in name.split("-")]
    label = " ".join(parts)
    if "Gemini" not in label:
        label = "Gemini " + label
    return label

def _get_config():
    """Dynamically load and return configuration from environment variables."""
    from dotenv import load_dotenv
    load_dotenv(override=True)
    
    provider = os.environ.get("LLM_PROVIDER", "groq").lower()
    base_url = os.environ.get("LLM_BASE_URL", "")
    api_key = os.environ.get("LLM_API_KEY", "") or os.environ.get("GROQ_API_KEY", "")
    
    if provider == "gemini":
        heavy_model = os.environ.get("GEMINI_HEAVY_MODEL", "gemini-1.5-pro")
        fast_model = os.environ.get("GEMINI_FAST_MODEL", "gemini-1.5-flash")
        heavy_label = _format_model_label(heavy_model)
        fast_label = _format_model_label(fast_model)
    else:
        heavy_model = os.environ.get("LLM_HEAVY_MODEL", "llama-3.3-70b-versatile")
        fast_model = os.environ.get("LLM_FAST_MODEL", "llama-3.3-70b-versatile")
        heavy_label = os.environ.get("LLM_HEAVY_LABEL", "Groq Llama 3.3 70B")
        fast_label = os.environ.get("LLM_FAST_LABEL", "Groq Llama 3.3 70B")
    
    temperature = float(os.environ.get("LLM_TEMPERATURE", "0.2"))
    
    return {
        "provider": provider,
        "base_url": base_url,
        "api_key": api_key,
        "heavy_model": heavy_model,
        "fast_model": fast_model,
        "heavy_label": heavy_label,
        "fast_label": fast_label,
        "temperature": temperature
    }

# Client cache references
_cached_client = None
_cached_key = None
_cached_provider = None
_cached_base_url = None

def _get_client(config=None):
    """Return appropriate client, recreating it dynamically if config changes."""
    global _cached_client, _cached_key, _cached_provider, _cached_base_url
    if config is None:
        config = _get_config()
        
    api_key = config["api_key"]
    provider = config["provider"]
    base_url = config["base_url"]
    
    if provider == "gemini":
        class DummyClient:
            pass
        return DummyClient()
        
    # Recreate client if configuration has changed
    if (_cached_client is None or 
        _cached_key != api_key or 
        _cached_provider != provider or 
        _cached_base_url != base_url):
        
        _cached_client = None
        _cached_key = api_key
        _cached_provider = provider
        _cached_base_url = base_url
        
        try:
            if provider == "groq":
                from groq import Groq
                _cached_client = Groq(api_key=api_key) if api_key else Groq()
                print("[LLM Config] Reinitialized Groq client dynamically.")
            else:
                from openai import OpenAI
                if base_url:
                    _cached_client = OpenAI(api_key=api_key, base_url=base_url)
                else:
                    _cached_client = OpenAI(api_key=api_key)
                print(f"[LLM Config] Reinitialized OpenAI client dynamically (base_url={base_url}).")
        except Exception as e:
            print(f"[LLM Config] Error dynamically initializing client: {e}")
            _cached_client = None
            
    return _cached_client

def _call_gemini_with_rotation(task_type: str,
                              system_prompt: str,
                              user_prompt: str = None,
                              max_tokens: int = 2500,
                              messages: list = None,
                              structured_schema: dict = None) -> tuple:
    """
    Executes a content generation request using the Gemini API key pool.
    Rotates keys dynamically on 429 rate limit or 401/403 auth failures.
    Returns (response_text, success_boolean).
    """
    start_time = time.time()
    keys = _get_gemini_keys_pool()
    if not keys:
        return "ERROR: No Gemini API keys configured.", False
        
    config = _get_config()
    model = config["heavy_model"] if task_type == TASK_HEAVY else config["fast_model"]
    temperature = config["temperature"]
    
    contents = []
    gemini_system = system_prompt
    
    if messages:
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")
            if role == "system":
                gemini_system = content
            else:
                role_mapped = "user" if role == "user" else "model"
                contents.append({
                    "role": role_mapped,
                    "parts": [{"text": content}]
                })
    else:
        if user_prompt:
            contents.append({
                "role": "user",
                "parts": [{"text": user_prompt}]
            })
            
    safe_max_tokens = min(16384, max(max_tokens, 4096))
    payload = {
        "contents": contents,
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": safe_max_tokens
        }
    }
    
    if gemini_system:
        payload["systemInstruction"] = {
            "parts": [{"text": gemini_system}]
        }
        
    if structured_schema:
        payload["generationConfig"]["responseMimeType"] = "application/json"
        
    max_attempts = len(keys) * 2
    for attempt in range(max_attempts):
        key, mask = _select_gemini_key(keys)
        if not key:
            return "ERROR_ALL_KEYS_EXHAUSTED: All Gemini API keys are rate-limited or invalid. Falling back.", False
            
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        headers = {"Content-Type": "application/json"}
        
        try:
            print(f"[LLM Rotation] Requesting {model} with key {mask} (Attempt {attempt+1})...")
            res = requests.post(url, headers=headers, json=payload, timeout=25.0)
            
            if res.status_code == 200:
                res_json = res.json()
                if "candidates" in res_json and len(res_json["candidates"]) > 0:
                    candidate = res_json["candidates"][0]
                    finish_reason = candidate.get("finishReason")
                    if finish_reason and finish_reason != "STOP":
                        print(f"[LLM Rotation Warning] Candidate finishReason: {finish_reason}")
                    parts = candidate.get("content", {}).get("parts", [])
                    text = "".join([p.get("text", "") for p in parts if "text" in p and not p.get("thought", False)])
                    if text:
                        label = config["heavy_label"] if task_type == TASK_HEAVY else config["fast_label"]
                        _set_last_llm_meta(label, "gemini", start_time, is_fallback=False)
                        return text, True
                    print(f"[LLM Rotation] No text parts found in Gemini response candidate")

                    
            elif res.status_code == 429:
                print(f"[LLM Rotation] Key {mask} rate-limited (429). Placing on 5s cooldown.")
                with _rotation_lock:
                    GEMINI_KEYS_COOLDOWN[mask] = datetime.now() + timedelta(seconds=5)
                continue
                
            elif res.status_code in [401, 403]:
                print(f"[LLM Rotation] Key {mask} unauthorized/invalid ({res.status_code}). Blacklisting key.")
                with _rotation_lock:
                    GEMINI_KEYS_BLACKLIST.add(mask)
                continue
                
            else:
                print(f"[LLM Rotation] Key {mask} returned status {res.status_code}: {res.text}. Rotating.")
                with _rotation_lock:
                    GEMINI_KEYS_COOLDOWN[mask] = datetime.now() + timedelta(seconds=5)
                continue
                
        except requests.exceptions.RequestException as req_ex:
            print(f"[LLM Rotation] Request failed for key {mask}: {req_ex}. Rotating.")
            with _rotation_lock:
                GEMINI_KEYS_COOLDOWN[mask] = datetime.now() + timedelta(seconds=10)
            continue
            
    return "ERROR: Exceeded maximum key rotation retry attempts.", False

def _stream_gemini_with_rotation(task_type: str,
                                 system_prompt: str,
                                 user_prompt: str = None,
                                 max_tokens: int = 2500,
                                 messages: list = None):
    """
    Executes a streaming content generation request using the Gemini API key pool.
    Yields chunks of text. Rotates keys on failure before streaming starts.
    """
    keys = _get_gemini_keys_pool()
    if not keys:
        yield "ERROR: No Gemini API keys configured."
        return
        
    config = _get_config()
    model = config["heavy_model"] if task_type == TASK_HEAVY else config["fast_model"]
    temperature = config["temperature"]
    
    contents = []
    gemini_system = system_prompt
    
    if messages:
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")
            if role == "system":
                gemini_system = content
            else:
                role_mapped = "user" if role == "user" else "model"
                contents.append({
                    "role": role_mapped,
                    "parts": [{"text": content}]
                })
    else:
        if user_prompt:
            contents.append({
                "role": "user",
                "parts": [{"text": user_prompt}]
            })
            
    safe_max_tokens = min(16384, max(max_tokens, 4096))
    payload = {
        "contents": contents,
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": safe_max_tokens
        }
    }
    
    if gemini_system:
        payload["systemInstruction"] = {
            "parts": [{"text": gemini_system}]
        }
        
    max_attempts = len(keys) * 2
    for attempt in range(max_attempts):
        key, mask = _select_gemini_key(keys)
        if not key:
            yield "ERROR_ALL_KEYS_EXHAUSTED: All Gemini API keys are rate-limited or invalid. Falling back."
            return
            
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?key={key}"
        headers = {"Content-Type": "application/json"}
        
        try:
            print(f"[LLM Rotation] Requesting streaming {model} with key {mask} (Attempt {attempt+1})...")
            res = requests.post(url, headers=headers, json=payload, timeout=30.0, stream=True)
            
            if res.status_code == 200:
                decoder = json.JSONDecoder()
                buffer = ""
                for chunk in res.iter_content(chunk_size=1024, decode_unicode=True):
                    if not chunk:
                        continue
                    buffer += chunk
                    buffer = buffer.strip()
                    
                    if buffer.startswith("["):
                        buffer = buffer[1:].strip()
                    if buffer.startswith(","):
                        buffer = buffer[1:].strip()
                        
                    while buffer:
                        try:
                            obj, idx = decoder.raw_decode(buffer)
                            try:
                                candidate = obj.get("candidates", [{}])[0]
                                finish_reason = candidate.get("finishReason")
                                if finish_reason and finish_reason != "STOP":
                                    print(f"[LLM Stream] Candidate finishReason: {finish_reason}")
                                parts = candidate.get("content", {}).get("parts", [])
                                text_parts = [p.get("text", "") for p in parts if "text" in p and not p.get("thought", False)]
                                text = "".join(text_parts)
                                if text:
                                    yield text
                            except (KeyError, IndexError):
                                pass
                            
                            buffer = buffer[idx:].strip()
                            if buffer.startswith(","):
                                buffer = buffer[1:].strip()
                            if buffer.startswith("]"):
                                buffer = buffer[1:].strip()
                        except json.JSONDecodeError:
                            break

                # Final flush for trailing unparsed buffer
                buffer = buffer.strip()
                if buffer.startswith(","): buffer = buffer[1:].strip()
                if buffer.startswith("]"): buffer = buffer[1:].strip()
                if buffer:
                    try:
                        obj, idx = decoder.raw_decode(buffer)
                        candidate = obj.get("candidates", [{}])[0]
                        parts = candidate.get("content", {}).get("parts", [])
                        text_parts = [p.get("text", "") for p in parts if "text" in p and not p.get("thought", False)]
                        text = "".join(text_parts)
                        if text:
                            yield text
                    except Exception:
                        pass
                return

                
            elif res.status_code == 429:
                print(f"[LLM Rotation] Key {mask} streaming rate-limited (429). Placing on 5s cooldown.")
                with _rotation_lock:
                    GEMINI_KEYS_COOLDOWN[mask] = datetime.now() + timedelta(seconds=5)
                continue
                
            elif res.status_code in [401, 403]:
                print(f"[LLM Rotation] Key {mask} streaming unauthorized ({res.status_code}). Blacklisting key.")
                with _rotation_lock:
                    GEMINI_KEYS_BLACKLIST.add(mask)
                continue
                
            else:
                print(f"[LLM Rotation] Key {mask} streaming returned status {res.status_code}. Rotating.")
                with _rotation_lock:
                    GEMINI_KEYS_COOLDOWN[mask] = datetime.now() + timedelta(seconds=5)
                continue
                
        except Exception as e:
            print(f"[LLM Rotation] Streaming request failed for key {mask}: {e}. Rotating.")
            with _rotation_lock:
                GEMINI_KEYS_COOLDOWN[mask] = datetime.now() + timedelta(seconds=10)
            continue
            
    yield "ERROR: Exceeded maximum key rotation retry attempts for streaming."

import threading
import time

_llm_meta_local = threading.local()
_last_global_llm_meta = None

def get_last_llm_meta() -> dict:
    """Retrieve execution metadata for the most recent LLM call on the current thread or globally."""
    meta = getattr(_llm_meta_local, "meta", None)
    if meta is not None:
        return meta
    if _last_global_llm_meta is not None:
        return _last_global_llm_meta
    return {
        "model_used": "Gemini 1.5 Flash",
        "provider": "gemini",
        "latency_ms": 0,
        "is_fallback": False
    }

def _set_last_llm_meta(model_used: str, provider: str, start_time: float, is_fallback: bool = False):
    global _last_global_llm_meta
    latency = int((time.time() - start_time) * 1000)
    meta_dict = {
        "model_used": model_used,
        "provider": provider,
        "latency_ms": latency,
        "is_fallback": is_fallback
    }
    _llm_meta_local.meta = meta_dict
    _last_global_llm_meta = meta_dict

def call_llm(task_type: str,
             system_prompt: str,
             user_prompt: str = None,
             max_tokens: int = 2500,
             messages: list = None) -> str:
    """
    Provider-agnostic LLM call. Routes to the correct model based on task_type.
    """
    start_time = time.time()
    config = _get_config()
    
    # Ensure system prompt suppresses thinking process/chain-of-thought metadata
    suppress_instructions = (
        "\n\nIMPORTANT CONSTRUCT LIMITS:\n"
        "1. Do NOT output any chain of thought, thinking process, planning steps, or self-correction commentary (such as 'Here's a thinking process' or 'Analyzing inputs').\n"
        "2. Do NOT include any introductory greetings, meta-explanations, or conversational filler.\n"
        "3. Start your response directly with the requested output (HTML, markdown, JSON, or paragraphs) in its final formatted state."
    )
    
    # Build messages if not pre-built
    if messages is None:
        messages_with_suppression = [
            {"role": "system", "content": system_prompt + suppress_instructions},
        ]
        if user_prompt:
            messages_with_suppression.append({"role": "user", "content": user_prompt})
    else:
        # If pre-built messages are provided, inject the suppression into the system message
        messages_with_suppression = [m.copy() for m in messages]
        for msg in messages_with_suppression:
            if msg.get("role") == "system":
                msg["content"] = msg["content"] + suppress_instructions
                break

    # Route to Gemini custom provider if requested
    if config["provider"] == "gemini":
        structured_schema = None
        if "json" in system_prompt.lower() or (user_prompt and "json" in user_prompt.lower()):
            structured_schema = {"type": "object"}
            
        result, success = _call_gemini_with_rotation(
            task_type=task_type,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            messages=messages,
            structured_schema=structured_schema
        )
        if success:
            return _clean_reasoning_metadata(result)
            
        print(f"[LLM Config] Gemini rotation failed ({result}). Falling back to Groq...")
        config["provider"] = "groq"
        config["heavy_model"] = os.environ.get("LLM_HEAVY_MODEL", "llama-3.3-70b-versatile")
        config["fast_model"] = os.environ.get("LLM_FAST_MODEL", "llama-3.3-70b-versatile")
        config["heavy_label"] = "Fallback Groq Llama 3.3"
        config["fast_label"] = "Fallback Groq Llama 3.3"

    client = _get_client(config)
    if client is None:
        return "ERROR_401: LLM client is not initialized. Please verify your API key and LLM_PROVIDER settings."

    model = config["heavy_model"] if task_type == TASK_HEAVY else config["fast_model"]
    label = config["heavy_label"] if task_type == TASK_HEAVY else config["fast_label"]
    temperature = config["temperature"]

    # Prevent token truncation: scale max_tokens up to allow headroom for thinking logs
    safe_max_tokens = min(16384, max(max_tokens, 4096))

    try:
        print(f"[LLM] Calling {label} (model: {model}, task: {task_type}, tokens: {safe_max_tokens})...")
        chat_completion = client.chat.completions.create(
            messages=messages_with_suppression,
            model=model,
            max_tokens=safe_max_tokens,
            temperature=temperature
        )
        response_content = chat_completion.choices[0].message.content
        print(f"[LLM] Successfully received response from {label} ({len(response_content)} chars)")
        is_fallback = (config["provider"] != "gemini")
        _set_last_llm_meta(label, config["provider"], start_time, is_fallback=is_fallback)
        return _clean_reasoning_metadata(response_content)
    except Exception as e:
        print(f"[LLM] Error calling {label}: {e}")
        err_msg = str(e)
        if "invalid_api_key" in err_msg or "401" in err_msg or "Invalid API Key" in err_msg:
            return "ERROR_401: Invalid API Key. Activating local high-fidelity fallback reasoning."

        fallback_model = config["fast_model"] if task_type == TASK_HEAVY else config["heavy_model"]
        if fallback_model != model:
            try:
                print(f"[LLM] Retrying with fallback model: {fallback_model}...")
                chat_completion = client.chat.completions.create(
                    messages=messages_with_suppression,
                    model=fallback_model,
                    max_tokens=safe_max_tokens,
                    temperature=temperature
                )
                _set_last_llm_meta(f"Fallback {fallback_model}", config["provider"], start_time, is_fallback=True)
                return _clean_reasoning_metadata(chat_completion.choices[0].message.content)
            except Exception as e2:
                if "invalid_api_key" in str(e2) or "401" in str(e2):
                    return "ERROR_401: Invalid API Key. Activating local high-fidelity fallback reasoning."
                return f"ERROR: Failed to query LLM. Details: {str(e2)}"
        
        return f"ERROR: Failed to query LLM model {model}. Details: {err_msg}"

def call_llm_with_meta(task_type: str,
                       system_prompt: str,
                       user_prompt: str = None,
                       max_tokens: int = 2500,
                       messages: list = None) -> tuple[str, dict]:
    """
    Executes call_llm and returns a tuple of (response_text, llm_meta_dict).
    """
    text = call_llm(task_type, system_prompt, user_prompt, max_tokens, messages)
    return text, get_last_llm_meta()

def _clean_reasoning_metadata(text: str) -> str:
    """Strip out any internal thinking process or chain-of-thought blocks from the text."""
    if not text:
        return text

    import re
    # 1. Remove explicit <think>...</think> or <reasoning>...</reasoning> tags
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<reasoning>.*?</reasoning>', '', text, flags=re.DOTALL | re.IGNORECASE)

    lower_text = text.lower().strip()
    thinking_prefixes = [
        "thinking process:", "reasoning process:", "analysis process:",
        "here's a thinking process", "here is the thinking process",
        "here is a thinking process", "here's the thinking process"
    ]
    
    starts_with_thinking = any(lower_text.startswith(p) for p in thinking_prefixes)
    if not starts_with_thinking:
        return text.strip()

    # 2. If it starts with an explicit thinking header block, look for markdown header transition
    header_match = re.search(r'\n\s*(?:#+\s*(?:final response|answer|summary|output|analysis|recommendation))\b', text, flags=re.IGNORECASE)
    if header_match:
        return text[header_match.start():].strip()

    # 3. Look for double blank lines after thinking block
    blocks = re.split(r'\n\s*\n', text.strip())
    if len(blocks) > 1:
        non_thinking_blocks = [b for b in blocks if not any(b.lower().strip().startswith(p) for p in thinking_prefixes)]
        if non_thinking_blocks:
            return "\n\n".join(non_thinking_blocks).strip()

    return text.strip()

def call_llm_stream(task_type: str,
                    system_prompt: str,
                    user_prompt: str = None,
                    max_tokens: int = 2500,
                    messages: list = None):
    """
    Provider-agnostic streaming LLM call. Routes to the correct model based on task_type.
    Yields chunks of generated text.
    """
    config = _get_config()
    
    suppress_instructions = (
        "\n\nIMPORTANT CONSTRUCT LIMITS:\n"
        "1. Do NOT output any chain of thought, thinking process, planning steps, or self-correction commentary.\n"
        "2. Do NOT include any introductory greetings or conversational filler.\n"
        "3. Start your response directly with the requested output."
    )

    if messages is None:
        messages_with_suppression = [
            {"role": "system", "content": system_prompt + suppress_instructions},
        ]
        if user_prompt:
            messages_with_suppression.append({"role": "user", "content": user_prompt})
    else:
        messages_with_suppression = [m.copy() for m in messages]
        for msg in messages_with_suppression:
            if msg.get("role") == "system":
                msg["content"] = msg["content"] + suppress_instructions
                break

    if config["provider"] == "gemini":
        for chunk in _stream_gemini_with_rotation(
            task_type=task_type,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=max_tokens,
            messages=messages
        ):
            yield chunk
        return

    client = _get_client(config)
    if client is None:
        yield "ERROR_401: LLM client is not initialized. Please verify your API key and LLM_PROVIDER settings."
        return

    model = config["heavy_model"] if task_type == TASK_HEAVY else config["fast_model"]
    temperature = config["temperature"]
    safe_max_tokens = min(16384, max(max_tokens, 4096))

    try:
        chat_completion = client.chat.completions.create(
            messages=messages_with_suppression,
            model=model,
            max_tokens=safe_max_tokens,
            temperature=temperature,
            stream=True
        )
        for chunk in chat_completion:
            if chunk.choices and len(chunk.choices) > 0:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    yield delta.content
    except Exception as e:
        fallback_model = config["fast_model"] if task_type == TASK_HEAVY else config["heavy_model"]
        if fallback_model != model:
            try:
                chat_completion = client.chat.completions.create(
                    messages=messages_with_suppression,
                    model=fallback_model,
                    max_tokens=safe_max_tokens,
                    temperature=temperature,
                    stream=True
                )
                for chunk in chat_completion:
                    if chunk.choices and len(chunk.choices) > 0:
                        delta = chunk.choices[0].delta
                        if delta and delta.content:
                            yield delta.content
                return
            except Exception as e2:
                yield f"ERROR: Failed to query LLM. Details: {str(e2)}"
                return
        yield f"ERROR: Failed to query LLM model {model}. Details: {str(e)}"

# ---------------------------------------------------------------------------
# Status & Configuration API (consumed by frontend via /api/llm-config)
# ---------------------------------------------------------------------------
def is_llm_available() -> bool:
    """Check whether a valid LLM client can be initialized."""
    config = _get_config()
    if config["provider"] == "gemini":
        return len(_get_gemini_keys_pool()) > 0
    return _get_client() is not None

def get_llm_config() -> dict:
    """Return active LLM configuration for the frontend API endpoint."""
    config = _get_config()
    available = is_llm_available()
    
    # Load SerpApi and Tavily keys from SQLite Database or .env fallback
    db_serpapi, db_tavily = "", ""
    try:
        db_dir = os.environ.get("DATABASE_DIR", os.path.join(os.path.dirname(__file__), "data"))
        db_path = os.path.join(db_dir, "watchlist_database.db")
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM alert_settings WHERE key = 'serpapi_api_key'")
            row = cursor.fetchone()
            if row:
                db_serpapi = _decode_key(row["value"])
            cursor.execute("SELECT value FROM alert_settings WHERE key = 'tavily_api_key'")
            row = cursor.fetchone()
            if row:
                db_tavily = _decode_key(row["value"])
            conn.close()
    except Exception:
        pass
        
    has_serp = bool(db_serpapi or os.environ.get("SERPAPI_API_KEY", ""))
    has_tav = bool(db_tavily or os.environ.get("TAVILY_API_KEY", ""))
    
    # Determine active provider and label
    active_provider = config["provider"]
    active_label = config["heavy_label"]
    
    if config["provider"] == "gemini":
        keys = _get_gemini_keys_pool()
        available_key, _ = _select_gemini_key(keys)
        if not available_key:
            # Fallback to Groq
            active_provider = "groq"
            groq_label = os.environ.get("LLM_FAST_LABEL") or os.environ.get("LLM_HEAVY_LABEL") or "Groq Llama 3.3"
            if "Groq" not in groq_label and "llama" in groq_label.lower():
                groq_label = "Groq " + groq_label
            active_label = groq_label
        else:
            active_provider = "gemini"
            active_label = config["fast_label"]
    else:
        active_provider = config["provider"]
        active_label = config["heavy_label"]
        
    return {
        "provider": config["provider"],
        "heavy_model": config["heavy_model"],
        "fast_model": config["fast_model"],
        "heavy_label": config["heavy_label"],
        "fast_label": config["fast_label"],
        "status": "connected" if available else "disconnected",
        "base_url": config["base_url"] or "(default provider endpoint)",
        "has_brave_key": bool(os.environ.get("BRAVE_API_KEY", "")),
        "has_serpapi_key": has_serp,
        "has_tavily_key": has_tav,
        "active_provider": active_provider,
        "active_label": active_label
    }
