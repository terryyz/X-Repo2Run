# Copyright (2025) Bytedance Ltd. and/or its affiliates 

# Licensed under the Apache License, Version 2.0 (the "License"); 
# you may not use this file except in compliance with the License. 
# You may obtain a copy of the License at 

#     https://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software 
# distributed under the License is distributed on an "AS IS" BASIS, 
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. 
# See the License for the specific language governing permissions and 
# limitations under the License. 


import requests
import time
import json
from typing import Dict, List, Any, Tuple, Optional

# Claude API endpoint and access key
CLAUDE_API_URL = "https://gpt-i18n.byteintl.net/gpt/openapi/online/v2/crawl"
CLAUDE_API_KEY = "54nhP5uBXv7iWgHJ4bWMD90Nwkn09BXN"

def get_llm_response(model: str, messages: List[Dict[str, str]], temperature: float = 0.0, n: int = 1, max_tokens: int = 4000) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """
    Send a request to the Claude API and get the response.
    
    Args:
        model: The Claude model to use (e.g., "gcp-claude37-sonnet")
        messages: List of message dictionaries with 'role' and 'content'
        temperature: Controls randomness (0.0 to 1.0)
        n: Number of completions to generate (only 1 supported currently)
        max_tokens: Maximum number of tokens to generate
        
    Returns:
        Tuple of (response_content, usage_info)
    """
    max_retry = 5
    count = 0
    
    headers = {
        'Content-Type': 'application/json',
        'X-TT-LOGID': 'claude-api-request'
    }
    
    # Set thinking budget tokens to be less than max_tokens
    thinking_budget = min(2000, max_tokens - 1000)
    
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
        "thinking": {
            "type": "enabled",
            "budget_tokens": thinking_budget
        },
        "stream": False
    }
    
    # Add temperature if not default
    if temperature != 0.0:
        payload["temperature"] = temperature
    
    url = f"{CLAUDE_API_URL}?ak={CLAUDE_API_KEY}"
    
    while count < max_retry:
        try:
            response = requests.post(url, headers=headers, data=json.dumps(payload))
            response.raise_for_status()  # Raise exception for HTTP errors
            
            response_data = response.json()
            
            # Check if there's an error in the response
            if "error" in response_data:
                error_msg = response_data["error"].get("message", "Unknown error")
                error_code = response_data["error"].get("code", "Unknown code")
                print(f"API Error: {error_code} - {error_msg}")
                count += 1
                time.sleep(3)
                continue
                
            # Extract content from the response
            if "choices" in response_data and len(response_data["choices"]) > 0:
                content = response_data["choices"][0].get("message", {}).get("content")
                usage = response_data.get("usage", {})
                return content, usage
            else:
                print(f"Unexpected response format: {response_data}")
                
        except Exception as e:
            print(f"Error: {e}")
            count += 1
            time.sleep(3)
    
    return None, None

if __name__ == "__main__":
    messages = [
        {"role": "user", "content": "Hello, how are you?"}
    ]
    response, usage = get_llm_response("gcp-claude37-sonnet", messages)
    print(response)
    print(usage)