import { Terminal, ArrowUpRight } from "lucide-react";
import { GithubIcon } from "@/components/ui/GithubIcon";

export function Footer() {
  return (
    <footer className="border-t border-zinc-800 bg-zinc-950 py-16 text-zinc-400 font-sans">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-10 pb-12 border-b border-zinc-850">
          {/* Col 1: Brand info */}
          <div className="md:col-span-2 space-y-4">
            <div className="flex items-center gap-2.5">
              <div className="w-7 h-7 rounded-lg bg-zinc-900 border border-zinc-750 flex items-center justify-center text-cyan-400">
                <Terminal className="w-4 h-4" />
              </div>
              <span className="font-mono text-lg font-bold tracking-tight text-zinc-100">
                <span className="text-cyan-400 font-extrabold">CON</span>texer
              </span>
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-zinc-900 border border-zinc-800 text-zinc-400">
                v0.1.0-alpha
              </span>
            </div>

            <p className="text-sm text-zinc-400 max-w-sm leading-relaxed">
              Autonomous engineering agent that turns your intent into a plan, executes work through
              coding agents, observes the running application, verifies the result, and fixes what doesn&apos;t work.
            </p>

            <div className="flex items-center gap-2 text-xs font-mono text-zinc-500">
              <span className="w-2 h-2 rounded-full bg-emerald-400" />
              <span>All Systems Operational</span>
              <span>•</span>
              <span>Local-First Execution</span>
            </div>
          </div>

          {/* Col 2: Navigation */}
          <div className="space-y-3 font-mono text-xs">
            <div className="text-zinc-200 font-bold uppercase tracking-wider">Product</div>
            <ul className="space-y-2">
              <li>
                <a href="#product" className="hover:text-zinc-200 transition-colors">
                  Overview
                </a>
              </li>
              <li>
                <a href="#how-it-works" className="hover:text-zinc-200 transition-colors">
                  Core Loop
                </a>
              </li>
              <li>
                <a href="#architecture" className="hover:text-zinc-200 transition-colors">
                  Architecture
                </a>
              </li>
              <li>
                <a href="#cli-experience" className="hover:text-zinc-200 transition-colors">
                  CLI Walkthrough
                </a>
              </li>
              <li>
                <a href="#download" className="hover:text-zinc-200 transition-colors text-cyan-400">
                  Download Contexer
                </a>
              </li>
            </ul>
          </div>

          {/* Col 3: Resources & Links */}
          <div className="space-y-3 font-mono text-xs">
            <div className="text-zinc-200 font-bold uppercase tracking-wider">Resources</div>
            <ul className="space-y-2">
              <li>
                <a
                  href="#github"
                  className="hover:text-zinc-200 transition-colors inline-flex items-center gap-1.5"
                >
                  <GithubIcon className="w-3.5 h-3.5" />
                  <span>GitHub</span>
                  <ArrowUpRight className="w-3 h-3 text-zinc-500" />
                </a>
              </li>
              <li>
                <a
                  href="#architecture"
                  className="hover:text-zinc-200 transition-colors inline-flex items-center gap-1"
                >
                  <span>Documentation</span>
                  <ArrowUpRight className="w-3 h-3 text-zinc-500" />
                </a>
              </li>
              <li>
                <a
                  href="#download"
                  className="hover:text-zinc-200 transition-colors inline-flex items-center gap-1"
                >
                  <span>Download Installers</span>
                  <ArrowUpRight className="w-3 h-3 text-zinc-500" />
                </a>
              </li>
              <li>
                <span className="text-zinc-500">Security Policy</span>
              </li>
            </ul>
          </div>
        </div>

        {/* Bottom row */}
        <div className="pt-8 flex flex-col sm:flex-row items-center justify-between text-xs font-mono text-zinc-500 gap-4">
          <div>
            © {new Date().getFullYear()} Contexer. Autonomous engineering layer for software teams.
          </div>
          <div className="flex items-center gap-4">
            <span className="text-zinc-400">INTENT → PLAN → EXECUTE → VERIFY → REPAIR → DONE</span>
          </div>
        </div>
      </div>
    </footer>
  );
}
