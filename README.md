# Contexer

**Autonomous Engineering Agent**

Contexer is an autonomous engineering layer that coordinates coding agents, tools, project context, and verification. Unlike traditional coding assistants that stop when a file is saved, Contexer turns engineering intent into an actionable plan, executes code changes, observes the running application, verifies behavior against intent, and autonomously fixes runtime failures.

```text
INTENT → CONTEXT → PLAN → EXECUTE → OBSERVE → VERIFY → REPAIR → DONE
```

---

## Repository Structure

```text
contexer/
├── website/                 # Next.js website (public landing page & product showcase)
├── contexer-agent/          # Python CLI agent (architecture placeholder, not implemented yet)
├── .agents/
│   └── skills/              # Project-local Antigravity skills for web development & validation
├── README.md                # This file
└── .gitignore
```

> **Note on Implementation Status**: The Python agent (`contexer-agent/`) is intentionally not implemented in this phase. This milestone focuses exclusively on establishing the project foundation, project-local Antigravity skills, and the production-grade Next.js technical landing page.

---

## Website Development

The website is built using:
- **Next.js 15** (App Router)
- **TypeScript** (Strict mode)
- **Tailwind CSS** (Custom dark-first engineering design tokens)
- **Lucide React** (Crisp technical iconography)

### Prerequisites

- Node.js >= 18.18.0 (Node 20+ recommended)
- npm >= 9.0.0

### Development Commands

```bash
# Navigate to the website directory
cd website

# Install dependencies
npm install

# Run the local development server (starts on http://localhost:3000)
npm run dev

# Run TypeScript type check
npx tsc --noEmit

# Run ESLint
npm run lint

# Build for production
npm run build

# Start the production server
npm start
```

---

## Future Contexer Agent (`contexer-agent/`)

The Python CLI agent will be implemented as an autonomous execution engine that:
1. Indexes project AST, symbols, and dependencies into an actionable context graph.
2. Formulates dependency-aware execution DAGs.
3. Delegates atomic coding tasks to model backends (starting with OpenCode).
4. Spins up headless browser runtimes (via Playwright) and test harnesses to observe application behavior.
5. Evaluates runtime outcomes against initial intent, triggering self-repair loops whenever assertions fail.

See [`contexer-agent/README.md`](./contexer-agent/README.md) for architectural details and roadmap.

---

## License

Apache-2.0
