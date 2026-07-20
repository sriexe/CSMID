"""
proxy_manager.py
CSMID — Proxy Pool Manager

Manages a local pool of HTTP/HTTPS proxies. Provides clean rotation, 
health verification, and block/cool-down tracking for rate-limited IPs.
"""

from __future__ import annotations

import logging
import os
import random
import subprocess
import time
from typing import List, Optional

logger = logging.getLogger("csmid.proxy_manager")

class ProxyManager:
    """
    A self-healing proxy pool manager.
    Reads proxy configurations, tracks working vs. blocked proxies, 
    and handles round-robin or randomized selection.
    """

    def __init__(
        self, 
        proxy_file: str = "proxies.txt", 
        cool_down_period: float = 1800.0,  # 30 mins cool-down on 429
        test_timeout: float = 5.0
    ):
        """
        Args:
            proxy_file: Path to a line-separated text file of proxies.
                        Format: http://user:pass@ip:port or http://ip:port
            cool_down_period: Seconds to ignore a proxy after a 429 rate limit.
            test_timeout: Max time in seconds to test-ping a proxy.
        """
        self.proxy_file = proxy_file
        self.cool_down_period = cool_down_period
        self.test_timeout = test_timeout
        
        # Internal state
        self.raw_proxies: List[str] = []
        self.blocked_proxies: dict[str, float] = {}  # proxy_string -> epoch_time_unblocked
        self._index = 0

        self.load_proxies()

    def load_proxies(self) -> None:
        """Loads proxies from environment or a text file."""
        # Method A: Load from environment variable (useful for Docker/CI)
        env_proxies = os.getenv("CSMID_PROXIES")
        if env_proxies:
            self.raw_proxies = [p.strip() for p in env_proxies.split(",") if p.strip()]
            logger.info("Loaded %d proxies from CSMID_PROXIES env var.", len(self.raw_proxies))
            return

        # Method B: Load from text file
        if os.path.exists(self.proxy_file):
            try:
                with open(self.proxy_file, "r", encoding="utf-8") as f:
                    self.raw_proxies = [
                        line.strip() 
                        for line in f 
                        if line.strip() and not line.strip().startswith("#")
                    ]
                logger.info("Loaded %d proxies from '%s'.", len(self.raw_proxies), self.proxy_file)
            except Exception as e:
                logger.error("Failed to read proxy file '%s': %s", self.proxy_file, e)
        else:
            # Create an empty template file to guide the user
            try:
                with open(self.proxy_file, "w", encoding="utf-8") as f:
                    f.write("# Enter your proxies here, one per line.\n")
                    f.write("# Format: http://username:password@ip:port\n")
                    f.write("# Example: http://192.168.1.50:8080\n")
                logger.info("Created empty proxy template file: %s", self.proxy_file)
            except Exception as e:
                logger.warning("Could not create empty template file: %s", e)

    def get_proxy(self) -> Optional[str]:
        """
        Returns a healthy, active proxy from the pool. 
        Returns None if the pool is empty or if all proxies are currently cooled down.
        """
        if not self.raw_proxies:
            return None

        now = time.time()
        
        # Clean up expired blocks
        self.blocked_proxies = {
            p: unblock_time 
            for p, unblock_time in self.blocked_proxies.items() 
            if unblock_time > now
        }

        # Filter out blocked proxies
        available = [p for p in self.raw_proxies if p not in self.blocked_proxies]

        if not available:
            logger.error("❌ All proxies in pool are currently rate-limited/cooling down!")
            return None

        # Fetch using round-robin rotation over available subset
        self._index = (self._index + 1) % len(available)
        return available[self._index]

    def get_next_proxy(self) -> Optional[str]:
        """Alias wrapper used by the scraper to explicitly skip to the next node."""
        return self.get_proxy()

    def mark_blocked(self, proxy: str) -> None:
        """Flags a proxy as rate-limited, cooling it down for `cool_down_period`."""
        if not proxy:
            return
        unblock_at = time.time() + self.cool_down_period
        self.blocked_proxies[proxy] = unblock_at
        logger.warning(
            "🛑 Proxy marked as BLOCKED. Cooled down for %d seconds: %s", 
            int(self.cool_down_period), proxy
        )

    def test_proxy(self, proxy: str) -> bool:
        """
        Quick health check for a proxy using the system's curl.
        Tries to reach a neutral, high-uptime server (e.g., cloudflare).
        """
        cmd = [
            "curl", "-s", "-o", "/dev/null", 
            "-w", "%{http_code}", 
            "--max-time", str(self.test_timeout), 
            "-x", proxy,
            "https://1.1.1.1"
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=self.test_timeout + 2)
            if result.returncode == 0 and result.stdout.strip() == "200":
                return True
        except Exception:
            pass
        return False


if __name__ == "__main__":
    # Quick manual diagnostics: python src/proxy_manager.py
    logging.basicConfig(level=logging.INFO)
    pm = ProxyManager()
    print(f"Raw pool size: {len(pm.raw_proxies)}")
    active = pm.get_proxy()
    print(f"Active selected: {active}")