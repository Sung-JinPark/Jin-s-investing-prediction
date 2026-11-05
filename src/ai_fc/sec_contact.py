"""The contact SEC EDGAR requires in a declared User-Agent, in one place.

SEC answers 403 to the GitHub noreply address (measured 2026-11-05), which silently froze the
monthly capital-cycle and registered-debt steps behind continue-on-error. The address below is the
one the repository owner designated for SEC requests. ``AI_FC_SEC_USER_AGENT`` still overrides it.
"""

from __future__ import annotations

import os

SEC_CONTACT = "91ssjj@gmail.com"


def sec_user_agent(client: str = "JinsInvestingResearch/1.0") -> str:
    return os.getenv("AI_FC_SEC_USER_AGENT") or f"{client} ({SEC_CONTACT})"
