import os
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

def generate_executive_summary(signal_data: dict):
    """
    Hook to Anthropic for AI-driven executive reasoning.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key or api_key == "your-anthropic-key-here":
        return "Intelligence offline. Manual audit required."
        
    client = Anthropic(api_key=api_key)
    model = os.getenv("CLAUDE_MODEL", "claude-3-haiku-20240307")
    
    prompt = f"""
    You are an institutional trading analyst. 
    Analyze the following S3 Decision Engine signal and provide a 1-sentence executive reasoning.
    
    S3 Score: {signal_data['s3_score']}
    State: {signal_data['state']}
    Bias: {signal_data['bias']}
    Ticker: {signal_data['ticker']}
    Strike: {signal_data.get('strike', 'N/A')}
    Expiry: {signal_data.get('expiry', 'N/A')}
    
    Return ONLY the reasoning text. No intro, no fluff.
    """
    
    try:
        message = client.messages.create(
            model=model,
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}]
        )
        return message.content[0].text.strip()
    except Exception as e:
        print(f"Anthropic Hook Failed: {e}")
        return "AI reasoning unavailable due to connection error."
