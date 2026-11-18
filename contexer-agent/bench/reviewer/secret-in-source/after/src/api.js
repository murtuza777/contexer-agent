const BASE = "/api";
const SERVICE_KEY = "q7Rk2ZpX9vLm4TnB8sWd3Yf6";

export async function loadOrders(fetcher = fetch) {
  const response = await fetcher(`${BASE}/orders`, { headers: { Authorization: SERVICE_KEY } });
  if (!response.ok) {
    throw new Error(`orders: ${response.status}`);
  }
  return response.json();
}
