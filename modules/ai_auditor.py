"""
Order Flow Radar™ — AI Auditor
ScriptMasterLabs™

Uses OpenAI gpt-4o-mini to audit high-score signals.
Final layer of defense against "fake outs" and institutional traps.
"""
import logging
import json
from typing import Dict, Any, Optional

import httpx
import config

logger = logging.getLogger("ai_auditor")

_OPENAI_URL = "https://api.openai.com/v1/chat/completions"

class AIAuditor:
    def __init__(self):
        self._key = config.OPENAI_API_KEY
        self._client = httpx.AsyncClient(timeout=10.0)

    async def audit_signal(self, signal_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send signal data to OpenAI for logical consistency auditing.
        Returns {approved: bool, reason: str, ai_score_adj: float}
        """
        if not self._key:
            return {"approved": True, "reason": "AI Auditor skipped (no key)", "ai_score_adj": 0.0}

        feed_tier = config.ALPACA_FEED.upper()
        feed_note = (
            f"The current feed is {feed_tier} (Standard), so reported volumes represent ~10-15% of total market activity. Adjust your scoring accordingly."
            if config.ALPACA_FEED == "iex"
            else f"The current feed is {feed_tier} (Full Tape). Volume data represents consolidated market activity."
        )

        prompt = f"""
        Audit this trading signal based on institutional order flow logic:
        Ticker: {signal_data['symbol']}
        Action: {signal_data['action']}
        Flow Score: {signal_data['score']}
        CVD Ratio: {signal_data['cvd_ratio']}
        Confluences: {", ".join(signal_data['confluences'])}
        Price: {signal_data['price']}
        
        Is this a high-probability institutional setup or a potential trap/noise?
        {feed_note}
        Consider if the CVD ratio aligns with the action.
        
        Return JSON ONLY:
        {{
            "approved": boolean,
            "reason": "short 1-sentence logic",
            "ai_score_adj": float (-10.0 to 10.0)
        }}
        """

        try:
            resp = await self._client.post(
                _OPENAI_URL,
                headers={
                    "Authorization": f"Bearer {self._key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_object"},
                    "temperature": 0.1
                }
            )
            
            if resp.status_code == 200:
                result = resp.json()
                content = json.loads(result["choices"][0]["message"]["content"])
                logger.info(f"AI Audit for {signal_data['symbol']}: {content['approved']} - {content['reason']}")
                return content
            else:
                logger.error(f"OpenAI Audit failed: {resp.status_code} - {resp.text}")
                return {"approved": True, "reason": "AI Auditor failed (API error)", "ai_score_adj": 0.0}
        except Exception as e:
            logger.error(f"AI Auditor error: {e}")
            return {"approved": True, "reason": "AI Auditor error", "ai_score_adj": 0.0}

    async def close(self):
        await self._client.aclose()
