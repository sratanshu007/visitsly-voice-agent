import asyncio
import base64
import json
import logging
import re
import time
from datetime import datetime
from typing import Optional
from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState
from sqlalchemy import select

from app.config import get_settings
from app.models.database import AsyncSessionLocal
from app.models.entities import Call, Booking, Transcript
from app.models.schemas import CallOutcome
from app.agent.state_machine import CallStateMachine
from app.agent.tools import AGENT_TOOLS
from app.agent.date_parser import parse_hindi_relative_datetime
from app.agent.prompts import (
    FALLBACK_ERROR_MESSAGE,
    SILENCE_REPROMPT_MESSAGE,
    SILENCE_HANGUP_MESSAGE,
    MAX_DURATION_HANGUP_MESSAGE,
)
from app.providers import get_stt_provider, get_llm_provider, get_tts_provider
from app.providers.base import STTResult, LLMToken
from app.realtime.audio_utils import compute_audio_energy
from app.realtime.latency_tracker import TurnLatencyTracker
from app.services.webhook_sender import WebhookSenderService
from app.services.optout import OptOutService
from app.services.plivo_service import PlivoService

logger = logging.getLogger("voice_agent.realtime.stream_handler")
settings = get_settings()

SENTENCE_SPLIT_REGEX = re.compile(r"([.!?;|।\n]+)")


class PlivoStreamHandler:
    """Core real-time bi-directional audio streaming pipeline for Plivo calls."""

    def __init__(self, websocket: WebSocket, call_id: str, booking_id: str):
        self.ws = websocket
        self.call_id = call_id
        self.booking_id = booking_id
        self.stream_id: Optional[str] = None
        self.state_machine: Optional[CallStateMachine] = None

        self.stt = get_stt_provider()
        self.llm = get_llm_provider()
        self.tts = get_tts_provider()

        self.is_active = True
        self.is_agent_speaking = False
        self.is_synthesizing = False
        self.current_llm_task: Optional[asyncio.Task] = None
        self.current_tts_task: Optional[asyncio.Task] = None
        self.playback_queue: asyncio.Queue[bytes] = asyncio.Queue()

        self.silence_timer_task: Optional[asyncio.Task] = None
        self.last_audio_received_time = time.perf_counter()
        self.agent_speech_end_time = 0.0
        self.current_tracker: Optional[TurnLatencyTracker] = None

        self.full_transcript_log: list[dict] = []

    async def run(self) -> None:
        """Main lifecycle of the Plivo WebSocket connection."""
        await self.ws.accept()
        logger.info(f"[Call {self.call_id}] WebSocket accepted. Loading booking details...")

        # 1. Fetch booking and call entities from DB
        booking_data = await self._load_booking_details()
        if not booking_data:
            logger.error(f"[Call {self.call_id}] Booking {self.booking_id} not found in DB.")
            await self.ws.close()
            return

        self.state_machine = CallStateMachine(
            call_id=self.call_id,
            booking_id=self.booking_id,
            customer_name=booking_data["customer_name"],
            phone=booking_data["phone"],
            property_name=booking_data["property_name"],
            visit_datetime=booking_data["visit_datetime"],
        )

        # 2. Mark call as IN_PROGRESS in DB
        await self._update_call_status("IN_PROGRESS")

        # 3. Connect to streaming STT
        await self.stt.connect(on_transcript=self._on_stt_transcript)

        playback_task: Optional[asyncio.Task] = None
        silence_task: Optional[asyncio.Task] = None

        try:
            # 4. Listen for incoming Plivo events
            while self.is_active:
                try:
                    message_str = await self.ws.receive_text()
                except (WebSocketDisconnect, RuntimeError):
                    logger.info(f"[Call {self.call_id}] Plivo WebSocket disconnected.")
                    break
                except Exception as e:
                    logger.warning(f"[Call {self.call_id}] WebSocket receive terminated: {e}")
                    break

                try:
                    data = json.loads(message_str)
                except Exception:
                    continue

                event = data.get("event")

                if event == "start":
                    start_data = data.get("start", {})
                    self.stream_id = start_data.get("streamId") or data.get("streamId")
                    logger.info(f"[Call {self.call_id}] Plivo stream started: stream_id={self.stream_id}")

                    # Stream is now active! Start audio playback worker and silence monitor
                    if not playback_task:
                        playback_task = asyncio.create_task(self._playback_loop())
                    if not silence_task:
                        silence_task = asyncio.create_task(self._silence_monitor_loop())

                    # Synthesize and speak the opening greeting
                    greeting = self.state_machine.get_initial_greeting()
                    asyncio.create_task(self._queue_agent_speech(greeting, is_opening=True))

                elif event == "media":
                    # Caller speech audio frame (base64 G.711 mu-law 8kHz)
                    media_data = data.get("media", {})
                    payload_b64 = media_data.get("payload", "")
                    if payload_b64:
                        raw_mulaw = base64.b64decode(payload_b64)
                        self.last_audio_received_time = time.perf_counter()
                        self.state_machine.reset_silence()

                        # Intelligent Acoustic Echo & Barge-In isolation
                        energy = compute_audio_energy(raw_mulaw)
                        is_agent_audio_active = (
                            self.is_agent_speaking
                            or self.is_synthesizing
                            or (time.perf_counter() < self.agent_speech_end_time)
                        )

                        if is_agent_audio_active:
                            # While agent speaks, discard low-energy speaker echo (150-320 RMS)
                            # Only forward audio if customer speaks loudly and clearly (> 350 RMS)
                            if energy > 350.0:
                                await self.stt.send_audio(raw_mulaw)
                        else:
                            # Agent is completely silent, normal caller speech flows freely into STT
                            await self.stt.send_audio(raw_mulaw)

                elif event == "clearedAudio":
                    logger.debug(f"[Call {self.call_id}] Plivo acknowledged clearedAudio")

                elif event == "stop":
                    logger.info(f"[Call {self.call_id}] Plivo stop event received")
                    break

        except (WebSocketDisconnect, RuntimeError):
            logger.info(f"[Call {self.call_id}] Plivo WebSocket disconnected")
        except Exception as e:
            logger.error(f"[Call {self.call_id}] Stream loop exception: {e}", exc_info=True)
            await self._play_fallback_and_hangup()
        finally:
            self.is_active = False
            if playback_task and not playback_task.done():
                playback_task.cancel()
            if silence_task and not silence_task.done():
                silence_task.cancel()
            if self.current_llm_task and not self.current_llm_task.done():
                self.current_llm_task.cancel()
            if self.current_tts_task and not self.current_tts_task.done():
                self.current_tts_task.cancel()
            await self.stt.disconnect()
            await self._finalize_and_cleanup()

    async def _on_stt_transcript(self, result: STTResult) -> None:
        """Called when STT engine outputs a transcript."""
        text = result.text.strip()
        if not text or not self.is_active:
            return

        logger.info(f"[Call {self.call_id}] [STT Final={result.is_final}] Caller: {text}")

        # If call is already finalized, ignore any further user speech while closing plays
        if self.state_machine and (self.state_machine.is_finalized or self.state_machine.is_terminated):
            logger.info(f"[Call {self.call_id}] Call finalized. Ignoring post-final speech: {text}")
            return

        # Barge-in safety (only when active and not finalized)
        if self.is_agent_speaking and not (self.state_machine and self.state_machine.is_finalized):
            await self._handle_barge_in()

        if not result.is_final:
            return

        # Start latency tracker for this turn
        self.current_tracker = TurnLatencyTracker(turn_index=self.state_machine.turn_count + 1)
        self.current_tracker.mark_user_speech_end()
        self.current_tracker.mark_stt_received()

        # Check for opt-out request ("call mat karo", etc.)
        if self.state_machine.check_opt_out(text):
            logger.info(f"[Call {self.call_id}] Opt-out detected from caller speech!")
            await self._record_transcript("user", text)
            # Add phone to opt-out database table
            async with AsyncSessionLocal() as session:
                await OptOutService.add_opt_out(
                    session,
                    self.state_machine.phone,
                    reason="Voice call caller request",
                )
            opt_out_msg = (
                "Maaf kijiye, hum aapka number list se hata dete hain aur dobara call nahi karenge. Dhanyavaad."
            )
            await self._queue_agent_speech(opt_out_msg)
            await asyncio.sleep(2.0)
            await self._stop_stream()
            return

        # Check if customer specified a new date/time in their speech
        parsed_res = parse_hindi_relative_datetime(text)
        if parsed_res:
            _, human_dt = parsed_res
            self.state_machine.new_datetime = human_dt
            self.state_machine.outcome = CallOutcome.RESCHEDULED
            logger.info(f"[Call {self.call_id}] Detected reschedule request: {human_dt}")

        # Record user turn in messages and DB
        self.state_machine.messages.append({"role": "user", "content": text})
        await self._record_transcript("user", text)

        # Trigger LLM generation
        if self.current_llm_task and not self.current_llm_task.done():
            self.current_llm_task.cancel()
        self.current_llm_task = asyncio.create_task(self._process_llm_turn())

    async def _process_llm_turn(self) -> None:
        """Streams response from LLM and synthesizes complete, natural response without stuttering."""
        self.current_tracker.mark_llm_start()
        system_prompt = self.state_machine.build_system_prompt()

        full_assistant_reply = ""
        tool_call_to_execute = None

        try:
            async for token in self.llm.stream_chat(
                messages=self.state_machine.messages,
                system_prompt=system_prompt,
                tools=AGENT_TOOLS,
            ):
                if token.is_first and self.current_tracker:
                    self.current_tracker.mark_llm_first_token()

                if token.tool_call:
                    tool_call_to_execute = token.tool_call

                if token.text:
                    full_assistant_reply += token.text

            reply_to_speak = full_assistant_reply.strip()

            # If tool call was executed and LLM generated no text or brief text, ensure polite closing
            if tool_call_to_execute and len(reply_to_speak) < 15:
                args = tool_call_to_execute.get("arguments", {})
                outcome_str = args.get("outcome", "CONFIRMED")
                outcome_enum = CallOutcome.__members__.get(outcome_str, CallOutcome.CONFIRMED)
                new_dt = args.get("new_datetime") or self.state_machine.new_datetime

                if outcome_enum == CallOutcome.CONFIRMED:
                    reply_to_speak = "Dhanyavaad ji, aapki booking confirm kar di gayi hai. Hum aapse site par milenge."
                elif outcome_enum == CallOutcome.RESCHEDULED:
                    reply_to_speak = f"Theek hai ji, main aapka visit {new_dt or 'naye samay'} ke liye reschedule kar deti hoon. Dhanyavaad!"
                elif outcome_enum == CallOutcome.CANCELLED:
                    reply_to_speak = "Theek hai ji, aapki site visit cancel kar di gayi hai. Dhanyavaad!"
                elif outcome_enum == CallOutcome.NOT_INTERESTED:
                    reply_to_speak = "Theek hai ji, hum aapka number note kar lete hain. Dhanyavaad!"
                else:
                    reply_to_speak = "Theek hai ji, hamari sales team aapse jald hi sampark karegi. Dhanyavaad!"

            # If LLM gave neither text nor tool call, prompt caller naturally
            elif not reply_to_speak and not tool_call_to_execute:
                reply_to_speak = "Ji, kya aap dobara bata sakte hain? Aapke liye kaun sa din aur time convenient rahega?"

            # Record transcript and speak complete response smoothly
            if reply_to_speak:
                self.state_machine.messages.append({"role": "assistant", "content": reply_to_speak})
                await self._record_transcript("assistant", reply_to_speak)
                await self._queue_agent_speech(reply_to_speak)

            # Execute tool call if triggered by LLM
            if tool_call_to_execute:
                args = tool_call_to_execute.get("arguments", {})
                outcome_str = args.get("outcome", "CONFIRMED")
                outcome_enum = CallOutcome.__members__.get(outcome_str, CallOutcome.CONFIRMED)
                new_dt = args.get("new_datetime") or self.state_machine.new_datetime
                notes = args.get("notes")
                self.state_machine.finalize_call(outcome=outcome_enum, new_datetime=new_dt, notes=notes)

                # Wait for outgoing speech to finish playing completely before ending stream
                await self._wait_playback_empty()
                await asyncio.sleep(1.2)
                await self._stop_stream()

        except asyncio.CancelledError:
            logger.info(f"[Call {self.call_id}] LLM processing cancelled due to barge-in.")
        except Exception as e:
            logger.error(f"[Call {self.call_id}] LLM processing error: {e}", exc_info=True)

    async def _queue_agent_speech(self, text: str, is_opening: bool = False) -> None:
        """Synthesizes text using TTS and enqueues audio frames for playback."""
        if not text.strip() or not self.is_active:
            return

        logger.info(f"[Call {self.call_id}] Agent Speaking: {text}")
        if self.current_tracker:
            self.current_tracker.mark_tts_start()

        self.is_agent_speaking = True
        self.is_synthesizing = True
        first_frame = True

        try:
            async for mulaw_frame in self.tts.stream_tts(text):
                if first_frame and self.current_tracker:
                    self.current_tracker.mark_tts_first_byte()
                    first_frame = False
                await self.playback_queue.put(mulaw_frame)
        except asyncio.CancelledError:
            logger.info(f"[Call {self.call_id}] TTS synthesis cancelled by barge-in.")
        except Exception as e:
            logger.error(f"[Call {self.call_id}] TTS stream error: {e}")
        finally:
            self.is_synthesizing = False

    async def _playback_loop(self) -> None:
        """Continuously pulls audio chunks from queue and sends playAudio events to Plivo."""
        while self.is_active:
            try:
                frame = await self.playback_queue.get()
                if self.current_tracker:
                    self.current_tracker.mark_first_audio_dispatched()
                    self.current_tracker.log_turn_summary()
                    self.current_tracker = None

                b64_payload = base64.b64encode(frame).decode("utf-8")
                event_payload = {
                    "event": "playAudio",
                    "media": {
                        "contentType": "audio/x-mulaw",
                        "sampleRate": 8000,
                        "payload": b64_payload,
                    },
                }
                if self.stream_id:
                    event_payload["streamId"] = self.stream_id

                if self.ws.application_state == WebSocketState.CONNECTED:
                    await self.ws.send_text(json.dumps(event_payload))
                    self.agent_speech_end_time = time.perf_counter() + 0.25
                else:
                    self.playback_queue.task_done()
                    break

                self.playback_queue.task_done()

                # If queue becomes empty and synthesis is finished, agent is no longer speaking
                if self.playback_queue.empty() and not self.is_synthesizing:
                    self.is_agent_speaking = False

                # 20ms real-time pacing per 160-byte frame (8000Hz 8-bit mulaw)
                await asyncio.sleep(0.0195)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Call {self.call_id}] Playback loop error: {e}")
                break

    async def _handle_barge_in(self) -> None:
        """
        Barge-in: if caller speaks while agent talking, immediately clear audio on Plivo,
        cancel TTS/LLM tasks, and flush queue.
        """
        # Never barge-in if call is finalized and agent is giving final closing
        if self.state_machine and self.state_machine.is_finalized:
            return

        logger.info(f"[Call {self.call_id}] Barge-in triggered! Stopping audio playback.")
        self.is_agent_speaking = False
        self.is_synthesizing = False
        self.agent_speech_end_time = 0.0

        # 1. Send clearAudio event to Plivo
        if self.stream_id and self.ws.application_state == WebSocketState.CONNECTED:
            clear_event = {"event": "clearAudio", "streamId": self.stream_id}
            try:
                await self.ws.send_text(json.dumps(clear_event))
            except Exception as e:
                logger.warning(f"Failed to send clearAudio: {e}")

        # 2. Cancel running TTS and LLM tasks
        if self.current_tts_task and not self.current_tts_task.done():
            self.current_tts_task.cancel()
        if self.current_llm_task and not self.current_llm_task.done():
            self.current_llm_task.cancel()

        # 3. Empty playback queue
        while not self.playback_queue.empty():
            try:
                self.playback_queue.get_nowait()
                self.playback_queue.task_done()
            except Exception:
                break

    async def _silence_monitor_loop(self) -> None:
        """Checks for customer silence every second."""
        while self.is_active:
            await asyncio.sleep(1.0)
            if not self.is_agent_speaking and not self.is_synthesizing and self.playback_queue.empty():
                elapsed = time.perf_counter() - self.last_audio_received_time

                # Check max call duration hard limit (180s)
                duration_exceeded, duration_msg = self.state_machine.check_duration_exceeded()
                if duration_exceeded:
                    logger.warning(f"[Call {self.call_id}] Max call duration reached (180s). Hanging up.")
                    await self._queue_agent_speech(duration_msg)
                    await self._wait_playback_empty()
                    await self._stop_stream()
                    break

                # Check silence timeout (6s)
                if elapsed >= self.state_machine.silence_timeout:
                    self.last_audio_received_time = time.perf_counter()
                    should_hangup, silence_msg = self.state_machine.handle_silence_prompt()
                    logger.info(
                        f"[Call {self.call_id}] Silence timeout prompt count={self.state_machine.silence_count}"
                    )
                    await self._queue_agent_speech(silence_msg)

                    if should_hangup:
                        logger.info(f"[Call {self.call_id}] Max silence prompts exceeded. Hanging up.")
                        await self._wait_playback_empty()
                        await self._stop_stream()
                        break

    async def _wait_playback_empty(self) -> None:
        while not self.playback_queue.empty() or self.is_agent_speaking or self.is_synthesizing:
            await asyncio.sleep(0.05)

    async def _stop_stream(self) -> None:
        """Sends stop event to Plivo."""
        self.is_active = False
        try:
            if self.ws.application_state == WebSocketState.CONNECTED:
                await self.ws.send_text(json.dumps({"event": "stop"}))
        except Exception:
            pass

    async def _play_fallback_and_hangup(self) -> None:
        """Plays graceful fallback audio on unexpected system crash."""
        if self.ws.application_state != WebSocketState.CONNECTED:
            return
        try:
            await self._queue_agent_speech(FALLBACK_ERROR_MESSAGE)
            await self._wait_playback_empty()
        except Exception:
            pass
        await self._stop_stream()

    async def _load_booking_details(self) -> Optional[dict]:
        async with AsyncSessionLocal() as session:
            if not self.booking_id and self.call_id:
                call_rec = await session.get(Call, self.call_id)
                if call_rec:
                    self.booking_id = call_rec.booking_id

            if not self.booking_id:
                call_rec = await session.get(Call, self.call_id)
                if call_rec:
                    self.booking_id = call_rec.booking_id

            if not self.booking_id:
                return None

            stmt = select(Booking).where(Booking.booking_id == self.booking_id)
            res = await session.execute(stmt)
            booking = res.scalar_one_or_none()
            if not booking:
                return None
            return {
                "customer_name": booking.customer_name,
                "phone": booking.phone,
                "property_name": booking.property_name,
                "visit_datetime": booking.visit_datetime,
            }

    async def _update_call_status(self, status: str) -> None:
        async with AsyncSessionLocal() as session:
            stmt = select(Call).where(Call.id == self.call_id)
            res = await session.execute(stmt)
            call_rec = res.scalar_one_or_none()
            if call_rec:
                call_rec.status = status
                if status == "IN_PROGRESS":
                    call_rec.started_at = datetime.utcnow()
                await session.commit()

    async def _record_transcript(self, role: str, text: str) -> None:
        self.full_transcript_log.append({"role": role, "text": text, "time": datetime.utcnow().isoformat()})
        async with AsyncSessionLocal() as session:
            t = Transcript(
                call_id=self.call_id,
                role=role,
                text=text,
                timestamp=datetime.utcnow(),
            )
            db_call = await session.get(Call, self.call_id)
            if db_call:
                session.add(t)
                await session.commit()

    async def _finalize_and_cleanup(self) -> None:
        """Saves outcome to DB and dispatches webhook to SaaS."""
        duration = self.state_machine.get_call_duration_seconds() if self.state_machine else 0
        final_outcome = (
            self.state_machine.outcome
            if (self.state_machine and self.state_machine.outcome)
            else CallOutcome.CALLBACK_REQUESTED
        )
        new_dt = self.state_machine.new_datetime if self.state_machine else None
        notes = self.state_machine.notes if self.state_machine else ""

        transcript_text = "\n".join(f"{m['role'].capitalize()}: {m['text']}" for m in self.full_transcript_log)
        summary = (
            f"Call finished with outcome {final_outcome.value} in {duration}s. "
            f"{notes or 'Visit confirmed or discussed with customer.'}"
        )

        async with AsyncSessionLocal() as session:
            stmt = select(Call).where(Call.id == self.call_id)
            res = await session.execute(stmt)
            call_rec = res.scalar_one_or_none()
            attempts = 1
            if call_rec:
                attempts = call_rec.attempts or 1
                call_rec.status = "COMPLETED"
                call_rec.ended_at = datetime.utcnow()
                call_rec.duration = duration
                call_rec.outcome = final_outcome.value
                call_rec.new_datetime = new_dt
                call_rec.transcript_summary = summary
                await session.commit()

            # Update booking table status and visit_datetime
            stmt_bk = select(Booking).where(Booking.booking_id == self.booking_id)
            res_bk = await session.execute(stmt_bk)
            booking_rec = res_bk.scalar_one_or_none()
            if booking_rec:
                booking_rec.status = final_outcome.value
                if new_dt:
                    booking_rec.visit_datetime = new_dt
                await session.commit()

            # Dispatch outbound result webhook to SaaS
            await WebhookSenderService.send_call_result_webhook(
                db=session,
                booking_id=self.booking_id,
                outcome=final_outcome,
                attempts=attempts,
                duration=duration,
                transcript_summary=summary,
                new_datetime=new_dt,
                transcript_full=transcript_text,
            )

        logger.info(
            f"[Call {self.call_id}] Session completed. Outcome: {final_outcome.value}, "
            f"Duration: {duration}s, Webhook dispatched."
        )

