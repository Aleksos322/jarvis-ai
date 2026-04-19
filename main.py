import asyncio
import base64
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from google import genai
from google.genai import types

from memory.memory_manager import MemoryManager
from storage.database import init_db

# Inicjalizacja bazy przy starcie
load_dotenv()
init_db()

BASE_DIR = Path(__file__).resolve().parent
SITE_DIR = BASE_DIR / "Site"

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(SITE_DIR)), name="static")

API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    print("❌ BŁĄD: Brak GEMINI_API_KEY w pliku .env")
    sys.exit(1)

client = genai.Client(api_key=API_KEY, http_options={"api_version": "v1beta"})
MODEL = "gemini-2.5-flash-native-audio-latest"

@app.get("/")
async def index():
    index_path = SITE_DIR / "index.html"
    return FileResponse(index_path) if index_path.exists() else {"error": "Brak index.html"}

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    print("🚀 JARVIS CONNECTED")

    memory = MemoryManager()
    stop_event = asyncio.Event()

    # 1. POBIERAMY HISTORIĘ Z BAZY (np. ostatnie 10 wiadomości)
    try:
        history = memory.get_recent_messages(limit=10)
    except Exception:
        history = []

    # Obsługa różnych reprezentacji wiadomości (dict lub obiekt)
    history_text = "\n".join([
        f"{m['role']}: {m['content']}" if isinstance(m, dict) else f"{getattr(m, 'role', '')}: {getattr(m, 'content', '')}"
        for m in history
    ])

    # 2. BUDUJEMY ROZSZERZONY PROMPT SYSTEMOWY
    base_prompt = memory.build_system_prompt()
    full_system_prompt = f"{base_prompt}\n\nOto historia Twojej poprzedniej rozmowy z użytkownikiem:\n{history_text}"

    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        system_instruction=types.Content(
            parts=[types.Part(text=full_system_prompt)]
        ),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Fenrir")
            )
        ),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        realtime_input_config=types.RealtimeInputConfig(
            turn_coverage="TURN_INCLUDES_ONLY_ACTIVITY"
        ),
    )

    pending_user_text = ""
    pending_assistant_text = ""

    try:
        async with client.aio.live.connect(model=MODEL, config=config) as session:

            async def recv_loop():
                nonlocal pending_user_text, pending_assistant_text
                try:
                    while not stop_event.is_set():
                        payload = await ws.receive_json()
                        
                        # Obsługa ręcznego dodawania faktów z UI
                        memory_action = payload.get("memory_action")
                        if memory_action:
                            if memory_action == "add":
                                note = str(payload.get("text", "")).strip()
                                if note:
                                    # Zakładamy prosty klucz-wartość lub fakt ogólny
                                    memory.update_user_fact(f"fact_{os.urandom(2).hex()}", note)
                                    await ws.send_json({"type": "memory_updated", "status": "success"})
                            continue

                        audio_b64 = payload.get("audio")
                        if audio_b64:
                            raw = base64.b64decode(audio_b64)
                            await session.send_realtime_input(
                                audio=types.Blob(
                                    data=raw,
                                    mime_type="audio/pcm;rate=16000",
                                )
                            )
                except Exception as e:
                    print(f"Recv Loop Error: {e}")
                finally:
                    stop_event.set()

            async def send_loop():
                nonlocal pending_user_text, pending_assistant_text
                try:
                    async for response in session.receive():
                        if stop_event.is_set(): break

                        # 1. Obsługa Audio
                        if response.data:
                            await ws.send_bytes(response.data)

                        # 2. Obsługa Transkrypcji i logowania do bazy
                        server_content = response.server_content
                        if server_content:
                            # Przechwyć tekst użytkownika
                            if server_content.input_transcription:
                                pending_user_text = server_content.input_transcription.text
                                print(f"👤 User: {pending_user_text}")

                            # Przechwyć tekst asystenta
                            if server_content.model_turn:
                                for part in server_content.model_turn.parts:
                                    if part.text:
                                        pending_assistant_text += part.text

                            # 3. KONIEC TURY - Zapis do bazy danych
                            if server_content.turn_complete:
                                if pending_user_text:
                                    memory.save_message("user", pending_user_text)
                                if pending_assistant_text:
                                    memory.save_message("assistant", pending_assistant_text)
                                    print(f"🤖 Jarvis: {pending_assistant_text}")
                                
                                pending_user_text = ""
                                pending_assistant_text = ""

                except Exception as e:
                    print(f"Send Loop Error: {e}")
                finally:
                    stop_event.set()

            await asyncio.gather(recv_loop(), send_loop())

    except Exception as e:
        print(f"❌ SESSION ERROR: {e}")
    finally:
        memory.close() # 🔥 WAŻNE: Zamykamy połączenie z bazą
        if not ws.client_state.name == "DISCONNECTED":
            await ws.close()
        print("🔌 Connection closed.")