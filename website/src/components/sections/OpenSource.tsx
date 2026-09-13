import React from "react";
import { Terminal } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { GithubIcon } from "@/components/ui/GithubIcon";

export function OpenSource() {
  return (
    <section id="github" className="py-24 sm:py-32 border-t border-zinc-800/60 relative">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="max-w-4xl mx-auto rounded-2xl bg-gradient-to-b from-zinc-900/80 to-zinc-950 border border-zinc-800 p-8 sm:p-12 text-center relative overflow-hidden">
          <div className="absolute top-0 right-0 w-64 h-64 bg-cyan-500/5 rounded-full blur-3xl pointer-events-none" />

          <div className="inline-flex items-center mb-6">
            <Badge variant="cyan" className="gap-1.5 font-mono">
              <GithubIcon className="w-3.5 h-3.5" />
              <span>Open Source Developer Infrastructure</span>
            </Badge>
          </div>

          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-zinc-100 font-sans leading-tight">
            Built in the open.{" "}
            <span className="text-zinc-400 block">
              Transparent, inspectable, and self-hostable.
            </span>
          </h2>

          <p className="mt-4 max-w-2xl mx-auto text-sm sm:text-base text-zinc-400 leading-relaxed">
            Developer infrastructure demands zero magic and complete predictability. Contexer is designed
            as an open architecture where you can inspect every planning step, AST query, and verification trace.
          </p>

          <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-4">
            <a
              href="https://github.com"
              target="_blank"
              rel="noopener noreferrer"
              className="w-full sm:w-auto"
            >
              <Button size="lg" variant="primary" className="w-full sm:w-auto font-mono text-sm">
                <GithubIcon className="w-4 h-4 mr-2" />
                View the Source on GitHub
              </Button>
            </a>
            <a href="#download" className="w-full sm:w-auto">
              <Button size="lg" variant="secondary" className="w-full sm:w-auto font-mono text-sm">
                <Terminal className="w-4 h-4 mr-2" />
                Read Architecture Specs
              </Button>
            </a>
          </div>

          <div className="mt-10 pt-8 border-t border-zinc-800/80 grid grid-cols-1 sm:grid-cols-3 gap-4 text-left font-mono text-xs">
            <div className="p-3 rounded-lg bg-zinc-950/60 border border-zinc-800/60">
              <div className="text-zinc-200 font-bold mb-1">Local-First Execution</div>
              <div className="text-zinc-500 font-sans">
                Runs entirely on your machine. Your proprietary source code stays on your filesystem.
              </div>
            </div>
            <div className="p-3 rounded-lg bg-zinc-950/60 border border-zinc-800/60">
              <div className="text-zinc-200 font-bold mb-1">Deterministic Planning</div>
              <div className="text-zinc-500 font-sans">
                Task DAGs are generated with strict verification gates, preventing rogue edits.
              </div>
            </div>
            <div className="p-3 rounded-lg bg-zinc-950/60 border border-zinc-800/60">
              <div className="text-zinc-200 font-bold mb-1">Pluggable Model Layer</div>
              <div className="text-zinc-500 font-sans">
                Switch coding agents seamlessly without changing your verification test harness.
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
