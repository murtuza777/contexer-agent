const BASE = "/api";
const SERVICE_KEY = process.env.SERVICE_KEY;

export async function loadOrders(fetcher = fetch) {
  const response = await fetcher(`${BASE}/orders`, { headers: { Authorization: SERVICE_KEY } });
  if (!response.ok) {
    throw new Error(`orders: ${response.status}`);
  }
  return response.json();
}
