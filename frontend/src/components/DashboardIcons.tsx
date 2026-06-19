import type { SVGProps } from 'react'

type IconProps = SVGProps<SVGSVGElement>

export const GlobeIcon = ({ className = '', ...props }: IconProps) => (
  <svg
    className={className}
    viewBox="0 0 24 24"
    fill="none"
    aria-hidden="true"
    focusable="false"
    {...props}
  >
    <circle cx="12" cy="12" r="8.25" stroke="currentColor" strokeWidth="1.55" />
    <path d="M3.9 12h16.2" stroke="currentColor" strokeWidth="1.35" strokeLinecap="round" />
    <path d="M12 3.75c2.25 2.2 3.32 4.95 3.32 8.25S14.25 18.05 12 20.25" stroke="currentColor" strokeWidth="1.35" strokeLinecap="round" />
    <path d="M12 3.75C9.75 5.95 8.68 8.7 8.68 12S9.75 18.05 12 20.25" stroke="currentColor" strokeWidth="1.35" strokeLinecap="round" />
    <path d="M6.15 6.45c1.6 1.05 3.56 1.62 5.85 1.62s4.25-.57 5.85-1.62" stroke="currentColor" strokeWidth="1.15" strokeLinecap="round" opacity="0.72" />
    <path d="M6.15 17.55c1.6-1.05 3.56-1.62 5.85-1.62s4.25.57 5.85 1.62" stroke="currentColor" strokeWidth="1.15" strokeLinecap="round" opacity="0.72" />
  </svg>
)

export const RefreshIcon = ({ className = '', ...props }: IconProps) => (
  <svg
    className={className}
    viewBox="0 0 24 24"
    fill="none"
    aria-hidden="true"
    focusable="false"
    {...props}
  >
    <path d="M20 7.2v5h-5" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M4.7 14.9a7.3 7.3 0 0 0 12.65 2.15L20 12.2" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M4 16.8v-5h5" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M19.3 9.1A7.3 7.3 0 0 0 6.65 6.95L4 11.8" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

export const ChevronRightIcon = ({ className = '', ...props }: IconProps) => (
  <svg
    className={className}
    viewBox="0 0 24 24"
    fill="none"
    aria-hidden="true"
    focusable="false"
    {...props}
  >
    <path d="m9 5 7 7-7 7" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)
