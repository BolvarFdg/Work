import requests
import time
import re
from config import DETECTION_MODEL, LLM_TIMEOUT
from typing import Dict, Optional

_FENCE_HEAD_RE = re.compile(r"^\s*```[ \t]*[A-Za-z0-9_-]*[ \t]*\r?\n?")   # ```json / ``` python 等
_FENCE_TAIL_RE = re.compile(r"\r?\n?[ \t]*```\s*$")


def strip_code_fence(text: Optional[str]) -> Optional[str]:
    """去掉模型输出外层的 markdown 代码围栏（```json ... ```）。

    模型偶尔无视「禁止 Markdown」的指令把 JSON 包在代码块里返回，
    这里在源头剥离，保证所有下游拿到的都是裸 JSON 字符串。
    仅当输出以 ``` 开头时才处理，不影响正常输出。
    """
    if not isinstance(text, str):
        return text
    s = text.strip()
    if not s.startswith("```"):
        return text
    return _FENCE_TAIL_RE.sub("", _FENCE_HEAD_RE.sub("", s)).strip()


class LLMClient:

    def __init__(self, model_config: Dict[str, str]):
        self.name = model_config["name"]
        self.api_url = model_config["api_url"]
        self.api_key = model_config["api_key"]

    def chat(self,
             system_prompt,
             user_prompt,
             temperature: float = 0.7,
             max_retries: int = 3
        ) -> Optional[str]:
        for attempt in range(max_retries):
            try:
                headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
                payload = {
                    "model": self.name,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": temperature,
                    "seed": 42
                }

                response = requests.post(
                    self.api_url,
                    headers=headers,
                    json=payload,
                    timeout=LLM_TIMEOUT
                )

                if response.status_code == 200:
                    content = response.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                    return strip_code_fence(content)
                elif response.status_code in (429, 500, 502, 503, 504):
                    # 限流/服务器错误：可重试
                    print(f"API error {response.status_code} (attempt {attempt + 1}/{max_retries})")
                    time.sleep(2)
                    continue
                else:
                    print(f"API error: {response.status_code} - {response.text}")
                    return None

            except requests.exceptions.Timeout:
                print(f"Request timeout (attempt {attempt + 1}/{max_retries})")
                time.sleep(2)
            except requests.exceptions.RequestException as e:
                print(f"Request error: {e}")
                return None

        return None


def create_detection_client():
    return LLMClient(DETECTION_MODEL)
