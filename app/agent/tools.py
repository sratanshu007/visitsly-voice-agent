from typing import Any, Dict, List

FINALIZE_CALL_TOOL: Dict[str, Any] = {
    "name": "finalize_call",
    "description": "Call this function as soon as the site visit call outcome is resolved with the customer.",
    "parameters": {
        "type": "object",
        "properties": {
            "outcome": {
                "type": "string",
                "enum": [
                    "CONFIRMED",
                    "RESCHEDULED",
                    "CANCELLED",
                    "CALLBACK_REQUESTED",
                    "NOT_INTERESTED",
                    "WRONG_PERSON",
                ],
                "description": "The final categorized outcome of the conversation.",
            },
            "new_datetime": {
                "type": "string",
                "description": "If RESCHEDULED, the new agreed date and time in YYYY-MM-DD HH:MM format or clear natural language (e.g. '2026-11-07 16:00').",
            },
            "notes": {
                "type": "string",
                "description": "Brief notes, customer questions, or reschedule context.",
            },
        },
        "required": ["outcome"],
    },
}

AGENT_TOOLS: List[Dict[str, Any]] = [FINALIZE_CALL_TOOL]

