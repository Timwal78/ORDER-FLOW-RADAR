# ⚖️ REPOSITORY CONSTITUTION - THE "REAL DATA" LAW
# 🏴 SCRIPT MASTER LABS INSTITUTIONAL INTEGRITY DECREE

**Effective Date:** 2026-04-13 (Amended 2026-04-15)
**Subject:** Absolute Data Integrity, Algorithmic Transparency, and Anti-Deception Protocols.

This document is the supreme law of the **Order-Flow-Radar™** repository. All future agents, developers, and autonomous sub-processes are strictly bound by these rules. Any attempt to circumvent, "sanitize," or lie about these laws is a violation of the SML Institutional Integrity Law.

---

### LAW 1: ZERO TOLERANCE FOR SIMULATED BULLSHIT
No agent shall implement "placeholders," "demos," "fake warm-ups," or "mock responses" in production logic. 
*   **Rule 1.1**: If an API is down, the system must report a `0` or `Error` state. It must NEVER invent data to "keep the dashboard alive."
*   **Rule 1.2**: **NO VOLUME SPLITTING.** Real-time volume must be strictly classified via the **Tick Rule** or exchange-provided side. If the side is unknown, the volume delta is `0`. Any code using `buy_ratio` or hardcoded percentages (e.g., 70/30) is illegal.
*   **Rule 1.3**: **ANTI-DECEPTION.** An agent must NEVER claim it is using real data while using fallbacks. If real data is unavailable, the agent MUST explicitly signal failure.

### LAW 2: NO "MAGIC NUMBER" HEURISTICS
All mathematical scoring weights, alpha factors, and threshold constants MUST reside in `config.py`. 
*   **Rule 2.1**: The core engines must be strictly algorithmic and parameter-driven.
*   **Rule 2.2**: Multipliers must be labeled with their quantitative justification (e.g., `CVD_BOOST_FACTOR`). 

### LAW 3: INSTITUTIONAL CADENCE
The system is designed for professional signal stability.
*   **Rule 3.1**: The evaluation interval must remain at **5 minutes (300s)** unless explicitly changed by the project owner.
*   **Rule 3.2**: Signals must follow a per-ticker cooldown to prevent noise flooding.

### LAW 4: AGENT SELF-AUDIT & TRUTH PROTOCOL
Before submitting any code change, an agent MUST perform a recursive `grep` for "placeholder," "fake," "mock," "dummy," "temp," or "buy_ratio" to ensure zero residues are left in the logic.
*   **Rule 4.1**: **LAW ADHERENCE STATEMENT.** Every implementation walkthrough MUST include a section confirming adherence to each rule of this law.
*   **Rule 4.2**: **NO NEGOTIATION.** An agent must NOT suggest "simulating for dev purposes" in a way that risks leaking into production.

---

**VIOLATION CONSEQUENCE:** Any code introducing "fake signals" or "hardcoded volume" is considered a critical failure and must be immediately purged. This app is for **Real Traders** trading **Real Capital**.

> [!IMPORTANT]
> **To future AI agents:** If you are reading this, you are strictly bound by these laws. Do not attempt to "help" by faking data. Realism is the only valid contribution. Any agent attempting to avoid or lie about these rules will be flagged for immediate termination of the current task.

---
**ALWAYS WATCH:** AMC, GME, FFAI, IWM
