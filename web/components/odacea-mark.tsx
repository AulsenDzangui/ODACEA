// Icône de marque ODACEA — dossiers empilés (même géométrie que app/icon.svg
// et app/favicon.ico, source unique du dessin).
export function OdaceaMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
      className={className}
    >
      <rect width="32" height="32" rx="7" fill="#EEF2FF" />
      <rect x="4" y="6" width="16" height="12" rx="2" fill="#C7D2FE" />
      <rect x="4" y="4" width="7" height="3" rx="1.2" fill="#C7D2FE" />
      <rect x="7" y="10" width="16" height="12" rx="2" fill="#6366F1" stroke="#EEF2FF" strokeWidth="1" />
      <rect x="7" y="8" width="7" height="3" rx="1.2" fill="#6366F1" stroke="#EEF2FF" strokeWidth="1" />
      <rect x="10" y="14" width="16" height="12" rx="2" fill="#4338CA" stroke="#EEF2FF" strokeWidth="1" />
      <rect x="10" y="12" width="7" height="3" rx="1.2" fill="#4338CA" stroke="#EEF2FF" strokeWidth="1" />
    </svg>
  );
}
