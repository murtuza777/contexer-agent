"use client";

import React, { useState } from "react";
import { Copy, Check, CornerDownLeft, CheckCircle2 } from "lucide-react";
import { Badge } from "@/components/ui/Badge";

export function DevExperience() {
  const [approved, setApproved] = useState<boolean>(false);
  const [copied, setCopied] = useState<boolean>(false);

  const handleCopy = () => {
    navigator.clipboard.writeText("contexer");
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <section id="cli-experience" className="py-24 sm:py-32 border-t border-zinc-800/60 relative">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="max-w-3xl mb-16">
          <Badge variant="outline" className="mb-4">
            Command Line Native
          </Badge>
          <h2 className="text-3xl sm:text-4xl lg:text-5xl font-bold tracking-tight text-zinc-100 leading-tight">
            Designed for the terminal.{" "}
            <span className="text-zinc-500 block">
              Works directly in your existing repository.
            </span>
          </h2>
          <p className="mt-4 text-base sm:text-lg text-zinc-400">
            No bloated web IDEs to adopt. No proprietary editors. Launch Contexer directly in any terminal
            session. It understands your codebase, presents the plan, and executes autonomously.
          </p>
        </div>

        {/* Realistic Terminal Experience Card */}
        <div className="max-w-4xl mx-auto rounded-2xl border border-zinc-800 bg-[#090a0f] shadow-2xl overflow-hidden font-mono text-xs sm:text-sm">
          {/* Header Bar */}
          <div className="flex items-center justify-between px-4 py-3 bg-zinc-900 border-b border-zinc-800/80">
            <div className="flex items-center gap-2">
              <div className="flex gap-1.5">
                <div className="w-3 h-3 rounded-full bg-zinc-700" />
                <div className="w-3 h-3 rounded-full bg-zinc-700" />
                <div className="w-3 h-3 rounded-full bg-zinc-700" />
              </div>
              <span className="ml-2 text-zinc-400 text-xs">zsh — ~/workspace/next-saas</span>
            </div>

            <button
              type="button"
              onClick={handleCopy}
              className="flex items-center gap-1.5 px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-xs transition-colors"
            >
              {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
              <span>{copied ? "Copied" : "Copy CLI"}</span>
            </button>
          </div>

          {/* Interactive Shell Body */}
          <div className="p-6 sm:p-8 space-y-4 text-zinc-300">
            {/* Step 1: Launch command */}
            <div className="flex items-center gap-2 text-zinc-100 font-bold">
              <span className="text-zinc-500">$</span>
              <span>contexer</span>
            </div>

            {/* Prompt Question */}
            <div className="text-zinc-400">
              <span className="text-cyan-400 font-bold">?</span> What do you want to build?
            </div>

            {/* User Input */}
            <div className="pl-4 py-1 text-cyan-300 bg-zinc-900/60 rounded border border-zinc-800/60 flex items-center justify-between">
              <span>&gt; Add authentication and a dashboard to this project.</span>
              <CornerDownLeft className="w-3.5 h-3.5 text-zinc-500 mr-2" />
            </div>

            {/* Analysis & Plan Generation */}
            <div className="space-y-1.5 text-zinc-400 text-xs pt-2">
              <div className="flex items-center gap-2">
                <span className="text-cyan-400">ℹ</span>
                <span>Analyzing repository AST &amp; symbols (58 files scanned)...</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-cyan-400">ℹ</span>
                <span>Synthesizing dependency DAG...</span>
              </div>
            </div>

            {/* Structured Plan */}
            <div className="p-4 rounded-xl bg-zinc-950 border border-zinc-800/80 space-y-2">
              <div className="text-xs font-bold text-zinc-200 tracking-wider">ENGINEERING PLAN:</div>
              <ol className="list-decimal list-inside space-y-1.5 text-xs text-zinc-300">
                <li>
                  <span className="font-semibold text-zinc-100">Authentication</span>{" "}
                  <span className="text-zinc-500">— OAuth 2.0 provider integration and session cookies</span>
                </li>
                <li>
                  <span className="font-semibold text-zinc-100">Dashboard</span>{" "}
                  <span className="text-zinc-500">— Responsive layout with key KPI metrics</span>
                </li>
                <li>
                  <span className="font-semibold text-zinc-100">Session Management</span>{" "}
                  <span className="text-zinc-500">— Token refresh interceptor &amp; protected routing</span>
                </li>
                <li>
                  <span className="font-semibold text-zinc-100">E2E Verification</span>{" "}
                  <span className="text-zinc-500">— Playwright headless assertion suite on /dashboard</span>
                </li>
              </ol>
            </div>

            {/* Interactive Approval Prompt */}
            <div className="pt-2 flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-t border-zinc-800/80">
              <div className="flex items-center gap-2">
                <span className="text-amber-400 font-bold">?</span>
                <span className="font-bold text-zinc-100">Approve plan?</span>
                <span className="text-zinc-500">[Y/n]</span>
                <span className="text-emerald-400 font-bold pl-1">{approved ? "Y" : ""}</span>
              </div>

              {!approved ? (
                <button
                  type="button"
                  onClick={() => setApproved(true)}
                  className="px-3 py-1.5 rounded bg-emerald-950 border border-emerald-700 text-emerald-300 hover:bg-emerald-900 text-xs font-bold transition-all flex items-center gap-1.5 self-start sm:self-auto"
                >
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                  <span>Simulate Approve (Press Y)</span>
                </button>
              ) : (
                <div className="flex items-center gap-2 text-emerald-400 text-xs">
                  <CheckCircle2 className="w-4 h-4" />
                  <span>Execution loop started autonomously in background</span>
                </div>
              )}
            </div>

            {approved && (
              <div className="p-3 bg-cyan-950/30 border border-cyan-900/50 rounded-lg text-xs text-cyan-300 animate-in fade-in duration-300">
                &gt;&gt; Contexer spawned headless Chromium verification session. Watching dev server on localhost:3000...
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
