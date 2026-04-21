from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
from engine.decision import evaluate_signal
from notifier import send_s3_alert
import uvicorn
import os

app = FastAPI(title="S3 Decision Engine")

class SignalRequest(BaseModel):
    ticker: str
    prices: List[float]
    volumes: List[float]

@app.get("/health")
async def health():
    return {"status": "operational", "engine": "S3"}

@app.post("/signal")
async def get_signal(request: SignalRequest):
    if len(request.prices) < 2:
        raise HTTPException(status_code=400, detail="Insufficient data points")
        
    signal = evaluate_signal(request.ticker, request.prices, request.volumes)
    
    # Auto-alert on high confidence signals
    if signal["state"] != "NEUTRAL" and signal["confidence"] > 70:
        send_s3_alert(signal)
        
    return signal

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("HOST", "0.0.0.0")
    uvicorn.run(app, host=host, port=port)
