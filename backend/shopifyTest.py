from app.shopify import ShopifyClient
import json
import os
from dotenv import load_dotenv

load_dotenv()
client = ShopifyClient(
    shop_name=os.getenv("SHOPIFY_SHOP_NAME"),
    access_token=os.getenv("SHOPIFY_ACCESS_TOKEN"),
    api_version=os.getenv("SHOPIFY_API_VERSION"),
)

# Get all products
products = client.get("/products.json", params={"limit": 10})
print(json.dumps(products, indent=2))