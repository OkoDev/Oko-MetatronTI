import os
import time
import hmac
import hashlib
import asyncio
import aiohttp
from dotenv import load_dotenv

load_dotenv()

async def test_bingx():
    API_KEY = os.getenv('BINGX_API_KEY')
    SECRET_KEY = os.getenv('BINGX_SECRET_KEY')
    url = "https://open-api.bingx.com/openApi/spot/v1/ticker/24hr"
    params = {
        'symbol': 'BTC-USDT',
        'timestamp': int(time.time() * 1000)
    }
    
    query_string = '&'.join([f"{k}={v}" for k, v in params.items()])
    signature = hmac.new(
        SECRET_KEY.encode('utf-8'),
        query_string.encode('utf-8'),
        digestmod=hashlib.sha256
    ).hexdigest()
    
    full_url = f"{url}?{query_string}&signature={signature}"
    
    headers = {
        'X-BX-APIKEY': API_KEY,
        'User-Agent': 'Mozilla/5.0'
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.get(full_url, headers=headers) as response:
            data = await response.json()
            print("Response status:", response.status)
            print("Response data:", data)

if __name__ == "__main__":
    asyncio.run(test_bingx())