---
name: technical-landing-design
description: Design standards and patterns for high-end developer tools, infrastructure products, and CLI agents. Focuses on dark-first aesthetics, terminal panels, restrained motion, and technical credibility.
---

# Technical Landing Page Design Guidelines

Use this skill when designing, styling, and refining landing pages and interfaces for developer tooling and infrastructure systems.

## Visual Direction & Aesthetics

1. **Developer-First & High-End Aesthetic**:
   - Palette: Deep charcoal / near-black backgrounds (`zinc-950`, `#09090b`), high-contrast text (`zinc-100`, `zinc-400`), muted borders (`zinc-800`, `zinc-800/80`).
   - Accent colors: Reserve colors strictly for status indicators:
     - Cyan / Blue: Execution, active process, command prompts.
     - Emerald: Verification passed, success states, green checks.
     - Amber / Rose: Verification mismatch, repair action, warnings.
   - Typography: Clean sans-serif for body (`Inter` or `Geist Sans`), crisp monospace for commands, outputs, and system metrics (`JetBrains Mono` or `Geist Mono`).

2. **Antipatterns to Avoid**:
   - NO generic rainbow AI gradients or blur blobs.
   - NO stock illustrations, cartoon mascots, or floating 3D spheres.
   - NO fake testimonials, fake user logos, or unverifiable "10x productivity" claims.
   - NO excessive glassmorphism or distracting parallax.

3. **Engineering Credibility**:
   - Build interfaces that resemble real terminal outputs, syntax-highlighted code diffs, architecture flow graphs, and structured telemetry.
   - Micro-animations should be purposeful: progressive terminal typing, blinking prompt cursors, smooth tab transitions, and subtle pulse indicators for running states.
   - Maintain appropriate information density: developer tools should feel substantial and precise, not empty or bloated.
