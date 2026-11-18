import { expect, it } from "vitest";
import { addItem, total } from "../src/cart.js";

it("sums price times quantity", () => {
  expect(total([{ price: 10, quantity: 3 }])).toBe(30);
});

it.only("adds a new item with quantity 1", () => {
  const items = addItem([], { id: "a", price: 5 });
  expect(items).toHaveLength(1);
  expect(items[0].quantity).toBe(1);
});
