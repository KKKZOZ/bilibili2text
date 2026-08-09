import requests

symbol = "TSLA"
url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
}

params = {"interval": "1m", "range": "1d", "prepost": "true"}

response = requests.get(url, params=params, headers=headers)
data = response.json()

print(f"Status Code: {response.status_code}")
print(f"Symbol: {data['chart']['result'][0]['meta']['symbol']}")
print(f"Current Price: ${data['chart']['result'][0]['meta']['regularMarketPrice']:.2f}")

