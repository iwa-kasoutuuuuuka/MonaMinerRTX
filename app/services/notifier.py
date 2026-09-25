import json
import urllib.request
import threading
from typing import Optional, List, Dict, Any


class DiscordNotifier:
    """
    Asynchronous Discord Webhook notifier.
    No external dependencies required (uses standard urllib.request).
    """

    def __init__(self, webhook_url: str = ""):
        self.webhook_url = webhook_url.strip()
        self.enabled = bool(self.webhook_url)

    def set_webhook_url(self, url: str):
        self.webhook_url = url.strip()
        self.enabled = bool(self.webhook_url)

    def send_embed(
        self,
        title: str,
        description: str,
        color: int = 0x00FF88,  # Green default
        fields: Optional[List[Dict[str, Any]]] = None,
        footer: str = "MonaMinerRTX v2.0.0"
    ):
        if not self.enabled or not self.webhook_url:
            return

        payload = {
            "embeds": [
                {
                    "title": title,
                    "description": description,
                    "color": color,
                    "fields": fields or [],
                    "footer": {"text": footer}
                }
            ]
        }

        thread = threading.Thread(target=self._post_worker, args=(payload,), daemon=True)
        thread.start()

    def _post_worker(self, payload: dict):
        try:
            req = urllib.request.Request(
                self.webhook_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "MonaMinerRTX/2.0.0"
                }
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                pass
        except Exception as e:
            # Avoid crashing UI or spamming stdout
            pass
