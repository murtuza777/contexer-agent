import { expect, it } from "vitest";
import { addItem, removeItem, total } from "../src/cart.js";

it("sums price times quantity", () => {
  expect(total([{ price: 10, quantity: 3 }])).toBe(30);
});

it("adds a new item with quantity 1", () => {
  const items = addItem([], { id: "a", price: 5 });
  expect(items).toHaveLength(1);
  expect(items[0].quantity).toBe(1);
});

it("removes an item by id", () => {
  expect(removeItem([{ id: "a" }, { id: "b" }], "a")).toEqual([{ id: "b" }]);
});
