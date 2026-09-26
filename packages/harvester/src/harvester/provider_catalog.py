"""Provider catalog and outcome contract owned by the Harvester boundary."""
from __future__ import annotations

from typing import Any


_EXTERNAL_MANAGED_PROVIDER_PRIORITIES = frozenset(
    {"external_public", "direct_ofr", "openbb_if_available"}
)


OFFICIAL_SERIES_MAP: dict[str, dict[str, Any]] = {
    "fred": {
        "series": [
            "T10Y2Y", "DFF", "TEDRATE", "BAMLH0A0HYM2", "VIXCLS",
            # Policy and funding rates (SOFR, CP, T-bill, prime, IORB)
            "SOFR", "DCPF3M", "DGS3MO", "DPRIME", "IORB",
            # Credit and funding-path spreads (ICE BofA OAS, Moody's Baa/Aaa)
            "BAMLC0A0CM", "BAMLC0A4CBBB", "DBAA", "DAAA", "BAA10YM",
            # cross-channel benchmarks
            "STLFSI4",
            # NFCI sub-indices
            "NFCIRISK", "NFCICREDIT", "NFCILEVERAGE",
            # Shadow leverage / liquidity (proxy catalog)
            "RRPONTSYD", "WRESBAL", "WTREGEN",
        ],
        "desc": {
            "T10Y2Y": "10-Year Treasury Constant Maturity Minus 2-Year Treasury Constant Maturity",
            "DFF": "Federal Funds Effective Rate",
            "TEDRATE": "TED Spread",
            "BAMLH0A0HYM2": "ICE BofA US High Yield Index Option-Adjusted Spread",
            "VIXCLS": "CBOE Volatility Index: VIX",
            "SOFR": "Secured Overnight Financing Rate",
            "DCPF3M": "3-Month AA Financial Commercial Paper Rate",
            "DGS3MO": "3-Month Treasury Constant Maturity Rate",
            "DPRIME": "Bank Prime Loan Rate",
            "IORB": "Interest Rate on Reserve Balances",
            "BAMLC0A0CM": "ICE BofA US Corporate Index Option-Adjusted Spread",
            "BAMLC0A4CBBB": "ICE BofA BBB US Corporate Index Option-Adjusted Spread",
            "DBAA": "Moody's Seasoned Baa Corporate Bond Yield",
            "DAAA": "Moody's Seasoned Aaa Corporate Bond Yield",
            "BAA10YM": "Moody's Seasoned Baa Corporate Bond Yield Relative to 10-Year Treasury",
            "STLFSI4": "St. Louis Fed Financial Stress Index",
            "NFCIRISK": "Chicago Fed NFCI Risk Subindex",
            "NFCICREDIT": "Chicago Fed NFCI Credit Subindex",
            "NFCILEVERAGE": "Chicago Fed NFCI Leverage Subindex",
            "RRPONTSYD": "Overnight Reverse Repurchase Agreements",
            "WRESBAL": "Reserve Balances with Federal Reserve Banks",
            "WTREGEN": "Treasury General Account balance",
        },
    },
    "h41": {
        "series": ["discount_window", "primary_credit", "btfp"],
        "desc": {
            "discount_window": "Discount Window Borrowing (direct H.4.1 DDP CSV; FRED fallback available)",
            "primary_credit": "Primary Credit (direct H.4.1 DDP CSV; FRED fallback available)",
            "btfp": "Bank Term Funding Program (direct H.4.1 DDP CSV; observed_zero post-expiry)",
        },
    },
    "treasury": {
        "series": [
            "debt_to_penny:tot_pub_debt_out_amt",
            "daily_treasury_statement:open_today_bal",
        ],
        "desc": {
            "debt_to_penny:tot_pub_debt_out_amt": "Total Public Debt Outstanding",
            "daily_treasury_statement:open_today_bal": "Opening Balance Today",
        },
    },
    "sec": {
        "series": ["0000072971"],
        "desc": {
            "0000072971": (
                "Issuer filing pulse — daily EDGAR filing count for CIK 0000072971. "
                "This is a filing_count proxy (coarse), NOT a credit-stress or "
                "risk-exposure metric.  Intended as a first-round verifiability "
                "pulse for downstream shadow-pressure interpretation."
            ),
        },
    },
    "openbb_fred": {
        "series": [
            "NFCI", "VIXCLS", "BAMLH0A0HYM2", "STLFSI4", "SOFR", "IORB",
            "DCPF3M", "DGS3MO", "DPRIME",
            "BAMLC0A0CM", "BAMLC0A4CBBB", "DBAA", "DAAA", "BAA10YM",
            "NFCIRISK", "NFCICREDIT", "NFCILEVERAGE",
        ],
        "desc": {
            "NFCI": "Chicago Fed National Financial Conditions Index via OpenBB/FRED.",
            "VIXCLS": "CBOE Volatility Index via OpenBB/FRED.",
            "BAMLH0A0HYM2": "ICE BofA US High Yield OAS via OpenBB/FRED.",
            "STLFSI4": "St. Louis Fed Financial Stress Index via OpenBB/FRED.",
            "SOFR": "Secured Overnight Financing Rate via OpenBB/FRED.",
            "IORB": "Interest on Reserve Balances via OpenBB/FRED.",
            "DCPF3M": "3-Month AA Financial Commercial Paper Rate via OpenBB/FRED.",
            "DGS3MO": "3-Month Treasury Constant Maturity Rate via OpenBB/FRED.",
            "DPRIME": "Bank Prime Loan Rate via OpenBB/FRED.",
            "BAMLC0A0CM": "ICE BofA US Corporate Index OAS via OpenBB/FRED.",
            "BAMLC0A4CBBB": "ICE BofA BBB US Corporate Index OAS via OpenBB/FRED.",
            "DBAA": "Moody's Baa Corporate Bond Yield via OpenBB/FRED.",
            "DAAA": "Moody's Aaa Corporate Bond Yield via OpenBB/FRED.",
            "BAA10YM": "Baa-10Y Treasury Spread via OpenBB/FRED.",
            "NFCIRISK": "Chicago Fed NFCI Risk Subindex via OpenBB/FRED.",
            "NFCICREDIT": "Chicago Fed NFCI Credit Subindex via OpenBB/FRED.",
            "NFCILEVERAGE": "Chicago Fed NFCI Leverage Subindex via OpenBB/FRED.",
        },
    },
    "cboe_direct": {
        "series": ["MOVE", "TYVIX", "VXTLT", "VVIX", "SKEW", "VIX9D", "VIX3M", "VIX6M", "SPX"],
        "desc": {
            "MOVE": "Rates-volatility slot backed by current CBOE VXTLT direct CSV.",
            "TYVIX": "CBOE/ICE Interest Rate Volatility Index; historical file currently ends in 2023.",
            "VXTLT": "Cboe 20+ Year Treasury Bond ETF Volatility Index.",
            "VVIX": "CBOE VIX Volatility Index.",
            "SKEW": "CBOE SKEW Index.",
            "VIX9D": "CBOE 9-Day Volatility Index.",
            "VIX3M": "CBOE 3-Month Volatility Index.",
            "VIX6M": "CBOE 6-Month Volatility Index.",
            "SPX": "CBOE S&P 500 Index close.",
        },
    },
    "openbb_tiingo": {
        "series": ["HYG", "LQD", "TLT"],
        "desc": {
            "HYG": "iShares iBoxx High Yield Corporate Bond ETF daily close via OpenBB/Tiingo.",
            "LQD": "iShares iBoxx Investment Grade Corporate Bond ETF daily close via OpenBB/Tiingo.",
            "TLT": "iShares 20+ Year Treasury Bond ETF daily close via OpenBB/Tiingo.",
        },
    },
    "etf_provider_chain": {
        "series": ["SPY", "QQQ", "IWM", "DIA", "HYG", "LQD", "TLT"],
        "desc": {
            "SPY": "SPDR S&P 500 ETF Trust daily close via Tiingo/Massive/yfinance chain.",
            "QQQ": "Invesco QQQ Trust daily close via Tiingo/Massive/yfinance chain.",
            "IWM": "iShares Russell 2000 ETF daily close via Tiingo/Massive/yfinance chain.",
            "DIA": "SPDR Dow Jones Industrial Average ETF daily close via Tiingo/Massive/yfinance chain.",
            "HYG": "iShares iBoxx High Yield Corporate Bond ETF daily close via Tiingo/Massive/yfinance chain.",
            "LQD": "iShares iBoxx Investment Grade Corporate Bond ETF daily close via Tiingo/Massive/yfinance chain.",
            "TLT": "iShares 20+ Year Treasury Bond ETF daily close via Tiingo/Massive/yfinance chain.",
        },
    },
    "openbb_yfinance": {
        "series": ["SPY", "QQQ", "IWM", "DIA", "^SKEW", "^VVIX"],
        "desc": {
            "SPY": "SPDR S&P 500 ETF Trust daily close via OpenBB/yfinance.",
            "QQQ": "Invesco QQQ Trust (Nasdaq-100) daily close via OpenBB/yfinance.",
            "IWM": "iShares Russell 2000 ETF daily close via OpenBB/yfinance.",
            "DIA": "SPDR Dow Jones Industrial Average ETF daily close via OpenBB/yfinance.",
            "^SKEW": "CBOE SKEW Index — tail risk pricing in S&P 500 options. K channel proxy.",
            "^VVIX": "CBOE VVIX — volatility of VIX (vol-of-vol). K channel proxy.",
        },
    },
}

DEFAULT_OFFICIAL_PROVIDERS = [
    "fred",
    "h41",
    "treasury",
    "sec",
    "openbb_fred",
    "cboe_direct",
    "openbb_tiingo",
    "openbb_yfinance",
    "etf_provider_chain",
]

OFFICIAL_PROVIDER_OUTCOME_STATUSES = {
    "refreshed",
    "reused_same_content",
    "reused_after_provider_failure",
    "partial_provider_success",
    "provider_failed_no_acceptable_fallback",
    "no_release_expected",
    "environmentally_blocked",
}

__all__ = [
    "DEFAULT_OFFICIAL_PROVIDERS",
    "OFFICIAL_PROVIDER_OUTCOME_STATUSES",
    "OFFICIAL_SERIES_MAP",
]
