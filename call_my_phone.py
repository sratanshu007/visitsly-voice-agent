import asyncio
import os
import sys
import httpx

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.config import get_settings, mask_phone

async def main():
    settings = get_settings()
    print("=" * 70)
    print("  VISITSLY AI VOICE AGENT - LIVE PHONE CALL DISPATCHER")
    print("=" * 70)

    # 1. Check Phone Number
    if len(sys.argv) > 1:
        phone = sys.argv[1].strip()
    else:
        phone = input("Enter your mobile phone number with country code (e.g., +919876543210): ").strip()

    if not phone.startswith("+") or len(phone) < 11:
        print("❌ Error: Phone number must be in E.164 format with country code (e.g., +919876543210)")
        sys.exit(1)

    customer_name = input("Enter your name [default: Sratanshu]: ").strip() or "Sratanshu"
    property_name = input("Enter property name [default: Godrej Woods]: ").strip() or "Godrej Woods"

    # 2. Check PUBLIC_HOST
    public_host = settings.PUBLIC_HOST
    print(f"\nCurrent configured PUBLIC_HOST: {public_host}")
    if "localhost" in public_host or "127.0.0.1" in public_host:
        print("⚠️  WARNING: PUBLIC_HOST is set to localhost!")
        print("   Plivo cannot reach localhost from the cloud.")
        print("   Please start ngrok in a separate terminal:")
        print("       ngrok http 8000")
        print("   Then update PUBLIC_HOST in .env with your ngrok domain (without http://)")
        proceed = input("\nDo you want to proceed anyway with a simulated test? (y/n): ").strip().lower()
        if proceed != "y":
            print("Aborted. Update .env and run again.")
            sys.exit(0)

    # 3. Check Plivo Credentials
    auth_id = settings.PLIVO_AUTH_ID
    auth_token = settings.PLIVO_AUTH_TOKEN
    caller_id = settings.PLIVO_CALLER_ID
    print(f"Plivo Caller ID: {caller_id}")
    print(f"Plivo Auth ID  : {auth_id[:6]}...{auth_id[-4:] if len(auth_id) > 10 else ''}")

    # 4. Trigger Booking Endpoint
    local_server_url = f"http://127.0.0.1:{settings.PORT}/api/bookings/confirmed"
    payload = {
        "booking_id": f"live-call-{int(asyncio.get_event_loop().time())}",
        "customer_name": customer_name,
        "phone": phone,
        "property_name": property_name,
        "visit_datetime": "Kal subah 11:00 AM",
        "language": "hi",
        "consent": {
            "given": True,
            "timestamp": "2026-11-05T12:00:00Z",
            "ip": "127.0.0.1",
            "text": "Live test consent from call_my_phone CLI.",
        },
    }
    headers = {
        "X-API-Key": settings.API_KEY,
        "Content-Type": "application/json",
    }

    print(f"\nSending booking request to local server: {local_server_url} ...")
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(local_server_url, json=payload, headers=headers)
            print(f"Server Response HTTP {resp.status_code}:")
            print(resp.json())

            if resp.status_code == 202:
                data = resp.json()
                status_code = data.get("status")
                if status_code == "CALL_INITIATED":
                    print("\n✅ SUCCESS: Call initiated via Plivo!")
                    print(f"   Destination: {mask_phone(phone)}")
                    print("   Your phone will ring shortly. Answer it to speak with the AI assistant!")
                elif status_code == "CALL_SCHEDULED":
                    print("\n⏳ Call was scheduled for next calling window (09:00 - 21:00 IST).")
                    print(f"   Scheduled for: {data.get('scheduled_for')}")
                elif status_code == "OPTED_OUT":
                    print(f"\n🚫 This phone number ({phone}) is currently on the Opt-Out / DND list.")
            else:
                print(f"❌ Failed: {resp.text}")
    except httpx.ConnectError:
        print(f"\n❌ Error: Could not connect to local server at {local_server_url}")
        print("   Make sure the FastAPI server is running first:")
        print("       uvicorn app.main:app --port 8000")


if __name__ == "__main__":
    asyncio.run(main())

