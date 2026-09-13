import React from "react";
import {
  CheckCircle2,
  XCircle,
  RotateCw,
  FileCode2,
  Terminal,
} from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";

export function ProblemDifference() {
  const engineeringSteps = [
    { label: "Understand intent", icon: "01" },
    { label: "Understand existing code", icon: "02" },
    { label: "Plan changes", icon: "03" },
    { label: "Execute changes", icon: "04" },
    { label: "Run application", icon: "05" },
    { label: "Observe runtime", icon: "06" },
    { label: "Verify against intent", icon: "07" },
    { label: "Diagnose failures", icon: "08" },
    { label: "Repair regressions", icon: "09" },
    { label: "Verify again", icon: "10" },
  ];

  return (
    <section id="product" className="py-24 sm:py-32 border-t border-zinc-800/60 relative">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        {/* Section Header */}
        <div className="max-w-3xl">
          <Badge variant="outline" className="mb-4">
            The Engineering Gap
          </Badge>
          <h2 className="text-3xl sm:text-4xl lg:text-5xl font-bold tracking-tight text-zinc-100 leading-tight">
            Coding agents can write code.{" "}
            <span className="text-zinc-500 block">
              They don&apos;t always know when the job is actually done.
            </span>
          </h2>
          <p className="mt-5 text-base sm:text-lg text-zinc-400 leading-relaxed">
            Coding agents are excellent at generating edits, updating files, and answering prompts.
            But writing code is only 20% of engineering. True software engineering is an
            observability and verification discipline.
          </p>
        </div>

        {/* The 10-Step Reality Flow */}
        <div className="mt-12 p-6 sm:p-8 rounded-2xl bg-zinc-950 border border-zinc-800/80 shadow-inner">
          <div className="text-xs font-mono text-zinc-400 uppercase tracking-wider mb-6 flex items-center gap-2">
            <Terminal className="w-4 h-4 text-cyan-400" />
            <span>The Complete Software Engineering Lifecycle</span>
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
            {engineeringSteps.map((step, idx) => {
              const isClosedByContexer = idx >= 4;
              return (
                <div
                  key={step.label}
                  className={`p-3 rounded-lg border transition-all ${
                    isClosedByContexer
                      ? "bg-cyan-950/20 border-cyan-800/50 text-cyan-200"
                      : "bg-zinc-900/60 border-zinc-800 text-zinc-300"
                  }`}
                >
                  <div className="flex items-center justify-between text-[11px] font-mono mb-1">
                    <span className={isClosedByContexer ? "text-cyan-400 font-bold" : "text-zinc-500"}>
                      {step.icon}
                    </span>
                    {isClosedByContexer && (
                      <span className="text-[9px] px-1 py-0.2 rounded bg-cyan-900/60 text-cyan-300 uppercase">
                        Contexer
                      </span>
                    )}
                  </div>
                  <div className="text-xs font-medium leading-snug">{step.label}</div>
                </div>
              );
            })}
          </div>

          <div className="mt-6 pt-4 border-t border-zinc-800/80 flex flex-col sm:flex-row items-start sm:items-center justify-between text-xs text-zinc-400 gap-2">
            <span className="font-mono text-zinc-300">
              Traditional coding assistants stop at step 04. Contexer closes the entire loop from 01 through 10.
            </span>
            <span className="inline-flex items-center gap-1 text-cyan-400 font-mono font-semibold">
              <RotateCw className="w-3.5 h-3.5" />
              Autonomous Closed Loop
            </span>
          </div>
        </div>

        {/* Side by Side Comparative Contrast */}
        <div className="mt-12 grid grid-cols-1 lg:grid-cols-2 gap-8">
          {/* Traditional Assistant Panel */}
          <Card className="p-6 sm:p-8 bg-zinc-900/40 border-zinc-800/80">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <FileCode2 className="w-5 h-5 text-zinc-400" />
                <h3 className="text-lg font-bold text-zinc-200 font-mono">Traditional Coding Agent</h3>
              </div>
              <Badge variant="outline" className="text-rose-400 border-rose-900/50">
                Open Loop (Unverified)
              </Badge>
            </div>

            <p className="text-sm text-zinc-400 mb-6">
              Emits code diffs directly into your repository. Does not know if the app compiles,
              crashes in the browser, or satisfies your intended behavior.
            </p>

            <ul className="space-y-3.5 text-xs sm:text-sm font-mono text-zinc-300">
              <li className="flex items-start gap-2.5">
                <XCircle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
                <span>Generates code blindly without running your test suite or app</span>
              </li>
              <li className="flex items-start gap-2.5">
                <XCircle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
                <span>Stops immediately when file write completes (&quot;I made the edits!&quot;)</span>
              </li>
              <li className="flex items-start gap-2.5">
                <XCircle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
                <span>Leaves syntax errors, runtime crashes, and CSS regressions for you to fix</span>
              </li>
              <li className="flex items-start gap-2.5">
                <XCircle className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
                <span>Forces you to manually copy-paste terminal errors back into a chatbox</span>
              </li>
            </ul>
          </Card>

          {/* Contexer Autonomous Engineering Layer */}
          <Card className="p-6 sm:p-8 bg-gradient-to-b from-zinc-900/90 to-zinc-950 border-cyan-900/40 relative overflow-hidden">
            <div className="absolute top-0 right-0 w-48 h-48 bg-cyan-500/5 rounded-full blur-3xl pointer-events-none" />

            <div className="flex items-center justify-between mb-4 relative">
              <div className="flex items-center gap-2">
                <Terminal className="w-5 h-5 text-cyan-400" />
                <h3 className="text-lg font-bold text-zinc-100 font-mono">Contexer Autonomous Layer</h3>
              </div>
              <Badge variant="cyan">
                Closed Loop (Verified)
              </Badge>
            </div>

            <p className="text-sm text-zinc-300 mb-6 relative">
              Coordinates coding agents, spins up the local application runtime, executes end-to-end
              verification assertions, and automatically drives repair loops if anything fails.
            </p>

            <ul className="space-y-3.5 text-xs sm:text-sm font-mono text-zinc-200 relative">
              <li className="flex items-start gap-2.5">
                <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                <span>Indexes full repo context, AST dependencies, and project configuration</span>
              </li>
              <li className="flex items-start gap-2.5">
                <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                <span>Boots dev runtime &amp; headless Playwright browser to observe actual behavior</span>
              </li>
              <li className="flex items-start gap-2.5">
                <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                <span>Detects mismatches between expected outcome and observed runtime results</span>
              </li>
              <li className="flex items-start gap-2.5">
                <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                <span>Autonomously repairs regressions and only reports done when verified green</span>
              </li>
            </ul>
          </Card>
        </div>
      </div>
    </section>
  );
}
