# Binance Futures USDC Auto-Trader GUI

A Python Tkinter GUI for trading **USDC-margined perpetual futures** on Binance via API. Allows multi-coin entries, leverage setting, PNL monitoring, and position closing (manual & experimental auto-TP).

---

## 🚨🚨 **EXTREME WARNING & DISCLAIMER** 🚨🚨

**USE AT YOUR OWN EXTREME RISK. FUTURES TRADING IS HIGHLY RISKY.**

*   **EXPERIMENTAL:** This software is **NOT well-tested** and likely contains bugs. Use with **EXTREME CAUTION**.
*   **NO PROFIT GUARANTEE:** This tool automates actions but **DOES NOT** guarantee profits or prevent losses. You are solely responsible for your trading decisions and outcomes.
*   **TESTNET FIRST:** **MANDATORY** to use only with a **Binance Testnet account** until you fully understand the code and risks. **DO NOT USE REAL MONEY IF YOU ARE UNSURE.**
*   **MARKET ORDERS & SLIPPAGE:** Uses MARKET orders, which are subject to **slippage**. Realized PNL may differ from targets.
*   **API KEY SECURITY:** Protect your API keys. Ensure keys have **Futures Trading ONLY** enabled and **Withdrawals DISABLED**.
*   **HEDGE MODE REQUIRED:** You **MUST** enable **Hedge Mode** (Dual Side Position) in your Binance Futures account settings.
*   **NO LIABILITY:** The author assumes **NO responsibility** for any financial losses.

---

## Core Features

*   Connect to Binance Futures (Mainnet/Testnet).
*   Dynamically load available USDC perpetual symbols.
*   Set leverage for new orders.
*   Place multi-coin Long/Short market orders (with optional market TP).
*   Add to positions individually.
*   Live PNL display.
*   Manual "Close All" button (Market Orders).
*   **Experimental:** "Activate Target TP" button to monitor total PNL and automatically close all positions via Market Order if target is reached.

## Prerequisites

*   Python 3.x
*   `pip install python-binance`
*   Binance Account: Futures Enabled, **Hedge Mode ON**, API Keys (Futures permission, Withdrawals OFF), USDC balance.
*   `tkinter` (usually included with Python, install `python3-tk` on Linux if needed).

## Basic Usage

1.  Run `main.py`.
2.  Enter API keys, select Testnet/Mainnet, click "Connect".
3.  Symbols load; set leverage.
4.  Select coins/direction/TPs/amounts.
5.  Use action buttons (Place Selected, L+, S+, Close All, Activate Target TP).
6.  Monitor PNL.
7.  Click "Disconnect" or close the window when done.

---

**Trade responsibly. This is a tool, not a strategy. Understand the code before use.**
