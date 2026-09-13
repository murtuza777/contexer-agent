---
name: frontend-testing-validation
description: Protocol for verifying frontend quality, running TypeScript type-checks, Next.js production builds, linting, and performing browser-based visual validation across desktop and mobile.
---

# Frontend Testing and Validation Protocol

Use this skill when auditing, testing, and visually validating the Contexer web application.

## Verification Checklist

1. **Static Type Safety**:
   ```bash
   cd website
   npx tsc --noEmit
   ```
   Zero errors, zero warnings.

2. **Linting**:
   ```bash
   cd website
   npm run lint
   ```
   Adhere to Next.js recommended ESLint rules.

3. **Production Compilation**:
   ```bash
   cd website
   npm run build
   ```
   Ensure static pages generate without build errors, hydration mismatches, or bundle size warnings.

4. **Live Browser Inspection**:
   - Start the local server (`npm run dev` or `npm start`).
   - Use browser automation tools to inspect the rendered page.
   - Verify:
     - Desktop viewport (1440x900): Layout alignment, typography scale, sticky navbar, interactive terminal demo, architecture diagram.
     - Mobile viewport (390x844): Navigation drawer/toggle, terminal responsiveness, card wrapping, no horizontal scroll bugs.
   - Test interaction loops: terminal execution replay, tab clicks, OS download switcher.
