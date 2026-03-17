#!/usr/bin/env python3
"""
AI-ready PDF Metadata Editor (single file, local-only core)

- Pure local metadata read/write using pypdf
- No telemetry, no network calls by default
- Clear LLM hook: plug in your own backend in `ai_suggest_metadata()`

Requirements:
    pip install pypdf requests  # requests only if you wire an HTTP LLM backend
"""

import argparse
import json
import os
from typing import Dict, Any, Optional

from pypdf import PdfReader, PdfWriter


# ---------------------------
# Core PDF metadata utilities
# ---------------------------

def load_metadata(pdf_path: str) -> Dict[str, Any]:
    reader = PdfReader(pdf_path)
    info = reader.metadata or {}
    # Normalize keys to simple strings (strip leading '/')
    meta = {}
    for k, v in info.items():
        key = str(k)
        if key.startswith("/"):
            key = key[1:]
        meta[key] = str(v) if v is not None else ""
    return meta


def save_metadata(pdf_path: str, output_path: str, new_metadata: Dict[str, Any]) -> None:
    reader = PdfReader(pdf_path)
    writer = PdfWriter()

    for page in reader.pages:
        writer.add_page(page)

    # pypdf expects keys with leading '/'
    pdf_meta = {}
    for k, v in new_metadata.items():
        if not k.startswith("/"):
            key = "/" + k
        else:
            key = k
        pdf_meta[key] = v

    writer.add_metadata(pdf_meta)

    with open(output_path, "wb") as f:
        writer.write(f)


def print_metadata(meta: Dict[str, Any]) -> None:
    if not meta:
        print("No metadata found.")
        return
    print("Current metadata:")
    for k, v in meta.items():
        print(f"  {k}: {v}")


# ---------------------------
# AI / LLM hook (extensible)
# ---------------------------

def ai_suggest_metadata(
    metadata: Dict[str, Any],
    pdf_path: str,
    llm_endpoint: Optional[str] = None,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Hook for AI/LLM-based metadata suggestions.

    This is intentionally a stub. You can:
      - Call a local LLM server
      - Call a remote HTTP endpoint
      - Use any Python LLM client

    Contract:
      Input:
        - metadata: current metadata dict
        - pdf_path: path to the PDF (you may choose to read text, etc.)
      Output:
        - dict of updated/augmented metadata (merged by caller)

    For now, we just echo back the original metadata.
    """
    # Example skeleton for HTTP-based LLM (commented out):
    #
    # import requests
    # if not llm_endpoint:
    #     return metadata
    # payload = {
    #     "metadata": metadata,
    #     "pdf_path": os.path.basename(pdf_path),
    #     "instruction": "Suggest improved, clean, human-readable PDF metadata fields."
    # }
    # headers = {}
    # if api_key:
    #     headers["Authorization"] = f"Bearer {api_key}"
    # resp = requests.post(llm_endpoint, json=payload, headers=headers, timeout=60)
    # resp.raise_for_status()
    # suggestions = resp.json().get("metadata", {})
    # merged = dict(metadata)
    # merged.update(suggestions)
    # return merged

    # Local no-op default:
    return metadata


# ---------------------------
# CLI interaction
# ---------------------------

def interactive_edit(meta: Dict[str, Any]) -> Dict[str, Any]:
    """
    Simple interactive editor in the terminal.
    - Shows current metadata
    - Lets you add/update/remove keys
    """
    print_metadata(meta)
    print("\nInteractive edit mode.")
    print("Commands:")
    print("  set <key> <value>   - set or update a field")
    print("  del <key>           - delete a field")
    print("  show                - show current working metadata")
    print("  done                - finish editing\n")

    working = dict(meta)

    while True:
        try:
            line = input("meta> ").strip()
        except EOFError:
            break

        if not line:
            continue

        parts = line.split(" ", 2)
        cmd = parts[0].lower()

        if cmd == "done":
            break
        elif cmd == "show":
            print_metadata(working)
        elif cmd == "set" and len(parts) == 3:
            key, value = parts[1], parts[2]
            working[key] = value
            print(f"Set {key} = {value}")
        elif cmd == "del" and len(parts) >= 2:
            key = parts[1]
            if key in working:
                del working[key]
                print(f"Deleted {key}")
            else:
                print(f"{key} not found.")
        else:
            print("Unknown command or wrong syntax.")

    return working


def parse_kv_overrides(kv_list: Optional[list[str]]) -> Dict[str, str]:
    """
    Parse key=value pairs from CLI into a dict.
    """
    result: Dict[str, str] = {}
    if not kv_list:
        return result
    for item in kv_list:
        if "=" not in item:
            continue
        k, v = item.split("=", 1)
        result[k.strip()] = v.strip()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Local PDF metadata editor with AI/LLM hook."
    )
    parser.add_argument("pdf", help="Input PDF file")
    parser.add_argument(
        "-o", "--output",
        help="Output PDF file (default: <input>_meta.pdf)",
        default=None,
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Show metadata and exit",
    )
    parser.add_argument(
        "--set",
        metavar="KEY=VALUE",
        nargs="*",
        help="Set metadata fields non-interactively (can be repeated)",
    )
    parser.add_argument(
        "--json",
        metavar="JSON_FILE",
        help="Load metadata overrides from JSON file (merged on top of existing)",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Interactive terminal editor for metadata",
    )
    parser.add_argument(
        "--use-ai",
        action="store_true",
        help="Pass metadata through AI/LLM suggestion hook before saving",
    )
    parser.add_argument(
        "--llm-endpoint",
        help="LLM endpoint URL (if you wire HTTP backend in ai_suggest_metadata)",
        default=None,
    )
    parser.add_argument(
        "--llm-api-key",
        help="LLM API key (optional, passed to ai_suggest_metadata)",
        default=None,
    )

    args = parser.parse_args()

    pdf_path = args.pdf
    if not os.path.isfile(pdf_path):
        raise SystemExit(f"File not found: {pdf_path}")

    output_path = args.output or os.path.splitext(pdf_path)[0] + "_meta.pdf"

    metadata = load_metadata(pdf_path)

    if args.show and not (args.set or args.json or args.interactive or args.use_ai):
        print_metadata(metadata)
        return

    # Apply CLI key=value overrides
    overrides = parse_kv_overrides(args.set)
    if overrides:
        metadata.update(overrides)

    # Apply JSON overrides
    if args.json:
        with open(args.json, "r", encoding="utf-8") as f:
            json_overrides = json.load(f)
        if not isinstance(json_overrides, dict):
            raise SystemExit("JSON overrides must be an object/dict.")
        for k, v in json_overrides.items():
            metadata[str(k)] = str(v)

    # Interactive edit if requested
    if args.interactive:
        metadata = interactive_edit(metadata)

    # AI/LLM suggestion pass
    if args.use_ai:
        metadata = ai_suggest_metadata(
            metadata=metadata,
            pdf_path=pdf_path,
            llm_endpoint=args.llm_endpoint,
            api_key=args.llm_api_key,
        )

    # If nothing changed and user only wanted show
    if args.show and not (args.set or args.json or args.interactive or args.use_ai):
        print_metadata(metadata)
        return

    # Save updated metadata
    save_metadata(pdf_path, output_path, metadata)
    print(f"Written updated PDF with metadata to: {output_path}")


if __name__ == "__main__":
    main()
