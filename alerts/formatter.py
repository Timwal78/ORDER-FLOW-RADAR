"""
Discord embed formatter for Order Flow Radar trade cards.
Builds rich embeds for tiered Discord channels.
REAL DATA ONLY - never fabricate or guess values.
"""

import logging

logger = logging.getLogger(__name__)


def format_discord_embed(trade_card: dict) -> dict:
    """
    Build Discord embed dict from trade card.
    Color: green (0x00ff00) for LONG, red (0xff0000) for SHORT
    Returns None if trade_card is invalid.
    """
    try:
        direction = trade_card.get("direction", "unknown").upper()
        color = 0x00ff00 if direction == "LONG" else 0xff0000 if direction == "SHORT" else 0xffff00

        direction_emoji = "🔼" if direction == "LONG" else "🔽" if direction == "SHORT" else "⚪"

        symbol = trade_card.get("symbol", "UNKNOWN")
        entry = trade_card.get("entry", 0)
        stop_loss = trade_card.get("stop_loss", 0)
        tp1 = trade_card.get("tp1", 0)
        tp2 = trade_card.get("tp2", 0)
        score = trade_card.get("score", 0)
        max_score = trade_card.get("max_score", 20)
        rr1 = trade_card.get("risk_reward_1", 0)
        rr2 = trade_card.get("risk_reward_2", 0)
        bias = trade_card.get("bias", "neutral").upper()
        timeframe = trade_card.get("timeframe", "MULTI")
        valid_for = trade_card.get("valid_for_minutes", 60)
        alert_level = trade_card.get("alert_level", "WARNING").upper()
        confluences = trade_card.get("confluences", [])

        # Calculate stop loss %
        if direction == "LONG":
            sl_pct = ((entry - stop_loss) / entry) * 100 if entry > 0 else 0
            entry_str = f"${entry:.2f}"
            sl_str = f"${stop_loss:.2f} (-{sl_pct:.2f}%)"
            tp1_str = f"${tp1:.2f} (+{rr1:.1f}R)"
            tp2_str = f"${tp2:.2f} (+{rr2:.1f}R)"
        else:
            sl_pct = ((stop_loss - entry) / entry) * 100 if entry > 0 else 0
            entry_str = f"${entry:.2f}"
            sl_str = f"${stop_loss:.2f} (+{sl_pct:.2f}%)"
            tp1_str = f"${tp1:.2f} (-{rr1:.1f}R)"
            tp2_str = f"${tp2:.2f} (-{rr2:.1f}R)"

        # Build fields
        fields = [
            {"name": "Entry", "value": entry_str, "inline": True},
            {"name": "Stop Loss", "value": sl_str, "inline": True},
            {"name": "Target 1", "value": tp1_str, "inline": True},
            {"name": "Target 2", "value": tp2_str, "inline": True},
            {"name": "Score", "value": f"{score:.1f}/{max_score:.0f} ({alert_level})", "inline": True},
            {"name": "Bias", "value": bias, "inline": True},
            {"name": "Timeframe", "value": timeframe, "inline": True},
            {"name": "Valid For", "value": f"{valid_for} min", "inline": True},
        ]

        # Confluences section
        if confluences:
            confluence_text = ""
            for conf in confluences[:10]:
                factor = conf.get("factor", "Unknown")
                confluence_text += f"✓ {factor}\n"
            fields.append({
                "name": f"Confluences ({len(confluences)})",
                "value": confluence_text.strip() if confluence_text else "None",
                "inline": False
            })

        # Options recommendation section
        options_rec = trade_card.get("options_recommendation")
        if options_rec:
            try:
                primary = options_rec.get("primary_pick", {})
                if primary:
                    contract = primary.get("contract", "N/A")
                    strike = primary.get("strike", 0)
                    exp = primary.get("expiration", "N/A")
                    premium = primary.get("estimated_premium", 0)
                    opt_type = primary.get("type", "call").upper()
                    options_text = (
                        f"**{opt_type}** {contract}\n"
                        f"Strike: ${strike:.2f} | Exp: {exp}\n"
                        f"Est Premium: ${premium:.2f}"
                    )
                    fields.append({
                        "name": "Options Pick",
                        "value": options_text,
                        "inline": False
                    })

                # Flow context
                flow_context = options_rec.get("options_flow_context", {})
                if flow_context:
                    pcr = flow_context.get("put_call_ratio")
                    sentiment = flow_context.get("sentiment", "neutral")
                    unusual_count = flow_context.get("unusual_activity_count", 0)
                    flow_text = f"P/C Ratio: {pcr:.2f} | Sentiment: {sentiment}" if pcr else f"Sentiment: {sentiment}"
                    if unusual_count > 0:
                        flow_text += f"\nUnusual Activity: {unusual_count} contracts"
                    fields.append({
                        "name": "Options Flow",
                        "value": flow_text,
                        "inline": False
                    })
            except Exception as e:
                logger.warning(f"Error formatting options section: {e}")

        embed = {
            "title": f"{direction_emoji} {symbol} — {direction}",
            "description": f"**Alert Level: {alert_level}** | Score: {score:.1f}/{max_score:.0f}",
            "color": color,
            "fields": fields,
            "footer": {
                "text": f"Order Flow Radar | {trade_card.get('timestamp', '')}"
            }
        }

        return embed

    except Exception as e:
        logger.error(f"Error formatting Discord embed: {e}")
        return None


def format_free_tier_embed(trade_card: dict) -> dict:
    """
    Build a simplified embed for the free tier.
    Shows direction, symbol, and score but NOT exact entry/SL/TP.
    """
    try:
        direction = trade_card.get("direction", "unknown").upper()
        color = 0x00ff00 if direction == "LONG" else 0xff0000 if direction == "SHORT" else 0xffff00
        direction_emoji = "🔼" if direction == "LONG" else "🔽"
        symbol = trade_card.get("symbol", "UNKNOWN")
        score = trade_card.get("score", 0)
        max_score = trade_card.get("max_score", 20)
        alert_level = trade_card.get("alert_level", "WARNING").upper()
        confluences = trade_card.get("confluences", [])

        fields = [
            {"name": "Direction", "value": direction, "inline": True},
            {"name": "Score", "value": f"{score:.1f}/{max_score:.0f}", "inline": True},
            {"name": "Alert Level", "value": alert_level, "inline": True},
        ]

        if confluences:
            conf_count = len(confluences)
            fields.append({
                "name": "Confluences",
                "value": f"{conf_count} factors aligned",
                "inline": True
            })

        fields.append({
            "name": "Upgrade",
            "value": "Get exact entries, stops & targets with Pro",
            "inline": False
        })

        embed = {
            "title": f"{direction_emoji} {symbol} Signal Detected",
            "description": f"A {alert_level} signal has been detected",
            "color": color,
            "fields": fields,
            "footer": {"text": "Order Flow Radar — Free Tier | Upgrade for full trade cards"}
        }

        return embed

    except Exception as e:
        logger.error(f"Error formatting free tier embed: {e}")
        return None
