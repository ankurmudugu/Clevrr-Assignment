from __future__ import annotations

import calendar
import difflib
import json
from datetime import date, datetime
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx


class ShopifyClient:
    def __init__(
        self,
        shop_name: str,
        access_token: str,
        api_version: str,
        timeout: float = 30.0,
        max_retries: int = 4,
    ) -> None:
        self.shop_name = shop_name.strip().replace("https://", "").replace("http://", "")
        self.access_token = access_token.strip()
        self.api_version = api_version.strip()
        self.timeout = timeout
        self.max_retries = max_retries
        self.base_url = f"https://{self.shop_name}/admin/api/{self.api_version}"

    def _headers(self) -> dict[str, str]:
        return {
            "X-Shopify-Access-Token": self.access_token,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _extract_next_page_info(self, link_header: str | None) -> str | None:
        if not link_header:
            return None

        for raw_part in link_header.split(","):
            part = raw_part.strip()
            if 'rel="next"' not in part:
                continue
            url_section = part.split(";")[0].strip()
            url = url_section.removeprefix("<").removesuffix(">")
            parsed = urlparse(url)
            page_info = parse_qs(parsed.query).get("page_info", [])
            if page_info:
                return page_info[0]
        return None

    def get(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
        paginate: bool = False,
        limit_pages: int = 10,
    ) -> dict[str, Any]:
        url = self._build_url(endpoint)
        merged_params = dict(params or {})
        page_info = None
        pages = 0
        collected: dict[str, list[Any]] = {}
        last_payload: dict[str, Any] = {}

        while True:
            request_params = self._build_request_params(merged_params, page_info)

            response = self._request_with_retries(url, request_params)
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Shopify API returned an unexpected response format.")

            last_payload = payload
            if paginate:
                for key, value in payload.items():
                    if isinstance(value, list):
                        collected.setdefault(key, []).extend(value)
            else:
                return payload

            pages += 1
            page_info = self._extract_next_page_info(response.headers.get("Link"))
            if not page_info or pages >= limit_pages:
                break

        if collected:
            last_payload.update(collected)
        last_payload["pagination"] = {
            "pages_fetched": pages,
            "has_more": bool(page_info),
        }
        return last_payload

    def count_orders_for_date(self, target_date: date) -> int:
        start = datetime.fromisoformat(f"{target_date.isoformat()}T00:00:00")
        end = datetime.fromisoformat(f"{target_date.isoformat()}T23:59:59")
        return self.count_orders_in_range(start=start, end=end)

    def count_orders_in_month(self, year: int, month: int) -> int:
        last_day = calendar.monthrange(year, month)[1]
        start = datetime(year, month, 1, 0, 0, 0)
        end = datetime(year, month, last_day, 23, 59, 59)
        return self.count_orders_in_range(start=start, end=end)

    def count_orders_in_range(self, start: datetime, end: datetime) -> int:
        payload = self.get(
            endpoint="/orders/count.json",
            params={
                "status": "any",
                "created_at_min": f"{start.isoformat()}Z",
                "created_at_max": f"{end.isoformat()}Z",
            },
            paginate=False,
        )
        count = payload.get("count", 0)
        return int(count) if isinstance(count, (int, float, str)) else 0

    def list_orders_in_year(self, year: int) -> list[dict[str, Any]]:
        start = datetime(year, 1, 1, 0, 0, 0)
        end = datetime(year, 12, 31, 23, 59, 59)
        return self.list_orders_in_range(
            start=start,
            end=end,
            fields=(
                "id,name,created_at,financial_status,total_price,current_total_price,"
                "customer,email,fulfillment_status"
            ),
        )

    def list_recent_orders(
        self,
        fields: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        payload = self.get(
            endpoint="/orders.json",
            params={
                "status": "any",
                "limit": min(limit, 250),
                "fields": fields,
                "order": "created_at desc",
            },
            paginate=False,
        )
        orders = payload.get("orders", [])
        return orders if isinstance(orders, list) else []

    def list_orders_in_range(
        self,
        start: datetime,
        end: datetime,
        fields: str,
        limit_pages: int = 10,
    ) -> list[dict[str, Any]]:
        payload = self.get(
            endpoint="/orders.json",
            params={
                "status": "any",
                "limit": 250,
                "fields": fields,
                "created_at_min": f"{start.isoformat()}Z",
                "created_at_max": f"{end.isoformat()}Z",
            },
            paginate=True,
            limit_pages=limit_pages,
        )
        orders = payload.get("orders", [])
        return orders if isinstance(orders, list) else []

    def list_customers(self) -> list[dict[str, Any]]:
        payload = self.get(
            endpoint="/customers.json",
            params={
                "limit": 250,
                "fields": "id,first_name,last_name,email,orders_count,total_spent,created_at",
            },
            paginate=True,
            limit_pages=10,
        )
        customers = payload.get("customers", [])
        return customers if isinstance(customers, list) else []

    def list_products(self) -> list[dict[str, Any]]:
        payload = self.get(
            endpoint="/products.json",
            params={
                "limit": 250,
                "fields": "id,title,status,variants",
            },
            paginate=True,
            limit_pages=10,
        )
        products = payload.get("products", [])
        return products if isinstance(products, list) else []

    def find_customer_by_name(self, name: str) -> dict[str, Any] | None:
        customers = self.list_customers()
        if not customers:
            return None

        normalized_target = self._normalize_name(name)
        exact_matches = [
            customer for customer in customers
            if self._normalize_name(self._customer_full_name(customer)) == normalized_target
        ]
        if exact_matches:
            return exact_matches[0]

        names = [self._normalize_name(self._customer_full_name(customer)) for customer in customers]
        close = difflib.get_close_matches(normalized_target, names, n=1, cutoff=0.75)
        if not close:
            return None

        matched_name = close[0]
        for customer in customers:
            if self._normalize_name(self._customer_full_name(customer)) == matched_name:
                return customer
        return None

    def list_orders_for_customer(self, customer_name: str, limit: int = 50) -> list[dict[str, Any]]:
        customer = self.find_customer_by_name(customer_name)
        if customer is None:
            return []

        customer_id = customer.get("id")
        email = customer.get("email")
        if not customer_id and not email:
            return []

        params: dict[str, Any] = {
            "status": "any",
            "limit": min(limit, 250),
            "fields": "id,name,created_at,total_price,financial_status,fulfillment_status,customer,email,line_items",
            "order": "created_at desc",
        }
        if customer_id:
            params["customer_id"] = customer_id
        elif email:
            params["email"] = email

        payload = self.get(
            endpoint="/orders.json",
            params=params,
            paginate=False,
        )
        orders = payload.get("orders", [])
        return orders if isinstance(orders, list) else []

    def customer_with_most_orders(self) -> dict[str, Any] | None:
        customers = self.list_customers()
        if not customers:
            return None
        return max(customers, key=lambda customer: int(customer.get("orders_count", 0) or 0))

    def _customer_full_name(self, customer: dict[str, Any]) -> str:
        return " ".join(
            part for part in [customer.get("first_name"), customer.get("last_name")] if part
        ).strip()

    def _normalize_name(self, name: str) -> str:
        return " ".join(name.lower().split())

    def _build_url(self, endpoint: str) -> str:
        normalized_endpoint = endpoint.strip()
        if not normalized_endpoint:
            raise ValueError("Shopify endpoint cannot be empty.")

        if normalized_endpoint.startswith("http://") or normalized_endpoint.startswith("https://"):
            parsed = urlparse(normalized_endpoint)
            normalized_endpoint = parsed.path

        admin_prefix = "/admin/api/"
        if admin_prefix in normalized_endpoint:
            normalized_endpoint = normalized_endpoint.split(admin_prefix, 1)[1]
            parts = normalized_endpoint.split("/", 1)
            normalized_endpoint = f"/{parts[1]}" if len(parts) == 2 else "/"

        if not normalized_endpoint.startswith("/"):
            normalized_endpoint = f"/{normalized_endpoint}"

        return f"{self.base_url}{normalized_endpoint}"

    def _build_request_params(
        self,
        params: dict[str, Any],
        page_info: str | None,
    ) -> dict[str, Any]:
        if not page_info:
            return dict(params)

        # Shopify cursor pagination expects page_info without the original filters.
        carry_over_keys = {"limit", "fields"}
        next_params = {key: value for key, value in params.items() if key in carry_over_keys}
        next_params["page_info"] = page_info
        return next_params

    def _request_with_retries(
        self,
        url: str,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                response = httpx.get(
                    url,
                    headers=self._headers(),
                    params=params,
                    timeout=self.timeout,
                )
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", attempt))
                    time.sleep(min(retry_after, 8))
                    continue
                response.raise_for_status()
                return response
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt == self.max_retries:
                    break
                time.sleep(min(2**attempt, 8))

        raise RuntimeError(f"Failed Shopify request after retries: {last_error}")

    def describe(self) -> str:
        return json.dumps(
            {
                "shop": self.shop_name,
                "api_version": self.api_version,
            }
        )
