import { ArrowDownToLine, Terminal } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { GithubIcon } from "@/components/ui/GithubIcon";

export function FinalCta() {
  return (
    <section className="py-24 sm:py-32 border-t border-zinc-800/80 relative overflow-hidden bg-gradient-to-b from-transparent to-zinc-950">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center relative">
        <div className="max-w-3xl mx-auto space-y-6">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-zinc-800 bg-zinc-900/60 font-mono text-xs text-zinc-400">
            <Terminal className="w-3.5 h-3.5 text-cyan-400" />
            <span>Autonomous Engineering Agent</span>
          </div>

          <h2 className="text-4xl sm:text-5xl lg:text-6xl font-bold tracking-tight text-zinc-100 font-sans">
            Give Contexer the outcome.
          </h2>

          <p className="text-lg sm:text-xl text-zinc-400 max-w-xl mx-auto font-normal">
            Let the engineering loop take it from there.
          </p>

          <div className="pt-4 flex flex-col sm:flex-row items-center justify-center gap-4">
            <a href="#download" className="w-full sm:w-auto">
              <Button size="lg" variant="primary" className="w-full sm:w-auto font-mono text-sm shadow-xl">
                <ArrowDownToLine className="w-4 h-4 mr-2" />
                Download Contexer
              </Button>
            </a>
            <a href="#github" className="w-full sm:w-auto">
              <Button size="lg" variant="secondary" className="w-full sm:w-auto font-mono text-sm">
                <GithubIcon className="w-4 h-4 mr-2" />
                GitHub
              </Button>
            </a>
          </div>

          <div className="pt-6 font-mono text-xs text-zinc-500">
            $ contexer --intent &quot;Deliver verified software outcomes&quot;
          </div>
        </div>
      </div>
    </section>
  );
}
