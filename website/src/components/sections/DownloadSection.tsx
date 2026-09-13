"use client";

import React, { useState } from "react";
import { Copy, Check, Apple, Monitor, Laptop, AlertCircle } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";

type Platform = "macos" | "linux" | "windows";

export function DownloadSection() {
  const [platform, setPlatform] = useState<Platform>("macos");
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);

  const installCommands: Record<Platform, { title: string; manager: string; cmd: string }[]> = {
    macos: [
      {
        title: "Homebrew (Recommended)",
        manager: "brew",
        cmd: "brew tap contexer/tap && brew install contexer",
      },
      {
        title: "Standalone Shell Installer",
        manager: "curl",
        cmd: "curl -fsSL https://contexer.dev/install.sh | sh",
      },
      {
        title: "Python Package (uv)",
        manager: "uv",
        cmd: "uv tool install contexer",
      },
    ],
    linux: [
      {
        title: "Standalone Shell Installer (Recommended)",
        manager: "curl",
        cmd: "curl -fsSL https://contexer.dev/install.sh | sh",
      },
      {
        title: "Python Package (uv / pip)",
        manager: "uv",
        cmd: "uv tool install contexer",
      },
      {
        title: "Debian / Ubuntu Package",
        manager: "apt",
        cmd: "curl -fsSL https://contexer.dev/apt/gpg.key | sudo apt-key add - && sudo apt-get install contexer",
      },
    ],
    windows: [
      {
        title: "Windows Package Manager",
        manager: "winget",
        cmd: "winget install Contexer.Contexer",
      },
      {
        title: "Python Package (pip / uv)",
        manager: "pip",
        cmd: "pip install contexer",
      },
      {
        title: "PowerShell One-Liner",
        manager: "pwsh",
        cmd: "irm https://contexer.dev/install.ps1 | iex",
      },
    ],
  };

  const handleCopy = (text: string, index: number) => {
    navigator.clipboard.writeText(text);
    setCopiedIndex(index);
    setTimeout(() => setCopiedIndex(null), 2000);
  };

  return (
    <section id="download" className="py-24 sm:py-32 border-t border-zinc-800/60 relative bg-zinc-950/60">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="max-w-3xl mb-16">
          <Badge variant="cyan" className="mb-4">
            Installation &amp; Distribution
          </Badge>
          <h2 className="text-3xl sm:text-4xl lg:text-5xl font-bold tracking-tight text-zinc-100 leading-tight">
            Download Contexer.{" "}
            <span className="text-zinc-500 block">
              Pre-release developer preview.
            </span>
          </h2>
          <p className="mt-4 text-base sm:text-lg text-zinc-400">
            Contexer is engineered as a lightweight, single-binary CLI tool. Select your target operating
            system to view planned installation methods.
          </p>
        </div>

        {/* Pre-release Notice Banner */}
        <div className="mb-8 p-4 rounded-xl bg-amber-950/20 border border-amber-800/50 flex items-start gap-3 text-xs text-amber-300">
          <AlertCircle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
          <div className="space-y-1">
            <div className="font-bold font-mono">STATUS: PRE-RELEASE ROADMAP (COMING SOON)</div>
            <p className="text-amber-300/80 font-sans">
              The Contexer agent CLI is currently in active architecture development (Milestone 3). Install commands
              shown below represent the forthcoming distribution channels. Star or follow our GitHub repository to receive
              release binary artifacts upon first public release.
            </p>
          </div>
        </div>

        {/* Platform Switcher */}
        <div className="flex items-center gap-2 mb-8 bg-zinc-900/80 p-1 rounded-xl border border-zinc-800 w-fit">
          <button
            type="button"
            onClick={() => setPlatform("macos")}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-mono font-medium transition-all ${
              platform === "macos"
                ? "bg-zinc-800 text-zinc-100 shadow-sm"
                : "text-zinc-400 hover:text-zinc-200"
            }`}
          >
            <Apple className="w-3.5 h-3.5" />
            <span>macOS</span>
          </button>
          <button
            type="button"
            onClick={() => setPlatform("linux")}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-mono font-medium transition-all ${
              platform === "linux"
                ? "bg-zinc-800 text-zinc-100 shadow-sm"
                : "text-zinc-400 hover:text-zinc-200"
            }`}
          >
            <Laptop className="w-3.5 h-3.5" />
            <span>Linux</span>
          </button>
          <button
            type="button"
            onClick={() => setPlatform("windows")}
            className={`flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-mono font-medium transition-all ${
              platform === "windows"
                ? "bg-zinc-800 text-zinc-100 shadow-sm"
                : "text-zinc-400 hover:text-zinc-200"
            }`}
          >
            <Monitor className="w-3.5 h-3.5" />
            <span>Windows</span>
          </button>
        </div>

        {/* Command list */}
        <div className="space-y-4 max-w-4xl">
          {installCommands[platform].map((item, idx) => (
            <Card
              key={item.title}
              className="p-5 bg-zinc-900/60 border-zinc-800/90 flex flex-col sm:flex-row sm:items-center justify-between gap-4"
            >
              <div className="space-y-1.5 flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-bold font-mono text-zinc-200">{item.title}</span>
                  <span className="text-[10px] px-1.5 py-0.2 rounded bg-zinc-800 text-zinc-400 font-mono">
                    {item.manager}
                  </span>
                  <span className="text-[10px] px-1.5 py-0.2 rounded bg-amber-950/80 text-amber-400 font-mono border border-amber-900/60">
                    Preview
                  </span>
                </div>
                <div className="font-mono text-xs text-cyan-300 bg-zinc-950 px-3 py-2 rounded border border-zinc-800/80 overflow-x-auto truncate">
                  {item.cmd}
                </div>
              </div>

              <div className="flex items-center gap-2 shrink-0 self-end sm:self-center">
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => handleCopy(item.cmd, idx)}
                  className="font-mono text-xs"
                >
                  {copiedIndex === idx ? (
                    <>
                      <Check className="w-3.5 h-3.5 text-emerald-400 mr-1" />
                      <span>Copied</span>
                    </>
                  ) : (
                    <>
                      <Copy className="w-3.5 h-3.5 mr-1 text-zinc-400" />
                      <span>Copy</span>
                    </>
                  )}
                </Button>
              </div>
            </Card>
          ))}
        </div>

        {/* Post-install walkthrough */}
        <div className="mt-8 max-w-4xl p-6 rounded-xl bg-zinc-950 border border-zinc-800/80 font-mono text-xs">
          <div className="text-zinc-400 mb-2">Once installed, verify the installation:</div>
          <div className="text-zinc-100 font-bold">$ contexer --version</div>
          <div className="text-zinc-500 mt-1">contexer v0.1.0-alpha (x86_64-apple-darwin / linux-gnu / windows-msvc)</div>
          <div className="text-zinc-100 font-bold mt-3">$ contexer --help</div>
          <div className="text-zinc-500 mt-1">Autonomous engineering agent for repository-scale closed loop tasks.</div>
        </div>
      </div>
    </section>
  );
}
