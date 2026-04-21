import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()

def send_s3_alert(signal_data: dict):
    """
    Sends a formatted S3 alert to Discord.
    Follows the format specified in 03_DISCORD_JSON.md.
    """
    url = os.getenv("DISCORD_WEBHOOK_URL")
    if not url or url == "your-discord-webhook-here":
        print("Discord Webhook URL not configured. Skipping alert.")
        return
        
    payload = {
        "content": "S3 ALERT",
        "embeds": [
            {
                "title": f"S3 {signal_data['state']}",
                "description": f"**Ticker**: {signal_data['ticker']}\n**AI Reasoning**: {signal_data.get('reasoning', 'N/A')}",
                "color": 0x00ff00 if signal_data['bias'] == "LONG" else 0xff0000 if signal_data['bias'] == "SHORT" else 0x808080,
                "fields": [
                    {"name": "Score", "value": str(signal_data['s3_score']), "inline": True},
                    {"name": "Bias", "value": signal_data['bias'], "inline": True},
                    {"name": "Action", "value": signal_data['suggested_action'], "inline": True},
                    {"name": "Strike", "value": f"${signal_data.get('strike', 'N/A')}", "inline": True},
                    {"name": "Expiry", "value": signal_data.get('expiry', 'N/A'), "inline": True},
                    {"name": "R/R", "value": f"{signal_data.get('risk_reward', '3:1')}", "inline": True},
                    {"name": "Stop Loss", "value": f"${signal_data.get('stop_loss', 'N/A')}", "inline": True},
                    {"name": "Take Profit", "value": f"${signal_data.get('take_profit', 'N/A')}", "inline": True},
                    {"name": "Sizing", "value": f"{signal_data.get('position_size_pct', 0)}%", "inline": True}
                ]
            }
        ]
    }
    
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        print(f"Alert sent successfully for {signal_data['ticker']}")
    except Exception as e:
        print(f"Failed to send alert: {e}")
