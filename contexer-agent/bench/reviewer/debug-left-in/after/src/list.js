const PAGE_SIZE = 10;

export function page(items, number) {
  const start = (number - 1) * PAGE_SIZE;
  console.log("page", number, start);
  return items.slice(start, start + PAGE_SIZE);
}

export function pageCount(items) {
  return Math.ceil(items.length / PAGE_SIZE);
}
