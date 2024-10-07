import json
import datetime
import mstarpy
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from scipy.optimize import newton

# Load the JSON file
with open('transaction_detail.json', 'r') as f:
    data = json.load(f)

# Access the 'data' array to fetch transactions
transaction_data = data['data']

# Function to fetch NAV for a single ISIN
def fetch_nav_for_isin(isin):
    try:
        fund = mstarpy.Funds(term=isin, country="in")
        end_date = datetime.datetime.now()
        history = fund.nav(start_date=end_date, end_date=end_date, frequency="daily")
        return isin, history[0]['nav']  # Return ISIN and NAV
    except Exception as e:
        print(f"Error fetching NAV for ISIN {isin}: {e}")
        return isin, 0.0  # Return 0.0 if fetch fails

# Function to fetch NAVs for all ISINs using parallel processing
def fetch_all_navs_parallel(transaction_data):
    isin_list = {transaction['isin'] for item in transaction_data for transaction in item.get('dtTransaction', [])}

    # Fetch NAVs in parallel
    nav_cache = {}
    with ThreadPoolExecutor() as executor:
        futures = [executor.submit(fetch_nav_for_isin, isin) for isin in isin_list]
        for future in as_completed(futures):
            isin, nav = future.result()
            nav_cache[isin] = nav

    return nav_cache

# Fetch all NAVs in parallel
nav_cache = fetch_all_navs_parallel(transaction_data)

# Initialize data structures for portfolio calculation
portfolio = defaultdict(lambda: {"remaining_units": 0, "total_cost": 0})
cash_flows = []
dates = []

# Process transactions for each folio and scheme
for item in transaction_data:
    transactions = item.get('dtTransaction', [])
    
    for transaction in transactions:
        trxn_units = float(transaction['trxnUnits'])
        trxn_amount = float(transaction['trxnAmount'])
        trxn_date = datetime.datetime.strptime(transaction['trxnDate'], "%d-%b-%Y")
        folio = transaction['folio']
        isin = transaction['isin']
        
        # Handle purchase and sale (positive and negative units)
        if trxn_units > 0:  # Purchase
            portfolio[(folio, isin)]['remaining_units'] += trxn_units
            portfolio[(folio, isin)]['total_cost'] += trxn_amount
        elif trxn_units < 0:  # Sale
            sold_units = abs(trxn_units)
            # Apply FIFO: Reduce remaining units and cost accordingly
            if portfolio[(folio, isin)]['remaining_units'] >= sold_units:
                avg_cost = portfolio[(folio, isin)]['total_cost'] / portfolio[(folio, isin)]['remaining_units']
                portfolio[(folio, isin)]['remaining_units'] -= sold_units
                portfolio[(folio, isin)]['total_cost'] -= sold_units * avg_cost

        # Add cash flows and dates for XIRR calculation
        cash_flows.append(-trxn_amount if trxn_units > 0 else trxn_amount)
        dates.append(trxn_date)

# Now calculate the total portfolio value and gains
total_portfolio_value = 0
total_portfolio_gain = 0

for (folio, isin), details in portfolio.items():
    remaining_units = details['remaining_units']
    total_cost = details['total_cost']
    
    # Use cached NAV to avoid redundant network calls
    current_nav = nav_cache.get(isin, 0.0)  # Use 0 if NAV fetch failed
    current_value = remaining_units * current_nav
    
    # Portfolio value and gain
    portfolio_gain = current_value - total_cost
    total_portfolio_value += current_value
    total_portfolio_gain += portfolio_gain
    
    # Add final cash flow and date for XIRR calculation
    cash_flows.append(current_value)
    dates.append(datetime.datetime.now())

# Print results
print(f"Total Portfolio Value: {total_portfolio_value}")
print(f"Total Portfolio Gain: {total_portfolio_gain}")

# XIRR Calculation using scipy's newton method
def xirr(cash_flows, dates):
    # Convert dates to numeric format (number of days since the first transaction)
    days = [(date - dates[0]).days for date in dates]
    
    # Define the XIRR function
    def xirr_func(rate):
        return sum(cf / (1 + rate) ** (day / 365) for cf, day in zip(cash_flows, days))
    
    # Use Newton's method to solve for the XIRR
    return newton(xirr_func, 0.1)

try:
    portfolio_xirr = xirr(cash_flows, dates)
    print(f"Portfolio XIRR: {portfolio_xirr}")
except Exception as e:
    print(f"Error calculating XIRR: {e}")
