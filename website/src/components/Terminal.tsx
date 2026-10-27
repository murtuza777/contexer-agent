type Tone = "plain" | "dim" | "pass" | "fail" | "cmd";

export type TerminalLine = { text: string; tone?: Tone };

const tones: Record<Tone, string> = {
  plain: "text-zinc-200",
  dim: "text-zinc-500",
  pass: "text-emerald-400",
  fail: "text-red-400",
  cmd: "text-white",
};

/** Real output, shown as text: readable, selectable, and searchable. */
export function Terminal({ title, lines }: { title: string; lines: TerminalLine[] }) {
  return (
    <figure className="overflow-hidden rounded-xl border border-zinc-900 bg-zinc-950">
      <figcaption className="border-b border-zinc-800 px-4 py-2 font-mono text-xs text-zinc-500">{title}</figcaption>
      <pre className="overflow-x-auto px-4 py-4 font-mono text-[13px] leading-6">
        {lines.map((line, i) => (
          <div key={i} className={tones[line.tone ?? "plain"]}>
            {line.text || " "}
          </div>
        ))}
      </pre>
    </figure>
  );
}
