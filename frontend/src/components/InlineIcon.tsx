export type InlineIconName =
  | 'sparkles'
  | 'upload'
  | 'document'
  | 'clipboard'
  | 'check'
  | 'x'
  | 'info'
  | 'exclamation'
  | 'bolt'
  | 'news'
  | 'balance'
  | 'globe'
  | 'warning'
  | 'package'
  | 'clock';

type InlineIconProps = {
  name: InlineIconName;
  size?: number;
  color?: string;
  className?: string;
};

export function InlineIcon({ name, size = 16, color = 'currentColor', className }: InlineIconProps) {
  const common = {
    width: size,
    height: size,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: color,
    strokeWidth: 2,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    className,
    'aria-hidden': true,
    focusable: false,
  };

  switch (name) {
    case 'check':
      return (
        <svg {...common}>
          <path d="M20 6L9 17l-5-5" />
        </svg>
      );
    case 'x':
      return (
        <svg {...common}>
          <path d="M18 6L6 18" />
          <path d="M6 6l12 12" />
        </svg>
      );
    case 'exclamation':
      return (
        <svg {...common}>
          <path d="M12 2v14" />
          <path d="M12 18h.01" />
        </svg>
      );
    case 'info':
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="10" />
          <path d="M12 10v6" />
          <path d="M12 7h.01" />
        </svg>
      );
    case 'sparkles':
      return (
        <svg {...common}>
          <path d="M12 2l1.3 4.9L18 8.2l-4.7 1.3L12 14l-1.3-4.5L6 8.2l4.7-1.3L12 2z" />
          <path d="M19 14l.8 2.6L22 17.4l-2.2.8L19 20l-.8-1.8-2.2-.8 2.2-.8L19 14z" />
          <path d="M4.5 13l.7 2.2 2.3.8-2.3.8-.7 2.2-.7-2.2-2.3-.8 2.3-.8.7-2.2z" />
        </svg>
      );
    case 'upload':
      return (
        <svg {...common}>
          <path d="M12 16V4" />
          <path d="M7 9l5-5 5 5" />
          <path d="M4 20h16" />
        </svg>
      );
    case 'document':
      return (
        <svg {...common}>
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
          <path d="M14 2v6h6" />
          <path d="M8 13h8" />
          <path d="M8 17h6" />
        </svg>
      );
    case 'clipboard':
      return (
        <svg {...common}>
          <path d="M9 4h6" />
          <path d="M9 2h6a2 2 0 0 1 2 2v2H7V4a2 2 0 0 1 2-2z" />
          <rect x="7" y="6" width="10" height="16" rx="2" />
          <path d="M9 10h6" />
          <path d="M9 14h6" />
        </svg>
      );
    case 'bolt':
      return (
        <svg {...common}>
          <path d="M13 2L3 14h8l-1 8 11-14h-8l0-6z" />
        </svg>
      );
    case 'warning':
      return (
        <svg {...common}>
          <path d="M12 2l10 18H2L12 2z" />
          <path d="M12 9v4" />
          <path d="M12 17h.01" />
        </svg>
      );
    case 'news':
      return (
        <svg {...common}>
          <path d="M4 19V5a2 2 0 0 1 2-2h13a1 1 0 0 1 1 1v15a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z" />
          <path d="M8 7h8" />
          <path d="M8 11h8" />
          <path d="M8 15h5" />
        </svg>
      );
    case 'balance':
      return (
        <svg {...common}>
          <path d="M12 3v18" />
          <path d="M6 6l6 0" />
          <path d="M18 6l-6 0" />
          <path d="M5 10l-2 4h4l-2-4z" />
          <path d="M19 10l-2 4h4l-2-4z" />
          <path d="M7 14h10" />
        </svg>
      );
    case 'globe':
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="10" />
          <path d="M2 12h20" />
          <path d="M12 2c3 3 3 17 0 20" />
          <path d="M12 2c-3 3-3 17 0 20" />
        </svg>
      );
    case 'package':
      return (
        <svg {...common}>
          <path d="M21 8l-9-5-9 5 9 5 9-5z" />
          <path d="M3 8v8l9 5 9-5V8" />
          <path d="M12 13v8" />
        </svg>
      );
    case 'clock':
      return (
        <svg {...common}>
          <circle cx="12" cy="12" r="10" />
          <path d="M12 6v6l4 2" />
        </svg>
      );
    default:
      return null;
  }
}

