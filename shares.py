#!/usr/bin/env python3
"""
NSE Option Chain Live Terminal Streamer  —  v4.0
═══════════════════════════════════════════════════════════════════════════════
Multi-source Option Chain with Signal & Buildup Engine

Available Data Sources
──────────────────────
  1. NSE Official API  — Direct hit to nseindia.com (no key, may throttle)
  2. Upstox API        — Broker REST API (free, needs Upstox access token)
  3. nsepython         — Python library wrapper over NSE (pip install nsepython)

Market Trend Buildup Engine (Refreshes every 5 seconds)
────────────────────────────────────────────────────────
  • LONG BUILDUP   (LB) — Price ▲ & OI ▲ (Strong Bullish accumulation)
  • SHORT BUILDUP  (SB) — Price ▼ & OI ▲ (Strong Bearish expansion)
  • SHORT COVERING (SC) — Price ▲ & OI ▼ (Bullish short squeeze)
  • LONG UNWINDING (LU) — Price ▼ & OI ▼ (Bearish profit booking / drag)
  Evaluates both Macro Session Trend and Live 5s Tick Impulse.

Signal Engine — 10 Institutional Factors & Reliability Filters
─────────────────────────────────────────────────────────────────
  1. PCR                (Put-Call Ratio by OI)
  2. Session Chg OI     (NSE cumulative changeinOpenInterest, PE−CE)
  3. Tick Δ OI          (our inter-tick 5s live diff, PE−CE)
  4. ATM OI Diff        (PE OI − CE OI at exact ATM strike)
  5. VCR                (Volume Put-Call Ratio)
  6. Max-Pain           (Spot position relative to max-pain strike)
  7. Market Buildup     (Current market buildup regime: LB/SB/SC/LU)
  8. Core Weighted Flow (Inverse-distance strike decay around ATM)
  9. Key S/R OI Walls   (Call Resistance Wall vs Put Support Wall & Breakout / Bounce Defense)
  10. ATM IV Skew       (Call vs Put Implied Volatility pricing & buyer aggression)

Reliability & Execution Protection
───────────────────────────────────
  • Bull & Bear Trap Radar (detects when option writers heavily fade price moves)
  • Signal Confidence Grade (% alignment across multi-factor indicators)
  • Multi-tick EMA Smoothing & Temporal Stability Meter (guards against 5s whipsaws)

Usage
─────
  python3 shares.py                        # interactive source selector
  python3 shares.py --source nse           # NSE Official API
  python3 shares.py --source upstox        # Upstox API (needs --token)
  python3 shares.py --source nsepython     # nsepython library
  python3 shares.py -s BANKNIFTY -i 5     # symbol + refresh interval
"""

import sys
import time
import argparse
import os
from collections import deque
from datetime import datetime
from urllib.parse import urlparse, parse_qs

import requests

# ── ANSI colours ──────────────────────────────────────────────────────────────
RESET           = "\033[0m"
BOLD            = "\033[1m"
DIM             = "\033[2m"
GREEN           = "\033[92m"
RED             = "\033[91m"
YELLOW          = "\033[93m"
CYAN            = "\033[96m"
BLUE            = "\033[94m"
MAGENTA         = "\033[95m"
WHITE           = "\033[97m"
BG_GREEN        = "\033[42;30m"
BG_RED          = "\033[41;37m"
BG_YELLOW_BLACK = "\033[43;30m"
BG_BLUE_BLACK   = "\033[44;37m"
BG_MAGENTA      = "\033[45;30m"
BG_CYAN_BLACK   = "\033[46;30m"

INDICES = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"}

# Upstox instrument key map (add more as needed)
UPSTOX_INSTRUMENT_KEY = {
    "NIFTY"      : "NSE_INDEX|Nifty 50",
    "BANKNIFTY"  : "NSE_INDEX|Nifty Bank",
    "FINNIFTY"   : "NSE_INDEX|Nifty Fin Service",
    "MIDCPNIFTY" : "NSE_INDEX|NIFTY MID SELECT",
    "NIFTYNXT50" : "NSE_INDEX|Nifty Next 50",
}

SOURCE_LABELS = {
    "nse"      : f"{CYAN}NSE Official API{RESET}",
    "upstox"   : f"{GREEN}Upstox API{RESET}",
    "nsepython": f"{BLUE}nsepython{RESET}",
}

# ─────────────────────────────────────────────────────────────────────────────
#  Source-selector menu
# ─────────────────────────────────────────────────────────────────────────────

def source_menu():
    """Prints an interactive source selection menu and returns chosen source."""
    print(f"\n{CYAN}{BOLD}{'═' * 68}{RESET}")
    print(f"  {BOLD}NSE Option Chain Streamer  —  Select Data Source{RESET}")
    print(f"{CYAN}{'─' * 68}{RESET}")

    print(f"""
  {BOLD}[1] NSE Official API{RESET}  {DIM}(Direct to nseindia.com){RESET}
      • No account or API key needed
      • Same data as the NSE option chain website
      • May throttle / block after many requests
      • Best for: casual use, no setup needed

  {BOLD}[2] Upstox API{RESET}  {DIM}(Broker REST API — Recommended){RESET}
      • {GREEN}Faster & more reliable{RESET} than NSE scraping
      • Free with an Upstox account (no trading required)
      • Needs a valid {BOLD}Access Token{RESET} (generated from Upstox Developer Portal)
      • Also returns Option Greeks (delta, gamma, theta, vega)
      • Get token at: {CYAN}https://developer.upstox.com/{RESET}

  {BOLD}[3] nsepython{RESET}  {DIM}(Python library wrapper over NSE){RESET}
      • pip install nsepython
      • Returns same NSE data through a cleaner wrapper
      • No key needed, but same rate-limit risks as option 1
      • Best for: scripting / analysis when NSE direct hits fail
""")
    print(f"{CYAN}{'─' * 68}{RESET}")

    source_map = {"1": "nse", "2": "upstox", "3": "nsepython"}
    while True:
        try:
            choice = input(
                f"  Enter choice {BOLD}[1/2/3]{RESET} "
                f"(default = 1 NSE Official): "
            ).strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            sys.exit(0)
        if not choice:
            return "nse"
        if choice in source_map:
            return source_map[choice]
        print(f"  {RED}Invalid choice. Please enter 1, 2, or 3.{RESET}")


def prompt_upstox_token():
    """Prompts user for an Upstox access token if not set."""
    print(f"\n  {BOLD}Upstox Access Token Required{RESET}")
    print(f"  {DIM}Get yours free at: {CYAN}https://developer.upstox.com/{RESET}")
    print(f"  {DIM}You can also set env var {BOLD}UPSTOX_TOKEN{RESET}{DIM} to skip this prompt.{RESET}\n")
    token = os.environ.get("UPSTOX_TOKEN", "").strip()
    if token:
        print(f"  {GREEN}✓ Using UPSTOX_TOKEN from environment.{RESET}\n")
        return token
    try:
        token = input("  Paste Upstox Access Token: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nExiting.")
        sys.exit(0)
    if not token:
        print(f"  {RED}No token provided. Falling back to NSE Official API.{RESET}\n")
        return None
    return token


# ─────────────────────────────────────────────────────────────────────────────
#  Data Adapters — each returns a unified expiry_data list + spot_price
# ─────────────────────────────────────────────────────────────────────────────

class NSEAdapter:
    """
    Fetches data directly from NSE India option-chain-v3 endpoint.
    No API key required. Uses cookie-based session like a browser.
    """
    BASE_URL          = "https://www.nseindia.com"
    OPTION_CHAIN_PAGE = "https://www.nseindia.com/option-chain"

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept"         : "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection"     : "keep-alive",
    }
    API_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept"         : "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer"        : "https://www.nseindia.com/option-chain",
        "Connection"     : "keep-alive",
    }

    def __init__(self, symbol, expiry_date=None):
        self.symbol      = symbol
        self.expiry_date = expiry_date
        self.session     = None
        self._init_session()

    def _init_session(self):
        if self.session:
            try:
                self.session.close()
            except Exception:
                pass
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        for url in [self.OPTION_CHAIN_PAGE, self.BASE_URL]:
            try:
                self.session.get(url, timeout=10)
                break
            except Exception:
                pass

    def _get_json(self, url, retries=2):
        for attempt in range(retries + 1):
            try:
                r = self.session.get(url, headers=self.API_HEADERS, timeout=8)
                if r.status_code in (401, 403, 404):
                    self._init_session()
                    continue
                r.raise_for_status()
                return r.json()
            except requests.exceptions.RequestException:
                if attempt < retries:
                    self._init_session()
                    time.sleep(0.4)
                else:
                    raise

    def fetch(self):
        """
        Returns: (expiry_data, spot_price, expiry_str, all_expiries, timestamp)
        expiry_data is a list of dicts with CE/PE keys matching NSE format.
        """
        info = self._get_json(
            f"https://www.nseindia.com/api/option-chain-contract-info"
            f"?symbol={self.symbol}"
        )
        all_expiries = info.get("expiryDates", [])
        if not all_expiries:
            raise ValueError(f"No contracts for '{self.symbol}'.")

        expiry = self.expiry_date
        if not expiry or expiry not in all_expiries:
            expiry = all_expiries[0]

        opt_type = "Indices" if self.symbol in INDICES else "Equity"
        url      = (f"https://www.nseindia.com/api/option-chain-v3"
                    f"?type={opt_type}&symbol={self.symbol}&expiry={expiry}")
        data     = self._get_json(url)

        records     = data.get("records", {})
        all_data    = records.get("data", [])
        spot        = records.get("underlyingValue", 0.0)
        timestamp   = records.get("timestamp", "N/A")

        # Filter to selected expiry
        expiry_data = [
            it for it in all_data
            if (it.get("expiryDate") == expiry
                or it.get("expiryDates") == expiry
                or ("expiryDate" not in it and "expiryDates" not in it))
        ] or all_data

        return expiry_data, spot, expiry, all_expiries, timestamp


class UpstoxAdapter:
    """
    Fetches data from the Upstox REST API v2.
    Requires a valid Upstox access token.
    Returns data normalised to the same CE/PE format as NSEAdapter.

    API doc: https://upstox.com/developer/api-documentation/option-chain
    """
    BASE_URL     = "https://api.upstox.com/v2"
    CHAIN_URL    = "https://api.upstox.com/v2/option/chain"
    CONTRACT_URL = "https://api.upstox.com/v2/option/contract"

    def __init__(self, symbol, access_token, expiry_date=None):
        self.symbol          = symbol
        self.token           = access_token
        self.expiry_date     = self._normalize_expiry(expiry_date)
        self.instr_key       = UPSTOX_INSTRUMENT_KEY.get(
            symbol,
            f"NSE_EQ|{symbol}"   # fallback for equity symbols
        )
        self._cached_expiries = None

    @staticmethod
    def _normalize_expiry(expiry_str):
        if not expiry_str:
            return None
        # Relative keywords accepted as-is by Upstox
        if expiry_str.lower() in (
            "current_week", "next_week", "far_week",
            "current_month", "next_month", "far_month"
        ):
            return expiry_str.lower()
        # If already YYYY-MM-DD
        try:
            return datetime.strptime(expiry_str, "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            pass
        # If NSE format like 25-Sep-2026 or 25-SEP-2026 or DD/MM/YYYY
        for fmt in ("%d-%b-%Y", "%d-%B-%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(expiry_str, fmt).strftime("%Y-%m-%d")
            except ValueError:
                pass
        return expiry_str

    @property
    def _headers(self):
        return {
            "Accept"       : "application/json",
            "Authorization": f"Bearer {self.token}",
        }

    def _get_expiries(self):
        if self._cached_expiries:
            return self._cached_expiries
        r = requests.get(
            self.CONTRACT_URL,
            params={"instrument_key": self.instr_key},
            headers=self._headers,
            timeout=10
        )
        r.raise_for_status()
        contracts = r.json().get("data", [])
        expiries = sorted({c["expiry"] for c in contracts if isinstance(c, dict) and c.get("expiry")})
        if expiries:
            self._cached_expiries = expiries
        return expiries

    def _get_chain(self, expiry):
        r = requests.get(
            self.CHAIN_URL,
            params={"instrument_key": self.instr_key, "expiry_date": expiry},
            headers=self._headers,
            timeout=10
        )
        r.raise_for_status()
        return r.json()

    @staticmethod
    def _to_nse_format(upstox_rows):
        """
        Converts Upstox option chain rows → NSE-compatible list.
        Upstox row:  {strike_price, call_options: {market_data, option_greeks}, put_options: {...}}
        NSE row:     {strikePrice, CE: {openInterest, changeinOpenInterest, ...}, PE: {...}}
        """
        normalised = []
        for row in upstox_rows:
            strike = row.get("strike_price", 0)
            ce_src = row.get("call_options") or {}
            pe_src = row.get("put_options") or {}

            def _map(src):
                md  = src.get("market_data") or {}
                grk = src.get("option_greeks") or {}
                ltp = md.get("ltp") or 0
                prev_close = md.get("prev_close_price")
                return {
                    "openInterest"         : md.get("oi") or 0,
                    "changeinOpenInterest" : md.get("oi") or 0,  # Upstox doesn't give session chg OI in /chain
                    "totalTradedVolume"    : md.get("volume") or 0,
                    "impliedVolatility"    : grk.get("iv") or 0,
                    "lastPrice"            : ltp,
                    "change"               : (ltp - prev_close) if prev_close is not None else 0,
                    # Upstox extras exposed under "extras" key
                    "delta"  : grk.get("delta", "-"),
                    "gamma"  : grk.get("gamma", "-"),
                    "theta"  : grk.get("theta", "-"),
                    "vega"   : grk.get("vega",  "-"),
                    "bid"    : md.get("bid_price", "-"),
                    "ask"    : md.get("ask_price", "-"),
                }

            normalised.append({
                "strikePrice": strike,
                "CE"         : _map(ce_src),
                "PE"         : _map(pe_src),
            })
        return normalised

    def fetch(self):
        expiries = self._get_expiries()
        if not expiries:
            if self.expiry_date:
                expiry = self.expiry_date
                expiries = [expiry]
            else:
                raise ValueError(f"No Upstox expiries found for '{self.symbol}'.")
        else:
            expiry = self.expiry_date
            if not expiry or (expiry not in expiries and expiry not in (
                "current_week", "next_week", "far_week",
                "current_month", "next_month", "far_month"
            )):
                expiry = expiries[0]

        raw  = self._get_chain(expiry)
        rows = raw.get("data", [])
        spot = 0.0

        # Upstox includes spot in the first row's underlying price
        # or in a dedicated field depending on version
        if rows:
            md_ce = (rows[0].get("call_options") or {}).get("market_data") or {}
            spot  = md_ce.get("underlying_spot_price", 0.0) or 0.0

        # Also try top-level or row level
        if not spot and rows:
            spot = rows[0].get("underlying_spot_price", 0.0) or raw.get("spot_price", 0.0) or 0.0
        elif not spot:
            spot = raw.get("spot_price", 0.0) or 0.0

        # If relative expiry keyword was used, resolve actual date from rows
        if expiry in ("current_week", "next_week", "far_week", "current_month", "next_month", "far_month") and rows:
            actual_expiry = rows[0].get("expiry")
            if actual_expiry:
                expiry = actual_expiry

        expiry_data = self._to_nse_format(rows)
        timestamp   = datetime.now().strftime("%d-%b-%Y %H:%M:%S")

        return expiry_data, spot, expiry, expiries, timestamp


class NSEPythonAdapter:
    """
    Uses the `nsepython` pip package to fetch option chain data.
    Install: pip install nsepython
    No API key needed — wraps NSE's public endpoints.
    """

    def __init__(self, symbol, expiry_date=None):
        self.symbol      = symbol
        self.expiry_date = expiry_date
        self._check_install()

    @staticmethod
    def _check_install():
        try:
            import nsepython  # noqa: F401
        except ImportError:
            print(
                f"\n{RED}nsepython is not installed.{RESET}\n"
                f"Run: {BOLD}pip install nsepython{RESET}\n"
                f"Then restart the streamer.\n"
            )
            sys.exit(1)

    def fetch(self):
        from nsepython import nse_optionchain  # type: ignore
        raw         = nse_optionchain(self.symbol)
        records     = raw.get("records", {})
        all_data    = records.get("data", [])
        spot        = records.get("underlyingValue", 0.0)
        timestamp   = records.get("timestamp", "N/A")
        all_expiries= records.get("expiryDates", [])

        expiry = self.expiry_date
        if not expiry or expiry not in all_expiries:
            expiry = all_expiries[0] if all_expiries else "N/A"

        expiry_data = [
            it for it in all_data
            if (it.get("expiryDate") == expiry
                or it.get("expiryDates") == expiry
                or ("expiryDate" not in it and "expiryDates" not in it))
        ] or all_data

        return expiry_data, spot, expiry, all_expiries, timestamp


# ─────────────────────────────────────────────────────────────────────────────
#  Buildup Engine (Long Buildup, Short Buildup, Short Covering, Long Unwinding)
# ─────────────────────────────────────────────────────────────────────────────

BUILDUP_CONFIG = {
    "LONG BUILDUP": {
        "code"     : "LB",
        "badge"    : f"{BG_GREEN}{BOLD} LONG BUILDUP 🐂 {RESET}",
        "color"    : GREEN,
        "sentiment": "BULLISH (Buyers Dominating / Put Writing Support)",
        "desc"     : "Price ▲ & OI ▲",
    },
    "SHORT BUILDUP": {
        "code"     : "SB",
        "badge"    : f"{BG_RED}{BOLD} SHORT BUILDUP 🐻 {RESET}",
        "color"    : RED,
        "sentiment": "BEARISH (Sellers Dominating / Call Writing Wall)",
        "desc"     : "Price ▼ & OI ▲",
    },
    "SHORT COVERING": {
        "code"     : "SC",
        "badge"    : f"{BG_CYAN_BLACK}{BOLD} SHORT COVERING ⚡ {RESET}",
        "color"    : CYAN,
        "sentiment": "BULLISH RALLY (Short Sellers Trapped & Covering)",
        "desc"     : "Price ▲ & OI ▼",
    },
    "LONG UNWINDING": {
        "code"     : "LU",
        "badge"    : f"{BG_MAGENTA}{BOLD} LONG UNWINDING 🔻 {RESET}",
        "color"    : MAGENTA,
        "sentiment": "BEARISH DRAG (Long Liquidation / Profit Booking)",
        "desc"     : "Price ▼ & OI ▼",
    },
    "NEUTRAL": {
        "code"     : "--",
        "badge"    : f"{BG_YELLOW_BLACK}{BOLD} NEUTRAL / CONSOLIDATION ⚖️ {RESET}",
        "color"    : YELLOW,
        "sentiment": "SIDEWAYS (Price & OI Flow Balanced)",
        "desc"     : "Flat Price / OI",
    },
}


def classify_buildup(price_chg, oi_chg):
    """
    Classifies Price Change and OI Change into the 4 standard derivative quadrants:
      • Price > 0 and OI > 0  -->  LONG BUILDUP   (LB)
      • Price < 0 and OI > 0  -->  SHORT BUILDUP  (SB)
      • Price > 0 and OI < 0  -->  SHORT COVERING (SC)
      • Price < 0 and OI < 0  -->  LONG UNWINDING (LU)
    """
    try:
        p = float(price_chg) if price_chg not in (None, "-") else 0.0
        oi = float(oi_chg) if oi_chg not in (None, "-") else 0.0
    except (ValueError, TypeError):
        return "NEUTRAL", "--", DIM

    if p > 0 and oi > 0:
        return "LONG BUILDUP", "LB", GREEN
    elif p < 0 and oi > 0:
        return "SHORT BUILDUP", "SB", RED
    elif p > 0 and oi < 0:
        return "SHORT COVERING", "SC", CYAN
    elif p < 0 and oi < 0:
        return "LONG UNWINDING", "LU", MAGENTA
    elif p > 0:
        return "PRICE GAIN", "PG", GREEN
    elif p < 0:
        return "PRICE DROP", "PD", RED
    elif oi > 0:
        return "OI EXPANSION", "OE", WHITE
    elif oi < 0:
        return "OI REDUCTION", "OR", DIM
    else:
        return "NEUTRAL", "--", DIM


def compute_market_trend(spot_change, tick_spot_change,
                         tot_ce_chg, tot_pe_chg,
                         tick_ce_oi, tick_pe_oi,
                         near_strikes, strike_map, atm):
    """
    Computes both Session Market Trend Buildup and Live 5s Tick Buildup.
    Returns:
      session_tag, session_reason, tick_tag, tick_reason, ce_cnt, pe_cnt, strike_buildup_map
    """
    ce_cnt = {"LB": 0, "SB": 0, "SC": 0, "LU": 0}
    pe_cnt = {"LB": 0, "SB": 0, "SC": 0, "LU": 0}
    strike_buildup_map = {}

    for s in near_strikes:
        it = strike_map.get(s, {})
        ce = it.get("CE", {})
        pe = it.get("PE", {})

        ce_p = ce.get("change") or 0.0
        ce_oi = ce.get("changeinOpenInterest") or 0.0
        ce_tag, ce_code, ce_col = classify_buildup(ce_p, ce_oi)
        if ce_code in ce_cnt:
            ce_cnt[ce_code] += 1

        pe_p = pe.get("change") or 0.0
        pe_oi = pe.get("changeinOpenInterest") or 0.0
        pe_tag, pe_code, pe_col = classify_buildup(pe_p, pe_oi)
        if pe_code in pe_cnt:
            pe_cnt[pe_code] += 1

        strike_buildup_map[s] = {
            "CE": (ce_tag, ce_code, ce_col),
            "PE": (pe_tag, pe_code, pe_col),
        }

    # Session market price momentum (using ATM options synthetic parity proxy)
    atm_ce_chg = strike_map.get(atm, {}).get("CE", {}).get("change") or 0.0
    atm_pe_chg = strike_map.get(atm, {}).get("PE", {}).get("change") or 0.0
    atm_synthetic_p = atm_ce_chg - atm_pe_chg

    if spot_change is not None and abs(spot_change) > 0.001:
        p_dir = spot_change
    else:
        p_dir = atm_synthetic_p

    net_oi_chg = tot_pe_chg - tot_ce_chg
    total_oi_chg = tot_pe_chg + tot_ce_chg

    # Macro Session Trend
    if p_dir > 0:  # Market Up
        if tot_pe_chg > 0 and (tot_pe_chg >= abs(tot_ce_chg) or tot_ce_chg >= 0):
            s_tag = "LONG BUILDUP"
            s_reason = f"Price ▲ with heavy PE writing (+{tot_pe_chg:,}) building strong support"
        elif tot_ce_chg < 0 or (tot_pe_chg <= 0 and total_oi_chg < 0):
            s_tag = "SHORT COVERING"
            s_reason = f"Price ▲ driven by trapped Call writers covering (CE ChgOI {tot_ce_chg:,})"
        elif net_oi_chg > 0:
            s_tag = "LONG BUILDUP"
            s_reason = f"Price ▲ with positive net OI creation (PE−CE: {net_oi_chg:+,})"
        else:
            s_tag = "SHORT COVERING"
            s_reason = f"Price ▲ with Call writers squaring off"
    elif p_dir < 0:  # Market Down
        if tot_ce_chg > 0 and (tot_ce_chg >= abs(tot_pe_chg) or tot_pe_chg >= 0):
            s_tag = "SHORT BUILDUP"
            s_reason = f"Price ▼ with heavy CE writing (+{tot_ce_chg:,}) creating overhead wall"
        elif tot_pe_chg < 0 or (tot_ce_chg <= 0 and total_oi_chg < 0):
            s_tag = "LONG UNWINDING"
            s_reason = f"Price ▼ driven by Put writers & longs liquidating (PE ChgOI {tot_pe_chg:,})"
        elif net_oi_chg < 0:
            s_tag = "SHORT BUILDUP"
            s_reason = f"Price ▼ with aggressive Call writing (CE−PE: {-net_oi_chg:+,})"
        else:
            s_tag = "LONG UNWINDING"
            s_reason = f"Price ▼ with long positions squaring off"
    else:  # Neutral
        if net_oi_chg > 50000:
            s_tag = "LONG BUILDUP"
            s_reason = f"Price steady, Put writing accumulation (+{tot_pe_chg:,})"
        elif net_oi_chg < -50000:
            s_tag = "SHORT BUILDUP"
            s_reason = f"Price steady, Call writing accumulation (+{tot_ce_chg:,})"
        else:
            s_tag = "NEUTRAL"
            s_reason = "Price and OI balanced"

    # Live 5-Second Tick Trend
    tick_ce = tick_ce_oi or 0
    tick_pe = tick_pe_oi or 0
    tick_tot_oi = tick_pe + tick_ce
    tick_net_oi = tick_pe - tick_ce

    if tick_spot_change is not None and abs(tick_spot_change) > 0.001:
        if tick_spot_change > 0:  # Spot ticked UP in last 5s
            if tick_tot_oi > 0 or tick_pe > 0:
                t_tag = "LONG BUILDUP"
                t_reason = f"Spot {tick_spot_change:+.2f} ▲, OI added (+{tick_tot_oi:,})"
            elif tick_tot_oi < 0 or tick_ce < 0:
                t_tag = "SHORT COVERING"
                t_reason = f"Spot {tick_spot_change:+.2f} ▲, OI shed ({tick_tot_oi:,})"
            else:
                t_tag = "LONG BUILDUP"
                t_reason = f"Spot {tick_spot_change:+.2f} ▲"
        else:  # Spot ticked DOWN in last 5s
            if tick_tot_oi > 0 or tick_ce > 0:
                t_tag = "SHORT BUILDUP"
                t_reason = f"Spot {tick_spot_change:+.2f} ▼, OI added (+{tick_tot_oi:,})"
            elif tick_tot_oi < 0 or tick_pe < 0:
                t_tag = "LONG UNWINDING"
                t_reason = f"Spot {tick_spot_change:+.2f} ▼, OI shed ({tick_tot_oi:,})"
            else:
                t_tag = "SHORT BUILDUP"
                t_reason = f"Spot {tick_spot_change:+.2f} ▼"
    else:  # Spot unchanged in this 5s tick
        if tick_net_oi > 5000:
            t_tag = "LONG BUILDUP"
            t_reason = f"Spot steady, PE OI added (+{tick_pe:,})"
        elif tick_net_oi < -5000:
            t_tag = "SHORT BUILDUP"
            t_reason = f"Spot steady, CE OI added (+{tick_ce:,})"
        elif tick_tot_oi < -5000:
            t_tag = "SHORT COVERING" if p_dir >= 0 else "LONG UNWINDING"
            t_reason = f"Spot steady, OI squaring off ({tick_tot_oi:,})"
        else:
            t_tag = s_tag
            t_reason = "Steady / Following session trend"

    return {
        "session_tag"       : s_tag,
        "session_reason"    : s_reason,
        "tick_tag"          : t_tag,
        "tick_reason"       : t_reason,
        "ce_cnt"            : ce_cnt,
        "pe_cnt"            : pe_cnt,
        "strike_buildup_map": strike_buildup_map,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Signal Engine
# ─────────────────────────────────────────────────────────────────────────────

def compute_max_pain(strikes, strike_map):
    def _loss(target):
        total = 0
        for s in strikes:
            item  = strike_map.get(s, {})
            ce_oi = item.get("CE", {}).get("openInterest", 0) or 0
            pe_oi = item.get("PE", {}).get("openInterest", 0) or 0
            total += ce_oi * max(0, s - target) + pe_oi * max(0, target - s)
        return total
    return min(strikes, key=_loss)


def compute_sr_walls(strikes, strike_map, spot_price):
    """
    Identifies Major Call Resistance Wall (Highest CE OI) and Major Put Support Wall (Highest PE OI).
    Evaluates wall strength, change in OI, and spot distance to walls.
    """
    if not strikes:
        return {}

    call_wall = max(strikes, key=lambda s: (strike_map.get(s, {}).get("CE", {}).get("openInterest") or 0))
    put_wall  = max(strikes, key=lambda s: (strike_map.get(s, {}).get("PE", {}).get("openInterest") or 0))

    call_ce = strike_map.get(call_wall, {}).get("CE", {})
    put_pe  = strike_map.get(put_wall, {}).get("PE", {})

    call_oi  = call_ce.get("openInterest") or 0
    call_chg = call_ce.get("changeinOpenInterest") or 0
    put_oi   = put_pe.get("openInterest") or 0
    put_chg  = put_pe.get("changeinOpenInterest") or 0

    dist_call_pct = ((call_wall - spot_price) / spot_price * 100.0) if spot_price else 0.0
    dist_put_pct  = ((spot_price - put_wall) / spot_price * 100.0) if spot_price else 0.0

    if call_wall > put_wall and (call_wall - put_wall) > 0:
        range_pos = (spot_price - put_wall) / (call_wall - put_wall) * 100.0
        range_pos = max(0.0, min(100.0, range_pos))
    else:
        range_pos = 50.0

    return {
        "call_wall"     : call_wall,
        "call_oi"       : call_oi,
        "call_chg"      : call_chg,
        "dist_call_pct" : dist_call_pct,
        "put_wall"      : put_wall,
        "put_oi"        : put_oi,
        "put_chg"       : put_chg,
        "dist_put_pct"  : dist_put_pct,
        "range_pos"     : range_pos,
    }


def analyse_option_chain(expiry_data, spot_price, strikes_count=10,
                          ce_oi_diffs=None, pe_oi_diffs=None,
                          spot_change=None, tick_spot_change=None,
                          tot_ce_oi_diff=None, tot_pe_oi_diff=None):
    """
    10-factor Institutional Scoring Engine + Buildup Engine + S/R Walls + Trap Radar.
    Returns:
      score, signal, trade_action, confidence_pct, confidence_label, trap_info, sr_info,
      per-factor breakdown, trend_info, strike_buildup.
    """
    ce_oi_diffs = ce_oi_diffs or {}
    pe_oi_diffs = pe_oi_diffs or {}

    strikes = sorted({it["strikePrice"] for it in expiry_data if "strikePrice" in it})
    if not strikes:
        return {}

    strike_map = {it["strikePrice"]: it for it in expiry_data}
    atm        = min(strikes, key=lambda s: abs(s - spot_price))
    aidx       = strikes.index(atm)
    near       = strikes[max(0, aidx - strikes_count):min(len(strikes), aidx + strikes_count + 1)]

    strike_step = abs(strikes[1] - strikes[0]) if len(strikes) > 1 else 50.0

    tot_ce_oi = tot_pe_oi = 0
    tot_ce_chg = tot_pe_chg = 0
    tot_ce_vol = tot_pe_vol = 0
    tick_ce = tick_pe = 0

    # Core strike window (ATM ± 2 strikes) & Inverse-Distance Weighted flow
    core_strikes = [s for s in near if abs(s - atm) <= 2.0 * strike_step]
    core_ce_chg = 0
    core_pe_chg = 0
    core_ce_oi  = 0
    core_pe_oi  = 0

    weighted_ce_chg = 0.0
    weighted_pe_chg = 0.0

    for s in near:
        it = strike_map.get(s, {})
        ce = it.get("CE", {})
        pe = it.get("PE", {})
        ce_oi_val  = ce.get("openInterest", 0) or 0
        pe_oi_val  = pe.get("openInterest", 0) or 0
        ce_chg_val = ce.get("changeinOpenInterest", 0) or 0
        pe_chg_val = pe.get("changeinOpenInterest", 0) or 0

        tot_ce_oi  += ce_oi_val
        tot_pe_oi  += pe_oi_val
        tot_ce_chg += ce_chg_val
        tot_pe_chg += pe_chg_val
        tot_ce_vol += (ce.get("totalTradedVolume", 0) or 0)
        tot_pe_vol += (pe.get("totalTradedVolume", 0) or 0)
        tick_ce    += (ce_oi_diffs.get(s) or 0)
        tick_pe    += (pe_oi_diffs.get(s) or 0)

        # Distance weighting: strikes right at ATM receive 1.0 weight, farther strikes decay
        dist_factor = 1.0 / (1.0 + (abs(s - atm) / strike_step))
        weighted_ce_chg += ce_chg_val * dist_factor
        weighted_pe_chg += pe_chg_val * dist_factor

        if s in core_strikes:
            core_ce_chg += ce_chg_val
            core_pe_chg += pe_chg_val
            core_ce_oi  += ce_oi_val
            core_pe_oi  += pe_oi_val

    pcr = (tot_pe_oi / tot_ce_oi) if tot_ce_oi > 0 else 0.0
    vcr = (tot_pe_vol / tot_ce_vol) if tot_ce_vol > 0 else 0.0
    core_net_chg = core_pe_chg - core_ce_chg
    weighted_net_chg = weighted_pe_chg - weighted_ce_chg

    oi_diff_rows = [
        (s, ((strike_map.get(s, {}).get("PE", {}).get("openInterest", 0) or 0)
             - (strike_map.get(s, {}).get("CE", {}).get("openInterest", 0) or 0)))
        for s in near
    ]

    atm_it      = strike_map.get(atm, {})
    atm_ce_oi   = atm_it.get("CE", {}).get("openInterest", 0) or 0
    atm_pe_oi   = atm_it.get("PE", {}).get("openInterest", 0) or 0
    atm_oi_diff = atm_pe_oi - atm_ce_oi

    max_pain    = compute_max_pain(strikes, strike_map)
    mp_pct      = (spot_price - max_pain) / max_pain * 100 if max_pain else 0

    # Key S/R Walls
    sr = compute_sr_walls(strikes, strike_map, spot_price)

    # Buildup Engine Evaluation
    trend_info = compute_market_trend(
        spot_change=spot_change,
        tick_spot_change=tick_spot_change,
        tot_ce_chg=tot_ce_chg,
        tot_pe_chg=tot_pe_chg,
        tick_ce_oi=tot_ce_oi_diff,
        tick_pe_oi=tot_pe_oi_diff,
        near_strikes=near,
        strike_map=strike_map,
        atm=atm,
    )

    # ATM Implied Volatility (IV) Skew
    atm_ce_iv = float(atm_it.get("CE", {}).get("impliedVolatility") or 0.0)
    atm_pe_iv = float(atm_it.get("PE", {}).get("impliedVolatility") or 0.0)
    iv_skew   = (atm_ce_iv - atm_pe_iv) if (atm_ce_iv > 0 and atm_pe_iv > 0) else 0.0

    # Trap Detection (Bull Trap / Bear Trap Radar)
    p_dir = spot_change if (spot_change is not None and abs(spot_change) > 0.001) else (
        (atm_it.get("CE", {}).get("change") or 0.0) - (atm_it.get("PE", {}).get("change") or 0.0)
    )

    trap_type = "NONE"
    trap_note = "Price movement aligns cleanly with option writer positioning"
    trap_penalty = 0

    if p_dir > 0 and core_ce_chg > 20000 and core_ce_chg > max(1, abs(core_pe_chg)) * 1.5:
        trap_type = "BULL TRAP"
        trap_note = f"Spot rising (+{p_dir:.2f}) into massive Core Call writing (+{core_ce_chg:,}) -> Ceiling Capping"
        trap_penalty = -2
    elif p_dir < 0 and core_pe_chg > 20000 and core_pe_chg > max(1, abs(core_ce_chg)) * 1.5:
        trap_type = "BEAR TRAP"
        trap_note = f"Spot falling ({p_dir:.2f}) into massive Core Put writing (+{core_pe_chg:,}) -> Floor Absorbing"
        trap_penalty = +2

    score   = 0
    factors = []

    # F1 PCR
    if pcr >= 1.5:
        pts, note = 2, "Very Bullish (> 1.5)"
    elif pcr >= 1.2:
        pts, note = 1, "Bullish (1.2 - 1.5)"
    elif pcr <= 0.5:
        pts, note = -2, "Very Bearish (< 0.5)"
    elif pcr <= 0.8:
        pts, note = -1, "Bearish (0.5 - 0.8)"
    else:
        pts, note = 0, "Neutral (0.8 - 1.2)"
    score += pts
    factors.append(("PCR", f"{pcr:.2f}", pts, note))

    # F2 Session Chg OI (Net PE−CE)
    sd = tot_pe_chg - tot_ce_chg
    if sd > 0:
        pts = min(2, max(1, int(sd / max(1, abs(tot_ce_chg)) * 3)))
        note = "PE session OI growing → Bullish support"
    elif sd < 0:
        pts = -min(2, max(1, int(abs(sd) / max(1, abs(tot_pe_chg)) * 3)))
        note = "CE session OI growing → Bearish overhead wall"
    else:
        pts = 0; note = "Balanced"
    score += pts
    factors.append(("Session Chg OI", f"{sd:+,}", pts, note))

    # F3 Tick Δ OI (Live 5s delta)
    td = tick_pe - tick_ce
    if td > 0:
        pts = min(2, max(1, int(td / max(1, abs(tick_ce) + 1) * 3)))
        note = "PE OI added this 5s tick → Fresh bullish flow"
    elif td < 0:
        pts = -min(2, max(1, int(abs(td) / max(1, abs(tick_pe) + 1) * 3)))
        note = "CE OI added this 5s tick → Fresh bearish flow"
    else:
        pts = 0; note = "No 5s tick change"
    score += pts
    factors.append(("Tick Δ OI (5s)", f"{td:+,}", pts, note))

    # F4 ATM OI Diff
    if atm_oi_diff > 0:
        pts = 1; note = f"PE>CE at ATM {atm:,.0f} → Immediate support"
    elif atm_oi_diff < 0:
        pts = -1; note = f"CE>PE at ATM {atm:,.0f} → Immediate resistance"
    else:
        pts = 0; note = "ATM balanced"
    score += pts
    factors.append(("ATM OI Diff", f"{atm_oi_diff:+,}", pts, note))

    # F5 VCR (Volume PCR)
    if vcr >= 1.3:
        pts, note = 2, "Strong buying volume (VCR ≥ 1.3)"
    elif vcr >= 1.1:
        pts, note = 1, "Mild buying volume (1.1 - 1.3)"
    elif vcr <= 0.7:
        pts, note = -2, "Strong selling volume (VCR ≤ 0.7)"
    elif vcr <= 0.9:
        pts, note = -1, "Mild selling volume (0.7 - 0.9)"
    else:
        pts, note = 0, "Volume balanced"
    score += pts
    factors.append(("VCR (Volume)", f"{vcr:.2f}", pts, note))

    # F6 Max-Pain Position
    if mp_pct > 1.5:
        pts = -1; note = f"Spot {mp_pct:+.1f}% above Max-Pain ({max_pain:,.0f}) → Pull-back risk"
    elif mp_pct < -1.5:
        pts = 1;  note = f"Spot {mp_pct:+.1f}% below Max-Pain ({max_pain:,.0f}) → Recovery bias"
    else:
        pts = 0;  note = f"Near Max-Pain ({max_pain:,.0f}) → Magnet neutral"
    score += pts
    factors.append(("Max-Pain", f"{max_pain:,.0f}", pts, note))

    # F7 Market Buildup (LB / SB / SC / LU)
    mkt_tag = trend_info["session_tag"]
    if mkt_tag == "LONG BUILDUP":
        pts = 2; note = "Price▲, OI▲ → Fresh buyer accumulation (Bullish)"
    elif mkt_tag == "SHORT COVERING":
        pts = 1; note = "Price▲, OI▼ → Short sellers covering (Bullish rally)"
    elif mkt_tag == "SHORT BUILDUP":
        pts = -2; note = "Price▼, OI▲ → Fresh short creation & call writing (Bearish)"
    elif mkt_tag == "LONG UNWINDING":
        pts = -1; note = "Price▼, OI▼ → Longs liquidating (Bearish drag)"
    else:
        pts = 0; note = "Neutral / Sideways consolidation"
    score += pts
    factors.append(("Market Buildup", mkt_tag, pts, note))

    # F8 Core Weighted Flow (Inverse-Distance Decay around ATM)
    if weighted_net_chg > 0 and core_net_chg > 0:
        pts = min(2, max(1, int(core_net_chg / max(1, abs(core_ce_chg) + 1) * 3)))
        note = f"Core ATM PE writers (+{core_pe_chg:,}) outpace CE (+{core_ce_chg:,}) -> Heavy Support"
    elif weighted_net_chg < 0 and core_net_chg < 0:
        pts = -min(2, max(1, int(abs(core_net_chg) / max(1, abs(core_pe_chg) + 1) * 3)))
        note = f"Core ATM CE writers (+{core_ce_chg:,}) outpace PE (+{core_pe_chg:,}) -> Heavy Ceiling"
    else:
        pts = 0; note = "Core ATM orderflow balanced / mixed"
    score += pts
    factors.append(("Core Weighted Flow", f"{core_net_chg:+,}", pts, note))

    # F9 Key S/R OI Walls Proximity & Defense
    if sr.get("dist_call_pct", 10.0) <= 0.35:
        if sr.get("call_chg", 0) > 0:
            pts = -2
            note = f"At Call Wall {sr['call_wall']:,.0f} (+{sr['call_chg']:,} OI) -> Heavy Rejection Risk"
        elif sr.get("call_chg", 0) < 0:
            pts = +2
            note = f"Testing Call Wall {sr['call_wall']:,.0f} while writers cover ({sr['call_chg']:,}) -> Squeeze Breakout"
        else:
            pts = -1
            note = f"At Call Wall {sr['call_wall']:,.0f} Resistance"
    elif sr.get("dist_put_pct", 10.0) <= 0.35:
        if sr.get("put_chg", 0) > 0:
            pts = +2
            note = f"At Put Wall {sr['put_wall']:,.0f} (+{sr['put_chg']:,} OI) -> Strong Bounce Floor"
        elif sr.get("put_chg", 0) < 0:
            pts = -2
            note = f"Testing Put Wall {sr['put_wall']:,.0f} while writers flee ({sr['put_chg']:,}) -> Breakdown Risk"
        else:
            pts = +1
            note = f"At Put Wall {sr['put_wall']:,.0f} Support"
    else:
        pts = 0
        note = f"Mid-Range ({sr.get('range_pos', 50):.0f}% between {sr.get('put_wall', 0):,.0f} & {sr.get('call_wall', 0):,.0f})"
    score += pts
    factors.append(("Key S/R Walls", f"{sr.get('range_pos', 50):.0f}% range", pts, note))

    # F10 ATM IV Skew
    if atm_ce_iv > 0 and atm_pe_iv > 0:
        if iv_skew >= 1.2:
            pts = 1
            note = f"Call IV ({atm_ce_iv:.1f}%) > Put IV ({atm_pe_iv:.1f}%) by {iv_skew:+.1f}% -> Call buyer aggression"
        elif iv_skew <= -1.2:
            pts = -1
            note = f"Put IV ({atm_pe_iv:.1f}%) > Call IV ({atm_ce_iv:.1f}%) by {abs(iv_skew):.1f}% -> Put buying / Downside hedging"
        else:
            pts = 0
            note = f"Balanced IV Skew (CE: {atm_ce_iv:.1f}% vs PE: {atm_pe_iv:.1f}%)"
    else:
        pts = 0; note = "IV data neutral or not reported"
    score += pts
    factors.append(("ATM IV Skew", f"{iv_skew:+.1f}%", pts, note))

    # Apply Trap Penalty / Bonus
    if trap_penalty != 0:
        score += trap_penalty
        factors.append(("Trap Radar Filter", trap_type, trap_penalty, trap_note))

    # Confidence Calculation (% agreement among active directional factors)
    pos_count = sum(1 for _, _, p, _ in factors if p > 0)
    neg_count = sum(1 for _, _, p, _ in factors if p < 0)
    total_active = pos_count + neg_count

    if score > 0:
        agreement = pos_count / max(1, total_active)
    elif score < 0:
        agreement = neg_count / max(1, total_active)
    else:
        agreement = 0.4

    confidence_pct = int(min(100, max(25, agreement * 100)))
    if trap_type != "NONE":
        confidence_pct = max(20, confidence_pct - 25)

    if confidence_pct >= 80:
        confidence_label = f"{GREEN}{BOLD}{confidence_pct}% [VERY HIGH ★★★]{RESET}"
    elif confidence_pct >= 65:
        confidence_label = f"{GREEN}{confidence_pct}% [HIGH ★★]{RESET}"
    elif confidence_pct >= 50:
        confidence_label = f"{YELLOW}{confidence_pct}% [MODERATE ★]{RESET}"
    else:
        confidence_label = f"{RED}{BOLD}{confidence_pct}% [LOW / CHOP ⚠️]{RESET}"

    # Final Signal Synthesis with Trap Protection
    if trap_type == "BULL TRAP" and score >= 2:
        signal      = "TRAP: FAKE BUY ⚠️"
        sig_type    = "AVOID CE / WAIT"
        sig_col     = f"{BG_YELLOW_BLACK}{BOLD}"
    elif trap_type == "BEAR TRAP" and score <= -2:
        signal      = "TRAP: FAKE SELL ⚠️"
        sig_type    = "AVOID PE / WAIT"
        sig_col     = f"{BG_YELLOW_BLACK}{BOLD}"
    elif score >= 7:
        signal      = "STRONG BUY  🚀"
        sig_type    = "BUY CE (CALL)"
        sig_col     = f"{BG_GREEN}{BOLD}"
    elif score >= 3:
        signal      = "BUY  📈"
        sig_type    = "BUY CE (CALL)"
        sig_col     = f"{GREEN}{BOLD}"
    elif score >= 1:
        signal      = "MILD BUY  🟢"
        sig_type    = "BUY CE (CALL)"
        sig_col     = f"{GREEN}"
    elif score <= -7:
        signal      = "STRONG SELL 💥"
        sig_type    = "BUY PE (PUT)"
        sig_col     = f"{BG_RED}{BOLD}"
    elif score <= -3:
        signal      = "SELL  📉"
        sig_type    = "BUY PE (PUT)"
        sig_col     = f"{RED}{BOLD}"
    elif score <= -1:
        signal      = "MILD SELL  🔴"
        sig_type    = "BUY PE (PUT)"
        sig_col     = f"{RED}"
    else:
        signal      = "NEUTRAL  ⚖️"
        sig_type    = "HOLD / WAIT"
        sig_col     = f"{YELLOW}"

    return dict(
        score            = score,
        signal           = signal,
        sig_type         = sig_type,
        sig_col          = sig_col,
        confidence_pct   = confidence_pct,
        confidence_label = confidence_label,
        trap_type        = trap_type,
        trap_note        = trap_note,
        sr_info          = sr,
        iv_skew          = iv_skew,
        atm_ce_iv        = atm_ce_iv,
        atm_pe_iv        = atm_pe_iv,
        pcr              = pcr,
        vcr              = vcr,
        atm              = atm,
        atm_oi_diff      = atm_oi_diff,
        max_pain         = max_pain,
        mp_pct           = mp_pct,
        tot_ce_oi        = tot_ce_oi,
        tot_pe_oi        = tot_pe_oi,
        tot_ce_chg       = tot_ce_chg,
        tot_pe_chg       = tot_pe_chg,
        tick_ce          = tick_ce,
        tick_pe          = tick_pe,
        tot_ce_vol       = tot_ce_vol,
        tot_pe_vol       = tot_pe_vol,
        core_net_chg     = core_net_chg,
        weighted_net_chg = weighted_net_chg,
        oi_diff_rows     = oi_diff_rows,
        factors          = factors,
        trend_info       = trend_info,
        strike_buildup   = trend_info["strike_buildup_map"],
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Main Streamer
# ─────────────────────────────────────────────────────────────────────────────

class NSEOptionChainLive:
    """
    Drives the terminal display loop.
    Accepts any adapter (NSEAdapter / UpstoxAdapter / NSEPythonAdapter).
    """

    def __init__(self, adapter, source_name, symbol,
                 strikes_count=10, interval=5.0):
        self.adapter       = adapter
        self.source_name   = source_name
        self.symbol        = symbol
        self.strikes_count = strikes_count
        self.interval      = interval

        # Spot tracking for 5-second interval
        self.initial_spot   = None
        self.prev_spot      = None
        self.tick_spot_diff = 0.0

        # OI diff tracking
        self.prev_ce_oi     = {}
        self.prev_pe_oi     = {}
        self.ce_oi_diffs    = {}
        self.pe_oi_diffs    = {}
        self.last_nse_ts    = None

        # Total OI delta
        self.prev_tot_ce_oi = None
        self.prev_tot_pe_oi = None
        self.tot_ce_oi_diff = None
        self.tot_pe_oi_diff = None

        # Signal history
        self.signal_history = deque(maxlen=8)

    # ── Formatters ────────────────────────────────────────────────────────────

    @staticmethod
    def fmt(val, is_float=False, dp=2):
        if val is None or val == "-":
            return "-"
        try:
            f = float(val)
            return f"{f:,.{dp}f}" if is_float else f"{int(f):,}"
        except (ValueError, TypeError):
            return str(val)

    @staticmethod
    def clr_chg(val, w=9):
        if val is None or val == "-":
            return f"{'-':>{w}}"
        try:
            f  = float(val)
            s  = f"{f:+,.0f}" if abs(f) >= 10 else f"{f:+,.2f}"
            s  = f"{s:>{w}}"
            return (f"{GREEN}{s}{RESET}" if f > 0 else
                    f"{RED}{s}{RESET}"   if f < 0 else s)
        except (ValueError, TypeError):
            return f"{str(val):>{w}}"

    @staticmethod
    def clr_diff(val, w=9):
        if val is None:
            return f"{'-':>{w}}"
        try:
            f = int(float(val))
            s = f"{f:+,}"
            s = f"{s:>{w}}"
            return (f"{GREEN}{s}{RESET}" if f > 0 else
                    f"{RED}{s}{RESET}"   if f < 0 else s)
        except (ValueError, TypeError):
            return f"{str(val):>{w}}"

    @staticmethod
    def fmt_buildup(code, col, w=6):
        raw = f"[{code}]"
        padded = f"{raw:^{w}}"
        return f"{col}{padded}{RESET}"

    # ── OI diff tracking ──────────────────────────────────────────────────────

    def _update_oi_diffs(self, expiry_data, nse_ts):
        cur_ce, cur_pe = {}, {}
        for it in expiry_data:
            s = it.get("strikePrice")
            if s is None:
                continue
            for side, mp in [("CE", cur_ce), ("PE", cur_pe)]:
                raw = it.get(side, {}).get("openInterest")
                try:
                    mp[s] = int(raw) if raw not in (None, "-") else None
                except (ValueError, TypeError):
                    mp[s] = None

        first      = not self.prev_ce_oi
        ts_changed = nse_ts not in ("N/A", None) and nse_ts != self.last_nse_ts
        oi_changed = (not first and (
            any(cur_ce.get(s) != self.prev_ce_oi.get(s) for s in cur_ce) or
            any(cur_pe.get(s) != self.prev_pe_oi.get(s) for s in cur_pe)
        ))

        if first or ts_changed or oi_changed:
            self.ce_oi_diffs = {
                s: (cur_ce[s] - self.prev_ce_oi[s])
                   if (cur_ce.get(s) is not None and self.prev_ce_oi.get(s) is not None)
                   else None
                for s in cur_ce
            }
            self.pe_oi_diffs = {
                s: (cur_pe[s] - self.prev_pe_oi[s])
                   if (cur_pe.get(s) is not None and self.prev_pe_oi.get(s) is not None)
                   else None
                for s in cur_pe
            }
            self.prev_ce_oi  = cur_ce
            self.prev_pe_oi  = cur_pe
            self.last_nse_ts = nse_ts

    # ── Countdown bar ─────────────────────────────────────────────────────────

    def _countdown_line(self, remaining, total):
        bar_w  = 22
        filled = max(0, int((total - remaining) / total * bar_w))
        bar    = f"{GREEN}{'█' * filled}{DIM}{'░' * (bar_w - filled)}{RESET}"
        pct    = int((total - remaining) / total * 100)
        return (f"  {DIM}Next refresh in {RESET}{BOLD}{remaining:.1f}s{RESET}  "
                f"[{bar}] {pct:>3}%  "
                f"{DIM}interval: {total:.0f}s  │  source: "
                f"{SOURCE_LABELS.get(self.source_name, self.source_name)}{RESET}")

    # ── Render ────────────────────────────────────────────────────────────────

    def render(self, expiry_data, spot, expiry, all_expiries, timestamp, count):
        if not expiry_data:
            print(f"{RED}No data.{RESET}")
            return

        strikes  = sorted({it["strikePrice"] for it in expiry_data if "strikePrice" in it})
        if not strikes:
            return

        strike_map = {it["strikePrice"]: it for it in expiry_data}
        atm        = min(strikes, key=lambda s: abs(s - spot))
        aidx       = strikes.index(atm)
        lo         = max(0, aidx - self.strikes_count)
        hi         = min(len(strikes), aidx + self.strikes_count + 1)
        disp       = strikes[lo:hi]

        self._update_oi_diffs(expiry_data, timestamp)

        # Total OI
        tot_ce_oi = tot_pe_oi = 0
        for it in expiry_data:
            tot_ce_oi += (it.get("CE", {}).get("openInterest", 0) or 0)
            tot_pe_oi += (it.get("PE", {}).get("openInterest", 0) or 0)

        if self.prev_tot_ce_oi is None:
            self.prev_tot_ce_oi = tot_ce_oi
            self.prev_tot_pe_oi = tot_pe_oi
            self.tot_ce_oi_diff = None
            self.tot_pe_oi_diff = None
        else:
            self.tot_ce_oi_diff = tot_ce_oi - self.prev_tot_ce_oi
            self.tot_pe_oi_diff = tot_pe_oi - self.prev_tot_pe_oi
            self.prev_tot_ce_oi = tot_ce_oi
            self.prev_tot_pe_oi = tot_pe_oi

        # Spot 5-second movement tracking
        if self.initial_spot is None and spot:
            self.initial_spot = spot
        if self.prev_spot is not None and spot:
            self.tick_spot_diff = spot - self.prev_spot
        else:
            self.tick_spot_diff = 0.0
        self.prev_spot = spot

        spot_change = (spot - self.initial_spot) if self.initial_spot else 0.0

        # Analysis
        an = analyse_option_chain(
            expiry_data, spot, self.strikes_count,
            ce_oi_diffs=self.ce_oi_diffs,
            pe_oi_diffs=self.pe_oi_diffs,
            spot_change=spot_change,
            tick_spot_change=self.tick_spot_diff,
            tot_ce_oi_diff=self.tot_ce_oi_diff,
            tot_pe_oi_diff=self.tot_pe_oi_diff,
        )
        if not an:
            return

        self.signal_history.append((
            datetime.now().strftime("%H:%M:%S"), an["signal"], an["score"]
        ))

        pcr       = an["pcr"]
        vcr       = an["vcr"]
        score     = an["score"]
        signal    = an["signal"]
        sig_type  = an["sig_type"]
        sig_col   = an["sig_col"]
        diff_map  = {s: d for s, d in an["oi_diff_rows"]}

        trend_info         = an.get("trend_info", {})
        session_cfg        = BUILDUP_CONFIG.get(trend_info.get("session_tag"), BUILDUP_CONFIG["NEUTRAL"])
        tick_cfg           = BUILDUP_CONFIG.get(trend_info.get("tick_tag"),    BUILDUP_CONFIG["NEUTRAL"])
        ce_cnt             = trend_info.get("ce_cnt", {})
        pe_cnt             = trend_info.get("pe_cnt", {})
        strike_buildup_map = an.get("strike_buildup", {})

        sent = (f"{GREEN}BULLISH ↑{RESET}" if pcr >= 1.2 else
                f"{RED}BEARISH ↓{RESET}"   if pcr <= 0.8 else
                f"{YELLOW}NEUTRAL ↔{RESET}")

        W       = 171
        CE_W    = 74
        PE_W    = 74
        now_str = datetime.now().strftime("%H:%M:%S")
        src_lbl = SOURCE_LABELS.get(self.source_name, self.source_name)

        sys.stdout.write("\033[H\033[J")

        # ── Title bar ─────────────────────────────────────────────────────────
        print(f"{CYAN}{BOLD}{'═' * W}{RESET}")
        print(
            f"  {BOLD}{CYAN}{self.symbol}{RESET}  │"
            f"  Spot: {YELLOW}{BOLD}{spot:,.2f}{RESET}  │"
            f"  5s Δ: {self.clr_chg(self.tick_spot_diff, 7)}  │"
            f"  Expiry: {CYAN}{expiry}{RESET}  │"
            f"  Data: {src_lbl}  │"
            f"  NSE TS: {DIM}{timestamp}{RESET}  │"
            f"  Local: {now_str}  │  #{count}"
        )

        # ── Market Trend Buildup Banner (Refreshes every 5 seconds) ────────────
        print(f"{CYAN}{'─' * W}{RESET}")
        print(
            f"  {BOLD}◈ CURRENT MARKET TREND:{RESET}  {session_cfg['badge']}  "
            f"{BOLD}{session_cfg['sentiment']}{RESET}  "
            f"│  {BOLD}5s Live Tick:{RESET} {tick_cfg['badge']}  "
            f"{DIM}({trend_info.get('tick_reason', '-')}){RESET}"
        )
        print(
            f"    {BOLD}Trend Drivers:{RESET} {DIM}{trend_info.get('session_reason', '-')}{RESET}  │  "
            f"{BOLD}Near Strikes:{RESET} "
            f"Calls: {GREEN}{ce_cnt.get('LB', 0)} LB{RESET}  {RED}{ce_cnt.get('SB', 0)} SB{RESET}  "
            f"{CYAN}{ce_cnt.get('SC', 0)} SC{RESET}  {MAGENTA}{ce_cnt.get('LU', 0)} LU{RESET}  │  "
            f"Puts: {GREEN}{pe_cnt.get('SB', 0)} SB(Wr){RESET}  {RED}{pe_cnt.get('LB', 0)} LB{RESET}  "
            f"{MAGENTA}{pe_cnt.get('LU', 0)} LU{RESET}  {CYAN}{pe_cnt.get('SC', 0)} SC{RESET}"
        )

        # ── Signal banner ─────────────────────────────────────────────────────
        print(f"{CYAN}{'─' * W}{RESET}")
        sb = (f"{GREEN}{'▮' * max(0, score)}{RESET}" if score > 0 else
              f"{RED}{'▮' * max(0, -score)}{RESET}")
        print(
            f"  {BOLD}◈ SIGNAL:{RESET}  {sig_col} {signal:<22}{RESET}"
            f"  │  {BOLD}Trade:{RESET} {sig_col}{sig_type}{RESET}"
            f"  │  {BOLD}Score:{RESET} {BOLD}{score:+d}{RESET} {sb}"
            f"  │  {BOLD}PCR:{RESET} {pcr:.2f} ({sent})"
            f"  │  {BOLD}VCR:{RESET} {vcr:.2f}"
            f"  │  {BOLD}MaxPain:{RESET} {MAGENTA}{an['max_pain']:,.0f}{RESET}"
        )

        # ── OI Summary ────────────────────────────────────────────────────────
        print(f"{CYAN}{'─' * W}{RESET}")
        print(
            f"  {BOLD}Total OI:{RESET}"
            f"  CE: {tot_ce_oi:>12,}  Δ {self.clr_chg(self.tot_ce_oi_diff, 9)}"
            f"   │   PE: {tot_pe_oi:>12,}  Δ {self.clr_chg(self.tot_pe_oi_diff, 9)}"
            f"   │   {BOLD}ATM OI Diff (PE−CE):{RESET}"
            f" {self.clr_diff(an['atm_oi_diff'], 12)}"
            f"  {'← support' if an['atm_oi_diff'] > 0 else ('← resistance' if an['atm_oi_diff'] < 0 else '')}"
        )
        print(
            f"  {BOLD}Vol & ChgOI:{RESET}"
            f"  CE Vol: {an['tot_ce_vol']:>10,}  PE Vol: {an['tot_pe_vol']:>10,}"
            f"   │  CE Chg OI: {self.clr_chg(an['tot_ce_chg'], 10)}"
            f"   PE Chg OI: {self.clr_chg(an['tot_pe_chg'], 10)}"
            f"   │  Tick ΔCE: {self.clr_chg(an['tick_ce'], 8)}"
            f"  Tick ΔPE: {self.clr_chg(an['tick_pe'], 8)}"
        )

        # ── Signal History ────────────────────────────────────────────────────
        print(f"{CYAN}{'─' * W}{RESET}")
        parts = []
        for ts, sig, sc in self.signal_history:
            col = GREEN if sc > 0 else (RED if sc < 0 else YELLOW)
            parts.append(f"{DIM}{ts}{RESET} {col}{sig}{RESET}({sc:+d})")
        print(f"  {BOLD}History:{RESET}  {'  →  '.join(parts) if parts else '–'}")

        # ── Table with Buildup Trend Columns ──────────────────────────────────
        print(f"{CYAN}{'═' * W}{RESET}")
        print(
            f"{BOLD}"
            f"{'CALLS (CE)':^{CE_W}}│{'STRIKE':^9}│{'OI DIFF':^11}│{'PUTS (PE)':^{PE_W}}\n"
            f"{'OI Δ(5s)':>9} {'OI':>10} {'Chg OI':>10} {'Volume':>10} {'IV':>6} {'LTP':>8} {'Change':>8} {'Trend':^6}│"
            f"{'PRICE':^9}│{'PE−CE':^11}│"
            f"{'Trend':^6} {'Change':>8} {'LTP':>8} {'IV':>6} {'Volume':>10} {'Chg OI':>10} {'OI':>10} {'OI Δ(5s)':>9}"
            f"{RESET}"
        )
        print(f"{'─' * CE_W}┼{'─' * 9}┼{'─' * 11}┼{'─' * PE_W}")

        for strike in disp:
            it  = strike_map.get(strike, {})
            ce  = it.get("CE", {})
            pe  = it.get("PE", {})

            ce_tick  = self.clr_diff(self.ce_oi_diffs.get(strike), 9)
            ce_oi_s  = self.fmt(ce.get("openInterest"))
            ce_coi   = self.clr_chg(ce.get("changeinOpenInterest"), 10)
            ce_vol   = self.fmt(ce.get("totalTradedVolume"))
            ce_iv    = self.fmt(ce.get("impliedVolatility"), True, 1)
            ce_ltp   = self.fmt(ce.get("lastPrice"),         True, 2)
            ce_chg   = self.clr_chg(ce.get("change"), 8)

            ce_b = strike_buildup_map.get(strike, {}).get("CE", ("NEUTRAL", "--", DIM))
            ce_trend_tag = self.fmt_buildup(ce_b[1], ce_b[2], 6)

            pe_b = strike_buildup_map.get(strike, {}).get("PE", ("NEUTRAL", "--", DIM))
            pe_trend_tag = self.fmt_buildup(pe_b[1], pe_b[2], 6)

            pe_chg   = self.clr_chg(pe.get("change"), 8)
            pe_ltp   = self.fmt(pe.get("lastPrice"),         True, 2)
            pe_iv    = self.fmt(pe.get("impliedVolatility"), True, 1)
            pe_vol   = self.fmt(pe.get("totalTradedVolume"))
            pe_coi   = self.clr_chg(pe.get("changeinOpenInterest"), 10)
            pe_oi_s  = self.fmt(pe.get("openInterest"))
            pe_tick  = self.clr_diff(self.pe_oi_diffs.get(strike), 9)

            oi_diffs = self.clr_diff(diff_map.get(strike), 11)

            if strike == atm:
                sk = f"{BG_YELLOW_BLACK}{strike:^9.1f}{RESET}"
            else:
                sk = f"{strike:^9.1f}"

            print(
                f"{ce_tick} {ce_oi_s:>10} {ce_coi} {ce_vol:>10}"
                f" {ce_iv:>6} {ce_ltp:>8} {ce_chg} {ce_trend_tag}│"
                f"{sk}│{oi_diffs}│"
                f"{pe_trend_tag} {pe_chg} {pe_ltp:>8} {pe_iv:>6} {pe_vol:>10}"
                f" {pe_coi} {pe_oi_s:>10} {pe_tick}"
            )

        print(f"{'─' * CE_W}┼{'─' * 9}┼{'─' * 11}┼{'─' * PE_W}")
        print(
            f"  {BOLD}BUILDUP KEY:{RESET}  "
            f"{GREEN}[LB] Long Buildup (Price▲ OI▲){RESET}   │  "
            f"{RED}[SB] Short Buildup (Price▼ OI▲){RESET}   │  "
            f"{CYAN}[SC] Short Covering (Price▲ OI▼){RESET}   │  "
            f"{MAGENTA}[LU] Long Unwinding (Price▼ OI▼){RESET}"
        )

        # ── Factor breakdown ──────────────────────────────────────────────────
        print(f"\n{CYAN}{BOLD}  ◈ SIGNAL FACTOR BREAKDOWN{RESET}"
              f"  (score: {BOLD}{score:+d}{RESET}  →  {sig_col}{signal}{RESET})")
        print(f"  {'─' * 80}")
        for label, val_s, pts, note in an["factors"]:
            col  = GREEN if pts > 0 else (RED if pts < 0 else DIM)
            ptss = f"{col}{pts:+d}{RESET}"
            print(f"  {BOLD}{label:<22}{RESET}  val= {val_s:<16}  pts= {ptss}   {DIM}{note}{RESET}")
        print(f"  {'─' * 80}")
        print(
            f"  {DIM}OI Diff (PE−CE): {GREEN}+ve → PE writers → support{RESET}"
            f"{DIM}  │  {RED}−ve → CE writers → resistance{RESET}"
        )
        print(
            f"  {DIM}Tick Δ = inter-tick 5s OI change  │  Chg OI = NSE session total  │"
            f"  Ctrl+C to exit{RESET}"
        )
        sys.stdout.flush()

    # ── Run loop ──────────────────────────────────────────────────────────────

    def run(self):
        count = 0
        errs  = 0
        print(
            f"\n{CYAN}Starting {BOLD}{self.symbol}{RESET}{CYAN} option chain stream "
            f"via {SOURCE_LABELS.get(self.source_name, self.source_name)}{RESET}"
        )
        print(f"{DIM}Refresh: {self.interval:.0f}s  │  Press Ctrl+C to exit{RESET}\n")

        while True:
            t0 = time.time()
            try:
                expiry_data, spot, expiry, all_expiries, ts = self.adapter.fetch()
                count += 1
                errs   = 0
                self.render(expiry_data, spot, expiry, all_expiries, ts, count)
            except KeyboardInterrupt:
                print(f"\n{YELLOW}Stopped.{RESET}")
                return
            except Exception as exc:
                errs += 1
                msg = str(exc)
                if hasattr(exc, "response") and getattr(exc, "response", None) is not None:
                    try:
                        err_payload = exc.response.json()
                        err_detail = err_payload.get("errors") or err_payload.get("message")
                        if err_detail:
                            msg += f" ({err_detail})"
                    except Exception:
                        pass
                sys.stdout.write(
                    f"\r{RED}[Error {errs}] {msg}. Retrying…{RESET}   "
                )
                sys.stdout.flush()
                if errs > 3:
                    time.sleep(3.0)

            wait = max(0.0, self.interval - (time.time() - t0))
            deadline = time.time() + wait
            try:
                while True:
                    rem = deadline - time.time()
                    if rem <= 0:
                        break
                    sys.stdout.write(f"\r{self._countdown_line(rem, self.interval)}   ")
                    sys.stdout.flush()
                    time.sleep(0.1)
                sys.stdout.write("\r" + " " * 90 + "\r")
                sys.stdout.flush()
            except KeyboardInterrupt:
                print(f"\n{YELLOW}Stopped.{RESET}")
                return


# ─────────────────────────────────────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="NSE Option Chain Streamer — multi-source with OI signal engine",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--source",
        choices=["nse", "upstox", "nsepython"],
        default=None,
        help=(
            "Data source to use:\n"
            "  nse       – NSE Official API (no key needed, may throttle)\n"
            "  upstox    – Upstox REST API  (fast, needs --token or UPSTOX_TOKEN env)\n"
            "  nsepython – nsepython library (pip install nsepython, no key)\n"
            "  [default: interactive menu]"
        ),
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Upstox access token (only needed for --source upstox). "
             "Can also set UPSTOX_TOKEN env var.",
    )
    parser.add_argument("-s", "--symbol",   default=None,
        help="Symbol e.g. NIFTY, BANKNIFTY, RELIANCE")
    parser.add_argument("-i", "--interval", type=float, default=5.0,
        help="Refresh interval in seconds (default: 5)")
    parser.add_argument("-c", "--strikes",  type=int,   default=10,
        help="Strikes above/below ATM (default: 10)")
    parser.add_argument("-e", "--expiry",   default=None,
        help="Specific expiry date (NSE fmt: 08-Sep-2026 | Upstox fmt: 2026-09-08)")

    args = parser.parse_args()

    # ── Source selection ──────────────────────────────────────────────────────
    source = args.source
    if not source:
        source = source_menu()

    # ── Symbol ────────────────────────────────────────────────────────────────
    symbol = args.symbol
    if not symbol:
        try:
            raw    = input(f"\n  Enter Symbol [Enter = NIFTY]: ").strip()
            symbol = raw.upper() if raw else "NIFTY"
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            sys.exit(0)
    else:
        symbol = symbol.upper()

    # ── Build adapter ─────────────────────────────────────────────────────────
    if source == "nse":
        adapter = NSEAdapter(symbol, expiry_date=args.expiry)
        print(f"\n  {CYAN}Using NSE Official API.{RESET}")

    elif source == "upstox":
        token = args.token or prompt_upstox_token()
        if not token:
            print(f"  {YELLOW}Falling back to NSE Official API.{RESET}")
            source  = "nse"
            adapter = NSEAdapter(symbol, expiry_date=args.expiry)
        else:
            adapter = UpstoxAdapter(symbol, access_token=token,
                                    expiry_date=args.expiry)
            print(f"\n  {GREEN}Using Upstox API.{RESET}")

    elif source == "nsepython":
        adapter = NSEPythonAdapter(symbol, expiry_date=args.expiry)
        print(f"\n  {BLUE}Using nsepython.{RESET}")

    else:
        print(f"{RED}Unknown source '{source}'.{RESET}")
        sys.exit(1)

    # ── Launch ────────────────────────────────────────────────────────────────
    streamer = NSEOptionChainLive(
        adapter       = adapter,
        source_name   = source,
        symbol        = symbol,
        strikes_count = args.strikes,
        interval      = args.interval,
    )
    streamer.run()


if __name__ == "__main__":
    main()
