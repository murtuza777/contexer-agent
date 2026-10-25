// A stand-in for a database: entries live in the server process, so every
// browser (and every check) sees what earlier ones saved.
globalThis.guestbookById ??= new Map();

export function listEntries() {
  return Array.from(globalThis.guestbookById.values()).reverse();
}

export function addEntry(name, message) {
  const entry = { id: crypto.randomUUID(), name, message };
  globalThis.guestbookById.set(entry.id, entry);
  return entry;
}

export function clearEntries() {
  globalThis.guestbookById.clear();
}
