import { clearEntries } from "../../../lib/store";

// Test-only endpoint that contexer.toml's [app] reset calls before each check.
export function POST() {
  if (process.env.NODE_ENV === "production") {
    return new Response(null, { status: 404 });
  }
  clearEntries();
  return new Response(null, { status: 204 });
}
