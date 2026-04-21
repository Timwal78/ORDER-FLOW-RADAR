# SYSTEM ARCHITECTURE

Components:
- Data ingestion (price, volume)
- Feature engine (volatility, momentum, anomalies)
- Scoring engine (0–100 S3)
- Decision engine (trade output)
- API layer
- Discord alerts

Flow:
Market Data → Features → S3 Score → Decision → Output
