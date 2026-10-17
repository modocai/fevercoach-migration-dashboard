# Design
## Source of truth
Active · 2026-10-17. Surface: GitHub Pages migration dashboard. Evidence: migration-dashboard-original.html (Claude original), current 28-task plan.
## Brand
Calm, practical team workspace. Restore original warm orange accent, neutral cards, restrained typography. Avoid flat document walls and invented progress.
## Product goals
See overall progress, scan six phases, open a task issue. No local-only status editing or implied live synchronization.
## Personas and jobs
Interns and project owner review progress and navigate to GitHub tickets.
## Information architecture
Header links → overall summary → phase navigation → task filters → task groups → snapshot notice.
## Design principles
Hierarchy before decoration; preserve original card and progress-bar language. Exact task content and real status take precedence.
## Visual language
Reuse original CSS tokens: gray backgrounds, orange progress, green complete; system Korean fonts, monospaced counts. 8px rhythm, 8–10px corners, no heavy shadows.
## Components
Summary card, phase cards, issue rows, status badges, filter buttons. Native links and buttons.
## Accessibility
Aim WCAG AA; keyboard focus rings, labeled progress, semantic headings, aria-pressed filters. Status text supplements color. Respect reduced motion.
## Responsive behavior
Desktop 3-column phase cards; mobile 2 columns and stacked summary. Touch buttons at least 44px tall.
## Interaction states
Static initial content works without JS. Filters hide nonmatching tasks and empty groups. No loading or network dependency. No in-page editing.
## Content voice
Short Korean labels, explicit snapshot date, no unverified completion claims.
## Implementation constraints
Standalone HTML/CSS/JS, no packages, no secrets. index.html and migration-dashboard.html identical. Validate desktop/mobile rendering and filtering before publication.
## Open questions
Project synchronization is separate future scope, not implemented here.
