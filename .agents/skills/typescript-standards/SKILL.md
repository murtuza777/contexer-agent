---
name: typescript-standards
description: Enforces strict TypeScript practices, strong type definitions, discriminated unions for state machines, component prop interfaces, and eliminates untyped or loose code.
---

# TypeScript Standards

Use this skill when defining component interfaces, data structures, application state, and ensuring zero type errors across the project.

## Core Rules

1. **Strict Type Safety**:
   - Always enable strict mode in `tsconfig.json` (`"strict": true`).
   - Forbid `any`. Use `unknown` with type guards or define explicit interfaces/types.
   - Avoid non-null assertions (`!`) unless guaranteed by invariants.

2. **Discriminated Unions for UI State**:
   - Represent multi-step state machines (such as the Contexer CLI execution loop) using discriminated unions:
     ```typescript
     export type ExecutionState =
       | { status: 'idle' }
       | { status: 'planning'; step: number; total: number }
       | { status: 'executing'; task: string; progress: number }
       | { status: 'verifying'; assertion: string }
       | { status: 'repairing'; issue: string; attempt: number }
       | { status: 'completed'; durationMs: number };
     ```

3. **Explicit Component Props**:
   - Every React component must have an explicit interface or type:
     ```typescript
     interface TerminalDemoProps {
       initialCommand?: string;
       autoPlay?: boolean;
       className?: string;
     }
     ```
   - Extend standard HTML attributes where appropriate (`React.HTMLAttributes<HTMLDivElement>`) to allow standard styling and event handling.

4. **Type Checking in CI / Validation**:
   - Validate code with `npx tsc --noEmit` before considering any task complete.
