#!/usr/bin/env python3
"""
AI LLM Proxy Tunnel Application for Linux Mint
Secure HTTP/HTTPS tunneling with AI-powered configuration
"""

import subprocess
import json
import sys
import os
from typing import Optional, Dict, Any
from dataclasses import dataclass
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class TunnelConfig:
    """Tunnel configuration parameters"""
    local_port: int
    remote_host: str
    remote_port: int
    protocol: str = "http"
    auth_token: Optional[str] = None
    ai_model: str = "gpt-3.5-turbo"

class LLMTunnelManager:
    def __init__(self, config: TunnelConfig):
        self.config = config
        self.tunnel_process = None
        
    def validate_config(self) -> bool:
        """Validate tunnel configuration"""
        if not 1 <= self.config.local_port <= 65535:
            logger.error("Invalid local port")
            return False
        if not 1 <= self.config.remote_port <= 65535:
            logger.error("Invalid remote port")
            return False
        return True
    
    def test_connectivity(self) -> bool:
        """Test basic connectivity before establishing tunnel"""
        try:
            result = subprocess.run(
                ['ping', '-c', '1', self.config.remote_host],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except Exception as e:
            logger.error(f"Connectivity test failed: {e}")
            return False
    
    def establish_tunnel(self) -> bool:
        """Establish SSH/local tunnel"""
        cmd = [
            'ssh', '-N', '-L',
            f"{self.config.local_port}:{self.config.remote_host}:{self.config.remote_port}",
            f"{self.config.remote_host}"
        ]
        
        try:
            self.tunnel_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            logger.info(f"Tunnel established on port {self.config.local_port}")
            return True
        except Exception as e:
            logger.error(f"Failed to establish tunnel: {e}")
            return False
    
    def close_tunnel(self):
        """Close active tunnel"""
        if self.tunnel_process:
            self.tunnel_process.terminate()
            self.tunnel_process.wait()
            logger.info("Tunnel closed")

def call_ai_llm(prompt: str, api_key: str, model: str = "gpt-3.5-turbo") -> str:
    """Call external LLM API for intelligent configuration advice"""
    import requests
    
    url = "https://api.openai.com/v1/chat/completions"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()
        return result["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"LLM API call failed: {e}")
        return ""

def get_ai_recommendations(current_config: Dict[str, Any], api_key: str) -> str:
    """Get AI-powered recommendations for tunnel optimization"""
    prompt = f"""
    Analyze this network tunnel configuration and provide security and performance recommendations:
    
    Current Config: {json.dumps(current_config, indent=2)}
    
    Consider:
    1. Port selection security
    2. Encryption strength
    3. Authentication requirements
    4. Potential vulnerabilities
    5. Performance optimizations
    
    Provide concise, actionable advice for Linux Mint environment.
    """
    
    return call_ai_llm(prompt, api_key)

# CLI Interface
if __name__ == "__main__":
    print("=== AI LLM Proxy Tunnel Manager ===")
    
    # Configuration
    local_port = int(input("Local port (e.g., 8080): ") or "8080")
    remote_host = input("Remote host (e.g., remote.server.com): ")
    remote_port = int(input("Remote port (e.g., 443): ") or "443")
    
    config = TunnelConfig(
        local_port=local_port,
        remote_host=remote_host,
        remote_port=remote_port
    )
    
    if not config.validate_config():
        sys.exit(1)
    
    # AI-powered recommendations
    llm_api_key = os.getenv("OPENAI_API_KEY", "")
    if llm_api_key:
        print("\nFetching AI recommendations...")
        recommendations = get_ai_recommendations(config.__dict__, llm_api_key)
        if recommendations:
            print(recommendations)
    
    # Establish tunnel
    manager = LLMTunnelManager(config)
    
    if manager.test_connectivity():
        if manager.establish_tunnel():
            print(f"\n✓ Tunnel active at localhost:{local_port}")
            print("Press Ctrl+C to stop")
            
            try:
                # Keep process running
                manager.tunnel_process.wait()
            except KeyboardInterrupt:
                manager.close_tunnel()
    else:
        print("✗ Connectivity test failed")
        sys.exit(1)
