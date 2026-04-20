"""
Serwer FastAPI - Jarvis AI
Moduł integrujący Google Gemini Live API z WebSockets.
Zawiera obsługę przesyłania audio w czasie rzeczywistym,
zarządzanie pamięcią (MemoryManager) oraz logikę trybu cichego.
"""

import asyncio
import base64
import json
import os
import sys
from pathlib import Path

# Ładowanie zmiennych środowiskowych i konfiguracji bazy
from dotenv import load_dotenv

# Importy FastAPI do obsługi serwera i WebSockets
from fastapi import FastAPI
from fastapi import WebSocket
from fastapi import WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# Importy Google GenAI
from google import genai
from google.genai import types

# Importy lokalnych modułów aplikacji
from memory.memory_manager import MemoryManager
from storage.database import init_db

# =====================================================================
# INICJALIZACJA APLIKACJI I BAZY DANYCH
# =====================================================================

# Inicjalizacja bazy przy starcie aplikacji
load_dotenv()
init_db()

# Ścieżki katalogów
BASE_DIR = Path(__file__).resolve().parent
SITE_DIR = BASE_DIR / "Site"

# Utworzenie instancji aplikacji FastAPI
app = FastAPI(
    title="Jarvis AI Backend",
    description="Backend dla asystenta głosowego Jarvis z wykorzystaniem Gemini Live",
    version="1.0.0"
)

# Konfiguracja CORS (Cross-Origin Resource Sharing)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Montowanie plików statycznych (frontend)
app.mount(
    "/static", 
    StaticFiles(directory=str(SITE_DIR)), 
    name="static"
)

# =====================================================================
# WERYFIKACJA KLUCZY API I KONFIGURACJA MODELU
# =====================================================================

API_KEY = os.getenv("GEMINI_API_KEY")
if not API_KEY:
    print("❌ BŁĄD KRYTYCZNY: Brak GEMINI_API_KEY w pliku .env")
    print("Upewnij się, że plik .env istnieje i zawiera poprawny klucz.")
    sys.exit(1)

# Inicjalizacja klienta Google GenAI
client = genai.Client(
    api_key=API_KEY, 
    http_options={"api_version": "v1beta"}
)

# Konfiguracja używanego modelu (według specyfikacji użytkownika)
MODEL = "gemini-2.5-flash-native-audio-latest"


# =====================================================================
# ENDPOINTY REST API
# =====================================================================

@app.get("/")
async def index():
    """
    Główny endpoint serwujący plik index.html.
    Sprawdza, czy plik istnieje w zdefiniowanym katalogu SITE_DIR.
    """
    index_path = SITE_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    else:
        return {"error": f"Brak pliku index.html w katalogu {SITE_DIR}"}


# =====================================================================
# WEBSOCKET ENDPOINT (GŁÓWNA LOGIKA JARVISA)
# =====================================================================

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    """
    Główny endpoint WebSocket obsługujący komunikację z frontendem.
    Zarządza sesją Google Gemini Live, odbiera audio od użytkownika,
    wysyła audio wygenerowane przez AI oraz obsługuje komendy specjalne.
    """
    await ws.accept()
    print("🚀 JARVIS CONNECTED (ws accepted)")
    print(f"📡 Adres klienta: {ws.client}")

    memory = MemoryManager()
    
    # Event służący do sygnalizowania zakończenia połączenia
    disconnect_event = asyncio.Event()  
    
    # Słownik stanu, aby zmienne były bezpiecznie współdzielone między zadaniami
    state = {
        "is_silent_mode": False,
        "pending_user_text": "",
        "pending_assistant_text": ""
    }

    # -----------------------------------------------------------------
    # PRZYGOTOWANIE KONTEKSTU I HISTORII
    # -----------------------------------------------------------------
    print("📚 Ładowanie historii konwersacji z bazy danych...")
    try:
        history = memory.get_recent_messages(limit=10)
    except Exception as e:
        print(f"⚠️ Nie udało się załadować historii: {e}")
        history = []

    # Formatowanie historii do postaci tekstowej
    history_lines = []
    for m in history:
        if isinstance(m, dict):
            history_lines.append(f"{m.get('role', 'unknown')}: {m.get('content', '')}")
        else:
            history_lines.append(f"{getattr(m, 'role', '')}: {getattr(m, 'content', '')}")
            
    history_text = "\n".join(history_lines)
    
    # Pobranie bazowego promptu z menedżera pamięci
    base_prompt = memory.build_system_prompt()
    
    # Budowa pełnego systemu instrukcji (System Prompt) z priorytetami
    full_system_prompt = (
        f"{base_prompt}\n\n"
        "=== ZASADY JĘZYKOWE ===\n"
        "- Mów WYŁĄCZNIE po polsku. Nigdy nie odpowiadaj po angielsku, chyba że wyraźnie Cię o to poproszę.\n"
        "- Nawet jeśli usłyszysz szum, oddechy lub pojedyncze polskie słowa, traktuj to jako język polski.\n\n"
        "=== ZASADY REAGOWANIA I PRIORYTETY (KRYTYCZNE) ===\n"
        "- TWOJA WYPOWIEDŹ JEST PRIORYTETEM. Nie przerywaj generowania odpowiedzi, gdy słyszysz szum lub moje pojedyncze słowa w tle.\n"
        "- Doprowadzaj swoje wypowiedzi do końca.\n"
        "- Przerwij mówienie TYLKO i wyłącznie wtedy, gdy usłyszysz wyraźne słowo 'STOP' (potwierdź to krótko w transkrypcji).\n"
        "- Jeśli usłyszysz 'NAKAZUJĘ MILCZENIE', natychmiast przejdź w tryb pracy w tle. Nadal analizuj co mówię i wykonuj zadania, ale CAŁKOWICIE ZAPRZESTAŃ GENEROWANIA DŹWIĘKU, dopóki nie powiem 'możesz mówić'.\n\n"
        "=== HISTORIA OSTATNIEJ KONWERSACJI ===\n"
        f"{history_text}\n"
        "======================================\n"
    )

    # Konfiguracja połączenia z Gemini Live
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
        # Ustawienie wspierające utrzymanie sesji przy braku głosu
        realtime_input_config=types.RealtimeInputConfig(turn_coverage="TURN_INCLUDES_ONLY_ACTIVITY"),
    )

    # -----------------------------------------------------------------
    # GŁÓWNA PĘTLA POŁĄCZENIA Z MODELEM
    # -----------------------------------------------------------------
    try:
        # Pętla utrzymuje działanie, wznawiając sesję modelu jeśli wygaśnie
        while not disconnect_event.is_set():
            print("\n🔁 Tworzę nową sesję GenAI (live.connect)...")
            config = types.LiveConnectConfig(**config_template)

            try:
                async with client.aio.live.connect(model=MODEL, config=config) as session:
                    print("✅ Sesja GenAI została pomyślnie otwarta i jest aktywna.")

                    # =================================================
                    # PĘTLA ODBIERAJĄCA (RECEIVE LOOP)
                    # =================================================
                    async def recv_loop():
                        """
                        Odbiera dane z przeglądarki (przez WebSocket) i wysyła je do modelu.
                        Obsługuje również lokalne akcje pamięci z interfejsu użytkownika.
                        """
                        print("▶️ Rozpoczęto nasłuchiwanie klienta (recv_loop)...")
                        try:
                            while not disconnect_event.is_set():
                                try:
                                    # Oczekiwanie na dane z timeoutem
                                    payload = await asyncio.wait_for(ws.receive_json(), timeout=120.0)
                                except asyncio.TimeoutError:
                                    # Timeout jest oczekiwany, po prostu kontynuujemy pętlę
                                    continue
                                except WebSocketDisconnect:
                                    print("🔌 Klient rozłączył się (WebSocketDisconnect w recv_loop)")
                                    disconnect_event.set()
                                    return
                                except Exception as e:
                                    print(f"❌ Niespodziewany błąd odbierania (recv_loop): {e}")
                                    disconnect_event.set()
                                    return

                                # 1. Obsługa poleceń modyfikacji pamięci z UI (memory_action)
                                memory_action = payload.get("memory_action")
                                if memory_action == "add":
                                    note = str(payload.get("text", "")).strip()
                                    if note:
                                        try:
                                            fact_id = f"fact_{os.urandom(2).hex()}"
                                            memory.update_user_fact(fact_id, note)
                                            print(f"🧠 Zapisano nowy fakt w pamięci: {note}")
                                            await ws.send_json({"type": "memory_updated", "status": "success"})
                                        except Exception as e:
                                            print(f"❌ Błąd podczas aktualizacji pamięci: {e}")
                                    continue # Po obsłudze pamięci wracamy na początek pętli

                                # 2. Obsługa strumienia Audio
                                audio_b64 = payload.get("audio")
                                if audio_b64:
                                    try:
                                        # Dekodowanie z Base64 i wysłanie jako Blob PCM
                                        raw_audio = base64.b64decode(audio_b64)
                                        await session.send_realtime_input(
                                            audio=types.Blob(
                                                data=raw_audio, 
                                                mime_type="audio/pcm;rate=16000"
                                            )
                                        )
                                    except Exception as e:
                                        print(f"❌ Błąd wysyłania audio do modelu Gemini: {e}")
                                        # Celowo nie przerywamy połączenia, próbujemy dalej
                                        continue

                        finally:
                            print("🛑 Zakończono pętlę nasłuchiwania (recv_loop).")

                    # =================================================
                    # PĘTLA WYSYŁAJĄCA (SEND LOOP)
                    # =================================================
                    async def send_loop():
                        """
                        Odbiera odpowiedzi ze strumienia Gemini (audio + transkrypcja)
                        i przesyła je z powrotem do przeglądarki klienta.
                        Parsuje również komendy sterujące (tryb cichy, stop).
                        """
                        print("▶️ Rozpoczęto nasłuchiwanie modelu (send_loop)...")
                        try:
                            async for response in session.receive():
                                if disconnect_event.is_set():
                                    break

                                server_content = getattr(response, "server_content", None)
                                
                                # -------------------------------------------------
                                # PRZETWARZANIE TRANSKRYPCJI WEJŚCIOWEJ (KOMENDY)
                                # -------------------------------------------------
                                if server_content and server_content.input_transcription:
                                    text = server_content.input_transcription.text.lower()
                                    
                                    if "stop" in text:
                                        print("🛑 Wykryto komendę 'STOP' - nakazuję UI wyczyszczenie buforów audio.")
                                        await ws.send_json({"type": "control", "action": "stop_audio"})
                                        # Opcjonalnie: można tu wysłać sygnał do modelu o przerwaniu generowania
                                        
                                    if "nakazuję milczenie" in text or "milcz" in text:
                                        state["is_silent_mode"] = True
                                        print("🔇 AKTYWACJA TRYBU CICHEGO. Jarvis będzie od teraz pracował w tle.")
                                        
                                    if "możesz mówić" in text or "wróć do mówienia" in text:
                                        state["is_silent_mode"] = False
                                        print("🔊 DEAKTYWACJA TRYBU CICHEGO. Jarvis odzyskuje głos.")

                                # -------------------------------------------------
                                # PRZESYŁANIE AUDIO DO KLIENTA
                                # -------------------------------------------------
                                if getattr(response, "data", None):
                                    if not state["is_silent_mode"]:
                                        # Przesyłamy surowe bajty audio przez WebSocket
                                        await ws.send_bytes(response.data)
                                    else:
                                        # W trybie cichym ignorujemy przychodzące paczki audio
                                        pass

                                # -------------------------------------------------
                                # ZBIERANIE I ZAPIS TRANSKRYPCJI DO BAZY (PAMIĘĆ)
                                # -------------------------------------------------
                                if server_content and getattr(server_content, "model_turn", None):
                                    for part in server_content.model_turn.parts:
                                        if getattr(part, "text", None):
                                            state["pending_assistant_text"] += part.text

                                # Aktualizacja transkrypcji z tury użytkownika
                                if server_content and server_content.input_transcription:
                                    state["pending_user_text"] += server_content.input_transcription.text

                                # Zapis pełnej wymiany, gdy model uzna turę za zakończoną
                                if server_content and getattr(server_content, "turn_complete", False):
                                    try:
                                        user_msg = state["pending_user_text"].strip()
                                        assist_msg = state["pending_assistant_text"].strip()
                                        
                                        if user_msg:
                                            memory.save_message("user", user_msg)
                                            print(f"👤 Użytkownik: {user_msg}")
                                            
                                        if assist_msg:
                                            memory.save_message("assistant", assist_msg)
                                            if not state["is_silent_mode"]:
                                                print(f"🤖 Jarvis: {assist_msg}")
                                            else:
                                                print(f"🤖 Jarvis (w tle): {assist_msg}")
                                                
                                    except Exception as e:
                                        print(f"❌ Błąd podczas zapisywania wiadomości do bazy: {e}")

                                    # Wyczyszczenie buforów na następną turę
                                    state["pending_user_text"] = ""
                                    state["pending_assistant_text"] = ""

                            print("ℹ️ Zakończono odczyt ze strumienia modelu (model zakończył sesję).")
                            
                        except Exception as e:
                            print(f"❌ Błąd krytyczny w pętli send_loop: {e}")
                        finally:
                            print("🛑 Zakończono pętlę nasłuchiwania modelu (send_loop).")

                    # =================================================
                    # URUCHOMIENIE I SYNCHRONIZACJA ZADAŃ
                    # =================================================
                    
                    # Tworzenie zadań asynchronicznych
                    recv_task = asyncio.create_task(recv_loop())
                    send_task = asyncio.create_task(send_loop())

                    # Oczekiwanie na zakończenie któregokolwiek z zadań
                    done, pending = await asyncio.wait(
                        [recv_task, send_task], 
                        return_when=asyncio.FIRST_COMPLETED
                    )

                    # Weryfikacja przyczyny wyjścia z zadań
                    if disconnect_event.is_set():
                        print("🔔 Wykryto rozłączenie klienta. Przerywam pętlę główną sesji.")
                        for t in pending:
                            t.cancel()
                        # Zbieranie anulowanych zadań
                        await asyncio.gather(*pending, return_exceptions=True)
                        break

                    # Jeśli sesja modelu wygasła (send_loop zakończył się naturalnie),
                    # a klient wciąż jest połączony, wymuszamy restart sesji
                    print("🔁 Klient podłączony, ale sesja wygasła. Wymuszam restart live.connect...")
                    for t in pending:
                        t.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)

                    # Krótki odpoczynek, aby zapobiec przeciążeniu pętli (tight-loop)
                    await asyncio.sleep(0.5)

            except Exception as e:
                # Obsługa błędów podczas nawiązywania połączenia z Gemini
                print(f"❌ Błąd nawiązywania sesji z modelem GenAI: {e}")
                if disconnect_event.is_set():
                    break
                # Odczekaj chwilę przed kolejną próbą nawiązania połączenia
                await asyncio.sleep(1.0)
                continue

    except WebSocketDisconnect:
        print("🔌 Główny wyjątek WebSocketDisconnect (outer loop).")
    except Exception as e:
        print(f"❌ Zewnętrzny błąd sesji JARVIS (outer exception): {e}")
    finally:
        # =================================================
        # CZYSZCZENIE ZASOBÓW PO ZAKOŃCZENIU POŁĄCZENIA
        # =================================================
        print("🧹 Sprzątanie zasobów po zakończeniu połączenia...")
        try:
            memory.close()
            print("✅ Pamięć bazy danych została zamknięta.")
        except Exception as e:
            print(f"❌ Błąd podczas zamykania połączenia z bazą: {e}")
            
        try:
            if ws.client_state.name != "DISCONNECTED":
                await ws.close()
                print("✅ Gniazdo WebSocket zostało bezpiecznie zamknięte.")
        except Exception as e:
            print(f"❌ Błąd podczas zamykania gniazda WebSocket: {e}")
            
        print("🔌 JARVIS DISCONNECTED - Koniec cyklu życia endpointu ws_endpoint.")

# Blok startowy na potrzeby uruchomienia pliku bezpośrednio przez Python
if __name__ == "__main__":
    import uvicorn
    # Uruchomienie deweloperskie na wszystkich interfejsach
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)