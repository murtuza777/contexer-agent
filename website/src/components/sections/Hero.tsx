import React from "react";
import { ArrowDownToLine, CheckCircle } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { GithubIcon } from "@/components/ui/GithubIcon";
import { TerminalDemo } from "@/components/sections/TerminalDemo";

export function Hero() {
  return (
    <section className="relative pt-32 pb-20 sm:pt-40 sm:pb-28 overflow-hidden">
      {/* Background Subtle Technical Grid */}
      <div
        className="absolute inset-0 pointer-events-none opacity-20 [mask-image:radial-gradient(ellipse_60%_50%_at_50%_0%,#000_70%,transparent_100%)]"
        style={{
          backgroundImage:
            "linear-gradient(to right, #27272a 1px, transparent 1px), linear-gradient(to bottom, #27272a 1px, transparent 1px)",
          backgroundSize: "32px 32px",
        }}
      />

      <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="text-center max-w-4xl mx-auto space-y-6">
          {/* Top Announcement Pill */}
          <div className="inline-flex items-center">
            <Badge variant="cyan" className="gap-2 px-3 py-1">
              <span className="w-2 h-2 rounded-full bg-cyan-400 animate-pulse" />
              <span>Contexer Autonomous Runtime v0.1.0-alpha</span>
              <span className="text-zinc-500">|</span>
              <span className="text-zinc-400 font-sans">Open Source Infrastructure</span>
            </Badge>
          </div>

          {/* Headline */}
          <h1 className="text-4xl sm:text-6xl lg:text-7xl font-bold tracking-tight text-zinc-100 font-sans leading-[1.1]">
            Build the outcome.{" "}
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-zinc-200 via-zinc-400 to-zinc-500">
              Contexer handles the engineering.
            </span>
          </h1>

          {/* Supporting Copy */}
          <p className="max-w-2xl mx-auto text-base sm:text-lg text-zinc-400 font-normal leading-relaxed">
            Contexer is an autonomous engineering agent that turns your intent into a
            plan, executes the work through coding agents, observes the running
            application, verifies the result, and fixes what doesn&apos;t work.
          </p>

          {/* CTAs */}
          <div className="pt-2 flex flex-col sm:flex-row items-center justify-center gap-3 sm:gap-4">
            <a href="#download" className="w-full sm:w-auto">
              <Button size="lg" variant="primary" className="w-full sm:w-auto font-mono text-sm shadow-xl">
                <ArrowDownToLine className="w-4 h-4 mr-2" />
                Download Contexer
              </Button>
            </a>
            <a href="#github" className="w-full sm:w-auto">
              <Button size="lg" variant="secondary" className="w-full sm:w-auto font-mono text-sm">
                <GithubIcon className="w-4 h-4 mr-2" />
                View GitHub
              </Button>
            </a>
          </div>

          {/* Quick value props pill */}
          <div className="pt-4 flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-xs font-mono text-zinc-500">
            <span className="flex items-center gap-1.5">
              <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />
              <span>Not a simple chatbot</span>
            </span>
            <span className="flex items-center gap-1.5">
              <CheckCircle className="w-3.5 h-3.5 text-cyan-400" />
              <span>Closed-loop verification</span>
            </span>
            <span className="flex items-center gap-1.5">
              <CheckCircle className="w-3.5 h-3.5 text-violet-400" />
              <span>Agent agnostic orchestration</span>
            </span>
          </div>
        </div>

        {/* Interactive Terminal Demo */}
        <div className="mt-12 sm:mt-16">
          <TerminalDemo />
        </div>
      </div>
    </section>
  );
}
