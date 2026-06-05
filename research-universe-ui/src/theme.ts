// ═══════════════════════════════════════════════════════════════════════════
//  UI THEME - single source of truth
// ═══════════════════════════════════════════════════════════════════════════
//
//  Current palette — AI Economy Universe Claude design
//  ────────────────────────────────────────────────────
//  brand      = blue      #2f6fe6  rgb(47, 111, 230)
//  canvas     = cream     #f8f4ed  (body CSS gradient)
//  surface    = warm white #fffdf9  (cards)
//  ink        = #15171a / #44474d / #5f6166 / #9a958b
//
//  To change the whole palette:
//  1. tailwind.config.js → update brand + boxShadow rgba
//  2. src/theme.ts → update LOGIN_CARD_SHADOW rgba
//  3. src/index.css → update body background + scrollbar
// ═══════════════════════════════════════════════════════════════════════════

// Login card shadow — warm glass style matching the Claude design
export const LOGIN_CARD_SHADOW =
  '0 8px 30px rgba(40,32,18,0.10), inset 0 1px 0 rgba(255,255,255,0.70)';
