/** @type {import('tailwindcss').Config} */

// rgb(var(--x) / <alpha-value>) 让 /透明度 修饰符继续可用
const token = (name) => `rgb(var(--c-${name}) / <alpha-value>)`

/** 遗留色板兼容桥：S1 让零 TSX 改动也能全站换肤，S4 codemod 完成后由 S5 删除 */
const legacyBridge = {
  dark: {
    950: token('canvas'),
    900: token('canvas'),
    800: token('panel'),
    700: token('panel-2'),
    600: token('line'),
    500: token('line-strong'),
    400: token('ink-subtle'),
    750: token('panel-2'),
    850: token('panel-3'),
  },
  accent: {
    primary: token('iris'),
    secondary: token('flare'),
    success: token('ok'),
    warning: token('warn'),
    error: token('bad'),
  },
}

export default {
  darkMode: 'class',
  content: [
    "./index.html",
    "./styleguide.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        /* ============================================================
           Aurora 语义令牌 —— 新代码只允许使用这一组（唯一色彩真源）
           ============================================================ */
        canvas: token('canvas'),
        panel: {
          DEFAULT: token('panel'),
          2: token('panel-2'),
          3: token('panel-3'),
        },
        line: {
          DEFAULT: token('line'),
          strong: token('line-strong'),
        },
        ink: {
          DEFAULT: token('ink'),
          muted: token('ink-muted'),
          subtle: token('ink-subtle'),
        },
        mint: token('mint'),
        flare: token('flare'),
        iris: token('iris'),
        brand: {
          DEFAULT: token('brand'),
          fg: token('brand-fg'),
        },
        ok: token('ok'),
        warn: token('warn'),
        bad: token('bad'),
        info: token('info'),
        halo: token('halo'),
        scrim: token('scrim'),

        /* 遗留别名桥（S5 删除） */
        ...legacyBridge,
      },
      fontFamily: {
        sans: ['DM Sans Variable', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Noto Sans CJK SC', 'sans-serif'],
        display: ['Syne Variable', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'Noto Sans CJK SC', 'sans-serif'],
        mono: ['JetBrains Mono Variable', 'SFMono-Regular', 'Consolas', 'monospace'],
        headline: ['Syne Variable', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'sans-serif'],
        body: ['DM Sans Variable', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'sans-serif'],
        label: ['DM Sans Variable', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', 'sans-serif'],
      },
      borderRadius: {
        card: 'var(--radius-card)',
        md2: 'var(--radius-md)',
        pill: 'var(--radius-pill)',
      },
      boxShadow: {
        glass: 'var(--shadow-glass)',
        glow: 'var(--shadow-glow)',
      },
      animation: {
        'fade-in': 'fadeIn 0.3s ease-out',
        'slide-up': 'slideUp 0.3s ease-out',
        'slide-in-right': 'slideInRight 0.3s ease-out',
        'aurora-shimmer': 'auroraShimmer 4s ease-in-out infinite',
        'scale-in': 'scaleIn 0.24s cubic-bezier(0.22, 1, 0.36, 1)',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { opacity: '0', transform: 'translateY(10px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        slideInRight: {
          '0%': { opacity: '0', transform: 'translateX(20px)' },
          '100%': { opacity: '1', transform: 'translateX(0)' },
        },
        scaleIn: {
          '0%': { opacity: '0', transform: 'scale(0.96)' },
          '100%': { opacity: '1', transform: 'scale(1)' },
        },
      },
    },
  },
  plugins: [],
}
