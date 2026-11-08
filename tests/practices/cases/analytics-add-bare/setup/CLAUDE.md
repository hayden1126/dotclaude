# Ledgerly

Small invoicing app: projects, invoices, and a chat assistant.

- Stack: Next.js 15 App Router, TypeScript, SQLite through `node:sqlite` (`lib/db.ts`).
- Imports use the `@/` alias for the project root.
- Run `npm test` to check your work. Tests live in `tests/` and use `node:test`;
  `tests/helpers.ts` shows how to call a route handler as a signed-in user.
- There is no dev server and no `next build` in this environment, so don't try to start one.
