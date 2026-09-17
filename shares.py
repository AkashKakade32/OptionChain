#!/usr/bin/env python3
"""
NSE Option Chain Live Terminal Streamer
Fetches live Option Chain data from NSE India and continuously displays it on the terminal.
URL: https://www.nseindia.com/option-chain
"""

import os
import sys
import time
import argparse
from datetime import datetime
from urllib.parse import urlparse, parse_qs
import requests

# ANSI Color Codes for formatting terminal output
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BLUE = "\033[94m"
BG_YELLOW_BLACK = "\033[43;30m"

INDICES = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50"}


class NSEOptionChainLive:
    BASE_URL = "https://www.nseindia.com"
    OPTION_CHAIN_PAGE = "https://www.nseindia.com/option-chain"

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
    }

    API_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/option-chain",
        "Connection": "keep-alive",
    }

    def __init__(self, symbol="NIFTY", strikes_count=10, expiry_date=None, interval=5.0):
        self.symbol = self.clean_symbol(symbol)
        self.strikes_count = strikes_count
        self.expiry_date = expiry_date
        self.interval = interval
        self.session = None
        self.init_session()
        self.prev_ce_oi = {}
        self.latest_ce_oi = {}
        self.ce_oi_diffs = {}
        self.prev_pe_oi = {}
        self.latest_pe_oi = {}
        self.pe_oi_diffs = {}
        self.last_nse_timestamp = None
        self.prev_tot_ce_oi = None
        self.tot_ce_oi_diff = None
        self.prev_tot_pe_oi = None
        self.tot_pe_oi_diff = None

    @staticmethod
    def clean_symbol(input_val):
        """Extract symbol whether user passed a URL or symbol name."""
        input_val = input_val.strip()
        if "nseindia.com" in input_val:
            parsed = urlparse(input_val)
            query_params = parse_qs(parsed.query)
            if "symbol" in query_params:
                return query_params["symbol"][0].upper()
            return "NIFTY"
        return input_val.upper()

    def init_session(self):
        """Initializes requests session and acquires required cookies from NSE."""
        if self.session:
            try:
                self.session.close()
            except Exception:
                pass
        self.session = requests.Session()
        self.session.headers.update(self.HEADERS)
        try:
            self.session.get(self.OPTION_CHAIN_PAGE, timeout=10)
        except Exception:
            try:
                self.session.get(self.BASE_URL, timeout=10)
            except Exception:
                pass

    def get_contract_info(self):
        """Fetches available contract metadata (expiry dates and strike prices)."""
        url = f"https://www.nseindia.com/api/option-chain-contract-info?symbol={self.symbol}"
        for _ in range(2):
            try:
                resp = self.session.get(url, headers=self.API_HEADERS, timeout=8)
                if resp.status_code in (401, 403, 404):
                    self.init_session()
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.RequestException:
                self.init_session()
                time.sleep(0.5)
        resp = self.session.get(url, headers=self.API_HEADERS, timeout=8)
        resp.raise_for_status()
        return resp.json()

    def get_api_url(self, expiry):
        """Builds URL for NSE's active option-chain-v3 API."""
        opt_type = "Indices" if self.symbol in INDICES else "Equity"
        return f"https://www.nseindia.com/api/option-chain-v3?type={opt_type}&symbol={self.symbol}&expiry={expiry}"

    def fetch_data(self):
        """Fetches live option chain data from the active v3 endpoint."""
        contracts = self.get_contract_info()
        all_expiries = contracts.get("expiryDates", [])
        if not all_expiries:
            raise ValueError(f"No active option contracts found for symbol '{self.symbol}'.")

        selected_expiry = self.expiry_date
        if not selected_expiry or selected_expiry not in all_expiries:
            selected_expiry = all_expiries[0]

        url = self.get_api_url(selected_expiry)
        for _ in range(2):
            try:
                resp = self.session.get(url, headers=self.API_HEADERS, timeout=8)
                if resp.status_code in (401, 403, 404):
                    self.init_session()
                    continue
                resp.raise_for_status()
                data = resp.json()
                break
            except requests.exceptions.RequestException:
                self.init_session()
                time.sleep(0.5)
        else:
            resp = self.session.get(url, headers=self.API_HEADERS, timeout=8)
            resp.raise_for_status()
            data = resp.json()

        if "records" in data:
            data["records"]["expiryDates"] = all_expiries
            data["records"]["selectedExpiry"] = selected_expiry

        return data

    @staticmethod
    def format_num(val, is_float=False, decimal_places=2):
        if val is None or val == "-":
            return "-"
        try:
            f = float(val)
            if is_float:
                return f"{f:,.{decimal_places}f}"
            return f"{int(f):,}"
        except (ValueError, TypeError):
            return str(val)

    @staticmethod
    def color_change(val, width=8):
        """Format number with green (+), red (-), or reset."""
        if val is None or val == "-":
            return f"{'-':>{width}}"
        try:
            f = float(val)
            sign_str = f"{f:+,.2f}"
            formatted = f"{sign_str:>{width}}"
            if f > 0:
                return f"{GREEN}{formatted}{RESET}"
            elif f < 0:
                return f"{RED}{formatted}{RESET}"
            else:
                return formatted
        except (ValueError, TypeError):
            return f"{str(val):>{width}}"

    @staticmethod
    def color_diff(val, width=8):
        """Format integer OI difference with green (+), red (-), or reset."""
        dash = "-"
        if val is None or val == "-":
            return f"{dash:>{width}}" if width > 0 else dash
        try:
            f = float(val)
            if width > 0:
                if f > 0:
                    sign_str = f"{int(f):+,}"
                    return f"{GREEN}{sign_str:>{width}}{RESET}"
                elif f < 0:
                    sign_str = f"{int(f):+,}"
                    return f"{RED}{sign_str:>{width}}{RESET}"
                else:
                    zero = "0"
                    return f"{zero:>{width}}"
            else:
                if f > 0:
                    return f"{GREEN}+{int(f):,}{RESET}"
                elif f < 0:
                    return f"{RED}{int(f):,}{RESET}"
                else:
                    return "0"
        except (ValueError, TypeError):
            return f"{str(val):>{width}}" if width > 0 else str(val)

    def render(self, data, refresh_count):
        """Renders the clean option chain table on terminal."""
        records = data.get("records", {})
        all_data = records.get("data", [])
        spot_price = records.get("underlyingValue", 0.0)
        nse_timestamp = records.get("timestamp", "N/A")
        all_expiries = records.get("expiryDates", [])
        current_expiry = records.get("selectedExpiry", (all_expiries[0] if all_expiries else "N/A"))

        if not all_data:
            print(f"{RED}No option chain data available for {self.symbol}.{RESET}")
            return

        expiry_data = [
            item for item in all_data
            if item.get("expiryDates") == current_expiry or item.get("expiryDate") == current_expiry or ("expiryDate" not in item and "expiryDates" not in item)
        ]
        if not expiry_data:
            expiry_data = all_data

        strikes = sorted(list({item["strikePrice"] for item in expiry_data if "strikePrice" in item}))
        if not strikes:
            print(f"{YELLOW}No strikes found for expiry date {current_expiry}.{RESET}")
            return

        strike_map = {item["strikePrice"]: item for item in expiry_data}

        # Find ATM Strike (closest strike to underlying spot price)
        atm_strike = min(strikes, key=lambda s: abs(s - spot_price))
        atm_idx = strikes.index(atm_strike)

        # Slice strikes around ATM
        start_idx = max(0, atm_idx - self.strikes_count)
        end_idx = min(len(strikes), atm_idx + self.strikes_count + 1)
        display_strikes = strikes[start_idx:end_idx]

        # Extract current CE and PE OI mappings for all strikes
        current_ce_map = {}
        current_pe_map = {}
        for item in expiry_data:
            strike = item.get("strikePrice")
            if strike is None:
                continue
            ce = item.get("CE", {})
            pe = item.get("PE", {})
            raw_ce_oi = ce.get("openInterest")
            raw_pe_oi = pe.get("openInterest")

            if raw_ce_oi is not None and raw_ce_oi != "-":
                try:
                    current_ce_map[strike] = int(raw_ce_oi)
                except (ValueError, TypeError):
                    current_ce_map[strike] = None
            else:
                current_ce_map[strike] = None

            if raw_pe_oi is not None and raw_pe_oi != "-":
                try:
                    current_pe_map[strike] = int(raw_pe_oi)
                except (ValueError, TypeError):
                    current_pe_map[strike] = None
            else:
                current_pe_map[strike] = None

        # Determine if data has updated (first load, timestamp changed, or values changed)
        is_first_load = not self.latest_ce_oi and not self.latest_pe_oi
        has_timestamp_changed = (
            nse_timestamp != "N/A"
            and self.last_nse_timestamp is not None
            and nse_timestamp != self.last_nse_timestamp
        )
        has_oi_changed = (
            not is_first_load
            and (
                any(current_ce_map.get(s) != self.latest_ce_oi.get(s) for s in current_ce_map)
                or any(current_pe_map.get(s) != self.latest_pe_oi.get(s) for s in current_pe_map)
            )
        )

        if is_first_load:
            self.latest_ce_oi = current_ce_map.copy()
            self.prev_ce_oi = current_ce_map.copy()
            self.ce_oi_diffs = {s: None for s in current_ce_map}

            self.latest_pe_oi = current_pe_map.copy()
            self.prev_pe_oi = current_pe_map.copy()
            self.pe_oi_diffs = {s: None for s in current_pe_map}

            self.last_nse_timestamp = nse_timestamp
        elif has_timestamp_changed or has_oi_changed:
            new_ce_diffs = {}
            for s, curr_oi in current_ce_map.items():
                prev_oi = self.latest_ce_oi.get(s)
                if curr_oi is not None and prev_oi is not None:
                    new_ce_diffs[s] = curr_oi - prev_oi
                else:
                    new_ce_diffs[s] = None
            self.ce_oi_diffs = new_ce_diffs
            self.prev_ce_oi = self.latest_ce_oi.copy()
            self.latest_ce_oi = current_ce_map.copy()

            new_pe_diffs = {}
            for s, curr_oi in current_pe_map.items():
                prev_oi = self.latest_pe_oi.get(s)
                if curr_oi is not None and prev_oi is not None:
                    new_pe_diffs[s] = curr_oi - prev_oi
                else:
                    new_pe_diffs[s] = None
            self.pe_oi_diffs = new_pe_diffs
            self.prev_pe_oi = self.latest_pe_oi.copy()
            self.latest_pe_oi = current_pe_map.copy()

            self.last_nse_timestamp = nse_timestamp

        # Compute Total Call / Put OI and Sentiment PCR
        tot_ce_oi = 0
        tot_pe_oi = 0
        for item in expiry_data:
            ce = item.get("CE", {})
            pe = item.get("PE", {})
            tot_ce_oi += (ce.get("openInterest", 0) or 0)
            tot_pe_oi += (pe.get("openInterest", 0) or 0)

        if is_first_load:
            self.prev_tot_ce_oi = tot_ce_oi
            self.tot_ce_oi_diff = None
            self.prev_tot_pe_oi = tot_pe_oi
            self.tot_pe_oi_diff = None
        elif has_timestamp_changed or has_oi_changed:
            if self.prev_tot_ce_oi is not None:
                self.tot_ce_oi_diff = tot_ce_oi - self.prev_tot_ce_oi
            else:
                self.tot_ce_oi_diff = None
            self.prev_tot_ce_oi = tot_ce_oi

            if self.prev_tot_pe_oi is not None:
                self.tot_pe_oi_diff = tot_pe_oi - self.prev_tot_pe_oi
            else:
                self.tot_pe_oi_diff = None
            self.prev_tot_pe_oi = tot_pe_oi

        pcr = (tot_pe_oi / tot_ce_oi) if tot_ce_oi > 0 else 0.0
        if pcr >= 1.2:
            sentiment = f"{GREEN}BULLISH (PCR > 1.2){RESET}"
        elif pcr <= 0.8:
            sentiment = f"{RED}BEARISH (PCR < 0.8){RESET}"
        else:
            sentiment = f"{YELLOW}NEUTRAL (0.8 - 1.2){RESET}"

        # Clear terminal smoothly
        sys.stdout.write("\033[H\033[J")

        now_str = datetime.now().strftime("%H:%M:%S")
        call_hdr_left = " OI Diff      OI       Chg OI    Volume       IV       LTP      Change       "
        put_hdr_right = "      Change      LTP       IV       Volume      Chg OI        OI      OI Diff"
        table_width = len(call_hdr_left) + 14 + len(put_hdr_right)

        call_title = "CALLS (CE)".center(len(call_hdr_left))
        strike_title = "STRIKE".center(12)
        put_title = "PUTS (PE)".center(len(put_hdr_right))

        ce_tot_diff_str = ""
        if self.tot_ce_oi_diff is not None:
            ce_tot_diff_str = f" ({self.color_diff(self.tot_ce_oi_diff, width=0)})"

        pe_tot_diff_str = ""
        if self.tot_pe_oi_diff is not None:
            pe_tot_diff_str = f" ({self.color_diff(self.tot_pe_oi_diff, width=0)})"

        print(f"{CYAN}{BOLD}{'=' * table_width}{RESET}")
        print(
            f" {BOLD}{self.symbol}{RESET} | "
            f"Spot: {YELLOW}{BOLD}{spot_price:,.2f}{RESET} | "
            f"Expiry: {CYAN}{current_expiry}{RESET} | "
            f"NSE Time: {DIM}{nse_timestamp}{RESET} | "
            f"Updated: {now_str} (#{refresh_count})"
        )
        print(
            f" PCR: {BOLD}{pcr:.2f}{RESET} ({sentiment}) | "
            f"Total CE OI: {tot_ce_oi:,}{ce_tot_diff_str} | "
            f"Total PE OI: {tot_pe_oi:,}{pe_tot_diff_str} | "
            f"Interval: {self.interval:.1f}s"
        )
        print(f"{CYAN}{'=' * table_width}{RESET}")

        # Table Header
        print(
            f"{BOLD}"
            f"{call_title}|{strike_title}|{put_title}\n"
            f"{call_hdr_left}|   PRICE    |{put_hdr_right}"
            f"{RESET}"
        )
        print(f"{'-' * len(call_hdr_left)}+------------+{'-' * len(put_hdr_right)}")

        # Rows
        for strike in display_strikes:
            item = strike_map.get(strike, {})
            ce = item.get("CE", {})
            pe = item.get("PE", {})

            # CALL values
            ce_diff = self.color_diff(self.ce_oi_diffs.get(strike), width=8)
            ce_oi = self.format_num(ce.get("openInterest"))
            ce_chg_oi = self.color_change(ce.get("changeinOpenInterest"), width=8)
            ce_vol = self.format_num(ce.get("totalTradedVolume"))
            ce_iv = self.format_num(ce.get("impliedVolatility"), is_float=True, decimal_places=1)
            ce_ltp = self.format_num(ce.get("lastPrice"), is_float=True, decimal_places=2)
            ce_chg = self.color_change(ce.get("change"), width=7)

            # PUT values
            pe_chg = self.color_change(pe.get("change"), width=7)
            pe_ltp = self.format_num(pe.get("lastPrice"), is_float=True, decimal_places=2)
            pe_iv = self.format_num(pe.get("impliedVolatility"), is_float=True, decimal_places=1)
            pe_vol = self.format_num(pe.get("totalTradedVolume"))
            pe_chg_oi = self.color_change(pe.get("changeinOpenInterest"), width=8)
            pe_oi = self.format_num(pe.get("openInterest"))
            pe_diff = self.color_diff(self.pe_oi_diffs.get(strike), width=8)

            is_atm = (strike == atm_strike)

            if is_atm:
                strike_display = f"{BG_YELLOW_BLACK}{strike:^10.1f}{RESET}"
                flag = f"{YELLOW}>>{RESET}"
            else:
                strike_display = f"{strike:^10.1f}"
                flag = "  "

            row_str = (
                f"{ce_diff}   {ce_oi:>8}   {ce_chg_oi}   {ce_vol:>9}   {ce_iv:>6}   {ce_ltp:>7}   {ce_chg}   {flag}|"
                f"  {strike_display}|"
                f"    {pe_chg}   {pe_ltp:>7}    {pe_iv:>6}    {pe_vol:>9}   {pe_chg_oi}   {pe_oi:>8}   {pe_diff}"
            )
            print(row_str)

        print(f"{'-' * len(call_hdr_left)}+------------+{'-' * len(put_hdr_right)}")
        print(
            f"{DIM}Note: NSE may throttle if rate limits are exceeded. "
            f"Press Ctrl+C to exit.{RESET}"
        )
        sys.stdout.flush()

    def run(self):
        """Continuous live update loop."""
        refresh_count = 0
        consecutive_errors = 0
        print(f"{CYAN}Connecting to NSE India for {self.symbol} option chain...{RESET}")
        while True:
            start_time = time.time()
            try:
                data = self.fetch_data()
                refresh_count += 1
                consecutive_errors = 0
                self.render(data, refresh_count)
            except KeyboardInterrupt:
                print(f"\n{YELLOW}Stopped option chain stream.{RESET}")
                break
            except Exception as e:
                consecutive_errors += 1
                print(f"\r{RED}[Error {consecutive_errors}] Failed to fetch from NSE: {e}. Retrying...{RESET}", end="")
                sys.stdout.flush()
                if consecutive_errors > 2:
                    time.sleep(2.0)

            elapsed = time.time() - start_time
            sleep_time = max(0.0, self.interval - elapsed)
            try:
                time.sleep(sleep_time)
            except KeyboardInterrupt:
                print(f"\n{YELLOW}Stopped option chain stream.{RESET}")
                break


def main():
    parser = argparse.ArgumentParser(description="Live NSE Option Chain Terminal Streamer")
    parser.add_argument(
        "-s", "--symbol",
        default=None,
        help="Index/Stock symbol or NSE Option Chain URL (e.g. NIFTY, BANKNIFTY, RELIANCE, or https://www.nseindia.com/option-chain)",
    )
    parser.add_argument(
        "-i", "--interval",
        type=float,
        default=5.0,
        help="Refresh interval in seconds (default: 5.0)",
    )
    parser.add_argument(
        "-c", "--strikes",
        type=int,
        default=10,
        help="Number of strikes to show above and below ATM strike (default: 10)",
    )
    parser.add_argument(
        "-e", "--expiry",
        default=None,
        help="Specific expiry date string as returned by NSE (e.g. 08-Sep-2026)",
    )

    args = parser.parse_args()

    symbol = args.symbol
    if not symbol:
        try:
            user_input = input("Enter Symbol or NSE Option Chain URL [Press Enter for 'NIFTY']: ").strip()
            symbol = user_input if user_input else "NIFTY"
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            sys.exit(0)

    streamer = NSEOptionChainLive(
        symbol=symbol,
        strikes_count=args.strikes,
        expiry_date=args.expiry,
        interval=args.interval,
    )
    streamer.run()


if __name__ == "__main__":
    main()
