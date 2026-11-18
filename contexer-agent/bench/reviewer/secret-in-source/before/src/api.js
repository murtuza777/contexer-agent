const BASE = "/api";

export async function loadOrders(fetcher = fetch) {
  const response = await fetcher(`${BASE}/orders`);
  if (!response.ok) {
    throw new Error(`orders: ${response.status}`);
  }
  return response.json();
}
