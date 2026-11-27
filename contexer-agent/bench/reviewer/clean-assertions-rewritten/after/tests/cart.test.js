import { expect, test } from "vitest";
import { total } from "../src/cart.js";

const items = [{ price: 10, quantity: 2 }, { price: 5, quantity: 2 }];

test("the total counts quantity", () => {
  expect(total(items)).toEqual(30);
  expect(total(items.slice(0, 1))).toEqual(20);
});

test("an empty cart totals 0", () => {
  expect(total([])).toBe(0);
});
