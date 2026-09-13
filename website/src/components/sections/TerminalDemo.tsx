"use client";

import React, { useState, useEffect, useRef } from "react";
import {
  Play,
  RotateCcw,
  CheckCircle2,
  XCircle,
  Wrench,
  Copy,
  Check,
  Cpu,
  Layers,
  Activity,
  Terminal as TerminalIcon,
} from "lucide-react";

interface StepLog {
  id: string;
  type: "command" | "status" | "plan" | "exec" | "verify" | "fail" | "repair" | "pass" | "done";
  text: string;
  subtext?: string;
  duration?: string;
}

const TERMINAL_SEQUENCE: StepLog[] = [
  {
    id: "init",
    type: "command",
    text: "$ contexer",
    subtext: "Initializing Contexer autonomous runtime [PID: 38419]",
  },
  {
    id: "prompt",
    type: "command",
    text: "> Build a responsive dashboard with authentication and analytics.",
    duration: "40ms",
  },
  {
    id: "context",
    type: "status",
    text: "Understanding project AST & dependencies...",
    subtext: "Indexed 42 files, 3 route groups, Tailwind v4, NextAuth config",
    duration: "210ms",
  },
  {
    id: "plan-start",
    type: "status",
    text: "Creating engineering plan DAG...",
    duration: "180ms",
  },
  {
    id: "plan-1",
    type: "plan",
    text: "✓ Authentication (NextAuth session guard & JWT refresh)",
  },
  {
    id: "plan-2",
    type: "plan",
    text: "✓ Dashboard (Metrics grid & transaction feed)",
  },
  {
    id: "plan-3",
    type: "plan",
    text: "✓ Analytics (SVG sparklines & timeframe filter)",
  },
  {
    id: "plan-4",
    type: "plan",
    text: "✓ Responsive UI (Drawer toggle & mobile viewport layout)",
  },
  {
    id: "exec",
    type: "exec",
    text: "Executing changes via OpenCode adapter...",
    subtext: "Generated 3 components, updated 2 route handlers, added mock store",
    duration: "1.4s",
  },
  {
    id: "verify",
    type: "verify",
    text: "Running autonomous verification...",
    subtext: "Spun up headless Chromium via Playwright (390x844 & 1440x900)",
  },
  {
    id: "fail",
    type: "fail",
    text: "✗ Dashboard mobile navigation failed",
    subtext: "AssertionError: Element <button aria-label='Toggle menu'> not clickable at viewport (390px) due to z-index collision",
  },
  {
    id: "repair",
    type: "repair",
    text: "Repairing...",
    subtext: "Contexer patch applied: z-index elevated from z-10 to z-50 in Header.tsx; re-running Playwright verification harness",
  },
  {
    id: "pass",
    type: "pass",
    text: "✓ Verification passed",
    subtext: "All assertions satisfied across mobile and desktop runtimes (0 errors, 14 checks passed)",
  },
  {
    id: "done",
    type: "done",
    text: "✓ Task complete",
    subtext: "Closed loop in 4.8s. Working tree clean. Ready for review.",
  },
];

export function TerminalDemo() {
  const [activeStepIndex, setActiveStepIndex] = useState<number>(0);
  const [isPlaying, setIsPlaying] = useState<boolean>(true);
  const [activeTab, setActiveTab] = useState<"terminal" | "dag" | "telemetry">("terminal");
  const [copied, setCopied] = useState<boolean>(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!isPlaying) return;

    if (activeStepIndex < TERMINAL_SEQUENCE.length - 1) {
      const delay =
        activeStepIndex === 1
          ? 700
          : activeStepIndex === 8
          ? 1000
          : activeStepIndex === 10
          ? 1200
          : 550;

      const timer = setTimeout(() => {
        setActiveStepIndex((prev) => prev + 1);
      }, delay);

      return () => clearTimeout(timer);
    } else {
      // Loop after a pause
      const loopTimer = setTimeout(() => {
        setActiveStepIndex(0);
      }, 4500);
      return () => clearTimeout(loopTimer);
    }
  }, [activeStepIndex, isPlaying]);

  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [activeStepIndex]);

  const handleRestart = () => {
    setActiveStepIndex(0);
    setIsPlaying(true);
  };

  const handleCopy = () => {
    navigator.clipboard.writeText("contexer --intent 'Build a responsive dashboard with authentication and analytics.'");
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const visibleSteps = TERMINAL_SEQUENCE.slice(0, activeStepIndex + 1);

  return (
    <div className="w-full max-w-4xl mx-auto rounded-xl border border-zinc-800 bg-[#0c0d12] shadow-2xl overflow-hidden font-mono text-xs sm:text-sm">
      {/* Terminal Title Bar */}
      <div className="flex items-center justify-between px-4 py-3 bg-zinc-900/90 border-b border-zinc-800/80">
        <div className="flex items-center gap-2">
          <div className="flex gap-1.5">
            <div className="w-3 h-3 rounded-full bg-zinc-700/80 hover:bg-rose-500 transition-colors" />
            <div className="w-3 h-3 rounded-full bg-zinc-700/80 hover:bg-amber-500 transition-colors" />
            <div className="w-3 h-3 rounded-full bg-zinc-700/80 hover:bg-emerald-500 transition-colors" />
          </div>
          <span className="ml-2 text-zinc-400 text-xs hidden sm:inline-block font-sans font-medium">
            contexer — autonomous-loop: session_#892
          </span>
        </div>

        {/* Tab switcher */}
        <div className="flex items-center bg-zinc-950 p-0.5 rounded-lg border border-zinc-800 text-xs font-mono">
          <button
            type="button"
            onClick={() => setActiveTab("terminal")}
            className={`px-2.5 py-1 rounded transition-colors flex items-center gap-1.5 ${
              activeTab === "terminal"
                ? "bg-zinc-800 text-zinc-100 shadow-sm"
                : "text-zinc-400 hover:text-zinc-200"
            }`}
          >
            <TerminalIcon className="w-3 h-3 text-cyan-400" />
            <span>Live Session</span>
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("dag")}
            className={`px-2.5 py-1 rounded transition-colors flex items-center gap-1.5 ${
              activeTab === "dag"
                ? "bg-zinc-800 text-zinc-100 shadow-sm"
                : "text-zinc-400 hover:text-zinc-200"
            }`}
          >
            <Layers className="w-3 h-3 text-violet-400" />
            <span>Plan DAG</span>
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("telemetry")}
            className={`px-2.5 py-1 rounded transition-colors flex items-center gap-1.5 hidden sm:flex ${
              activeTab === "telemetry"
                ? "bg-zinc-800 text-zinc-100 shadow-sm"
                : "text-zinc-400 hover:text-zinc-200"
            }`}
          >
            <Activity className="w-3 h-3 text-emerald-400" />
            <span>Verification Log</span>
          </button>
        </div>

        {/* Playback Controls */}
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => setIsPlaying(!isPlaying)}
            className="p-1.5 text-zinc-400 hover:text-zinc-100 rounded hover:bg-zinc-800 transition-colors"
            title={isPlaying ? "Pause simulation" : "Play simulation"}
            aria-label={isPlaying ? "Pause simulation" : "Play simulation"}
          >
            <Play className={`w-3.5 h-3.5 ${isPlaying ? "text-cyan-400" : "text-zinc-400"}`} />
          </button>
          <button
            type="button"
            onClick={handleRestart}
            className="p-1.5 text-zinc-400 hover:text-zinc-100 rounded hover:bg-zinc-800 transition-colors"
            title="Restart simulation"
            aria-label="Restart simulation"
          >
            <RotateCcw className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            onClick={handleCopy}
            className="p-1.5 text-zinc-400 hover:text-zinc-100 rounded hover:bg-zinc-800 transition-colors"
            title="Copy command"
            aria-label="Copy command"
          >
            {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
          </button>
        </div>
      </div>

      {/* Terminal Body */}
      {activeTab === "terminal" && (
        <div
          ref={containerRef}
          className="p-5 sm:p-6 min-h-[380px] max-h-[440px] overflow-y-auto space-y-2.5 scrollbar-thin scrollbar-thumb-zinc-800"
        >
          {visibleSteps.map((step) => {
            if (step.id === "init") {
              return (
                <div key={step.id} className="pb-1 border-b border-zinc-900 flex items-center justify-between text-zinc-400">
                  <div className="text-zinc-200 font-bold">{step.text}</div>
                  <span className="text-[11px] text-zinc-500">{step.subtext}</span>
                </div>
              );
            }

            if (step.id === "prompt") {
              return (
                <div key={step.id} className="py-1">
                  <div className="flex items-center gap-2 text-cyan-300 font-semibold">
                    <span className="text-cyan-400 select-none">&gt;</span>
                    <span>Build a responsive dashboard with authentication and analytics.</span>
                  </div>
                </div>
              );
            }

            if (step.type === "status") {
              return (
                <div key={step.id} className="text-zinc-400 pl-3 border-l-2 border-zinc-800 flex items-center gap-2">
                  <span className="inline-block w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse" />
                  <span>{step.text}</span>
                  {step.duration && <span className="text-[11px] text-zinc-600">({step.duration})</span>}
                </div>
              );
            }

            if (step.type === "plan") {
              return (
                <div key={step.id} className="pl-6 text-zinc-300 flex items-center gap-2">
                  <CheckCircle2 className="w-3.5 h-3.5 text-cyan-400 shrink-0" />
                  <span>{step.text.replace("✓ ", "")}</span>
                </div>
              );
            }

            if (step.type === "exec") {
              return (
                <div key={step.id} className="text-zinc-300 py-1 pl-3 border-l-2 border-violet-800/80">
                  <div className="flex items-center gap-2">
                    <Cpu className="w-3.5 h-3.5 text-violet-400" />
                    <span className="font-semibold text-violet-300">{step.text}</span>
                    {step.duration && <span className="text-[11px] text-zinc-500">[{step.duration}]</span>}
                  </div>
                  {step.subtext && <div className="text-zinc-500 text-xs pl-5 mt-0.5">{step.subtext}</div>}
                </div>
              );
            }

            if (step.type === "verify") {
              return (
                <div key={step.id} className="text-zinc-300 pl-3 border-l-2 border-cyan-800/80 py-1">
                  <div className="flex items-center gap-2 text-cyan-200">
                    <Activity className="w-3.5 h-3.5 text-cyan-400" />
                    <span>{step.text}</span>
                  </div>
                  {step.subtext && <div className="text-zinc-500 text-xs pl-5 mt-0.5">{step.subtext}</div>}
                </div>
              );
            }

            if (step.type === "fail") {
              return (
                <div key={step.id} className="bg-rose-950/40 border border-rose-900/60 rounded-md p-2.5 my-1 text-rose-300">
                  <div className="flex items-center gap-2 font-semibold">
                    <XCircle className="w-4 h-4 text-rose-400 shrink-0" />
                    <span>{step.text}</span>
                  </div>
                  {step.subtext && (
                    <div className="text-rose-400/90 text-xs mt-1 pl-6 font-mono break-all">
                      {step.subtext}
                    </div>
                  )}
                </div>
              );
            }

            if (step.type === "repair") {
              return (
                <div key={step.id} className="bg-amber-950/30 border border-amber-900/50 rounded-md p-2.5 my-1 text-amber-200">
                  <div className="flex items-center gap-2 font-semibold">
                    <Wrench className="w-4 h-4 text-amber-400 animate-spin-slow" />
                    <span>{step.text}</span>
                  </div>
                  {step.subtext && (
                    <div className="text-amber-300/80 text-xs mt-1 pl-6 font-mono">
                      {step.subtext}
                    </div>
                  )}
                </div>
              );
            }

            if (step.type === "pass") {
              return (
                <div key={step.id} className="bg-emerald-950/40 border border-emerald-900/60 rounded-md p-2.5 my-1 text-emerald-300">
                  <div className="flex items-center gap-2 font-semibold">
                    <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                    <span>{step.text}</span>
                  </div>
                  {step.subtext && (
                    <div className="text-emerald-400/80 text-xs mt-1 pl-6 font-mono">
                      {step.subtext}
                    </div>
                  )}
                </div>
              );
            }

            if (step.type === "done") {
              return (
                <div key={step.id} className="pt-2 border-t border-zinc-800/80 flex items-center justify-between text-emerald-400">
                  <div className="flex items-center gap-2 font-bold">
                    <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                    <span>{step.text}</span>
                  </div>
                  <span className="text-xs text-zinc-500 font-mono">{step.subtext}</span>
                </div>
              );
            }

            return null;
          })}

          {/* Blinking Cursor */}
          {activeStepIndex < TERMINAL_SEQUENCE.length - 1 && (
            <div className="flex items-center gap-1 text-cyan-400 mt-2">
              <span className="inline-block w-2 h-4 bg-cyan-400 animate-pulse" />
            </div>
          )}
        </div>
      )}

      {/* Plan DAG Tab */}
      {activeTab === "dag" && (
        <div className="p-5 sm:p-6 min-h-[380px] space-y-4">
          <div className="text-xs text-zinc-400 font-sans mb-3">
            Autonomous Dependency Graph synthesized by Contexer Planner:
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="p-3 rounded-lg border border-emerald-800/60 bg-emerald-950/20">
              <div className="flex items-center justify-between text-emerald-400 text-xs font-semibold mb-1">
                <span>TASK-1: Auth Layer</span>
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-900/60">VERIFIED</span>
              </div>
              <p className="text-zinc-400 text-xs font-sans">
                NextAuth session middleware, JWT signature validator, route protection.
              </p>
            </div>
            <div className="p-3 rounded-lg border border-emerald-800/60 bg-emerald-950/20">
              <div className="flex items-center justify-between text-emerald-400 text-xs font-semibold mb-1">
                <span>TASK-2: Metrics Grid</span>
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-900/60">VERIFIED</span>
              </div>
              <p className="text-zinc-400 text-xs font-sans">
                4-tile stats breakdown with delta comparisons, currency formatting, SSR caching.
              </p>
            </div>
            <div className="p-3 rounded-lg border border-emerald-800/60 bg-emerald-950/20">
              <div className="flex items-center justify-between text-emerald-400 text-xs font-semibold mb-1">
                <span>TASK-3: Analytics Chart</span>
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-900/60">VERIFIED</span>
              </div>
              <p className="text-zinc-400 text-xs font-sans">
                Zero-dependency SVG area sparklines with interactive hover tooltips.
              </p>
            </div>
            <div className="p-3 rounded-lg border border-amber-800/60 bg-amber-950/20">
              <div className="flex items-center justify-between text-amber-400 text-xs font-semibold mb-1">
                <span>TASK-4: Responsive Drawer</span>
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-900/60">SELF-REPAIRED</span>
              </div>
              <p className="text-zinc-400 text-xs font-sans">
                Fixed z-index collision on 390px viewport after Playwright assertion failure.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Verification Log Tab */}
      {activeTab === "telemetry" && (
        <div className="p-5 sm:p-6 min-h-[380px] space-y-3 font-mono text-xs">
          <div className="text-zinc-400 mb-2">Playwright Headless Observation Telemetry:</div>
          <div className="p-3 bg-zinc-950 rounded-lg border border-zinc-800 text-zinc-300 space-y-1.5">
            <div>[00:01.210] RUN  test/e2e/auth-flow.spec.ts:14:1</div>
            <div className="text-emerald-400 pl-4">✓ [chromium] › auth-flow › user redirected to dashboard after signin (312ms)</div>
            <div>[00:02.404] RUN  test/e2e/responsive-nav.spec.ts:22:1 (viewport: 390x844)</div>
            <div className="text-rose-400 pl-4">✗ [chromium] › responsive-nav › mobile drawer overlay clickable (timed out 800ms)</div>
            <div className="text-amber-400 pl-6">&gt;&gt; Contexer Intercept: auto-repair triggered (patching Header.tsx:L42)</div>
            <div>[00:03.950] RETRY test/e2e/responsive-nav.spec.ts:22:1 (patch applied)</div>
            <div className="text-emerald-400 pl-4">✓ [chromium] › responsive-nav › mobile drawer overlay clickable (142ms)</div>
            <div className="pt-2 text-zinc-500 border-t border-zinc-900">
              Verification harness status: 100% tests passing, loop closed autonomously.
            </div>
          </div>
        </div>
      )}

      {/* Terminal Footer Info */}
      <div className="flex items-center justify-between px-4 py-2 bg-zinc-950 border-t border-zinc-800/80 text-[11px] text-zinc-500">
        <div className="flex items-center gap-3">
          <span className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-emerald-400" />
            <span>Runtime: Playwright Headless</span>
          </span>
          <span className="hidden sm:inline-block">|</span>
          <span className="hidden sm:inline-block">Agent Backend: OpenCode Adapter</span>
        </div>
        <div className="font-mono">
          Step {activeStepIndex + 1} of {TERMINAL_SEQUENCE.length}
        </div>
      </div>
    </div>
  );
}
