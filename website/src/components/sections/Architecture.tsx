import React from "react";
import { Terminal, Workflow } from "lucide-react";
import { Badge } from "@/components/ui/Badge";

export function Architecture() {
  const coreEngines = [
    {
      name: "Intent Engine",
      role: "Outcome Decomposition",
      status: "MVP Core",
      description: "Parses user specifications and translates loose prompts into strict acceptance criteria.",
    },
    {
      name: "Context Engine",
      role: "Repository Comprehension",
      status: "MVP Core",
      description: "Extracts AST structures, symbol mappings, configuration, and dependencies across the workspace.",
    },
    {
      name: "Planner",
      role: "Task Graph Synthesis",
      status: "MVP Core",
      description: "Builds a deterministic task plan with explicit verification gates between atomic steps.",
    },
    {
      name: "Task Graph",
      role: "DAG Execution Engine",
      status: "MVP Core",
      description: "Manages state, dependencies, rollback checkpoints, and execution ordering across files.",
    },
    {
      name: "Agent Runtime",
      role: "Adapter Abstraction Layer",
      status: "MVP Core",
      description: "Provides unified execution interfaces to coding agents, starting with OpenCode.",
    },
    {
      name: "Verification Engine",
      role: "Runtime Observation",
      status: "MVP Core",
      description: "Spins up headless Playwright sessions, checks HTTP responses, and validates user flows.",
    },
    {
      name: "Repair Loop",
      role: "Autonomous Correction",
      status: "MVP Core",
      description: "Analyzes assertion failures, generates targeted regression-safe diffs, and re-triggers validation.",
    },
  ];

  const externalIntegrations = [
    {
      name: "GitHub",
      type: "VCS Integration",
      status: "MVP",
      desc: "Branch isolation, automated commit authoring, and verification report PRs.",
    },
    {
      name: "Coding Agents",
      type: "Model Execution",
      status: "MVP: OpenCode | Future: Codex, Claude Code",
      desc: "Orchestrated via standardized adapter layer with isolated working trees.",
    },
    {
      name: "Playwright",
      type: "Browser Automation",
      status: "MVP",
      desc: "Headless Chromium / WebKit validation for UI state and user interactions.",
    },
    {
      name: "MCP (Model Context Protocol)",
      type: "Tool Extensions",
      status: "Roadmap",
      desc: "Standardized tool discovery for database fixtures and cloud resources.",
    },
    {
      name: "Project Runtime",
      type: "Process Supervisor",
      status: "MVP",
      desc: "Local dev servers, build tools (Next.js, Vite), and test runner hooks.",
    },
  ];

  return (
    <section id="architecture" className="py-24 sm:py-32 border-t border-zinc-800/60 relative">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        {/* Section Header */}
        <div className="max-w-3xl mb-16">
          <Badge variant="outline" className="mb-4">
            System Topology
          </Badge>
          <h2 className="text-3xl sm:text-4xl lg:text-5xl font-bold tracking-tight text-zinc-100 leading-tight">
            Designed as an engineering layer,{" "}
            <span className="text-zinc-500 block">not a simple prompt wrapper.</span>
          </h2>
          <p className="mt-4 text-base sm:text-lg text-zinc-400">
            Contexer coordinates coding agents, project context, runtime observation, and verification
            through a modular architecture. Here is how the subsystems interact.
          </p>
        </div>

        {/* Technical Architecture Canvas */}
        <div className="p-6 sm:p-10 rounded-2xl bg-[#0a0b0e] border border-zinc-800/90 shadow-2xl relative font-mono">
          {/* Top Level: User Intent */}
          <div className="flex flex-col items-center">
            <div className="px-6 py-3 rounded-lg bg-zinc-900 border border-zinc-700 text-zinc-100 font-semibold text-xs sm:text-sm flex items-center gap-2 shadow-lg">
              <Terminal className="w-4 h-4 text-cyan-400" />
              <span>Developer Intent &amp; Engineering Outcome</span>
            </div>
            <div className="h-8 w-px bg-zinc-700 my-1 relative">
              <span className="absolute -bottom-1 -left-[3px] text-zinc-500 text-[10px]">▼</span>
            </div>
          </div>

          {/* Contexer Engine Box */}
          <div className="mt-2 p-6 sm:p-8 rounded-xl bg-zinc-950 border-2 border-cyan-900/60 relative">
            <div className="flex items-center justify-between mb-6 pb-4 border-b border-zinc-800/80">
              <div className="flex items-center gap-2.5">
                <div className="w-7 h-7 rounded bg-cyan-950/80 border border-cyan-800 flex items-center justify-center">
                  <Workflow className="w-4 h-4 text-cyan-400" />
                </div>
                <span className="text-sm font-bold text-zinc-100">CONTEXER CORE ENGINE</span>
              </div>
              <Badge variant="cyan" className="text-[10px]">Autonomous Orchestration Layer</Badge>
            </div>

            {/* Core Subsystem Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
              {coreEngines.slice(0, 4).map((engine) => (
                <div
                  key={engine.name}
                  className="p-3.5 rounded-lg bg-zinc-900/70 border border-zinc-800 hover:border-zinc-700 transition-colors"
                >
                  <div className="flex items-center justify-between text-xs mb-1">
                    <span className="font-bold text-zinc-200">{engine.name}</span>
                  </div>
                  <div className="text-[11px] text-cyan-400 mb-1">{engine.role}</div>
                  <p className="text-[11px] text-zinc-400 font-sans leading-relaxed">
                    {engine.description}
                  </p>
                </div>
              ))}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mt-3">
              {coreEngines.slice(4).map((engine) => (
                <div
                  key={engine.name}
                  className="p-3.5 rounded-lg bg-zinc-900/70 border border-zinc-800 hover:border-zinc-700 transition-colors"
                >
                  <div className="flex items-center justify-between text-xs mb-1">
                    <span className="font-bold text-zinc-200">{engine.name}</span>
                  </div>
                  <div className="text-[11px] text-violet-400 mb-1">{engine.role}</div>
                  <p className="text-[11px] text-zinc-400 font-sans leading-relaxed">
                    {engine.description}
                  </p>
                </div>
              ))}
            </div>
          </div>

          {/* Connection Line */}
          <div className="flex flex-col items-center">
            <div className="h-8 w-px bg-zinc-700 my-1 relative">
              <span className="absolute -bottom-1 -left-[3px] text-zinc-500 text-[10px]">▼</span>
            </div>
            <div className="text-[10px] text-zinc-500 uppercase tracking-widest my-1">
              External Runtime &amp; Infrastructure Adapters
            </div>
          </div>

          {/* External Integrations Grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3 mt-2">
            {externalIntegrations.map((item) => {
              const isRoadmap = item.status === "Roadmap";
              return (
                <div
                  key={item.name}
                  className={`p-4 rounded-xl border transition-all ${
                    isRoadmap
                      ? "bg-zinc-950/50 border-zinc-800/60 opacity-80"
                      : "bg-zinc-900/50 border-zinc-800"
                  }`}
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-bold text-zinc-200">{item.name}</span>
                    <span
                      className={`text-[9px] px-1.5 py-0.5 rounded uppercase font-mono ${
                        isRoadmap
                          ? "bg-zinc-800 text-zinc-400 border border-zinc-700"
                          : "bg-emerald-950/80 text-emerald-400 border border-emerald-800/80"
                      }`}
                    >
                      {item.status.includes("MVP") ? "MVP" : "Roadmap"}
                    </span>
                  </div>
                  <div className="text-[10px] text-zinc-400 font-sans">{item.desc}</div>
                </div>
              );
            })}
          </div>
        </div>

        {/* MVP Honesty Note */}
        <div className="mt-8 p-4 rounded-xl bg-zinc-900/30 border border-zinc-800/80 flex items-start gap-3 text-xs text-zinc-400 font-mono">
          <span className="text-cyan-400 font-bold">NOTE:</span>
          <span>
            Contexer clearly separates its current MVP implementation (OpenCode execution adapter, AST-based context graph,
            local runtime supervisor, and Playwright verification harness) from future architectural expansions such as
            distributed MCP multi-agent swarms.
          </span>
        </div>
      </div>
    </section>
  );
}
