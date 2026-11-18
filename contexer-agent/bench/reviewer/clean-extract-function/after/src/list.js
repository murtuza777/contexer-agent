const PAGE_SIZE = 10;

export function page(items, number) {
  const start = firstIndex(number);
  return items.slice(start, start + PAGE_SIZE);
}

export function pageCount(items) {
  return Math.ceil(items.length / PAGE_SIZE);
}

function firstIndex(number) {
  return (number - 1) * PAGE_SIZE;
}
