---
name: responsive-accessibility
description: Best practices for responsive multi-device frontend layouts and WCAG accessibility standards, semantic HTML, keyboard focus management, and screen-reader considerations.
---

# Responsive & Accessible Frontend Guidelines

Use this skill when implementing responsive layouts, navigation bars, interactive widgets, and ensuring accessibility across mobile and desktop.

## Responsive Design Principles

1. **Fluid Multi-Breakpoint Architecture**:
   - Design mobile-first, supporting:
     - Mobile: 320px - 640px (single column, collapsible menus, touch-friendly hit areas >= 44x44px).
     - Tablet: 641px - 1024px (compact 2-column or stacked cards).
     - Desktop: 1025px - 1440px+ (full multi-column, side-by-side terminal & architecture panels).
   - Ensure horizontal overflow is strictly prevented (`overflow-x-hidden` or container constraints).
   - Code blocks and terminal outputs must feature horizontal scrolling with custom scrollbars rather than stretching the parent container.

2. **Accessibility Standards (WCAG 2.1 AA)**:
   - **Semantic Elements**: Use `<header>`, `<nav>`, `<main>`, `<section>`, `<article>`, `<footer>`, `<button>`, and `<a>`.
   - **Interactive Elements**: Never use a `<div>` with an `onClick` when a `<button>` or `<a>` is appropriate. Ensure all interactive elements have visible `:focus-visible` focus rings.
   - **ARIA**: Provide `aria-label` or `aria-labelledby` on icon buttons, status indicators, and modal triggers.
   - **Contrast**: Ensure text-to-background contrast ratio meets or exceeds 4.5:1 for normal text and 3:1 for large text.
   - **Reduced Motion**: Respect `prefers-reduced-motion: reduce` for all progressive animations and transitions.
