from flask import Flask, request, jsonify
from pyngrok import ngrok
from openai import OpenAI

# -----------------------------
# CONFIG
# -----------------------------
OPENAI_API_KEY = "YOUR_API_KEY"

client = OpenAI(api_key=OPENAI_API_KEY)

app = Flask(__name__)

# -----------------------------
# AI CHAT ENDPOINT
# -----------------------------
@app.route("/chat", methods=["POST"])
def chat():

    data = request.json
    user_message = data.get("message", "")

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": "You are a helpful AI assistant."},
                {"role": "user", "content": user_message}
            ]
        )

        reply = response.choices[0].message.content

        return jsonify({
            "success": True,
            "response": reply
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        })

# -----------------------------
# START SERVER + TUNNEL
# -----------------------------
if __name__ == "__main__":

    port = 5000

    # Create public tunnel
    public_url = ngrok.connect(port).public_url

    print("\n==============================")
    print("AI Tunnel Running")
    print("Public URL:", public_url)
    print("==============================\n")

    app.run(port=port)
