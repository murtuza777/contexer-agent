import React from "react";
import { CheckCircle2, Clock, PlugZap } from "lucide-react";
import { Badge } from "@/components/ui/Badge";

export function AgentAgnostic() {
  const adapters = [
    {
      name: "OpenCode",
      status: "Active MVP",
      type: "First-party Execution Adapter",
      active: true,
      description: "Primary autonomous coding runtime for the initial Contexer release. Full diff and AST support.",
    },
    {
      name: "Codex",
      status: "Upcoming Adapter",
      type: "Planned Integration",
      active: false,
      description: "Direct integration with OpenAI Codex agent environments for enterprise codebases.",
    },
    {
      name: "Claude Code",
      status: "Upcoming Adapter",
      type: "Planned Integration",
      active: false,
      description: "Adapter bridging Anthropic's agentic CLI toolchain with Contexer verification loops.",
    },
    {
      name: "Custom Agent API",
      status: "Plugin Specification",
      type: "Extensibility Interface",
      active: false,
      description: "Open JSON-RPC / CLI protocol allowing developers to plug proprietary internal coding models.",
    },
  ];

  return (
    <section className="py-24 sm:py-32 border-t border-zinc-800/60 relative bg-zinc-950/40">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        {/* Section Header */}
        <div className="max-w-3xl mb-16">
          <Badge variant="cyan" className="mb-4">
            Orchestration Layer
          </Badge>
          <h2 className="text-3xl sm:text-4xl lg:text-5xl font-bold tracking-tight text-zinc-100 leading-tight">
            Contexer sits above coding agents.{" "}
            <span className="text-zinc-500 block">
              It directs, observes, and verifies them.
            </span>
          </h2>
          <p className="mt-4 text-base sm:text-lg text-zinc-400">
            Model architectures and coding agents evolve rapidly. Contexer is built to be agent-agnostic:
            it formulates the plan, feeds atomic tasks into the coding agent adapter, tests the resulting application,
            and validates the outcome.
          </p>
        </div>

        {/* Adapter Topology Card */}
        <div className="p-6 sm:p-10 rounded-2xl bg-zinc-950 border border-zinc-800 font-mono">
          <div className="text-xs text-zinc-400 uppercase tracking-wider mb-6 flex items-center gap-2">
            <PlugZap className="w-4 h-4 text-cyan-400" />
            <span>Contexer Coding Agent Adapter Protocol</span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {adapters.map((adapter) => (
              <div
                key={adapter.name}
                className={`p-5 rounded-xl border flex flex-col justify-between transition-all ${
                  adapter.active
                    ? "bg-zinc-900/90 border-cyan-500/60 shadow-[0_0_20px_rgba(6,182,212,0.1)]"
                    : "bg-zinc-950/60 border-zinc-800/80 opacity-80"
                }`}
              >
                <div>
                  <div className="flex items-center justify-between mb-3">
                    <span className="text-sm font-bold text-zinc-100">{adapter.name}</span>
                    <span
                      className={`text-[10px] px-2 py-0.5 rounded font-mono ${
                        adapter.active
                          ? "bg-cyan-950 text-cyan-300 border border-cyan-800"
                          : "bg-zinc-900 text-zinc-400 border border-zinc-800"
                      }`}
                    >
                      {adapter.status}
                    </span>
                  </div>
                  <div className="text-xs text-zinc-400 mb-3 font-sans">{adapter.type}</div>
                  <p className="text-xs text-zinc-400 font-sans leading-relaxed">
                    {adapter.description}
                  </p>
                </div>

                <div className="mt-6 pt-3 border-t border-zinc-800/80 flex items-center gap-2 text-xs">
                  {adapter.active ? (
                    <span className="flex items-center gap-1.5 text-emerald-400">
                      <CheckCircle2 className="w-3.5 h-3.5" />
                      <span>Supported in MVP</span>
                    </span>
                  ) : (
                    <span className="flex items-center gap-1.5 text-zinc-500">
                      <Clock className="w-3.5 h-3.5" />
                      <span>Target Adapter Roadmap</span>
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>

          <div className="mt-8 p-4 rounded-lg bg-zinc-900/40 border border-zinc-800/80 text-xs text-zinc-400 font-sans leading-relaxed">
            <strong className="text-zinc-200 font-mono">Adapter Isolation Guarantee: </strong>
            Coding agent adapters run in ephemeral worktrees. They never commit directly to your production
            branch until Contexer&apos;s Verification Engine passes all browser assertions, type checks, and test harnesses.
          </div>
        </div>
      </div>
    </section>
  );
}
