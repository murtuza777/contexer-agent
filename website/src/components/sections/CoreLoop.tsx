"use client";

import React, { useState } from "react";
import {
  Sparkles,
  Database,
  GitPullRequest,
  Cpu,
  Eye,
  CheckCircle,
  Wrench,
  Flag,
} from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";

interface Phase {
  id: string;
  name: string;
  short: string;
  color: "cyan" | "emerald" | "amber" | "violet" | "default";
  icon: React.ComponentType<{ className?: string }>;
  tagline: string;
  description: string;
  input: string;
  engine: string;
  output: string;
}

const PHASES: Phase[] = [
  {
    id: "intent",
    name: "INTENT",
    short: "01",
    color: "cyan",
    icon: Sparkles,
    tagline: "Natural engineering specification",
    description:
      "A developer specifies an engineering outcome in natural language or passes a feature ticket with constraints.",
    input: "Prompt, ticket requirements, target repository",
    engine: "Intent Parser & Constraint Extractor",
    output: "Structured Intent Model & Acceptance Criteria",
  },
  {
    id: "context",
    name: "CONTEXT",
    short: "02",
    color: "violet",
    icon: Database,
    tagline: "Full-repo structural comprehension",
    description:
      "Indexes AST syntax trees, symbol relationships, configuration manifests, test suites, and runtime environment specifications.",
    input: "Repository files, git history, tsconfig, env schemas",
    engine: "Context Graph Engine & Tree-sitter Indexer",
    output: "Targeted Context Subgraph & Symbol References",
  },
  {
    id: "plan",
    name: "PLAN",
    short: "03",
    color: "cyan",
    icon: GitPullRequest,
    tagline: "Deterministic task dependency DAG",
    description:
      "Decomposes the intent into atomic, dependency-ordered engineering tasks with explicit verification checkpoints.",
    input: "Structured Intent + Context Subgraph",
    engine: "Hierarchical Task Network (HTN) Planner",
    output: "Directed Acyclic Graph (DAG) of verified tasks",
  },
  {
    id: "execute",
    name: "EXECUTE",
    short: "04",
    color: "violet",
    icon: Cpu,
    tagline: "Pluggable coding agent dispatch",
    description:
      "Dispatches discrete code modification tasks to coding agent adapters (such as OpenCode), generating isolated diffs.",
    input: "Atomic DAG Task + Local Context Slice",
    engine: "Coding Agent Adapter (OpenCode runtime)",
    output: "Candidate file diffs & workspace mutations",
  },
  {
    id: "observe",
    name: "OBSERVE",
    short: "05",
    color: "cyan",
    icon: Eye,
    tagline: "Live runtime telemetry capture",
    description:
      "Boots the application server in an isolated container or local environment, spins up headless browsers, and gathers telemetry.",
    input: "Updated repository state & dev server runner",
    engine: "Playwright Headless Browser & Process Supervisor",
    output: "DOM snapshots, network traffic, console logs, visual traces",
  },
  {
    id: "verify",
    name: "VERIFY",
    short: "06",
    color: "emerald",
    icon: CheckCircle,
    tagline: "Intent vs. reality assertion engine",
    description:
      "Validates live behavior against the original intent. Verifies route responses, UI accessibility, button clickability, and data flow.",
    input: "Observed Runtime State vs. Acceptance Criteria",
    engine: "Autonomous Assertion Engine",
    output: "Verification Report (Pass / Failure Mismatch)",
  },
  {
    id: "repair",
    name: "REPAIR",
    short: "07",
    color: "amber",
    icon: Wrench,
    tagline: "Autonomous failure self-correction",
    description:
      "When verification fails, Contexer isolates the mismatch, formulates an automated regression-safe patch, and loops back to execute.",
    input: "Assertion failure trace & DOM mismatch logs",
    engine: "Diagnostic Engine & Targeted Patch Synthesizer",
    output: "Correction Task injected into Execution Loop",
  },
  {
    id: "done",
    name: "DONE",
    short: "08",
    color: "emerald",
    icon: Flag,
    tagline: "Verifiable engineering completion",
    description:
      "Only exits when 100% of verification assertions pass. Produces a clean git commit, execution walkthrough, and proof of work.",
    input: "Passed verification proofs & clean test runner",
    engine: "Artifact Compiler & Branch Finalizer",
    output: "Production-ready PR with verification transcript",
  },
];

export function CoreLoop() {
  const [selectedPhase, setSelectedPhase] = useState<Phase>(PHASES[0]);

  return (
    <section id="how-it-works" className="py-24 sm:py-32 border-t border-zinc-800/60 relative">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        {/* Section Heading */}
        <div className="text-center max-w-3xl mx-auto mb-16">
          <Badge variant="outline" className="mb-4">
            Autonomous Architecture
          </Badge>
          <h2 className="text-3xl sm:text-4xl lg:text-5xl font-bold tracking-tight text-zinc-100">
            The Contexer Core Loop
          </h2>
          <p className="mt-4 text-base sm:text-lg text-zinc-400">
            Software engineering is an iterative closed feedback loop. Click each phase to inspect
            how Contexer transitions from raw intent to verified reality.
          </p>
        </div>

        {/* The 8-phase timeline track */}
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-2.5 mb-10">
          {PHASES.map((phase) => {
            const isSelected = selectedPhase.id === phase.id;
            const Icon = phase.icon;

            return (
              <button
                key={phase.id}
                type="button"
                onClick={() => setSelectedPhase(phase)}
                className={`p-3 rounded-xl border text-left font-mono transition-all relative flex flex-col justify-between h-28 ${
                  isSelected
                    ? "bg-zinc-900 border-cyan-500/80 shadow-[0_0_15px_rgba(6,182,212,0.15)] ring-1 ring-cyan-500/40"
                    : "bg-zinc-950/60 border-zinc-800/80 hover:border-zinc-700 hover:bg-zinc-900/40 text-zinc-400"
                }`}
              >
                <div className="flex items-center justify-between w-full">
                  <span className={`text-[11px] font-bold ${isSelected ? "text-cyan-400" : "text-zinc-500"}`}>
                    {phase.short}
                  </span>
                  <Icon
                    className={`w-4 h-4 ${
                      isSelected
                        ? "text-cyan-400"
                        : phase.id === "repair"
                        ? "text-amber-400/80"
                        : phase.id === "verify" || phase.id === "done"
                        ? "text-emerald-400/80"
                        : "text-zinc-500"
                    }`}
                  />
                </div>

                <div>
                  <div className={`text-xs font-bold tracking-wider ${isSelected ? "text-zinc-100" : "text-zinc-300"}`}>
                    {phase.name}
                  </div>
                  <div className="text-[10px] text-zinc-500 truncate mt-0.5">{phase.tagline}</div>
                </div>

                {phase.id === "repair" && (
                  <div className="absolute -top-2 right-2 px-1 py-0.2 rounded bg-amber-950/90 border border-amber-800 text-[9px] text-amber-400">
                    ↺ Loop
                  </div>
                )}
              </button>
            );
          })}
        </div>

        {/* Active Phase Deep Dive Card */}
        <Card className="p-6 sm:p-8 bg-zinc-950 border-zinc-800 shadow-2xl relative overflow-hidden">
          <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-6 pb-6 border-b border-zinc-800/80">
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 rounded-xl bg-zinc-900 border border-zinc-700 flex items-center justify-center shrink-0">
                <selectedPhase.icon className="w-6 h-6 text-cyan-400" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-xs font-mono text-cyan-400 font-bold">PHASE {selectedPhase.short}</span>
                  <span className="text-zinc-600">•</span>
                  <h3 className="text-xl sm:text-2xl font-bold font-mono text-zinc-100">
                    {selectedPhase.name}
                  </h3>
                </div>
                <p className="text-sm text-zinc-400 mt-1">{selectedPhase.tagline}</p>
              </div>
            </div>

            <div className="flex items-center gap-2 font-mono text-xs">
              <span className="text-zinc-500">Autonomous Cycle:</span>
              <span className="px-2.5 py-1 rounded bg-zinc-900 border border-zinc-800 text-zinc-300">
                Self-Supervised
              </span>
            </div>
          </div>

          <div className="mt-6 grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="p-4 rounded-lg bg-zinc-900/40 border border-zinc-800/80 space-y-1.5">
              <div className="text-[11px] font-mono text-zinc-500 uppercase tracking-wider">Input Stream</div>
              <div className="text-xs sm:text-sm text-zinc-200 font-mono">{selectedPhase.input}</div>
            </div>
            <div className="p-4 rounded-lg bg-zinc-900/40 border border-zinc-800/80 space-y-1.5">
              <div className="text-[11px] font-mono text-zinc-500 uppercase tracking-wider">Engine Subsystem</div>
              <div className="text-xs sm:text-sm text-cyan-300 font-mono">{selectedPhase.engine}</div>
            </div>
            <div className="p-4 rounded-lg bg-zinc-900/40 border border-zinc-800/80 space-y-1.5">
              <div className="text-[11px] font-mono text-zinc-500 uppercase tracking-wider">Verified Artifact</div>
              <div className="text-xs sm:text-sm text-emerald-300 font-mono">{selectedPhase.output}</div>
            </div>
          </div>

          <div className="mt-6 text-sm text-zinc-300 leading-relaxed bg-zinc-900/20 p-4 rounded-lg border border-zinc-800/40">
            {selectedPhase.description}
          </div>
        </Card>
      </div>
    </section>
  );
}
