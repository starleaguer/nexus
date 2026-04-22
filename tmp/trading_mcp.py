from fastmcp import FastMCP
import kis_v2
import make_korea_db
import FinanceDataReader as fdr
import json
import datetime
import pandas as pd

# Initialize FastMCP server
mcp = FastMCP("Trading Analyzer")

@mcp.tool()
def search_stock_code(name: str) -> str:
    """Search for a Korean stock ticker code by its name (e.g., '삼성전자')."""
    return make_korea_db.get_code_name(name)

@mcp.tool()
def get_current_price(code: str) -> str:
    """Get the current price, 52-week high/low for a given stock code."""
    now = datetime.datetime.now()
    try:
        # Get data for the last 10 days to ensure we have the latest closing price
        df = fdr.DataReader(code, (now - datetime.timedelta(days=10)).strftime('%Y%m%d'))
        if df.empty:
            return f"No data found for code {code}"
        last = df.iloc[-1]
        
        # Get 52-week data
        df_year = fdr.DataReader(code, (now - datetime.timedelta(days=365)).strftime('%Y%m%d'))
        high_52 = df_year['High'].max()
        low_52 = df_year['Low'].min()
        
        res = {
            "code": code,
            "current_price": int(last['Close']),
            "change_percent": round((last['Close'] - df.iloc[-2]['Close']) / df.iloc[-2]['Close'] * 100, 2) if len(df) > 1 else 0,
            "high": int(last['High']),
            "low": int(last['Low']),
            "volume": int(last['Volume']),
            "high_52w": int(high_52),
            "low_52w": int(low_52)
        }
        return json.dumps(res, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def analyze_stock(name_or_code: str) -> str:
    """Perform annual performance analysis and show a trendline chart for a stock.
    This will open a Matplotlib chart window on the local machine.
    """
    try:
        # single_annual returns [True, result_data] or [False]
        result = kis_v2.single_annual(name_or_code)
        if result[0]:
            return f"Analysis complete for {name_or_code}.\nResult: {json.dumps(result[1], ensure_ascii=False, indent=2)}"
        else:
            return f"Analysis failed for {name_or_code}. Could not retrieve enough data or no significant trend found."
    except Exception as e:
        return f"Error during analysis: {str(e)}"

@mcp.tool()
def get_financial_summary(code: str) -> str:
    """Get a snapshot of financial metrics (PER, PBR, ROE, etc.) for a stock code."""
    try:
        data = make_korea_db.snapshot(code)
        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"Error fetching financial summary: {str(e)}"

@mcp.tool()
def get_business_headline(code: str) -> str:
    """Get the business summary headline (bizSummary) for a stock code."""
    try:
        headline = kis_v2.get_stock_headline(code)
        if headline:
            return headline
        return "No business summary available."
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
def refresh_stock_db(code: str) -> str:
    """Update the local SQLite database (korea_stock.db) with the latest financial and investment data for a stock code."""
    try:
        make_korea_db.save_year_data(code)
        make_korea_db.save_tooja_data(code)
        return f"Database updated successfully for {code}."
    except Exception as e:
        return f"Failed to update database for {code}: {str(e)}"

if __name__ == "__main__":
    mcp.run()
