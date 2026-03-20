'use client';

export default function Header() {
  return (
    <header
      style={{
        background: '#fff',
        borderBottom: '1px solid #E2E8F0',
        padding: '0 24px',
        height: 56,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        position: 'sticky',
        top: 0,
        zIndex: 100,
        boxShadow: '0 1px 8px rgba(0,0,0,0.06)',
      }}
    >
      {/* Logo */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
        {/* Custom provided logo */}
        <img 
          src="/logo.png" 
          alt="ChainIQ Logo" 
          style={{ height: 36, objectFit: 'contain' }} 
        />
        
        <div style={{ paddingLeft: 12, borderLeft: '2px solid #E2E8F0' }}>
          <div
            style={{
              fontFamily: 'Inter, sans-serif',
              fontWeight: 800,
              fontSize: 16,
              color: '#0F172A',
              letterSpacing: '0.05em',
              lineHeight: 1.1,
            }}
          >
            ARIA
          </div>
          <div
            style={{
              fontSize: 10,
              color: '#6B7280',
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
              fontWeight: 600,
              marginTop: 2,
            }}
          >
            Audit-Ready Intelligence Agent
          </div>
        </div>
      </div>

      {/* Right side */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        {/* Status dot */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: '#475569', fontWeight: 500 }}>
          <div
            style={{
              width: 7,
              height: 7,
              borderRadius: '50%',
              background: '#059669',
              boxShadow: '0 0 0 3px rgba(5,150,105,0.2)',
              animation: 'pulse-dot 2s ease-in-out infinite',
            }}
          />
          ONLINE
        </div>

        <nav style={{ display: 'flex', gap: 16, marginLeft: 20 }}>
          <a 
            href="/" 
            style={{ 
              fontSize: 13, 
              fontWeight: 600, 
              color: '#475569', 
              textDecoration: 'none',
              padding: '6px 12px',
              borderRadius: 6,
              transition: 'all 0.2s'
            }}
            onMouseOver={(e) => { e.currentTarget.style.background = '#F1F5F9'; e.currentTarget.style.color = '#0F172A'; }}
            onMouseOut={(e) => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = '#475569'; }}
          >
            Dashboard
          </a>
          <a 
            href="/analytics" 
            style={{ 
              fontSize: 13, 
              fontWeight: 600, 
              color: '#475569', 
              textDecoration: 'none',
              padding: '6px 12px',
              borderRadius: 6,
              transition: 'all 0.2s'
            }}
            onMouseOver={(e) => { e.currentTarget.style.background = '#F1F5F9'; e.currentTarget.style.color = '#0F172A'; }}
            onMouseOut={(e) => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = '#475569'; }}
          >
            Analytics
          </a>
        </nav>


      </div>

      <style>{`
        @keyframes pulse-dot {
          0%, 100% { opacity: 1; box-shadow: 0 0 0 3px rgba(5,150,105,0.2); }
          50% { opacity: 0.7; box-shadow: 0 0 0 5px rgba(5,150,105,0.1); }
        }
      `}</style>
    </header>
  );
}
