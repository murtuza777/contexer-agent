const BASE = "/api";

export async function loadOrders(fetcher = fetch) {
  const response = await fetcher(`${BASE}/orders`);
  if (!response.ok) {
    console.error("orders did not load", response.status);
    throw new Error(`orders: ${response.status}`);
  }
  return response.json();
}
