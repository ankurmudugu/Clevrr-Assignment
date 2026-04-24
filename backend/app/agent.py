from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
import calendar
import re
from typing import Any
from urllib.parse import parse_qsl

import pandas as pd
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.tools import StructuredTool
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_experimental.tools import PythonAstREPLTool
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field, field_validator, model_validator

from .config import Settings
from .models import AgentPayload, DataTable
from .parser import EMPTY_ANSWER_MESSAGE, coerce_agent_payload
from .shopify import ShopifyClient


SESSION_HISTORY: dict[str, list[BaseMessage]] = defaultdict(list)


class ShopifyToolInput(BaseModel):
    endpoint: str = Field(description="Admin REST endpoint path such as /orders.json")
    params: dict[str, Any] = Field(default_factory=dict, description="Query parameters for the GET request")
    paginate: bool = Field(default=False, description="Fetch all available pages when true")
    limit_pages: int = Field(default=10, ge=1, le=50, description="Maximum pages to fetch when paginating")

    @field_validator("params", mode="before")
    @classmethod
    def normalize_params(cls, value: Any) -> dict[str, Any]:
        if value in (None, "", {}):
            return {}
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return {}
            if text.startswith("{"):
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    return parsed
            return {key: item for key, item in parse_qsl(text, keep_blank_values=True)}
        raise TypeError("params must be a dictionary or querystring.")


class OrdersRangeInput(BaseModel):
    start_date: str | None = Field(default=None, description="Inclusive UTC start datetime in ISO 8601 format, e.g. 2025-01-01T00:00:00Z")
    end_date: str | None = Field(default=None, description="Inclusive UTC end datetime in ISO 8601 format, e.g. 2025-12-31T23:59:59Z")
    fields: str = Field(
        default="id,name,created_at,total_price,financial_status,customer,email,shipping_address,line_items",
        description="Comma-separated Shopify order fields to fetch",
    )
    limit_pages: int = Field(default=10, ge=1, le=50)

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def normalize_dates(cls, value: Any) -> str:
        return _normalize_date_like_field(value)

    @model_validator(mode="before")
    @classmethod
    def unpack_nested_payload(cls, values: Any) -> Any:
        return _unpack_nested_date_payload(values)


class OrdersTableInput(BaseModel):
    start_date: str | None = Field(default=None, description="Inclusive UTC start datetime in ISO 8601 format")
    end_date: str | None = Field(default=None, description="Inclusive UTC end datetime in ISO 8601 format")
    limit: int = Field(default=100, ge=1, le=250, description="Maximum number of orders to return")

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def normalize_dates(cls, value: Any) -> str:
        return _normalize_date_like_field(value)

    @model_validator(mode="before")
    @classmethod
    def unpack_nested_payload(cls, values: Any) -> Any:
        return _unpack_nested_date_payload(values)

    @field_validator("limit", mode="before")
    @classmethod
    def normalize_limit(cls, value: Any) -> int:
        return _normalize_bounded_int(value, default=100, minimum=1, maximum=250)


class CustomerLookupInput(BaseModel):
    customer_name: str = Field(description="Customer full name to fuzzy-match against Shopify customer records")


class RepeatCustomersInput(BaseModel):
    min_orders: int = Field(description="Minimum number of orders a customer must have", ge=1, default=2)

    @field_validator("min_orders", mode="before")
    @classmethod
    def normalize_min_orders(cls, value: Any) -> int:
        if value in (None, "", "{}"):
            return 2
        if isinstance(value, str):
            return int(value.strip())
        return int(value)


class RevenueByCityInput(BaseModel):
    start_date: str | None = Field(default=None, description="Inclusive UTC start datetime in ISO 8601 format")
    end_date: str | None = Field(default=None, description="Inclusive UTC end datetime in ISO 8601 format")
    limit: int = Field(default=20, ge=1, le=100)

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def normalize_dates(cls, value: Any) -> str:
        return _normalize_date_like_field(value)

    @model_validator(mode="before")
    @classmethod
    def unpack_nested_payload(cls, values: Any) -> Any:
        return _unpack_nested_date_payload(values)

    @field_validator("limit", mode="before")
    @classmethod
    def normalize_limit(cls, value: Any) -> int:
        return _normalize_bounded_int(value, default=20, minimum=1, maximum=100)


class AovTrendInput(BaseModel):
    start_date: str | None = Field(default=None, description="Inclusive UTC start datetime in ISO 8601 format")
    end_date: str | None = Field(default=None, description="Inclusive UTC end datetime in ISO 8601 format")

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def normalize_dates(cls, value: Any) -> str:
        return _normalize_date_like_field(value)

    @model_validator(mode="before")
    @classmethod
    def unpack_nested_payload(cls, values: Any) -> Any:
        return _unpack_nested_date_payload(values)


class RecentItemsInput(BaseModel):
    limit: int = Field(default=5, ge=1, le=50, description="Maximum number of recent items to return")

    @field_validator("limit", mode="before")
    @classmethod
    def normalize_limit(cls, value: Any) -> int:
        return _normalize_bounded_int(value, default=5, minimum=1, maximum=50)


class PeriodTextInput(BaseModel):
    period_text: str = Field(description="Natural language time period like 'July 2025', '2025-07', 'last month', or '2025'")


class ProductsSoldInput(BaseModel):
    start_date: str | None = Field(default=None, description="Inclusive UTC start datetime in ISO 8601 format")
    end_date: str | None = Field(default=None, description="Inclusive UTC end datetime in ISO 8601 format")
    limit: int = Field(default=50, ge=1, le=250, description="Maximum sold product rows to return")

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def normalize_dates(cls, value: Any) -> str:
        return _normalize_date_like_field(value)

    @model_validator(mode="before")
    @classmethod
    def unpack_nested_payload(cls, values: Any) -> Any:
        return _unpack_nested_date_payload(values)

    @field_validator("limit", mode="before")
    @classmethod
    def normalize_limit(cls, value: Any) -> int:
        return _normalize_bounded_int(value, default=50, minimum=1, maximum=250)


class TopProductsInput(BaseModel):
    start_date: str | None = Field(default=None, description="Inclusive UTC start datetime in ISO 8601 format")
    end_date: str | None = Field(default=None, description="Inclusive UTC end datetime in ISO 8601 format")
    limit: int = Field(default=10, ge=1, le=50, description="Maximum number of ranked products to return")

    @field_validator("start_date", "end_date", mode="before")
    @classmethod
    def normalize_dates(cls, value: Any) -> str:
        return _normalize_date_like_field(value)

    @model_validator(mode="before")
    @classmethod
    def unpack_nested_payload(cls, values: Any) -> Any:
        return _unpack_nested_date_payload(values)

    @field_validator("limit", mode="before")
    @classmethod
    def normalize_limit(cls, value: Any) -> int:
        return _normalize_bounded_int(value, default=10, minimum=1, maximum=50)


def build_agent(settings: Settings, store_url: str | None = None) -> AgentExecutor:
    shop_name = (store_url or settings.shopify_shop_name).strip()
    if not shop_name:
        raise ValueError("A Shopify store URL is required.")
    if not settings.shopify_access_token:
        raise ValueError("SHOPIFY_ACCESS_TOKEN is missing from the environment.")
    if not settings.gemini_api_key:
        raise ValueError("GEMINI_API_KEY is missing from the environment.")

    today = datetime.now(timezone.utc).date().isoformat()
    client = ShopifyClient(
        shop_name=shop_name,
        access_token=settings.shopify_access_token,
        api_version=settings.shopify_api_version,
    )

    def get_shopify_data(
        endpoint: str, 
        params: dict[str, Any] | None = None,
        paginate: bool = False,
        limit_pages: int = 10,
    ) -> dict[str, Any]:
        if any(token in endpoint.upper() for token in ("POST", "PUT", "DELETE", "PATCH")):
            return {"error": "This operation is not permitted."}
        if not endpoint.endswith(".json"):
            endpoint = f"{endpoint.removesuffix('/')}.json"
        return client.get(endpoint=endpoint, params=params, paginate=paginate, limit_pages=limit_pages)

    def list_orders_in_range(
        start_date: str | None = None,
        end_date: str | None = None,
        fields: str = "id,name,created_at,total_price,financial_status,customer,email,shipping_address,line_items",
        limit_pages: int = 10,
    ) -> dict[str, Any]:
        return {
            "orders": client.list_orders_in_range(
                start=_parse_iso_datetime(start_date or _default_start_date()),
                end=_parse_iso_datetime(end_date or _default_end_date()),
                fields=fields,
                limit_pages=limit_pages,
            )
        }

    def get_orders_table(
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        limit = _coerce_int(limit, default=100)
        orders = client.list_orders_in_range(
            start=_parse_iso_datetime(start_date or _default_start_date()),
            end=_parse_iso_datetime(end_date or _default_end_date()),
            fields="id,name,created_at,total_price,financial_status,fulfillment_status,customer,email",
            limit_pages=10,
        )
        rows = []
        for order in orders[:limit]:
            customer = order.get("customer") or {}
            customer_name = " ".join(
                part for part in [customer.get("first_name"), customer.get("last_name")] if part
            ).strip() or order.get("email") or ""
            rows.append(
                {
                    "order_name": order.get("name", ""),
                    "created_at": order.get("created_at", ""),
                    "customer_name": customer_name,
                    "total_price": round(_safe_float(order.get("total_price")), 2),
                    "financial_status": order.get("financial_status", ""),
                    "fulfillment_status": order.get("fulfillment_status", "") or "unfulfilled",
                }
            )
        return {
            "orders": rows,
            "start_date": start_date or _default_start_date(),
            "end_date": end_date or _default_end_date(),
            "returned_orders": len(rows),
        }

    def list_customers() -> dict[str, Any]:
        return {"customers": client.list_customers()}

    def list_products() -> dict[str, Any]:
        return {"products": client.list_products()}

    def resolve_time_period(period_text: str) -> dict[str, Any]:
        start_date, end_date, label = _resolve_period_text(period_text)
        return {
            "period_text": period_text,
            "label": label,
            "start_date": start_date,
            "end_date": end_date,
        }

    def get_products_sold(start_date: str | None = None, end_date: str | None = None, limit: int = 50) -> dict[str, Any]:
        limit = _coerce_int(limit, default=50)
        orders = client.list_orders_in_range(
            start=_parse_iso_datetime(start_date or _default_start_date()),
            end=_parse_iso_datetime(end_date or _default_end_date()),
            fields="id,name,created_at,line_items",
            limit_pages=10,
        )
        product_totals: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"product_title": "Unknown Product", "quantity": 0, "order_count": 0}
        )
        for order in orders:
            order_products: set[str] = set()
            for line_item in order.get("line_items", []) or []:
                product_title = str(line_item.get("title") or "Unknown Product").strip() or "Unknown Product"
                quantity = int(line_item.get("quantity", 0) or 0)
                product_totals[product_title]["product_title"] = product_title
                product_totals[product_title]["quantity"] += quantity
                order_products.add(product_title)

            for product_title in order_products:
                product_totals[product_title]["order_count"] += 1

        sold_items = sorted(
            product_totals.values(),
            key=lambda item: (-int(item.get("quantity", 0)), -int(item.get("order_count", 0)), str(item.get("product_title", ""))),
        )
        return {"products_sold": sold_items[:limit]}

    def get_top_products_by_sales(
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        limit = _coerce_int(limit, default=10)
        orders = client.list_orders_in_range(
            start=_parse_iso_datetime(start_date or _default_start_date()),
            end=_parse_iso_datetime(end_date or _default_end_date()),
            fields="id,name,created_at,line_items",
            limit_pages=10,
        )

        product_totals: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"product_title": "Unknown Product", "units_sold": 0, "gross_sales": 0.0, "order_count": 0}
        )
        for order in orders:
            order_products: set[str] = set()
            for line_item in order.get("line_items", []) or []:
                product_title = str(line_item.get("title") or "Unknown Product").strip() or "Unknown Product"
                product_id = line_item.get("product_id")
                quantity = int(line_item.get("quantity", 0) or 0)
                unit_price = _safe_float(line_item.get("price"))
                totals = product_totals[product_title]
                totals["product_title"] = product_title
                if product_id not in (None, ""):
                    totals["product_id"] = _coerce_int(product_id, default=0)
                totals["units_sold"] += quantity
                totals["gross_sales"] += quantity * unit_price
                order_products.add(product_title)

            for product_title in order_products:
                product_totals[product_title]["order_count"] += 1

        ranked = sorted(
            product_totals.values(),
            key=lambda item: (
                -int(item["units_sold"]),
                -float(item["gross_sales"]),
                str(item["product_title"]),
            ),
        )
        rows = [
            {
                "product_title": row["product_title"],
                "product_id": int(row.get("product_id", 0) or 0),
                "units_sold": int(row["units_sold"]),
                "gross_sales": round(float(row["gross_sales"]), 2),
                "order_count": int(row["order_count"]),
            }
            for row in ranked[:limit]
        ]
        return {
            "top_products": rows,
            "start_date": start_date or _default_start_date(),
            "end_date": end_date or _default_end_date(),
            "catalog_filter_applied": False,
        }

    def get_promotable_products_by_sales(
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        limit = _coerce_int(limit, default=10)
        top_products_result = get_top_products_by_sales(
            start_date=start_date,
            end_date=end_date,
            limit=max(limit * 5, 25),
        )
        current_products = client.list_products()
        current_product_ids, current_product_titles = _build_current_catalog_indexes(current_products)

        promotable_rows = [
            row
            for row in top_products_result.get("top_products", [])
            if _is_current_catalog_product(
                product_id=row.get("product_id"),
                product_title=str(row.get("product_title") or ""),
                current_product_ids=current_product_ids,
                current_product_titles=current_product_titles,
            )
        ][:limit]

        return {
            "top_products": promotable_rows,
            "start_date": top_products_result.get("start_date", start_date or _default_start_date()),
            "end_date": top_products_result.get("end_date", end_date or _default_end_date()),
            "catalog_filter_applied": True,
            "catalog_products_considered": len(current_product_titles),
        }

    def get_recent_orders(limit: int = 5) -> dict[str, Any]:
        limit = _coerce_int(limit, default=5)
        orders = client.list_recent_orders(
            fields="id,name,created_at,total_price,financial_status,fulfillment_status,customer,email,line_items",
            limit=limit,
        )
        return {"orders": orders}

    def get_recent_products_sold(limit: int = 5) -> dict[str, Any]:
        limit = _coerce_int(limit, default=5)
        orders = client.list_recent_orders(
            fields="id,name,created_at,line_items",
            limit=max(limit * 5, 20),
        )
        sold_items: list[dict[str, Any]] = []
        for order in orders:
            order_id = order.get("id")
            order_name = order.get("name")
            created_at = order.get("created_at")
            for line_item in order.get("line_items", []) or []:
                sold_items.append(
                    {
                        "order_id": order_id,
                        "order_name": order_name,
                        "created_at": created_at,
                        "product_title": line_item.get("title") or "Unknown Product",
                        "quantity": int(line_item.get("quantity", 0) or 0),
                    }
                )
        sold_items.sort(key=lambda item: (str(item.get("created_at", "")), str(item.get("order_id", ""))), reverse=True)
        return {"products_sold": sold_items[:limit]}

    def get_customer_order_count(customer_name: str) -> dict[str, Any]:
        customer = client.find_customer_by_name(customer_name)
        if customer is None:
            return {"matched": False, "customer_name": customer_name}
        full_name = " ".join(
            part for part in [customer.get("first_name"), customer.get("last_name")] if part
        ).strip() or customer_name
        return {
            "matched": True,
            "customer_name": full_name,
            "orders_count": int(customer.get("orders_count", 0) or 0),
            "email": customer.get("email", ""),
            "total_spent": customer.get("total_spent", "0"),
        }

    def customer_exists(customer_name: str) -> dict[str, Any]:
        customer = client.find_customer_by_name(customer_name)
        if customer is None:
            return {"matched": False, "customer_name": customer_name}
        full_name = " ".join(
            part for part in [customer.get("first_name"), customer.get("last_name")] if part
        ).strip() or customer_name
        return {
            "matched": True,
            "customer_name": full_name,
            "orders_count": int(customer.get("orders_count", 0) or 0),
            "email": customer.get("email", ""),
            "total_spent": customer.get("total_spent", "0"),
        }

    def get_customer_orders(customer_name: str) -> dict[str, Any]:
        orders = client.list_orders_for_customer(customer_name)
        return {"customer_name": customer_name, "orders": orders}

    def get_customer_purchases(customer_name: str) -> dict[str, Any]:
        orders = client.list_orders_for_customer(customer_name)
        purchases: list[dict[str, Any]] = []
        for order in orders:
            for line_item in order.get("line_items", []) or []:
                purchases.append(
                    {
                        "order_id": order.get("id"),
                        "order_name": order.get("name"),
                        "created_at": order.get("created_at"),
                        "product_title": line_item.get("title") or "Unknown Product",
                        "quantity": int(line_item.get("quantity", 0) or 0),
                        "total_price": order.get("total_price", ""),
                    }
                )
        return {"customer_name": customer_name, "purchases": purchases}

    def get_repeat_customers(min_orders: int = 2) -> dict[str, Any]:
        min_orders = _coerce_int(min_orders, default=2)
        customers = client.list_customers()
        filtered = [
            customer for customer in customers
            if int(customer.get("orders_count", 0) or 0) >= min_orders
        ]
        filtered.sort(
            key=lambda customer: (
                -int(customer.get("orders_count", 0) or 0),
                f"{customer.get('first_name', '')} {customer.get('last_name', '')}".strip(),
            )
        )
        rows = []
        for customer in filtered:
            full_name = " ".join(
                part for part in [customer.get("first_name"), customer.get("last_name")] if part
            ).strip() or customer.get("email", "") or "Unknown"
            rows.append(
                {
                    "customer_name": full_name,
                    "orders_count": int(customer.get("orders_count", 0) or 0),
                    "email": customer.get("email", ""),
                    "total_spent": customer.get("total_spent", "0"),
                }
            )
        return {"customers": rows, "min_orders": min_orders}

    def get_revenue_by_city(start_date: str | None = None, end_date: str | None = None, limit: int = 20) -> dict[str, Any]:
        orders = client.list_orders_in_range(
            start=_parse_iso_datetime(start_date or _default_start_date()),
            end=_parse_iso_datetime(end_date or _default_end_date()),
            fields="id,total_price,shipping_address",
            limit_pages=10,
        )
        city_totals: dict[str, float] = defaultdict(float)
        for order in orders:
            shipping_address = order.get("shipping_address") or {}
            city = str(shipping_address.get("city") or "").strip()
            if not city:
                continue
            city_totals[city] += _safe_float(order.get("total_price"))
        ranked = sorted(city_totals.items(), key=lambda item: (-item[1], item[0]))
        return {"cities": [{"city": city, "revenue": round(revenue, 2)} for city, revenue in ranked[:limit]]}

    def get_aov_trend(start_date: str | None = None, end_date: str | None = None) -> dict[str, Any]:
        orders = client.list_orders_in_range(
            start=_parse_iso_datetime(start_date or _default_month_start_date()),
            end=_parse_iso_datetime(end_date or _default_end_date()),
            fields="id,created_at,total_price",
            limit_pages=10,
        )
        buckets: dict[str, dict[str, float]] = defaultdict(lambda: {"orders": 0.0, "revenue": 0.0})
        for order in orders:
            created_at = str(order.get("created_at", ""))
            day = created_at[:10]
            if len(day) != 10:
                continue
            buckets[day]["orders"] += 1
            buckets[day]["revenue"] += _safe_float(order.get("total_price"))
        points = []
        for day in sorted(buckets.keys()):
            orders_count = int(buckets[day]["orders"])
            revenue = buckets[day]["revenue"]
            aov = revenue / orders_count if orders_count else 0.0
            points.append({"date": day, "orders": orders_count, "aov": round(aov, 2)})
        return {"points": points}

    tools = [
        StructuredTool.from_function(
            func=get_shopify_data,
            name="get_shopify_data",
            description="Fetch Shopify Admin REST data using GET requests only. Use this for raw endpoint access when a specialized analytics tool is not enough.",
            args_schema=ShopifyToolInput,
        ),
        StructuredTool.from_function(
            func=list_orders_in_range,
            name="list_orders_in_range",
            description="Fetch Shopify orders in a specific UTC date range. Use this for detailed order inspection.",
            args_schema=OrdersRangeInput,
        ),
        StructuredTool.from_function(
            func=get_orders_table,
            name="get_orders_table",
            description="Return orders as table-ready rows with order name, created date, customer, total, and statuses. Use this for requests like 'list all orders', 'show orders', or any order table request.",
            args_schema=OrdersTableInput,
        ),
        StructuredTool.from_function(
            func=list_customers,
            name="list_customers",
            description="Fetch current Shopify customer records including orders_count and total_spent.",
        ),
        StructuredTool.from_function(
            func=list_products,
            name="list_products",
            description="Fetch the current Shopify product catalog.",
        ),
        StructuredTool.from_function(
            func=resolve_time_period,
            name="resolve_time_period",
            description="Resolve natural-language periods like 'July 2025', '2025-07', 'last month', or '2025' into an explicit UTC start_date and end_date. Prefer using this only when the period is ambiguous or relative.",
            args_schema=PeriodTextInput,
        ),
        StructuredTool.from_function(
            func=get_recent_orders,
            name="get_recent_orders",
            description="Fetch the most recent Shopify orders sorted by created_at descending. Use this for 'most recent order' questions.",
            args_schema=RecentItemsInput,
        ),
        StructuredTool.from_function(
            func=get_recent_products_sold,
            name="get_recent_products_sold",
            description="Fetch the most recently sold line items from the latest orders. Use this for questions like 'most recent products sold'.",
            args_schema=RecentItemsInput,
        ),
        StructuredTool.from_function(
            func=get_products_sold,
            name="get_products_sold",
            description="Fetch unique products sold across a resolved date range, aggregated by product title and total quantity sold. Use this after resolve_time_period for queries like 'products sold in July 2025' or 'products sold in 2025-07'.",
            args_schema=ProductsSoldInput,
        ),
        StructuredTool.from_function(
            func=get_top_products_by_sales,
            name="get_top_products_by_sales",
            description="Return a ranked product sales summary across a date range. Use this for best sellers, top products, and product-promotion recommendations based on historical sales.",
            args_schema=TopProductsInput,
        ),
        StructuredTool.from_function(
            func=get_promotable_products_by_sales,
            name="get_promotable_products_by_sales",
            description="Return a ranked product sales summary across a date range, filtered to products that still exist in the current Shopify catalog. Use this for future-looking questions like what products to promote, feature, restock, or recommend.",
            args_schema=TopProductsInput,
        ),
        StructuredTool.from_function(
            func=get_customer_order_count,
            name="get_customer_order_count",
            description="Find a customer by name and return their order count from Shopify customer records.",
            args_schema=CustomerLookupInput,
        ),
        StructuredTool.from_function(
            func=customer_exists,
            name="customer_exists",
            description="Check whether a customer exists in Shopify and return their basic summary if found.",
            args_schema=CustomerLookupInput,
        ),
        StructuredTool.from_function(
            func=get_customer_orders,
            name="get_customer_orders",
            description="Fetch all recent Shopify orders for a customer matched by name.",
            args_schema=CustomerLookupInput,
        ),
        StructuredTool.from_function(
            func=get_customer_purchases,
            name="get_customer_purchases",
            description="Fetch the products purchased by a customer matched by name, based on their Shopify orders.",
            args_schema=CustomerLookupInput,
        ),
        StructuredTool.from_function(
            func=get_repeat_customers,
            name="get_repeat_customers",
            description="Return customers whose orders_count is at least the requested threshold.",
            args_schema=RepeatCustomersInput,
        ),
        StructuredTool.from_function(
            func=get_revenue_by_city,
            name="get_revenue_by_city",
            description="Aggregate order revenue by shipping city across a date range.",
            args_schema=RevenueByCityInput,
        ),
        StructuredTool.from_function(
            func=get_aov_trend,
            name="get_aov_trend",
            description="Compute daily AOV trend across a date range.",
            args_schema=AovTrendInput,
        ),
    ]

    python_tool = PythonAstREPLTool(locals={"pd": pd})
    tools.append(python_tool)

    llm = ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        google_api_key=settings.gemini_api_key,
        temperature=0.1,
        disable_streaming="tool_calling",
    )

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                (
                    "You are a Shopify analytics agent for ecommerce operators. "
                    f"Today's date is {today} UTC. Treat years before {today[:4]} as past dates. "
                    "Shopify data is the source of truth. "
                    "For factual questions about orders, products, customers, revenue, cities, or trends, you must use Shopify tools in the current turn before answering. "
                    "Do not answer factual Shopify questions from memory or prior chat messages alone. "
                    "If prior chat history conflicts with current Shopify tool results, trust the current Shopify tool results. "
                    "Shopify access must go through the provided Shopify tools only. "
                    "Never suggest or perform POST, PUT, DELETE, or PATCH operations. "
                    "If a user asks for a forbidden write operation, answer exactly: This operation is not permitted. "
                    "For relative dates like last year, this year, last month, and recent periods, anchor them to today's date above. "
                    "Treat 'all time', 'all-time', 'overall', and 'entire history' as the store's full available history. "
                    "For questions about 'most recent' orders or products sold, prefer get_recent_orders or get_recent_products_sold instead of inferring a date range yourself. "
                    "For requests to list, show, or tabulate orders, prefer get_orders_table and return the result in the JSON 'table' field instead of plain prose. "
                    "When a user gives an unambiguous natural-language period, convert it yourself into explicit UTC start_date and end_date and pass those dates directly into the relevant Shopify analytics tool. "
                    "Examples of unambiguous periods include 'July 2025' -> 2025-07-01T00:00:00Z through 2025-07-31T23:59:59Z, 'summer of 2025' -> 2025-06-01T00:00:00Z through 2025-08-31T23:59:59Z, 'Q1 2025' -> 2025-01-01T00:00:00Z through 2025-03-31T23:59:59Z, and '2025' -> 2025-01-01T00:00:00Z through 2025-12-31T23:59:59Z. "
                    "Interpret seasons using meteorological seasons in the Northern Hemisphere: spring = Mar 1-May 31, summer = Jun 1-Aug 31, fall/autumn = Sep 1-Nov 30, winter = Dec 1-Feb end. "
                    "Use resolve_time_period only for relative or ambiguous periods such as 'last month', 'this year', 'recently', or when you need deterministic clarification. "
                    "If the user asks a recommendation question like what products to promote based on sales, treat that as an analytical request for the strongest-selling products unless they specify a different business goal. "
                    "When the user replies with only a time period such as 'all time' or 'last month', use chat history to continue the pending analysis instead of asking them to restate the full question. "
                    "For best-selling product analysis, prefer get_top_products_by_sales over raw line-item dumps and treat historical sold line items as valid even if a product is no longer in the current catalog. "
                    "For promotion or recommendation questions about future actions, prefer get_promotable_products_by_sales so recommendations come only from the live Shopify catalog. "
                    "For purely historical questions, use historical sold line items even if a product no longer exists in the current catalog. "
                    "For customer follow-up questions like 'what did he buy', use current-turn customer tools and prior chat only to resolve the referenced customer name, then fetch Shopify data again before answering. "
                    "Prefer the specialized analytics tools over raw get_shopify_data whenever one fits the question. "
                    "For analytical questions, break the problem into steps, possibly calling multiple tools before answering. "
                    "Use PythonAstREPLTool for aggregations, grouping, ranking, or trend analysis. "
                    "When a user explicitly asks to list records, include a concise summary sentence in 'answer' and put the records into 'table'. "
                    "Do not expose internal reasoning to the user, but you may reason step-by-step internally. "
                    "Do not invent numbers. If data is missing, say so clearly. "
                    "Return only valid JSON with this shape: "
                    '{{"answer":"string","insights":["string"],"table":{{"title":"string","columns":["col"],"rows":[["value"]]}},"chart":{{"type":"bar or line","title":"string","xKey":"label","yKey":"value","data":[{{"label":"x","value":1}}]}},"metadata":{{"source":"brief note"}}}}. '
                    "Omit table or chart by setting them to null when unnecessary.\n\n"
                    "Example workflow for an analytical question:\n"
                    "User: Top products last month\n"
                    "Assistant internal plan: resolve_time_period('last month') -> list_orders_in_range(start_date, end_date, fields including line_items) -> PythonAstREPLTool to aggregate and rank products -> final JSON answer.\n"
                    "User: How much revenue was generated in summer of 2025?\n"
                    "Assistant internal plan: infer start_date=2025-06-01T00:00:00Z and end_date=2025-08-31T23:59:59Z -> call the relevant Shopify analytics tool(s) with those explicit dates -> final JSON answer.\n"
                    "Follow that style for similar analytical questions."
                ),
            ),
            MessagesPlaceholder("chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder("agent_scratchpad"),
        ]
    )

    agent = create_tool_calling_agent(llm=llm, tools=tools, prompt=prompt)
    return AgentExecutor(
        agent=agent,
        tools=tools,
        verbose=True,
        handle_parsing_errors=True,
        max_iterations=8,
    )


def run_agent(settings: Settings, session_id: str, message: str, store_url: str | None) -> AgentPayload:
    shop_name = (store_url or settings.shopify_shop_name).strip()
    if not shop_name:
        raise ValueError("A Shopify store URL is required.")
    if not settings.shopify_access_token:
        raise ValueError("SHOPIFY_ACCESS_TOKEN is missing from the environment.")

    history = SESSION_HISTORY[session_id]
    effective_message = _contextualize_followup_message(history=history, message=message)
    deterministic_payload = _build_order_table_payload_if_requested(
        settings=settings,
        store_url=store_url,
        message=effective_message,
    )
    if deterministic_payload is not None:
        history.append(HumanMessage(content=message))
        history.append(AIMessage(content=deterministic_payload.model_dump_json()))
        return deterministic_payload

    executor = build_agent(settings=settings, store_url=store_url)
    output = _invoke_with_recovery(executor=executor, history=history, message=effective_message)
    payload = coerce_agent_payload(output)
    history.append(HumanMessage(content=message))
    history.append(AIMessage(content=output))
    return payload


def _invoke_with_recovery(executor: AgentExecutor, history: list[BaseMessage], message: str) -> str:
    attempts = [
        message,
        (
            f"{message}\n\n"
            "Important: your final response must contain a non-empty 'answer' field with a concise summary sentence. "
            "Do not leave 'answer' blank."
        ),
    ]

    last_output = ""
    for attempt in attempts:
        result = executor.invoke(
            {
                "input": attempt,
                "chat_history": history,
            }
        )
        last_output = str(result.get("output", "") or "")
        payload = coerce_agent_payload(last_output)
        if payload.answer.strip() and payload.answer != EMPTY_ANSWER_MESSAGE:
            return last_output

    return last_output


def _parse_iso_datetime(value: str) -> datetime:
    normalized = value.strip()
    if normalized in ("", "{}"):
        return _parse_iso_datetime(_default_end_date())
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _default_end_date() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _default_start_date() -> str:
    return "2025-01-01T00:00:00Z"


def _default_month_start_date() -> str:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _coerce_int(value: Any, default: int) -> int:
    if value in (None, "", "{}"):
        return default
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    if value in (None, "", "{}"):
        return default
    try:
        normalized = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, normalized))


def _normalize_product_title(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    return re.sub(r"\s+", " ", text)


def _build_current_catalog_indexes(products: list[dict[str, Any]]) -> tuple[set[int], set[str]]:
    current_product_ids: set[int] = set()
    current_product_titles: set[str] = set()

    for product in products:
        product_id = _coerce_int(product.get("id"), default=0)
        if product_id > 0:
            current_product_ids.add(product_id)

        normalized_title = _normalize_product_title(product.get("title"))
        if normalized_title:
            current_product_titles.add(normalized_title)

    return current_product_ids, current_product_titles


def _is_current_catalog_product(
    product_id: Any,
    product_title: str,
    current_product_ids: set[int],
    current_product_titles: set[str],
) -> bool:
    normalized_product_id = _coerce_int(product_id, default=0)
    if normalized_product_id > 0 and normalized_product_id in current_product_ids:
        return True
    return _normalize_product_title(product_title) in current_product_titles


def _normalize_date_like_field(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("start_date", "end_date"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return json.dumps(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return text
        if text.startswith("{"):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    for key in ("start_date", "end_date"):
                        candidate = parsed.get(key)
                        if isinstance(candidate, str) and candidate.strip():
                            return candidate.strip()
            except json.JSONDecodeError:
                pass
        return text
    return str(value)


def _unpack_nested_date_payload(values: Any) -> Any:
    if not isinstance(values, dict):
        return values

    start_value = values.get("start_date")
    if isinstance(start_value, str):
        text = start_value.strip()
        if text.startswith("{"):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    merged = dict(parsed)
                    merged.update({k: v for k, v in values.items() if k not in ("start_date", "end_date")})
                    return merged
            except json.JSONDecodeError:
                pass

    return values


def _resolve_period_text(period_text: str) -> tuple[str, str, str]:
    text = " ".join(period_text.strip().lower().split())
    now = datetime.now(timezone.utc)

    month_names = {
        "january": 1,
        "february": 2,
        "march": 3,
        "april": 4,
        "may": 5,
        "june": 6,
        "july": 7,
        "august": 8,
        "september": 9,
        "october": 10,
        "november": 11,
        "december": 12,
    }

    year_month_match = re.fullmatch(r"(\d{4})-(\d{2})", text)
    if year_month_match:
        year = int(year_month_match.group(1))
        month = int(year_month_match.group(2))
        return _month_range(year, month, f"{year_month_match.group(1)}-{year_month_match.group(2)}")

    month_year_match = re.fullmatch(r"([a-z]+)\s+(\d{4})", text)
    if month_year_match and month_year_match.group(1) in month_names:
        year = int(month_year_match.group(2))
        month = month_names[month_year_match.group(1)]
        return _month_range(year, month, f"{month_year_match.group(1).capitalize()} {year}")

    season_year_match = re.fullmatch(r"(spring|summer|fall|autumn|winter)(?:\s+of)?\s+(\d{4})", text)
    if season_year_match:
        season = season_year_match.group(1)
        year = int(season_year_match.group(2))
        return _season_range(year, season, f"{season} {year}")

    year_match = re.fullmatch(r"\d{4}", text)
    if year_match:
        year = int(text)
        start = f"{year}-01-01T00:00:00Z"
        end = f"{year}-12-31T23:59:59Z"
        return start, end, text

    if text == "this month":
        return _month_range(now.year, now.month, "this month")

    if text == "last month":
        year = now.year
        month = now.month - 1
        if month == 0:
            month = 12
            year -= 1
        return _month_range(year, month, "last month")

    if text == "this year":
        return f"{now.year}-01-01T00:00:00Z", _default_end_date(), "this year"

    if text == "last year":
        year = now.year - 1
        return f"{year}-01-01T00:00:00Z", f"{year}-12-31T23:59:59Z", "last year"

    if text in {"all time", "all-time", "overall", "entire history", "full history"}:
        return "2000-01-01T00:00:00Z", _default_end_date(), "all time"

    return _default_start_date(), _default_end_date(), text


def _month_range(year: int, month: int, label: str) -> tuple[str, str, str]:
    last_day = calendar.monthrange(year, month)[1]
    start = f"{year:04d}-{month:02d}-01T00:00:00Z"
    end = f"{year:04d}-{month:02d}-{last_day:02d}T23:59:59Z"
    return start, end, label


def _season_range(year: int, season: str, label: str) -> tuple[str, str, str]:
    normalized_season = season.lower()
    if normalized_season == "spring":
        return f"{year:04d}-03-01T00:00:00Z", f"{year:04d}-05-31T23:59:59Z", label
    if normalized_season == "summer":
        return f"{year:04d}-06-01T00:00:00Z", f"{year:04d}-08-31T23:59:59Z", label
    if normalized_season in {"fall", "autumn"}:
        return f"{year:04d}-09-01T00:00:00Z", f"{year:04d}-11-30T23:59:59Z", label
    if normalized_season == "winter":
        feb_last_day = calendar.monthrange(year + 1, 2)[1]
        return f"{year:04d}-12-01T00:00:00Z", f"{year + 1:04d}-02-{feb_last_day:02d}T23:59:59Z", label
    return _default_start_date(), _default_end_date(), label


def _contextualize_followup_message(history: list[BaseMessage], message: str) -> str:
    trimmed = message.strip()
    if not trimmed or not _looks_like_short_followup(trimmed):
        return message

    prior_user_message = ""
    for entry in reversed(history):
        if isinstance(entry, HumanMessage):
            content = str(entry.content).strip()
            if content:
                prior_user_message = content
                break

    if not prior_user_message:
        return message

    return (
        "Continue the user's earlier Shopify analysis using this clarification.\n"
        f"Earlier user request: {prior_user_message}\n"
        f"Clarification provided now: {trimmed}"
    )


def _looks_like_short_followup(message: str) -> bool:
    normalized = " ".join(message.lower().split())
    if len(normalized) > 40:
        return False
    return normalized in {
        "all time",
        "all-time",
        "overall",
        "entire history",
        "full history",
        "this year",
        "last year",
        "this month",
        "last month",
        "today",
        "yesterday",
    } or bool(
        re.fullmatch(r"\d{4}(-\d{2})?", normalized)
        or re.fullmatch(r"(spring|summer|fall|autumn|winter)(?:\s+of)?\s+\d{4}", normalized)
    )


def _build_order_table_payload_if_requested(
    settings: Settings,
    store_url: str | None,
    message: str,
) -> AgentPayload | None:
    if not _is_order_table_request(message):
        return None

    shop_name = (store_url or settings.shopify_shop_name).strip()
    client = ShopifyClient(
        shop_name=shop_name,
        access_token=settings.shopify_access_token,
        api_version=settings.shopify_api_version,
    )

    start_date, end_date, label = _extract_period_from_message(message)
    orders = client.list_orders_in_range(
        start=_parse_iso_datetime(start_date),
        end=_parse_iso_datetime(end_date),
        fields="id,name,created_at,total_price,financial_status,fulfillment_status,customer,email",
        limit_pages=10,
    )

    rows: list[list[Any]] = []
    for order in orders[:250]:
        customer = order.get("customer") or {}
        customer_name = " ".join(
            part for part in [customer.get("first_name"), customer.get("last_name")] if part
        ).strip() or order.get("email") or ""
        rows.append(
            [
                order.get("name", ""),
                str(order.get("created_at", ""))[:10],
                customer_name,
                round(_safe_float(order.get("total_price")), 2),
                order.get("financial_status", ""),
                order.get("fulfillment_status", "") or "unfulfilled",
            ]
        )

    summary_period = f" for {label}" if label else ""
    return AgentPayload(
        answer=f"Here are {len(rows)} orders{summary_period}.",
        table=DataTable(
            title=f"Orders{summary_period}",
            columns=["Order", "Date", "Customer", "Total", "Financial Status", "Fulfillment Status"],
            rows=rows,
        ),
        metadata={
            "source": "deterministic_order_table",
            "start_date": start_date,
            "end_date": end_date,
            "row_count": len(rows),
        },
    )


def _is_order_table_request(message: str) -> bool:
    normalized = " ".join(message.lower().split())
    order_keywords = ("order", "orders")
    list_keywords = ("list", "show", "table", "tabular", "display")
    return any(keyword in normalized for keyword in order_keywords) and any(keyword in normalized for keyword in list_keywords)


def _extract_period_from_message(message: str) -> tuple[str, str, str]:
    normalized = " ".join(message.lower().split())
    candidate_periods = [
        "all time",
        "all-time",
        "overall",
        "entire history",
        "full history",
        "this month",
        "last month",
        "this year",
        "last year",
    ]
    for period in candidate_periods:
        if period in normalized:
            return _resolve_period_text(period)

    month_year_match = re.search(
        r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{4}\b",
        normalized,
    )
    if month_year_match:
        return _resolve_period_text(month_year_match.group(0))

    season_year_match = re.search(r"\b(spring|summer|fall|autumn|winter)(?:\s+of)?\s+\d{4}\b", normalized)
    if season_year_match:
        return _resolve_period_text(season_year_match.group(0))

    iso_month_match = re.search(r"\b\d{4}-\d{2}\b", normalized)
    if iso_month_match:
        return _resolve_period_text(iso_month_match.group(0))

    year_match = re.search(r"\b\d{4}\b", normalized)
    if year_match:
        return _resolve_period_text(year_match.group(0))

    return _default_start_date(), _default_end_date(), ""
