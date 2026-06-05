/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
      },

      // ── COLOR SYSTEM ─────────────────────────────────────────────────────────
      // Source: AI Economy Universe Claude design artifact
      //
      // brand   = blue  #2f6fe6 / bright #3b7bf0 / deep #2563eb
      // surface = warm cream  #fffdf9
      // canvas  = cream       #f8f4ed
      // ink     = warm near-black #15171a
      //
      // To swap brand: update brand.400/500/600 + boxShadow rgba + LOGIN_CARD_SHADOW
      // brand-500 RGB = 47, 111, 230
      // ─────────────────────────────────────────────────────────────────────────
      colors: {
        // ── Ink (text) palette ─────────────────────────────────────────────────
        ink:   '#15171a',   // --ink   primary text
        'ink-2':'#44474d',  // --ink-2 secondary text
        'ink-3':'#5f6166',  // --ink-3 tertiary / descriptions
        'ink-4':'#9a958b',  // --ink-4 muted / labels

        // ── Surface / background palette ───────────────────────────────────────
        surface: '#fffdf9',   // --surface  card backgrounds
        cream:   '#f8f4ed',   // --cream    page canvas
        'cream-2':'#f3ede2',  // --cream-2  hover/selected row
        peach:   '#fbf2e8',   // --peach    gradient highlight
        line:    '#ece4d6',   // --line     borders
        'line-soft':'#f1ebe0',// --line-soft soft borders

        // ── Brand (blue) ───────────────────────────────────────────────────────
        brand: {
          50:  '#f0f5ff',
          100: '#dce8fe',
          200: '#bfd3fd',
          300: '#93b4fb',
          400: '#3b7bf0',  // --blue-bright  ← lighter / icons
          500: '#2f6fe6',  // --blue         ← primary accent
          600: '#2563eb',  // --blue-deep    ← hover state
          700: '#1d4ed8',
          800: '#1e40af',
          900: '#1e3a8a',
          950: '#172554',
        },

        // ── Blue fills ─────────────────────────────────────────────────────────
        'blue-soft':  '#eaf0fd',  // --blue-soft   chip / tag backgrounds
        'blue-border':'#cfdcfa',  // --blue-border input focus borders

        // ── 19-sector accent spectrum (dots, discovery tab) ────────────────────
        sector: {
          1:  '#c98a2b', 2:  '#e07b39', 3:  '#d65745', 4:  '#d64f7d',
          5:  '#b357c9', 6:  '#8a5cf0', 7:  '#5b6ef0', 8:  '#2f7be0',
          9:  '#2ba6d9', 10: '#16a39a', 11: '#1f9e84', 12: '#3a9e54',
          13: '#6f9e2e', 14: '#6b78a8', 15: '#189e6e', 16: '#5e7a8f',
          17: '#b8902a', 18: '#2898b0', 19: '#7d5ad0',
        },
      },

      boxShadow: {
        // Warm-tinted shadow system from the Claude design artifact
        // rgba base: (40,32,18) = warm dark brown
        // btn shadow: rgba(31,95,224,…) = brand blue
        card:          '0 2px 10px rgba(40,32,18,0.05)',
        'card-hover':  '0 14px 34px rgba(40,32,18,0.12)',
        'input-focus': '0 0 0 4px rgba(31,95,224,0.12)',
        btn:           '0 10px 24px rgba(31,95,224,0.32)',
        'btn-hover':   '0 10px 24px rgba(31,95,224,0.42)',
        glass:         '0 8px 30px rgba(40,32,18,0.10), inset 0 1px 0 rgba(255,255,255,0.70)',
      },

      animation: {
        typing:    'typing-bounce 1.2s ease-in-out infinite',
        'fade-up': 'fadeUp 0.22s ease-out',
        'slide-in':'slideIn 0.15s ease-out',
        'scale-in':'scaleIn 0.18s ease-out',
      },
      keyframes: {
        'typing-bounce': {
          '0%, 100%': { transform: 'translateY(0)', opacity: '1' },
          '50%':       { transform: 'translateY(-5px)', opacity: '0.4' },
        },
        fadeUp:  { '0%': { opacity: '0', transform: 'translateY(8px)' },  '100%': { opacity: '1', transform: 'translateY(0)' } },
        slideIn: { '0%': { opacity: '0', transform: 'translateX(-6px)' }, '100%': { opacity: '1', transform: 'translateX(0)' } },
        scaleIn: { '0%': { opacity: '0', transform: 'scale(0.95)' },      '100%': { opacity: '1', transform: 'scale(1)' } },
      },
    },
  },
  plugins: [],
};
