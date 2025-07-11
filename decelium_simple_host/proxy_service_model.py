from lmstudio import BaseModel
import requests
from typing import List, Dict, Any

class ProxyServiceModel(BaseModel):
    endpoint: str    # e.g. "http://localhost:8003"
    api_key: str
    model_id: str

    def generate(self,
                 messages: List[Dict[str, str]],
                 **kwargs: Any) -> str:
        url = f"{self.endpoint}/v1/chat/completions"
        assert self.endpoint != None
        assert self.model_id != None
        assert messages != None

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type":  "application/json",
        }
        payload = {"model": self.model_id, "messages": messages, **kwargs}
        print(f"URL OUT : {type(url)}----{url}")
        r = requests.post(url, json=payload, headers=headers, timeout=60)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    def stream(self,
               messages: List[Dict[str, str]],
               **kwargs: Any):
        url = f"{self.endpoint}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type":  "application/json",
        }
        payload = {"model": self.model_id,
                   "messages": messages,
                   "stream": True,
                   **kwargs}
        r = requests.post(url, json=payload,
                          headers=headers,
                          stream=True,
                          timeout=None)
        r.raise_for_status()
        for line in r.iter_lines():
            if line.startswith(b"data:"):
                data = line.removeprefix(b"data:").strip()
                if data == b"[DONE]":
                    break
                yield data.decode()
