---
name: nextjs-app-router
description: Guidance and best practices for developing Next.js App Router applications, structuring React Server and Client Components, routing, layout composition, and performance optimization.
---

# Next.js App Router Guidelines

Use this skill when developing, refactoring, or optimizing Next.js applications using the App Router (`app/` directory).

## Core Principles

1. **Server Components by Default**:
   - Keep components as React Server Components (RSC) unless interactive hooks (`useState`, `useEffect`, `useCallback`) or browser APIs are required.
   - Place `'use client'` only at the top of leaf components requiring interactivity to minimize client bundle size.

2. **Directory and Routing Structure**:
   - Route segments map directly to folders inside `app/`.
   - Use `layout.tsx` for persistent shell layouts (Navbar, Footer, font injection).
   - Use `page.tsx` for unique route views.
   - Create specialized convention files when needed: `robots.ts`, `sitemap.ts`, `not-found.tsx`, `error.tsx`.

3. **Performance & Asset Loading**:
   - Use `next/font` (`Geist`, `Inter`, `JetBrains Mono`) to eliminate render-blocking external font requests and layout shifts.
   - Use `next/image` with explicit `width`, `height`, or `fill` with responsive `sizes` attribute.
   - Keep bundle size small: avoid importing massive utility libraries when native JavaScript or CSS suffices.

4. **Component Hierarchy**:
   - `components/ui/`: Atomic, reusable UI primitives (buttons, badges, cards).
   - `components/layout/`: Navigation headers, footers, containers.
   - `components/sections/`: High-level domain-specific page sections.
