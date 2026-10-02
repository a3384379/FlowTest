import { theme, type ThemeConfig } from 'antd'

export const iceColors = {
  app: '#F3F8FF',
  surface: '#FFFFFF',
  surfaceSubtle: '#EBF3FF',
  chrome: '#F4F8FF',
  canvas: '#F7FBFF',
  text: '#142B50',
  textSecondary: '#4C6384',
  textTertiary: '#586E8D',
  borderSubtle: '#DCE8F7',
  borderControl: '#7B93B2',
  brand: '#1765E8',
  brandHover: '#0E56D6',
  brandActive: '#0848BB',
  brandSoft: '#E8F1FF',
  brandDecorative: '#4392FF',
  edge: '#587DAA',
  nodeBorder: '#89A9D6',
  success: '#147D57',
  successBg: '#EAF8F1',
  danger: '#C6324D',
  dangerBg: '#FFF0F3',
  warning: '#9B5A08',
  warningBg: '#FFF6E7',
  iconExtract: '#6753BC',
  iconControl: '#9B5A08',
} as const

export const iceFonts = {
  sans: "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', 'Noto Sans CJK SC', sans-serif",
  mono: "ui-monospace, 'SFMono-Regular', Consolas, 'Liberation Mono', monospace",
} as const

export const iceShadows = {
  panel: '0 4px 16px rgba(47,103,171,.06)',
  node: '0 4px 12px rgba(44,110,197,.10), inset 0 1px 0 #FFFFFF',
  selected: '0 0 0 3px rgba(23,101,232,.12), 0 5px 16px rgba(44,110,197,.12)',
  overlay: '0 18px 48px rgba(54,90,145,.16)',
} as const

export const iceChartTheme = {
  color: [iceColors.success, iceColors.danger, iceColors.brand, iceColors.warning],
  backgroundColor: 'transparent',
  textStyle: { color: iceColors.textSecondary, fontFamily: iceFonts.sans, fontSize: 12 },
  categoryAxis: {
    axisLine: { lineStyle: { color: iceColors.borderSubtle } },
    axisLabel: { color: iceColors.textSecondary },
    axisTick: { show: false },
  },
  valueAxis: {
    axisLabel: { color: iceColors.textSecondary },
    splitLine: { lineStyle: { color: iceColors.borderSubtle } },
  },
  legend: { textStyle: { color: iceColors.textSecondary } },
  tooltip: {
    backgroundColor: iceColors.surface,
    borderColor: iceColors.borderSubtle,
    textStyle: { color: iceColors.text },
    extraCssText: `box-shadow:${iceShadows.panel};border-radius:9px;`,
  },
} as const

export function applyIceAppearance(root: HTMLElement): void {
  root.dataset.flowtestTheme = 'ice-light'
  root.style.colorScheme = 'light'
  for (const [name, value] of Object.entries(iceColors)) {
    root.style.setProperty(
      `--ft-${name.replace(/[A-Z]/g, (part) => `-${part.toLowerCase()}`)}`,
      value,
    )
  }
  for (const [name, value] of Object.entries(iceShadows))
    root.style.setProperty(`--ft-shadow-${name}`, value)
  root.style.setProperty('--ft-font-sans', iceFonts.sans)
  root.style.setProperty('--ft-font-mono', iceFonts.mono)
}

export function createIceTheme(reduceMotion: boolean): ThemeConfig {
  return {
    algorithm: theme.defaultAlgorithm,
    token: {
      colorPrimary: iceColors.brand,
      colorPrimaryHover: iceColors.brandHover,
      colorPrimaryActive: iceColors.brandActive,
      colorPrimaryBg: iceColors.brandSoft,
      colorLink: iceColors.brand,
      colorBgLayout: iceColors.app,
      colorBgContainer: iceColors.surface,
      colorBgElevated: iceColors.surface,
      colorBgMask: 'rgba(122,158,205,.24)',
      colorBgSolid: iceColors.brand,
      colorBgSolidHover: iceColors.brandHover,
      colorBgSolidActive: iceColors.brandActive,
      colorText: iceColors.text,
      colorTextHeading: iceColors.text,
      colorTextSecondary: iceColors.textSecondary,
      colorTextTertiary: iceColors.textTertiary,
      colorTextDescription: iceColors.textSecondary,
      colorTextPlaceholder: iceColors.textTertiary,
      colorBorder: iceColors.borderControl,
      colorBorderSecondary: iceColors.borderSubtle,
      colorSplit: iceColors.borderSubtle,
      colorSuccess: iceColors.success,
      colorSuccessBg: iceColors.successBg,
      colorError: iceColors.danger,
      colorErrorBg: iceColors.dangerBg,
      colorWarning: iceColors.warning,
      colorWarningBg: iceColors.warningBg,
      colorInfo: iceColors.brand,
      fontFamily: iceFonts.sans,
      fontFamilyCode: iceFonts.mono,
      fontSize: 14,
      fontSizeSM: 12,
      controlHeight: 36,
      controlHeightLG: 40,
      borderRadius: 9,
      borderRadiusLG: 14,
      borderRadiusSM: 6,
      motion: !reduceMotion,
      boxShadow: iceShadows.overlay,
      boxShadowSecondary: iceShadows.panel,
    },
    components: {
      Tooltip: { colorBgSpotlight: iceColors.surface, colorTextLightSolid: iceColors.text },
      Menu: {
        itemBg: iceColors.chrome,
        itemSelectedBg: iceColors.brandSoft,
        itemSelectedColor: iceColors.brand,
      },
      Table: {
        headerBg: iceColors.chrome,
        headerColor: iceColors.textSecondary,
        rowHoverBg: iceColors.canvas,
      },
      Card: { headerFontSize: 16 },
      Tabs: { titleFontSize: 14 },
    },
  }
}
