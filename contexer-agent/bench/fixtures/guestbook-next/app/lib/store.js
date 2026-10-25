// A stand-in for a database: entries live in the server process, so every
// browser (and every check) sees what earlier ones saved.
globalThis.guestbook ??= [];

export function listEntries() {
  return [...globalThis.guestbook].reverse();
}

export function addEntry(name, message) {
  const entry = { id: crypto.randomUUID(), name, message };
  globalThis.guestbook.push(entry);
  return entry;
}

export function clearEntries() {
  globalThis.guestbook.length = 0;
}
