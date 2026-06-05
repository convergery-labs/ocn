interface AppLogoProps {
  size?: 'sm' | 'lg';
}

export function AppLogo({ size = 'sm' }: AppLogoProps) {
  const isLg = size === 'lg';

  return (
    <div className={`bg-gradient-to-br from-brand-400 to-brand-600 flex items-center justify-center flex-shrink-0 ${
      isLg
        ? 'w-20 h-20 rounded-3xl shadow-lg shadow-brand-200'
        : 'w-11 h-11 rounded-2xl shadow-md shadow-brand-200'
    }`}>
      <svg
        width={isLg ? 40 : 22}
        height={isLg ? 40 : 22}
        viewBox="0 0 24 24"
        fill="none"
      >
        {/* Primary hub-to-satellite edges */}
        <line x1="12" y1="12" x2="12" y2="3.5" stroke="white" strokeWidth="1.2" strokeOpacity="0.6" strokeLinecap="round"/>
        <line x1="12" y1="12" x2="20" y2="9"   stroke="white" strokeWidth="1.2" strokeOpacity="0.6" strokeLinecap="round"/>
        <line x1="12" y1="12" x2="18" y2="20"  stroke="white" strokeWidth="1.2" strokeOpacity="0.6" strokeLinecap="round"/>
        <line x1="12" y1="12" x2="4"  y2="15"  stroke="white" strokeWidth="1.2" strokeOpacity="0.6" strokeLinecap="round"/>
        {/* Cross-edges between satellites */}
        <line x1="12" y1="3.5" x2="20" y2="9"  stroke="white" strokeWidth="1.0" strokeOpacity="0.4" strokeLinecap="round"/>
        <line x1="4"  y1="15"  x2="18" y2="20" stroke="white" strokeWidth="1.0" strokeOpacity="0.4" strokeLinecap="round"/>
        <line x1="20" y1="9"   x2="18" y2="20" stroke="white" strokeWidth="1.0" strokeOpacity="0.4" strokeLinecap="round"/>
        {/* Hub node */}
        <circle cx="12" cy="12"  r="2.2" fill="white"/>
        {/* Satellite nodes */}
        <circle cx="12" cy="3.5" r="1.5" fill="white"/>
        <circle cx="20" cy="9"   r="1.5" fill="white"/>
        <circle cx="18" cy="20"  r="1.5" fill="white"/>
        <circle cx="4"  cy="15"  r="1.5" fill="white"/>
      </svg>
    </div>
  );
}
