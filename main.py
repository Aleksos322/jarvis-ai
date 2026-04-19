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
    print("🚀 JARVIS CONNECTED (ws accepted)")

    memory = MemoryManager()
    disconnect_event = asyncio.Event()  # ustawiamy tylko gdy klient się rozłączy lub krytyczny błąd
    pending_user_text = ""
    pending_assistant_text = ""

    # Przygotuj prompt/history
    try:
        history = memory.get_recent_messages(limit=10)
    except Exception:
        history = []

    history_text = "\n".join([
        f"{m['role']}: {m['content']}" if isinstance(m, dict) else f"{getattr(m, 'role', '')}: {getattr(m, 'content', '')}"
        for m in history
    ])
    base_prompt = memory.build_system_prompt()
    full_system_prompt = (
        f"{base_prompt}\n\nOto historia Twojej poprzedniej rozmowy z użytkownikiem:\n{history_text}"
        + "\n\nWAŻNE OGRANICZENIE: Zawsze generuj faktyczną odpowiedź dźwiękową dla użytkownika. Nigdy nie kończ swojej tury po wygenerowaniu samego planu czy procesu myślowego."
        + " NAJWAŻNIEJSZA ZASADA: Odpowiadaj WYŁĄCZNIE głosem (audio)."
    )

    config_template = dict(
        response_modalities=[types.Modality.AUDIO],
        system_instruction=types.Content(parts=[types.Part(text=full_system_prompt)]),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Fenrir")
            )
        ),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        realtime_input_config=types.RealtimeInputConfig(turn_coverage="TURN_INCLUDES_ONLY_ACTIVITY"),
    )

    try:
        # Główna pętla: jako długo nie ma rozłączenia klienta, tworzymy (i wznawiamy) sesję modelu wielokrotnie.
        while not disconnect_event.is_set():
            print("🔁 Tworzę sesję GenAI (nowa live.connect)...")
            # zbuduj config z template (można modyfikować jeśli potrzeba)
            config = types.LiveConnectConfig(**config_template)

            try:
                async with client.aio.live.connect(model=MODEL, config=config) as session:
                    print("✅ Sesja GenAI otwarta")

                    # recv_loop: odbiera dane z WebSocket klienta i przesyła do modelu
                    async def recv_loop():
                        nonlocal pending_user_text, pending_assistant_text
                        try:
                            while not disconnect_event.is_set():
                                try:
                                    payload = await asyncio.wait_for(ws.receive_json(), timeout=300.0)
                                except asyncio.TimeoutError:
                                    # brak aktywności klienta — wracamy i nadal trzymamy sesję/model
                                    continue
                                except WebSocketDisconnect:
                                    print("🔌 Client disconnected (recv_loop)")
                                    # sygnalizuj że klient się rozłączył i zakończ outer loop
                                    disconnect_event.set()
                                    return
                                except Exception as e:
                                    # Poważny błąd z WebSocket (np. closed while reading)
                                    print(f"❌ WebSocket receive error (recv_loop): {e}")
                                    disconnect_event.set()
                                    return

                                # Obsługa pamięci z UI
                                memory_action = payload.get("memory_action")
                                if memory_action == "add":
                                    note = str(payload.get("text", "")).strip()
                                    if note:
                                        try:
                                            memory.update_user_fact(f"fact_{os.urandom(2).hex()}", note)
                                            await ws.send_json({"type": "memory_updated", "status": "success"})
                                        except Exception as e:
                                            print(f"❌ Error updating memory: {e}")
                                    continue

                                audio_b64 = payload.get("audio")
                                if audio_b64:
                                    try:
                                        raw = base64.b64decode(audio_b64)
                                        await session.send_realtime_input(
                                            audio=types.Blob(data=raw, mime_type="audio/pcm;rate=16000")
                                        )
                                    except Exception as e:
                                        print(f"❌ Error sending audio to model: {e}")
                                        # Nie ustawiamy disconnect_event — możemy spróbować dalej
                                        continue

                        finally:
                            print("🔍 recv_loop finished")

                    # send_loop: odbiera odpowiedzi z modelu i przekazuje do klienta
                    async def send_loop():
                        nonlocal pending_user_text, pending_assistant_text
                        try:
                            print("🔍 send_loop started (session.receive)")
                            async for response in session.receive():
                                # Jeżeli klient się rozłączył, przerywamy
                                if disconnect_event.is_set():
                                    print("🔍 disconnect_event set — przerywam send_loop")
                                    break

                                # 1) audio
                                if getattr(response, "data", None) and isinstance(response.data, (bytes, bytearray)) and len(response.data) > 0:
                                    try:
                                        await ws.send_bytes(response.data)
                                    except Exception as e:
                                        print(f"❌ Error sending audio to client: {e}")
                                        # klient może być zamknięty — zgłaszamy disconnect
                                        disconnect_event.set()
                                        break

                                # 2) transkrypcja / tekst / logika tury
                                server_content = getattr(response, "server_content", None)
                                if server_content:
                                    if server_content.input_transcription:
                                        pending_user_text = server_content.input_transcription.text
                                        print(f"👤 User: {pending_user_text}")

                                    if server_content.model_turn:
                                        for part in server_content.model_turn.parts:
                                            if getattr(part, "text", None):
                                                pending_assistant_text += part.text

                                    if server_content.turn_complete:
                                        try:
                                            if pending_user_text:
                                                memory.save_message("user", pending_user_text)
                                            if pending_assistant_text:
                                                memory.save_message("assistant", pending_assistant_text)
                                                print(f"🤖 Jarvis: {pending_assistant_text}")
                                        except Exception as e:
                                            print(f"❌ Error saving messages: {e}")

                                        # reset wewnętrznej tury; NIE zamykamy websocket
                                        pending_user_text = ""
                                        pending_assistant_text = ""
                                        print("✅ Tura zakończona (turn_complete). Czekam na kolejne dane od klienta.")
                            # koniec async for session.receive() -> sesja modelu się zakończyła normalnie
                            print("ℹ️ session.receive() zakończyło się (model zakończył sesję).")
                            # nie ustawiamy disconnect_event — chcemy spróbować otworzyć nową sesję i kontynuować
                        except Exception as e:
                            print(f"❌ Send Loop Error: {e}")
                            # w przypadku błędu wysłania do klienta lub błędu sesji — jeśli klient jest otwarty, kontynuujemy próbę restartu sesji
                        finally:
                            print("🔍 send_loop finished")

                    # Uruchom pętle
                    recv_task = asyncio.create_task(recv_loop())
                    send_task = asyncio.create_task(send_loop())

                    # Poczekaj a�� którykolwiek task zakończy się z powodu disconnect_event lub błędu
                    done, pending = await asyncio.wait([recv_task, send_task], return_when=asyncio.FIRST_COMPLETED)

                    # Jeśli recv_task zakończył się ustawiając disconnect_event (klient rozłączył się), to przerwij outer loop
                    if disconnect_event.is_set():
                        print("🔔 disconnect_event wykryty po zakończeniu tasks — przerywam pętlę sesji.")
                        # anuluj drugą pętlę i wyjdź
                        for t in pending:
                            t.cancel()
                        await asyncio.gather(*pending, return_exceptions=True)
                        break

                    # Jeżeli natomiast send_loop zakończył się normalnie (sesja modelu dobiegła końca),
                    # anulujemy recv_task i spróbujemy utworzyć nową sesję (kontynuacja)
                    print("🔁 Przywracam sesję (zrestartuję live.connect), klient nadal połączony.")
                    for t in pending:
                        t.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)

                    # krótkie opóźnienie przed ponownym połączeniem (zapobiega tight-loop)
                    await asyncio.sleep(0.2)

            except Exception as e:
                # błąd podczas nawiązywania/utrzymania sesji GenAI - logujemy i spróbujemy ponownie jeśli klient nadal połączony
                print(f"❌ Błąd sesji GenAI: {e}")
                if disconnect_event.is_set():
                    break
                await asyncio.sleep(0.5)
                continue

        # koniec głównej pętli while
    except WebSocketDisconnect:
        print("🔌 WebSocket disconnected (outer)")
    except Exception as e:
        print(f"❌ SESSION ERROR (outer): {e}")
    finally:
        try:
            memory.close()
        except Exception as e:
            print(f"❌ Error closing memory: {e}")
        try:
            if not ws.client_state.name == "DISCONNECTED":
                await ws.close()
        except Exception as e:
            print(f"❌ Error closing ws: {e}")
        print("🔌 Connection closed (handler).")