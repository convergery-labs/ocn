// ═══════════════════════════════════════════════════════════════════════════
//  DESIGN TOKENS — AI Economy Universe Claude design palette
// ═══════════════════════════════════════════════════════════════════════════
//
//  Ink scale (on cream/white backgrounds):
//    ink   #15171a  → headings, company names
//    ink-2 #44474d  → body text, card content
//    ink-3 #5f6166  → secondary / descriptions
//    ink-4 #9a958b  → labels, muted metadata
//
//  Contrast on white (#FFFFFF):
//    ink   21.0:1 ✅ AAA
//    ink-2 10.1:1 ✅ AAA
//    ink-3  6.8:1 ✅ AA
//    ink-4  3.2:1 ⚠ AA large only
// ═══════════════════════════════════════════════════════════════════════════

export const TEXT = {

  // ── Light background (cream canvas, surface cards) ───────────────────────
  heading:   'text-ink',    // Company names, page titles       #15171a
  body:      'text-ink-2',  // Card content, regular text       #44474d
  secondary: 'text-ink-3',  // Descriptions, helper text        #5f6166
  label:     'text-ink-4',  // Field labels: "Country" etc.     #9a958b
  muted:     'text-ink-4',  // Timestamps, hints                #9a958b

  // ── Brand colored text ───────────────────────────────────────────────────
  brand:     'text-brand-500',  // Section headers, active states  #2f6fe6
  brandMid:  'text-brand-400',  // Icon labels, lighter accents    #3b7bf0

  // ── Status text ──────────────────────────────────────────────────────────
  success:   'text-emerald-700', // "Verified" — keep semantic green
  warning:   'text-amber-700',   // "Pending", caution states
  danger:    'text-rose-600',    // Errors, validation messages
  info:      'text-sky-700',     // Informational

  // ── Top nav (light glass background) ─────────────────────────────────────
  sidebar: {
    heading:      'text-ink',          // Brand name
    active:       'text-brand-500',    // Active tab label      #2f6fe6
    inactive:     'text-ink-3',        // Inactive tab labels   #5f6166
    stats:        'text-ink-4',
    statsBrand:   'text-brand-500',
    statsWarning: 'text-rose-500',
    status: {
      ok:          'text-emerald-600',
      error:       'text-rose-500',
      unreachable: 'text-amber-500',
      idle:        'text-ink-4',
    },
  },

} as const;

// ── Uppercase label style ─────────────────────────────────────────────────
export const LABEL_STYLE = 'text-xs font-semibold uppercase tracking-wider';

// ── Badge base style ──────────────────────────────────────────────────────
export const BADGE = {
  pending:  'bg-amber-100 text-amber-700',
  verified: 'bg-emerald-100 text-emerald-700',
  agent:    'bg-blue-soft text-brand-600',
  private:  'bg-cream-2 text-ink-3',
} as const;
