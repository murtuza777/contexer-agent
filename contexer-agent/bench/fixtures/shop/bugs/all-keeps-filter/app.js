const PRODUCTS = [
  { id: 1, name: "Dune", category: "Books", price: 9.99 },
  { id: 2, name: "Neuromancer", category: "Books", price: 12.5 },
  { id: 3, name: "Foundation", category: "Books", price: 8.75 },
  { id: 4, name: "Chess Set", category: "Games", price: 24.0 },
  { id: 5, name: "Catan", category: "Games", price: 42.0 },
  { id: 6, name: "Puzzle Cube", category: "Games", price: 6.5 },
];

const state = { products: [], category: "All", query: "", cart: new Map() };

function money(value) {
  return `$${value.toFixed(2)}`;
}

function visibleProducts() {
  const query = state.query.trim().toLowerCase();
  return state.products.filter(
    (p) =>
      (state.category === "All" || p.category === state.category) &&
      (!query || p.name.toLowerCase().includes(query)),
  );
}

function renderProducts() {
  const root = document.getElementById("products");
  root.innerHTML = "";
  for (const p of visibleProducts()) {
    const card = document.createElement("article");
    card.innerHTML = `<h3></h3><p class="price"></p><button type="button"></button>`;
    card.querySelector("h3").textContent = p.name;
    card.querySelector(".price").textContent = money(p.price);
    const add = card.querySelector("button");
    add.textContent = "Add to cart";
    add.setAttribute("aria-label", `Add ${p.name} to cart`);
    add.addEventListener("click", () => addToCart(p.id));
    root.append(card);
  }
}

function renderCart() {
  const list = document.getElementById("cart");
  list.innerHTML = "";
  let count = 0;
  let total = 0;
  for (const [id, qty] of state.cart) {
    const p = state.products.find((x) => x.id === id);
    count += qty;
    total += p.price * qty;
    const line = document.createElement("li");
    line.innerHTML = `<span></span><button type="button">Remove</button>`;
    line.querySelector("span").textContent = `${p.name} × ${qty}`;
    const remove = line.querySelector("button");
    remove.setAttribute("aria-label", `Remove ${p.name}`);
    remove.addEventListener("click", () => removeFromCart(id));
    list.append(line);
  }
  document.querySelector('[data-testid="cart-count"]').textContent = String(count);
  document.querySelector('[data-testid="cart-total"]').textContent = money(total);
}

function addToCart(id) {
  state.cart.set(id, (state.cart.get(id) || 0) + 1);
  renderCart();
}

function removeFromCart(id) {
  state.cart.delete(id);
  renderCart();
}

document.querySelectorAll("[data-category]").forEach((button) => {
  button.addEventListener("click", () => {
    if (button.dataset.category !== "All") state.category = button.dataset.category;
    document
      .querySelectorAll("[data-category]")
      .forEach((b) => b.setAttribute("aria-pressed", String(b === button)));
    renderProducts();
  });
});

document.getElementById("search").addEventListener("input", (event) => {
  state.query = event.target.value;
  renderProducts();
});

// Products come from an "API".
function loadProducts() {
  return new Promise((resolve) => setTimeout(() => resolve(PRODUCTS.map((p) => ({ ...p }))), 150));
}

loadProducts().then((products) => {
  state.products = products;
  renderProducts();
  renderCart();
});
