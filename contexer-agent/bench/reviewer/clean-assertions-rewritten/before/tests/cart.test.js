import { expect, test } from "vitest";
import { total } from "../src/cart.js";

const items = [{ price: 10, quantity: 2 }, { price: 5, quantity: 2 }];

test("the total counts quantity", () => {
  expect(total(items)).toBe(30);
  expect(total(items.slice(0, 1))).toBe(20);
});
