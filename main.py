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

load_dotenv()

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
    print("Brak GEMINI_API_KEY")
    sys.exit(1)

client = genai.Client(api_key=API_KEY, http_options={"api_version": "v1beta"})
MODEL = "gemini-2.5-flash-native-audio-latest"


@app.get("/")
async def index():
    index_path = SITE_DIR / "index.html"
    if not index_path.exists():
        return {"error": f"Brak pliku: {index_path}"}
    return FileResponse(index_path)


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    print("WS CONNECTED")

    memory = MemoryManager()
    stop_event = asyncio.Event()

    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        system_instruction=types.Content(
            parts=[
                types.Part(
                    text=(
                        "You are Jarvis. Speak naturally and briefly. "
                        "Respond only with spoken audio."
                    )
                )
            ]
        ),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name="Fenrir"
                )
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
                        try:
                            payload = await ws.receive_json()
                        except WebSocketDisconnect:
                            print("Client disconnected")
                            stop_event.set()
                            break
                        except Exception as e:
                            print("WebSocket receive error:", e)
                            stop_event.set()
                            break

                        if not isinstance(payload, dict):
                            continue

                        memory_action = payload.get("memory_action")
                        if memory_action:
                            if memory_action == "add":
                                note = str(payload.get("text", "")).strip()
                                if note:
                                    memory.add_entity_fact(note)
                                    state = memory.export_state()
                                    await ws.send_text(
                                        json.dumps(
                                            {
                                                "type": "memory_state",
                                                "items": state["entity_memory"],
                                            },
                                            ensure_ascii=False,
                                        )
                                    )
                                    print("MEMORY ADD:", note)

                            elif memory_action == "clear":
                                memory.clear_entity_memory()
                                state = memory.export_state()
                                await ws.send_text(
                                    json.dumps(
                                        {
                                            "type": "memory_state",
                                            "items": state["entity_memory"],
                                        },
                                        ensure_ascii=False,
                                    )
                                )
                                print("MEMORY CLEARED")

                            continue

                        audio_b64 = payload.get("audio")
                        if not audio_b64:
                            continue

                        try:
                            raw = base64.b64decode(audio_b64)
                        except Exception as e:
                            print("Błąd dekodowania audio:", e)
                            continue

                        sample_rate = int(payload.get("sampleRate", 16000))

                        await session.send_realtime_input(
                            audio=types.Blob(
                                data=raw,
                                mime_type=f"audio/pcm;rate={sample_rate}",
                            )
                        )

                finally:
                    stop_event.set()

            async def send_loop():
                nonlocal pending_user_text, pending_assistant_text

                try:
                    while not stop_event.is_set():
                        try:
                            async for response in session.receive():
                                if stop_event.is_set():
                                    break

                                audio_bytes = None
                                server_content = getattr(response, "server_content", None)

                                if server_content and getattr(server_content, "model_turn", None):
                                    parts = getattr(server_content.model_turn, "parts", []) or []
                                    for part in parts:
                                        if (
                                            part.inline_data
                                            and getattr(part.inline_data, "data", None) is not None
                                        ):
                                            data = part.inline_data.data
                                            if isinstance(data, str):
                                                try:
                                                    data = base64.b64decode(data)
                                                except Exception as e:
                                                    print("Błąd dekodowania inline_data:", e)
                                                    continue
                                            audio_bytes = data

                                if audio_bytes is None and getattr(response, "data", None):
                                    audio_bytes = response.data
                                    if isinstance(audio_bytes, str):
                                        try:
                                            audio_bytes = base64.b64decode(audio_bytes)
                                        except Exception as e:
                                            print("Błąd dekodowania response.data:", e)
                                            audio_bytes = None

                                if audio_bytes:
                                    await ws.send_bytes(audio_bytes)
                                    print("AUDIO:", len(audio_bytes))

                                if server_content:
                                    if getattr(server_content, "input_transcription", None):
                                        text = getattr(server_content.input_transcription, "text", "")
                                        if text and text.strip():
                                            pending_user_text = text.strip()
                                            print("USER:", pending_user_text)

                                    if getattr(server_content, "output_transcription", None):
                                        text = getattr(server_content.output_transcription, "text", "")
                                        if text and text.strip():
                                            pending_assistant_text = text.strip()
                                            print("JARVIS:", pending_assistant_text)

                                    if getattr(server_content, "interrupted", False):
                                        print("TURN INTERRUPTED")

                                    if getattr(server_content, "turn_complete", False):
                                        print("TURN COMPLETE")

                                        if pending_user_text:
                                            memory.add_user_message(pending_user_text)
                                            pending_user_text = ""

                                        if pending_assistant_text:
                                            memory.add_assistant_message(pending_assistant_text)
                                            pending_assistant_text = ""

                            if stop_event.is_set():
                                break

                            await asyncio.sleep(0.05)

                        except Exception as e:
                            if stop_event.is_set():
                                break
                            print("Session receive error:", e)
                            await asyncio.sleep(0.2)

                finally:
                    stop_event.set()

            recv_task = asyncio.create_task(recv_loop())
            send_task = asyncio.create_task(send_loop())

            await asyncio.gather(recv_task, send_task)

    except Exception as e:
        print("SESSION ERROR:", e)

    finally:
        stop_event.set()
        try:
            await ws.close()
        except Exception:
            pass
        print("WS CLOSED")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)