"use client";

import React, { useState, useEffect } from "react";
import { Terminal, Menu, X, ArrowDownToLine } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { GithubIcon } from "@/components/ui/GithubIcon";

export function Navbar() {
  const [scrolled, setScrolled] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  useEffect(() => {
    const handleScroll = () => {
      setScrolled(window.scrollY > 20);
    };
    window.addEventListener("scroll", handleScroll, { passive: true });
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);

  const navLinks = [
    { label: "Product", href: "#product" },
    { label: "How it Works", href: "#how-it-works" },
    { label: "Architecture", href: "#architecture" },
    { label: "CLI Experience", href: "#cli-experience" },
    { label: "GitHub", href: "#github" },
  ];

  return (
    <header
      className={`fixed top-0 left-0 right-0 z-50 transition-all duration-200 ${
        scrolled
          ? "bg-zinc-950/85 backdrop-blur-md border-b border-zinc-800/80 py-3 shadow-lg shadow-black/40"
          : "bg-transparent py-5 border-b border-transparent"
      }`}
    >
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 flex items-center justify-between">
        {/* Brand Logo */}
        <a
          href="#"
          className="flex items-center gap-2.5 group focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 rounded-md py-1 px-1.5"
          aria-label="Contexer Homepage"
        >
          <div className="w-8 h-8 rounded-lg bg-zinc-900 border border-zinc-700/80 flex items-center justify-center text-zinc-100 group-hover:border-cyan-500/80 group-hover:shadow-[0_0_12px_rgba(6,182,212,0.35)] transition-all">
            <Terminal className="w-4 h-4 text-cyan-400" />
          </div>
          <span className="font-mono text-lg font-bold tracking-tight text-zinc-100">
            <span className="text-cyan-400 font-extrabold">CON</span>texer
          </span>
          <span className="hidden sm:inline-flex text-[10px] uppercase font-mono px-1.5 py-0.5 rounded border border-zinc-800 bg-zinc-900/80 text-zinc-400">
            alpha
          </span>
        </a>

        {/* Desktop Nav */}
        <nav
          className="hidden md:flex items-center gap-7 text-sm font-medium text-zinc-400"
          aria-label="Main Navigation"
        >
          {navLinks.map((link) => (
            <a
              key={link.label}
              href={link.href}
              className="hover:text-zinc-100 transition-colors py-1 focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400 rounded"
            >
              {link.label}
            </a>
          ))}
        </nav>

        {/* Action CTAs */}
        <div className="hidden md:flex items-center gap-3">
          <a
            href="#github"
            className="p-2 rounded-lg text-zinc-400 hover:text-zinc-100 hover:bg-zinc-900 border border-transparent hover:border-zinc-800 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400"
            aria-label="View Contexer on GitHub"
          >
            <GithubIcon className="w-4 h-4" />
          </a>
          <a href="#download">
            <Button size="sm" variant="primary" className="font-mono text-xs">
              <ArrowDownToLine className="w-3.5 h-3.5 mr-1" />
              Download
            </Button>
          </a>
        </div>

        {/* Mobile menu button */}
        <div className="flex md:hidden items-center gap-2">
          <a href="#download">
            <Button size="sm" variant="primary" className="text-xs px-2.5 h-8">
              Download
            </Button>
          </a>
          <button
            type="button"
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            className="p-2 text-zinc-400 hover:text-zinc-100 hover:bg-zinc-900 rounded-lg border border-zinc-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400"
            aria-expanded={mobileMenuOpen}
            aria-label="Toggle navigation menu"
          >
            {mobileMenuOpen ? (
              <X className="w-5 h-5" />
            ) : (
              <Menu className="w-5 h-5" />
            )}
          </button>
        </div>
      </div>

      {/* Mobile Drawer */}
      {mobileMenuOpen && (
        <div className="md:hidden border-b border-zinc-800 bg-zinc-950/95 backdrop-blur-xl px-4 py-5 shadow-2xl animate-in fade-in slide-in-from-top-2 duration-150">
          <nav className="flex flex-col gap-3 font-mono text-sm">
            {navLinks.map((link) => (
              <a
                key={link.label}
                href={link.href}
                onClick={() => setMobileMenuOpen(false)}
                className="px-3 py-2 rounded-md text-zinc-300 hover:text-white hover:bg-zinc-900 transition-colors"
              >
                {link.label}
              </a>
            ))}
            <div className="pt-3 border-t border-zinc-800/80 flex items-center justify-between px-3">
              <a
                href="#github"
                onClick={() => setMobileMenuOpen(false)}
                className="flex items-center gap-2 text-zinc-400 hover:text-zinc-200 text-xs"
              >
                <GithubIcon className="w-4 h-4" />
                <span>GitHub Repository</span>
              </a>
              <span className="text-[10px] text-zinc-500 font-mono">v0.1.0-alpha</span>
            </div>
          </nav>
        </div>
      )}
    </header>
  );
}
