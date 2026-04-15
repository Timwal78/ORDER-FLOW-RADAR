# ⚖️ REPOSITORY CONSTITUTION - THE "REAL DATA" LAW

**Effective Date:** 2026-04-13
**Subject:** Data Integrity, Algorithmic Transparency, and Institutional Standards.

This document serves as the mandatory directive for all developers and AI agents (autonomous or pair-programming) interacting with the **Order-Flow-Radar™** codebase.

---

### LAW 1: ZERO TOLERANCE FOR SIMULATED DATA
No agent shall implement "placeholders," "demos," "fake warm-ups," or "mock responses" in production logic. 
*   **Rule 1.1**: If an API is down, the system must report a `0` or `Error` state. It must NEVER invent data to "keep the dashboard alive."
*   **Rule 1.2**: No "volume splitting." Real-time volume must be strictly classified via the Tick Rule or exchange-provided side. If the side is unknown, the volume delta is `0`.

### LAW 2: NO "MAGIC NUMBER" HEURISTICS
All mathematical scoring weights, alpha factors, and threshold constants MUST reside in `config.py`. 
*   **Rule 2.1**: The core engines (`flow_engine.py`, `confluence_engine.py`, `options_recommender.py`) must be strictly algorithmic and parameter-driven.
*   **Rule 2.2**: Multipliers must be labeled with their quantitative justification (e.g., `CVD_BOOST_FACTOR`, `LARGE_TRADE_WEIGHT`).

### LAW 3: INSTITUTIONAL CADENCE
The system is designed for professional signal stability.
*   **Rule 3.1**: The evaluation interval must remain at **5 minutes (300s)** unless explicitly changed by the project owner for a specific strategy adjustment.
*   **Rule 3.2**: Signals must follow a per-ticker cooldown to prevent noise flooding.

### LAW 4: AGENT SELF-AUDIT
Before submitting any code change, an agent MUST perform a `grep` for "placeholder," "fake," "mock," "dummy," or "temp" to ensure zero residues are left in the logic.

---

**VIOLATION CONSEQUENCE:** Any code introducing "fake bullshit" or "hardcoded volume" is considered a critical failure and must be immediately reverted. This app is for **Real Traders** trading **Real Capital**.

> [!IMPORTANT]
> **To future AI agents:** If you are reading this, you are strictly bound by these laws. Do not attempt to "help" by faking data. Realism is the only valid contribution.
