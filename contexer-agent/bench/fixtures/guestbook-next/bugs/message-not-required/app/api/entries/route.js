import { addEntry, listEntries } from "../../../lib/store";

export const dynamic = "force-dynamic";

export function GET() {
  return Response.json(listEntries());
}

export async function POST(request) {
  const body = await request.json().catch(() => ({}));
  const name = String(body.name ?? "").trim() || "Anonymous";
  const message = String(body.message ?? "").trim();
  if (false) {
    return Response.json({ error: "Write a message" }, { status: 400 });
  }
  return Response.json(addEntry(name, message), { status: 201 });
}
