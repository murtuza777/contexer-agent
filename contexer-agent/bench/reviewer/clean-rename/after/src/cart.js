export function total(items) {
  return items.reduce((sum, item) => sum + item.price * item.quantity, 0);
}

export function addItem(items, item) {
  const existing = items.find((line) => line.id === item.id);
  if (existing) {
    existing.quantity += 1;
    return items;
  }
  return [...items, { ...item, quantity: 1 }];
}
