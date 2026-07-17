# Feature modules

Place screen-specific components under a domain folder here as they are extracted from `App.tsx`.

Current domains include accounts, imports, net worth, overview, refunds, review, rules, sidebar navigation, transactions, and transfers.

Phase 12 extraction rules:

- `App.tsx` should contain providers, route coordination, and shell layout—not feature JSX.
- Server reads use resource-specific TanStack Query hooks and stable query keys.
- Mutations use shared hooks with targeted invalidation and return operation IDs for Undo.
- Feature components may compose shared components, but shared components must not import feature modules.
- Preserve bookmarkable filter state and the mutation journal during behavior-neutral moves.
