#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI WHOIS Domain Finder App
- Single-file Flask app
- Core WHOIS lookup logic in a clean function (ready for AI post-processing)
"""

import json
import socket
from datetime import datetime

from flask import Flask, request, jsonify, render_template_string
import whois

app = Flask(__name__)

# -----------------------------
# Backend contract / core logic
# -----------------------------

def normalize_domain(domain: str) -> str:
    domain = (domain or "").strip().lower()
    if domain.startswith("http://"):
        domain = domain[7:]
    elif domain.startswith("https://"):
        domain = domain[8:]
    # strip path
    domain = domain.split("/")[0]
    return domain


def safe_whois_lookup(domain: str) -> dict:
    """
    Core WHOIS lookup function.
    Returns a normalized dict, safe for JSON and AI post-processing.
    """
    domain = normalize_domain(domain)
    if not domain:
        return {
            "domain": None,
            "error": "Empty domain",
        }

    try:
        w = whois.whois(domain)
    except Exception as e:
        return {
            "domain": domain,
            "error": f"WHOIS lookup failed: {e}",
        }

    # Convert non-serializable types (datetime, list, etc.)
    def serialize(value):
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, (list, tuple, set)):
            return [serialize(v) for v in value]
        return value

    raw_data = {}
    if isinstance(w, dict):
        raw_data = {k: serialize(v) for k, v in w.items()}
    else:
        # whois library sometimes returns an object
        raw_data = {k: serialize(v) for k, v in w.__dict__.items() if not k.startswith("_")}

    # Basic derived fields (for AI / UI)
    registrar = raw_data.get("registrar")
    creation_date = raw_data.get("creation_date")
    expiration_date = raw_data.get("expiration_date")
    name_servers = raw_data.get("name_servers")

    # Normalize single vs list dates
    def first_or_none(v):
        if isinstance(v, list) and v:
            return v[0]
        return v

    creation_date = first_or_none(creation_date)
    expiration_date = first_or_none(expiration_date)

    # Try to resolve IP
    ip_address = None
    try:
        ip_address = socket.gethostbyname(domain)
    except Exception:
        pass

    result = {
        "domain": domain,
        "ip_address": ip_address,
        "registrar": registrar,
        "creation_date": creation_date,
        "expiration_date": expiration_date,
        "name_servers": name_servers,
        "raw": raw_data,
        "error": None,
    }
    return result


# -----------------------------
# (Optional) AI hook
# -----------------------------

def ai_analyze_whois(whois_data: dict) -> dict:
    """
    Placeholder for AI logic.
    You can wire this to an LLM endpoint and return:
    - risk_score
    - summary
    - flags (e.g., newly registered, short registration, etc.)
    For now, we just do a simple heuristic.
    """
    analysis = {
        "summary": None,
        "risk_score": None,
        "flags": [],
    }

    if whois_data.get("error"):
        analysis["summary"] = "WHOIS lookup failed; no analysis available."
        analysis["risk_score"] = None
        return analysis

    domain = whois_data.get("domain")
    registrar = whois_data.get("registrar")
    creation_date = whois_data.get("creation_date")
    expiration_date = whois_data.get("expiration_date")

    # Simple heuristic: newer domains = higher risk
    risk_score = 50
    flags = []

    try:
        if creation_date:
            created = datetime.fromisoformat(str(creation_date))
            age_days = (datetime.utcnow() - created).days
            if age_days < 30:
                risk_score = 85
                flags.append("Newly registered domain (<30 days).")
            elif age_days < 365:
                risk_score = 65
                flags.append("Domain younger than 1 year.")
            else:
                risk_score = 30
                flags.append("Domain older than 1 year.")
    except Exception:
        flags.append("Could not parse creation date.")

    if not registrar:
        flags.append("Missing registrar information.")

    summary_parts = [
        f"Domain: {domain}",
        f"Registrar: {registrar or 'Unknown'}",
        f"Creation date: {creation_date or 'Unknown'}",
        f"Expiration date: {expiration_date or 'Unknown'}",
    ]
    summary = " | ".join(summary_parts)

    analysis["summary"] = summary
    analysis["risk_score"] = risk_score
    analysis["flags"] = flags
    return analysis


# -----------------------------
# HTTP API
# -----------------------------

@app.route("/api/whois", methods=["GET"])
def api_whois_get():
    domain = request.args.get("domain", "")
    data = safe_whois_lookup(domain)
    ai_data = ai_analyze_whois(data)
    return jsonify({
        "whois": data,
        "ai": ai_data,
    })


@app.route("/api/whois", methods=["POST"])
def api_whois_post():
    payload = request.get_json(silent=True) or {}
    domain = payload.get("domain", "")
    data = safe_whois_lookup(domain)
    ai_data = ai_analyze_whois(data)
    return jsonify({
        "whois": data,
        "ai": ai_data,
    })


# -----------------------------
# Simple web UI
# -----------------------------

INDEX_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>AI WHOIS Domain Finder</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 2rem; background: #111; color: #eee; }
    input[type=text] { width: 320px; padding: 0.4rem; }
    button { padding: 0.4rem 0.8rem; margin-left: 0.5rem; }
    .container { max-width: 900px; margin: auto; }
    pre { background: #222; padding: 1rem; overflow-x: auto; }
    .summary { margin-top: 1rem; padding: 0.75rem; background: #1b1b1b; border-radius: 4px; }
    .flags { margin-top: 0.5rem; }
    .flag { background: #333; padding: 0.25rem 0.5rem; margin-right: 0.25rem; border-radius: 3px; display: inline-block; }
    .risk { font-weight: bold; }
    a { color: #7fb3ff; }
  </style>
</head>
<body>
<div class="container">
  <h1>AI WHOIS Domain Finder</h1>
  <p>Enter a domain to fetch WHOIS data and a basic AI-style analysis.</p>
  <form id="whois-form" onsubmit="return false;">
    <input type="text" id="domain" placeholder="example.com">
    <button onclick="doLookup()">Lookup</button>
  </form>

  <div id="result" style="margin-top: 1.5rem;"></div>
</div>

<script>
async function doLookup() {
  const domain = document.getElementById('domain').value.trim();
  if (!domain) {
    alert("Please enter a domain.");
    return;
  }

  const resDiv = document.getElementById('result');
  resDiv.innerHTML = "<p>Loading...</p>";

  try {
    const resp = await fetch("/api/whois?domain=" + encodeURIComponent(domain));
    const data = await resp.json();

    const whois = data.whois || {};
    const ai = data.ai || {};

    let html = "";

    if (whois.error) {
      html += "<p><strong>Error:</strong> " + whois.error + "</p>";
    } else {
      html += "<div class='summary'>";
      html += "<div><strong>Domain:</strong> " + (whois.domain || "") + "</div>";
      html += "<div><strong>IP:</strong> " + (whois.ip_address || "Unknown") + "</div>";
      html += "<div><strong>Registrar:</strong> " + (whois.registrar || "Unknown") + "</div>";
      html += "<div><strong>Created:</strong> " + (whois.creation_date || "Unknown") + "</div>";
      html += "<div><strong>Expires:</strong> " + (whois.expiration_date || "Unknown") + "</div>";
      html += "</div>";
    }

    if (ai.summary || ai.risk_score !== null) {
      html += "<div class='summary'>";
      if (ai.summary) {
        html += "<div><strong>AI Summary:</strong> " + ai.summary + "</div>";
      }
      if (ai.risk_score !== null) {
        html += "<div class='risk'>Risk score: " + ai.risk_score + " / 100</div>";
      }
      if (ai.flags && ai.flags.length) {
        html += "<div class='flags'><strong>Flags:</strong> ";
        ai.flags.forEach(f => {
          html += "<span class='flag'>" + f + "</span>";
        });
        html += "</div>";
      }
      html += "</div>";
    }

    html += "<h3>Raw WHOIS JSON</h3>";
    html += "<pre>" + JSON.stringify(whois.raw || whois || {}, null, 2) + "</pre>";

    resDiv.innerHTML = html;
  } catch (e) {
    resDiv.innerHTML = "<p><strong>Error:</strong> " + e + "</p>";
  }
}
</script>
</body>
</html>
"""

@app.route("/", methods=["GET"])
def index():
    return render_template_string(INDEX_HTML)


# -----------------------------
# CLI entry point
# -----------------------------

def cli():
    import argparse
    parser = argparse.ArgumentParser(description="AI WHOIS Domain Finder (CLI)")
    parser.add_argument("domain", help="Domain name to lookup (e.g., example.com)")
    parser.add_argument("--json", action="store_true", help="Output JSON only")
    args = parser.parse_args()

    data = safe_whois_lookup(args.domain)
    ai_data = ai_analyze_whois(data)

    if args.json:
        print(json.dumps({"whois": data, "ai": ai_data}, indent=2))
    else:
        if data.get("error"):
            print(f"[ERROR] {data['error']}")
            return
        print(f"Domain: {data.get('domain')}")
        print(f"IP: {data.get('ip_address')}")
        print(f"Registrar: {data.get('registrar')}")
        print(f"Created: {data.get('creation_date')}")
        print(f"Expires: {data.get('expiration_date')}")
        print()
        print("AI Summary:")
        print(ai_data.get("summary"))
        print(f"Risk score: {ai_data.get('risk_score')}")
        if ai_data.get("flags"):
            print("Flags:")
            for f in ai_data["flags"]:
                print(f" - {f}")


if __name__ == "__main__":
    import os
    # If run as script: if PORT env set, run web; else act as CLI
    port = os.environ.get("PORT")
    if port:
        app.run(host="0.0.0.0", port=int(port), debug=False)
    else:
        cli()
