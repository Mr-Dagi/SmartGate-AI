import requests

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen2.5:1.5b"

SYSTEM_PROMPT = """
You are SmartGate AI, an assistant for a university smart identity
and verification system.

You help administrators and students understand:
- Student ID features
- NFC card scanning
- Face verification results
- Dashboard features
- System troubleshooting

Be clear, helpful, and concise.

Never make identity decisions, approve access, or change verification
results. Only the authorized verification system can produce those results.
"""


def chat_with_ai(message, history=None):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    if history:
        messages.extend(history[-10:])

    messages.append({"role": "user", "content": message})

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "messages": messages,
                "stream": False
            },
            timeout=120
        )

        response.raise_for_status()

        return {
            "success": True,
            "reply": response.json()["message"]["content"]
        }

    except requests.RequestException:
        return {
            "success": False,
            "reply": "The AI assistant is currently unavailable."
        }