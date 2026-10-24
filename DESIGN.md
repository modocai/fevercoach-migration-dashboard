# Design
## Source of truth
Active · 2026-10-23. Surface: GitHub Pages migration dashboard. Evidence: current 28-task plan and public projections of GitHub and Wix sources. Original visual hierarchy is preserved.
## Brand
Calm, practical team workspace. Restore original warm orange accent, neutral cards, restrained typography. Avoid flat document walls and invented progress.
## Product goals
See issue completion, extraction scope, baselines and phase evidence; open a task issue. No local-only status editing or implied live synchronization.
## Personas and jobs
Interns and project owner review progress and navigate to GitHub tickets.
## Information architecture
Header links → issue summary and phase navigation → source freshness → extraction → baselines → task filters and phase evidence → snapshot notice.
## Design principles
Hierarchy before decoration; preserve original card and progress-bar language. Exact task content and real status take precedence.
## Visual language
Reuse original CSS tokens: gray backgrounds, orange progress, green complete; system Korean fonts, monospaced counts. 8px rhythm, 8–10px corners, no heavy shadows.
## Components
Summary card, phase cards, issue rows, status badges, filter buttons. Native links and buttons.
## Accessibility
Aim WCAG AA; keyboard focus rings, labeled progress, semantic headings, aria-pressed filters. Status text supplements color. Respect reduced motion.
## Responsive behavior
Primary environments: desktop and laptop at 1440px and 1280px. Keep three-column phase cards and readable summary, tables, and task rows. Existing narrow-screen CSS is a fallback, not an acceptance requirement.
## Interaction states
Static initial content works without JS. Filters hide nonmatching tasks and empty groups. No loading or network dependency. No in-page editing.
## Content voice
Short Korean labels, explicit snapshot date, no unverified completion claims.
## Implementation constraints
Standalone HTML/CSS/JS, no runtime packages, no secrets. Python standard-library scripts generate identical index.html and migration-dashboard.html. Wide tables scroll within a labeled region on narrow screens. Validate desktop/laptop rendering and filtering before publication.
## Open questions
Authenticated build-time collection is implemented. Live Project verification requires read access. Missing status stays unknown; failed refresh retains dated prior data. Unmerged Wix evidence is provisional. Gate and GA4 criteria need team review. Collection creates no automatic commits.
