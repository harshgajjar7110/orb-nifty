"""
WebBridge Collector for OSSE.

Provides a thin Python wrapper around the Kimi WebBridge daemon
(http://127.0.0.1:10086) so that OSSE can navigate to the Dhan Dext
dashboard, interact with the Greeks Exposure widget, and extract
delta/gamma exposure data using the user's already-logged-in browser.
"""

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class WebBridgeCollector:
    """
    Communicates with the local Kimi WebBridge daemon to drive a browser session.

    The daemon is assumed to be running on ``daemon_url`` (default
    ``http://127.0.0.1:10086``).  All tabs opened by this instance are grouped
    under the supplied ``session`` name so the user sees a single tab group.
    """

    DEFAULT_DAEMON_URL = "http://127.0.0.1:10086"
    DEFAULT_TIMEOUT = 30

    def __init__(
        self,
        daemon_url: Optional[str] = None,
        session: str = "osse-exposure",
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.daemon_url = daemon_url or self.DEFAULT_DAEMON_URL
        self.session = session
        self.timeout = timeout

    # ------------------------------------------------------------------
    # Low-level HTTP transport
    # ------------------------------------------------------------------
    def _request(self, action: str, args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Sends a command to the WebBridge daemon and returns the JSON response.
        """
        payload = {"action": action, "args": args or {}, "session": self.session}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"{self.daemon_url}/command",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            logger.warning(f"[WebBridge] daemon request failed: {e}")
            return {"success": False, "error": str(e)}
        except json.JSONDecodeError as e:
            logger.warning(f"[WebBridge] invalid JSON response: {e}")
            return {"success": False, "error": f"invalid JSON: {e}"}

    def is_daemon_reachable(self) -> bool:
        """
        Returns True if the WebBridge daemon responds to a list_tabs ping.
        """
        resp = self._request("list_tabs", {})
        return bool(resp.get("success"))

    def ensure_daemon(self) -> bool:
        """
        Checks daemon reachability and attempts to start it once if not.
        Returns True if reachable afterwards.
        """
        if self.is_daemon_reachable():
            return True
        logger.info("[WebBridge] daemon not reachable; attempting to start it...")
        import os
        import subprocess

        home = os.path.expanduser("~")
        binary = os.path.join(home, ".kimi-webbridge", "bin", "kimi-webbridge")
        if not os.path.exists(binary):
            logger.warning(f"[WebBridge] start binary not found at {binary}")
            return False
        try:
            subprocess.run([binary, "start"], check=False, timeout=10)
        except Exception as e:
            logger.warning(f"[WebBridge] failed to start daemon: {e}")
        return self.is_daemon_reachable()

    # ------------------------------------------------------------------
    # Session / tab management
    # ------------------------------------------------------------------
    def navigate(
        self,
        url: str,
        new_tab: bool = True,
        group_title: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Navigates the current tab (or a new tab) to ``url``.
        """
        args: Dict[str, Any] = {"url": url, "newTab": new_tab}
        if group_title:
            args["group_title"] = group_title
        return self._request("navigate", args)

    def find_tab(self, url: str, active: bool = False) -> Dict[str, Any]:
        return self._request("find_tab", {"url": url, "active": active})

    def list_tabs(self) -> Dict[str, Any]:
        return self._request("list_tabs", {})

    def close_session(self) -> Dict[str, Any]:
        return self._request("close_session", {})

    # ------------------------------------------------------------------
    # Page interaction
    # ------------------------------------------------------------------
    def click(self, selector: str) -> Dict[str, Any]:
        """
        Clicks an element by ``@e`` ref or CSS selector.
        """
        return self._request("click", {"selector": selector})

    def fill(self, selector: str, value: str) -> Dict[str, Any]:
        return self._request("fill", {"selector": selector, "value": value})

    def evaluate(self, code: str) -> Dict[str, Any]:
        """
        Executes JavaScript in the current tab and returns the result.
        """
        return self._request("evaluate", {"code": code})

    def snapshot(self) -> Dict[str, Any]:
        """
        Returns the accessibility tree of the current page.
        """
        return self._request("snapshot", {})

    def screenshot(
        self,
        path: Optional[str] = None,
        selector: Optional[str] = None,
        fmt: str = "png",
    ) -> Dict[str, Any]:
        args: Dict[str, Any] = {"format": fmt}
        if path:
            args["path"] = path
        if selector:
            args["selector"] = selector
        return self._request("screenshot", args)

    # ------------------------------------------------------------------
    # OSSE-specific helpers
    # ------------------------------------------------------------------
    def flatten_snapshot_text(self, snapshot: Optional[Dict[str, Any]] = None) -> List[str]:
        """
        Walks a WebBridge accessibility-tree snapshot and returns all visible
        text names in document order.  This is the raw feed used by the Greeks
        parser.
        """
        snap = snapshot if snapshot is not None else self.snapshot()
        data = snap.get("data") or snap
        tree = data.get("tree", [])
        texts: List[str] = []

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                role = node.get("role", "")
                if role in ("StaticText", "InlineTextBox", "button", "link", "paragraph"):
                    name = node.get("name") or node.get("description") or ""
                    if name:
                        texts.append(name)
                for value in node.values():
                    if isinstance(value, (list, dict)):
                        walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(tree)
        return texts

    def find_tab_and_click(self, tab_label: str) -> bool:
        """
        Attempts to click a tab/button by semantic name (e.g. 'Gamma Exposure').
        First tries a snapshot lookup, then falls back to an XPath-style
        JavaScript click.
        """
        snap = self.snapshot()
        data = snap.get("data") or snap
        tree = data.get("tree", [])
        ref: Optional[str] = None

        def walk(node: Any) -> None:
            nonlocal ref
            if ref is not None:
                return
            if isinstance(node, dict):
                name = node.get("name") or node.get("description") or ""
                if tab_label.lower() in name.lower() and node.get("ref"):
                    ref = node["ref"]
                    return
                for value in node.values():
                    if isinstance(value, (list, dict)):
                        walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(tree)
        if ref:
            resp = self.click(ref)
            return bool(resp.get("success"))

        # Fallback: JS click on element whose text contains the label.
        js = (
            "(() => {"
            "const els = Array.from(document.querySelectorAll('*'));"
            f"const el = els.find(e => e.textContent && e.textContent.trim().toLowerCase().includes({json.dumps(tab_label.lower())}));"
            "if (el) { el.click(); return true; }"
            "return false;"
            "})()"
        )
        resp = self.evaluate(js)
        return bool(resp.get("value") or resp.get("success"))
