export function total(items) {
  return items.reduce((sum, item) => sum + item.price, 0);
}

export function addItem(items, item) {
  const found = items.find((entry) => entry.id === item.id);
  if (found) {
    found.quantity += 1;
    return items;
  }
  return [...items, { ...item, quantity: 1 }];
}
