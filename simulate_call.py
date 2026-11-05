import asyncio
import os
import sys
import time
from datetime import datetime

# Add root directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.config import get_settings
from app.agent.state_machine import CallStateMachine
from app.agent.tools import AGENT_TOOLS
from app.providers import get_llm_provider, get_tts_provider, get_stt_provider
from app.realtime.latency_tracker import TurnLatencyTracker
from app.models.schemas import CallOutcome

settings = get_settings()


async def simulate_conversation_loop():
    print("=" * 70)
    print("  VISITSLY AI VOICE AGENT - LOCAL CALL SIMULATOR (NO PLIVO REQUIRED)")
    print("=" * 70)
    print(f"Active LLM: {settings.LLM_PROVIDER.upper()}")
    print(f"Active TTS: {settings.TTS_PROVIDER.upper()}")
    print(f"Active STT: {settings.STT_PROVIDER.upper()}")
    print("=" * 70)

    customer_name = input("Customer Name [default: Rahul Sharma]: ").strip() or "Rahul Sharma"
    property_name = input("Property Name [default: Godrej Woods Phase 2]: ").strip() or "Godrej Woods Phase 2"
    visit_datetime = input("Scheduled Visit [default: Kal subah 11:00 AM]: ").strip() or "Kal subah 11:00 AM"

    state = CallStateMachine(
        call_id="sim-call-12345",
        booking_id="bk-9999",
        customer_name=customer_name,
        phone="+919876543210",
        property_name=property_name,
        visit_datetime=visit_datetime,
    )

    llm = get_llm_provider()
    tts = get_tts_provider()

    print("\n[Call Connected!]")
    greeting = state.get_initial_greeting()
    print(f"\nAI Agent: {greeting}")

    # Synthesize greeting with TTS to test audio pipeline
    t_start = time.perf_counter()
    chunk_count = 0
    async for _ in tts.stream_tts(greeting):
        chunk_count += 1
    tts_time = round((time.perf_counter() - t_start) * 1000, 1)
    print(f"   (TTS Latency: {tts_time}ms | {chunk_count} mu-law frames generated)")

    while not state.is_finalized and not state.is_terminated:
        try:
            print("\n" + "-" * 70)
            user_input = input(f"You ({customer_name}) [or type 'exit' / press Enter for silence]: ").strip()

            if user_input.lower() in ("exit", "quit"):
                print("Ending simulation.")
                break

            # Simulate silence handling if user presses enter with no input
            if not user_input:
                should_hangup, silence_msg = state.handle_silence_prompt()
                print(f"\nAI Agent (Silence Reprompt): {silence_msg}")
                if should_hangup:
                    print("\n[Call disconnected due to silence timeout]")
                    break
                continue

            state.reset_silence()

            # Latency Tracker
            tracker = TurnLatencyTracker(turn_index=state.turn_count + 1)
            tracker.mark_user_speech_end()
            tracker.mark_stt_received()

            # Check Opt-out
            if state.check_opt_out(user_input):
                print("\n[DND / Opt-Out Detected!]")
                closing = "Maaf kijiye, hum aapka number list se hata dete hain aur aage call nahi karenge. Dhanyavaad."
                print(f"AI Agent: {closing}")
                break

            state.messages.append({"role": "user", "content": user_input})
            tracker.mark_llm_start()

            system_prompt = state.build_system_prompt()
            print("\nAI Agent: ", end="", flush=True)

            first_token = True
            assistant_reply = ""
            tool_call_to_exec = None

            async for token in llm.stream_chat(
                messages=state.messages,
                system_prompt=system_prompt,
                tools=AGENT_TOOLS,
            ):
                if token.is_first:
                    tracker.mark_llm_first_token()

                if token.tool_call:
                    tool_call_to_exec = token.tool_call

                if token.text:
                    print(token.text, end="", flush=True)
                    assistant_reply += token.text

            print()  # newline
            tracker.mark_tts_start()

            # Synthesize reply
            async for _ in tts.stream_tts(assistant_reply):
                if tracker.tts_first_byte_time is None:
                    tracker.mark_tts_first_byte()
                    tracker.mark_first_audio_dispatched()

            tracker.log_turn_summary()

            if assistant_reply.strip():
                state.messages.append({"role": "assistant", "content": assistant_reply.strip()})
                state.turn_count += 1

            # Handle finalize call tool
            if tool_call_to_exec:
                args = tool_call_to_exec.get("arguments", {})
                outcome_str = args.get("outcome", "CONFIRMED")
                outcome = CallOutcome.__members__.get(outcome_str, CallOutcome.CONFIRMED)
                new_dt = args.get("new_datetime")
                notes = args.get("notes")
                state.finalize_call(outcome=outcome, new_datetime=new_dt, notes=notes)
                print(f"\n[TOOL CALLED: finalize_call]")
                print(f"   Outcome: {outcome.value}")
                print(f"   New Datetime: {new_dt or 'N/A'}")
                print(f"   Notes: {notes or 'N/A'}")
                print("\n[Call Finalized Successfully!]")
                break

        except KeyboardInterrupt:
            print("\nSimulation aborted.")
            break

    print("\n" + "=" * 70)
    print(f"FINAL CALL OUTCOME: {state.outcome.value if state.outcome else 'INCOMPLETE'}")
    print(f"Total Duration: {state.get_call_duration_seconds()} seconds")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(simulate_conversation_loop())

