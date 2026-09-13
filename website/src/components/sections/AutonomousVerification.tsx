"use client";

import React, { useState } from "react";
import {
  ShieldCheck,
  AlertOctagon,
  RotateCw,
  CheckCircle2,
  Play,
} from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";

export function AutonomousVerification() {
  const [repairState, setRepairState] = useState<"failed" | "repairing" | "passed">("failed");

  const runRepair = () => {
    setRepairState("repairing");
    setTimeout(() => {
      setRepairState("passed");
    }, 1200);
  };

  const resetState = () => {
    setRepairState("failed");
  };

  return (
    <section className="py-24 sm:py-32 border-t border-zinc-800/60 relative bg-zinc-950/40">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        {/* Section Header */}
        <div className="max-w-3xl mb-16">
          <Badge variant="cyan" className="mb-4">
            Autonomous Verification Engine
          </Badge>
          <h2 className="text-3xl sm:text-4xl lg:text-5xl font-bold tracking-tight text-zinc-100 leading-tight">
            Expected vs. Observed.{" "}
            <span className="text-zinc-500 block">
              Contexer detects the mismatch and fixes it.
            </span>
          </h2>
          <p className="mt-4 text-base sm:text-lg text-zinc-400">
            A coding agent might write syntactically valid code that compiles, yet fails completely in the real
            user journey. Contexer operates a headless browser runtime to verify ground truth before marking
            any task complete.
          </p>
        </div>

        {/* Expected vs Observed Comparison Panels */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 items-stretch">
          {/* Expected Behavior */}
          <Card className="p-6 sm:p-8 bg-zinc-900/50 border-zinc-800 flex flex-col justify-between">
            <div>
              <div className="flex items-center justify-between mb-6">
                <div className="flex items-center gap-2">
                  <ShieldCheck className="w-5 h-5 text-emerald-400" />
                  <span className="font-mono font-bold text-zinc-200">EXPECTED BEHAVIOR</span>
                </div>
                <Badge variant="success">Specification</Badge>
              </div>

              <div className="p-4 rounded-lg bg-zinc-950/80 border border-zinc-800/80 font-mono text-xs sm:text-sm text-zinc-300 space-y-3">
                <div className="text-emerald-400 font-semibold">
                  Assertion: User logs in → dashboard opens
                </div>
                <div className="space-y-2 text-zinc-400 pl-2 border-l border-zinc-800">
                  <div className="flex items-center gap-2">
                    <span className="text-zinc-500">1.</span>
                    <span>POST /api/auth/callback/credentials</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-zinc-500">2.</span>
                    <span>Session cookie <code className="text-zinc-300">__Secure-auth.session</code> set</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-zinc-500">3.</span>
                    <span>Browser navigates to <code className="text-zinc-300">/dashboard</code></span>
                  </div>
                  <div className="flex items-center gap-2 text-emerald-300">
                    <span className="text-zinc-500">4.</span>
                    <span>DOM renders <code className="text-emerald-400">&lt;DashboardView /&gt;</code></span>
                  </div>
                </div>
              </div>

              <div className="mt-6 text-xs text-zinc-400 leading-relaxed">
                Derived directly from developer intent: authentication flow must successfully authenticate
                and grant access to the protected workspace view.
              </div>
            </div>

            <div className="mt-8 pt-4 border-t border-zinc-800/80 flex items-center gap-2 text-xs font-mono text-zinc-400">
              <span className="w-2 h-2 rounded-full bg-emerald-400" />
              <span>Target Acceptance Standard</span>
            </div>
          </Card>

          {/* Observed Behavior (Live Playwright Capture) */}
          <Card
            className={`p-6 sm:p-8 flex flex-col justify-between transition-all duration-300 ${
              repairState === "passed"
                ? "bg-zinc-900/60 border-emerald-800/70"
                : "bg-zinc-900/50 border-rose-900/70 shadow-[0_0_20px_rgba(244,63,94,0.08)]"
            }`}
          >
            <div>
              <div className="flex items-center justify-between mb-6">
                <div className="flex items-center gap-2">
                  {repairState === "passed" ? (
                    <CheckCircle2 className="w-5 h-5 text-emerald-400" />
                  ) : (
                    <AlertOctagon className="w-5 h-5 text-rose-400" />
                  )}
                  <span className="font-mono font-bold text-zinc-200">OBSERVED RUNTIME BEHAVIOR</span>
                </div>
                {repairState === "passed" ? (
                  <Badge variant="success">Repaired &amp; Verified</Badge>
                ) : (
                  <Badge variant="danger">Mismatch Detected</Badge>
                )}
              </div>

              <div className="p-4 rounded-lg bg-zinc-950/90 border border-zinc-800 font-mono text-xs sm:text-sm text-zinc-300 space-y-3">
                <div
                  className={`font-semibold ${
                    repairState === "passed" ? "text-emerald-400" : "text-rose-400"
                  }`}
                >
                  {repairState === "passed"
                    ? "Result: Login succeeds → dashboard opens (PASS)"
                    : "Observed: Login succeeds → dashboard remains inaccessible"}
                </div>

                <div className="space-y-2 text-zinc-400 pl-2 border-l border-zinc-800">
                  <div className="flex items-center gap-2">
                    <span className="text-zinc-500">1.</span>
                    <span>POST /api/auth/callback/credentials → 200 OK</span>
                  </div>
                  {repairState === "passed" ? (
                    <>
                      <div className="flex items-center gap-2 text-emerald-400">
                        <span className="text-zinc-500">2.</span>
                        <span>Middleware parsed session token correctly</span>
                      </div>
                      <div className="flex items-center gap-2 text-emerald-400">
                        <span className="text-zinc-500">3.</span>
                        <span>Redirect to /dashboard → HTTP 200 OK</span>
                      </div>
                      <div className="flex items-center gap-2 text-emerald-400 font-bold">
                        <span className="text-zinc-500">4.</span>
                        <span>✓ Assertion passed (0 regressions)</span>
                      </div>
                    </>
                  ) : (
                    <>
                      <div className="flex items-center gap-2 text-rose-300">
                        <span className="text-zinc-500">2.</span>
                        <span>Middleware 307 Redirect loop to /login?error=403</span>
                      </div>
                      <div className="flex items-center gap-2 text-rose-400 font-semibold">
                        <span className="text-zinc-500">3.</span>
                        <span>Dashboard inaccessible: HTTP 403 Forbidden</span>
                      </div>
                      <div className="text-[11px] text-rose-400/80 bg-rose-950/40 p-2 rounded border border-rose-900/60 mt-2">
                        Playwright timeout: page.waitForSelector(&apos;[data-testid=&quot;dashboard&quot;]&apos;) exceeded 4000ms
                      </div>
                    </>
                  )}
                </div>
              </div>

              <div className="mt-6 text-xs text-zinc-400 leading-relaxed">
                {repairState === "passed"
                  ? "Contexer automatically identified the middleware cookie parsing flaw, applied the patch, rebuilt the runtime, and re-executed Playwright assertions."
                  : "A traditional coding assistant would say 'Done!' here. Contexer intercepts the mismatch, blocks exit, and triggers an autonomous repair task."}
              </div>
            </div>

            {/* Interactive Repair Control */}
            <div className="mt-8 pt-4 border-t border-zinc-800/80 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div className="text-xs font-mono text-zinc-400">
                {repairState === "failed" && "Status: Autonomous Repair Triggered"}
                {repairState === "repairing" && "Status: Synthesizing fix diff..."}
                {repairState === "passed" && "Status: Verified Green"}
              </div>

              {repairState === "failed" && (
                <Button size="sm" variant="secondary" onClick={runRepair} className="font-mono text-xs">
                  <Play className="w-3.5 h-3.5 mr-1 text-cyan-400" />
                  Simulate Self-Repair
                </Button>
              )}
              {repairState === "repairing" && (
                <Button size="sm" variant="secondary" disabled className="font-mono text-xs">
                  <RotateCw className="w-3.5 h-3.5 mr-1 animate-spin text-amber-400" />
                  Patching &amp; Verifying...
                </Button>
              )}
              {repairState === "passed" && (
                <Button size="sm" variant="outline" onClick={resetState} className="font-mono text-xs">
                  <RotateCw className="w-3.5 h-3.5 mr-1" />
                  Reset Demo
                </Button>
              )}
            </div>
          </Card>
        </div>

        {/* The Diagnostic Flow explanation */}
        <div className="mt-12 p-6 rounded-xl bg-zinc-950 border border-zinc-800/80">
          <div className="text-xs font-mono text-cyan-400 font-bold uppercase mb-3">
            The Contexer Self-Repair Protocol
          </div>
          <p className="text-sm text-zinc-300 leading-relaxed">
            When Contexer detects a verification mismatch, it does not prompt the human for assistance.
            Instead, it passes the failure stack trace, DOM snapshot, and network log back to the
            <strong> Context Engine</strong> to isolate the faulty code segment. The
            <strong> Agent Adapter</strong> produces a surgical repair diff, which is re-tested in an isolated runtime
            before any commit is accepted.
          </p>
        </div>
      </div>
    </section>
  );
}
