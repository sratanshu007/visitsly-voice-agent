import sqlite3
import sys
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "voice_agent.db")

def print_separator(title=""):
    print("\n" + "=" * 80)
    if title:
        print(f"  {title}")
        print("=" * 80)

def view_recent_calls():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print_separator("RECENT CALLS (LATEST FIRST)")
    cursor.execute("""
        SELECT c.id, c.booking_id, b.customer_name, b.phone, c.status, c.duration, c.outcome, c.new_datetime, c.started_at, c.transcript_summary
        FROM calls c
        LEFT JOIN bookings b ON c.booking_id = b.booking_id
        ORDER BY c.created_at DESC
        LIMIT 10;
    """)
    rows = cursor.fetchall()
    
    if not rows:
        print("Koi call records nahi mile.")
        conn.close()
        return

    for idx, r in enumerate(rows, 1):
        call_id, booking_id, name, phone, status, duration, outcome, new_dt, started, summary = r
        print(f"\n[{idx}] Call ID: {call_id}")
        print(f"    Customer : {name or 'N/A'} ({phone or 'N/A'})")
        print(f"    Status   : {status} | Duration: {duration}s | Outcome: {outcome}")
        if new_dt:
            print(f"    New Visit: {new_dt}")
        print(f"    Started  : {started}")
        if summary:
            print(f"    Summary  : {summary}")
            
    conn.close()

def view_transcripts(call_id_filter=None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    if call_id_filter:
        print_separator(f"TRANSCRIPT FOR CALL: {call_id_filter}")
        cursor.execute("""
            SELECT role, text, timestamp
            FROM transcripts
            WHERE call_id = ?
            ORDER BY timestamp ASC;
        """, (call_id_filter,))
    else:
        print_separator("LATEST CONVERSATION TRANSCRIPTS (LAST 25 MESSAGES)")
        cursor.execute("""
            SELECT call_id, role, text, timestamp
            FROM transcripts
            ORDER BY timestamp DESC
            LIMIT 25;
        """)
    
    rows = cursor.fetchall()
    if not rows:
        print("Koi transcript records nahi mile.")
        conn.close()
        return
        
    if call_id_filter:
        for role, text, ts in rows:
            speaker = "🤖 AI AGENT" if role == "assistant" else "👤 CALLER"
            print(f"[{ts}] {speaker}: {text}")
    else:
        for cid, role, text, ts in reversed(rows):
            speaker = "🤖 AI" if role == "assistant" else "👤 USER"
            print(f"[Call ...{cid[-6:]}] {speaker}: {text}")

    conn.close()

def view_bookings():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    print_separator("CONFIRMED BOOKINGS")
    cursor.execute("""
        SELECT booking_id, customer_name, phone, property_name, visit_datetime, status, created_at
        FROM bookings
        ORDER BY created_at DESC
        LIMIT 10;
    """)
    rows = cursor.fetchall()
    if not rows:
        print("Koi bookings nahi mile.")
    for b in rows:
        print(f"• ID: {b[0]} | {b[1]} | Phone: {b[2]} | Property: {b[3]} | Visit: {b[4]} | Status: {b[5]}")
    conn.close()

def view_opt_outs():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    print_separator("OPT-OUT (DND) LIST")
    cursor.execute("SELECT phone_hash, reason, created_at FROM opt_outs ORDER BY created_at DESC;")
    rows = cursor.fetchall()
    if not rows:
        print("Opt-out list abhi empty hai.")
    for o in rows:
        print(f"• Hash: {o[0][:16]}... | Reason: {o[1]} | Date: {o[2]}")
    conn.close()

if __name__ == "__main__":
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg == "calls":
            view_recent_calls()
        elif arg == "transcripts" or arg == "chat":
            cid = sys.argv[2] if len(sys.argv) > 2 else None
            view_transcripts(cid)
        elif arg == "bookings":
            view_bookings()
        elif arg == "optout":
            view_opt_outs()
        else:
            view_transcripts(sys.argv[1])
    else:
        view_recent_calls()
        view_transcripts()
        print("\n" + "=" * 80)
        print("💡 Commands to inspect specific tables:")
        print("   python view_db.py calls              -> Sirf call history dekhne ke liye")
        print("   python view_db.py chat               -> Latest conversation transcript dekhne ke liye")
        print("   python view_db.py chat <CALL_ID>     -> Kisi specific call ka poora conversation dekhne ke liye")
        print("   python view_db.py bookings           -> Bookings table dekhne ke liye")
        print("   python view_db.py optout             -> DND / Opt-out list dekhne ke liye")
        print("=" * 80 + "\n")

