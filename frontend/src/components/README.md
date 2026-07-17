# Shared components

Place reusable, feature-independent UI components in this directory.

Current examples include shared primitives, deletion confirmation, filtered transaction summaries, primary navigation, and the canonical date-range picker.

Guidelines:

- Components must not own domain-specific API mutations.
- Accept typed data and callbacks rather than importing `App.tsx` state.
- Reuse canonical URL/filter helpers from `lib/` instead of inventing local query formats.
- Add focused Vitest coverage for state-independent calculations and interaction policy.
- A component used by only one domain belongs under that domain in `features/`.
